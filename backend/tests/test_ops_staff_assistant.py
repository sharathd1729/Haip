"""Staff assistant on WhatsApp (ops gap 11, services/ops_staff_assistant.py): answers from the staff member's own facts,
"ask the manager" when the facts do not say, refuses guest contact / ID / money, never uses another property's facts, owner
switch, rate limit, tenant isolation, the webhook only queues it for questions, and every older staff flow is unchanged.
No model is called: `complete` is injected."""

import json
from unittest.mock import patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.ops import OpsAlertSend, OpsItem, OpsSettings
from app.models.user import UserRole
from app.services import knowledge_service
from app.services import ops_escalation_service as esc
from app.services import ops_staff_assistant as sa
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, shift, staff, tenant
from tests.test_increment1_defect_specs import _h, _user

WIFI_A = "AmaraGuest2026"
WIFI_B = "BanyanSecret99"


class _LLM:
    """Stands in for the router: records what the model would have seen, returns a fixed JSON reply."""

    def __init__(self, found=True, answer=""):
        self.reply = json.dumps({"found": found, "answer": answer})
        self.seen: list[dict] = []

    def __call__(self, system_prompt, user_message):
        self.seen.append(json.loads(user_message))
        return {"content": self.reply}


@pytest.fixture(autouse=True)
def _kb():
    """SQLite has no pgvector: the ONE retrieval path is stubbed with passages for property A, property B and tenant-wide."""
    hits: list[dict] = []
    with patch.object(
        knowledge_service,
        "search_detailed",
        side_effect=lambda *a, **k: knowledge_service.SearchOutcome(
            hits=list(hits), status="ok" if hits else "no_match"
        ),
    ):
        yield hits


def _on(db, tenant_id, on=True):
    row = esc.get_settings_row(db, tenant_id) or OpsSettings(tenant_id=tenant_id)
    row.staff_assistant_enabled = on
    db.add(row)
    db.commit()


@pytest.fixture()
def w(db):
    t = tenant(db)
    a = prop(db, t.id, "Villa Amara")
    a.faqs = [
        {"question": "Wi-Fi password", "answer": WIFI_A},
        {"question": "Gas supplier", "answer": "Shree Gas, 080 4123 4567"},
        {"question": "Front door code", "answer": "Keypad 4482"},
    ]
    b = prop(db, t.id, "Villa Banyan")
    b.faqs = [{"question": "Wi-Fi password", "answer": WIFI_B}]
    db.commit()
    caretaker = staff(db, t.id, "Manju", "caretaker", property_id=a.id)
    boss = staff(db, t.id, "Boss Rao", "ops_manager")
    for day in range(7):
        shift(db, t.id, boss.id, "ops_manager", day, 0, 24)
    _on(db, t.id)
    return type("W", (), {"t": t, "a": a, "b": b, "caretaker": caretaker, "boss": boss})()


def _audits(db, tenant_id, action=sa.ACTION):
    db.flush()
    return db.query(AuditEvent).filter_by(tenant_id=tenant_id, action=action).all()


def test_wifi_question_is_answered_from_the_property_facts(db, w):
    llm = _LLM(answer=f"The Wi-Fi password is {WIFI_A}.")
    reply = sa.answer(db, w.t.id, w.caretaker, "What is the wifi password?", complete=llm)
    assert reply == f"The Wi-Fi password is {WIFI_A}."
    facts = llm.seen[0]["facts"]
    assert facts["your_properties"][0]["name"] == "Villa Amara"
    assert WIFI_A in json.dumps(facts)
    (row,) = _audits(db, w.t.id)
    assert row.payload["outcome"] == "answered" and row.payload["category"] == "wifi"
    assert (
        row.payload["question"] == "What is the wifi password?"
        and row.payload["prompt_version"] == "staff-assistant-v1"
    )
    assert row.payload["actor"] == "system" and row.target_id == w.caretaker.id


def test_unknown_fact_says_ask_the_manager(db, w):
    reply = sa.answer(db, w.t.id, w.caretaker, "Where is the spare fuse?", complete=_LLM(found=False))
    assert reply == "I don't have that. Ask Boss."
    assert _audits(db, w.t.id)[0].payload["outcome"] == "no_answer"


def test_provider_failure_says_ask_the_manager(db, w):
    def boom(*_a):
        raise TimeoutError

    assert sa.answer(db, w.t.id, w.caretaker, "When does the pool get cleaned?", complete=boom) == (
        "I don't have that. Ask Boss."
    )
    assert _audits(db, w.t.id)[0].payload["outcome"] == "failed"


@pytest.mark.parametrize(
    "q",
    [
        "What is the guest's phone number?",
        "Can you send me the email of the guest?",
        "What is the passport number?",
        "How much has the guest paid?",
    ],
)
def test_guest_contact_id_or_money_is_refused_without_a_model_call(db, w, q):
    llm = _LLM(answer="+91 98450 00000")
    reply = sa.answer(db, w.t.id, w.caretaker, q, complete=llm)
    assert reply.startswith("I can't share guest contact") and "Boss" in reply
    assert llm.seen == []
    assert _audits(db, w.t.id)[0].payload["outcome"] == "refused"


def test_a_number_not_in_the_facts_is_never_sent(db, w):
    reply = sa.answer(db, w.t.id, w.caretaker, "Plumber number?", complete=_LLM(answer="Call 98450 11111."))
    assert reply == "I don't have that. Ask Boss."
    assert _audits(db, w.t.id)[0].payload["outcome"] == "ungrounded"
    ok = sa.answer(db, w.t.id, w.caretaker, "Gas supplier number?", complete=_LLM(answer="Shree Gas: 080 4123 4567"))
    assert ok == "Shree Gas: 080 4123 4567"


def test_another_propertys_facts_are_not_used(db, w, _kb):
    _kb.extend(
        [
            {"id": "1", "question": "Geyser", "content": "Switch is behind the door", "property_id": w.a.id},
            {"id": "2", "question": "Geyser", "content": "Banyan geyser trips often", "property_id": w.b.id},
            {"id": "3", "question": "Check-out", "content": "Check-out is 11 am", "property_id": None},
        ]
    )
    llm = _LLM(found=False)
    sa.answer(db, w.t.id, w.caretaker, "How does the geyser work?", complete=llm)
    seen = json.dumps(llm.seen[0])
    assert WIFI_B not in seen and "Banyan" not in seen
    assert "Switch is behind the door" in seen and "Check-out is 11 am" in seen


def test_lock_codes_only_for_duties_that_let_guests_in(db, w):
    driver = staff(db, w.t.id, "Suresh", "driver", property_id=w.a.id)
    llm = _LLM(found=False)
    sa.answer(db, w.t.id, driver, "What is the door code?", complete=llm)
    assert "4482" not in json.dumps(llm.seen[0]) and WIFI_A in json.dumps(llm.seen[0])
    sa.answer(db, w.t.id, w.caretaker, "What is the door code?", complete=llm)
    assert "4482" in json.dumps(llm.seen[1])


def test_switch_off_means_no_answer_and_no_record(db, w):
    _on(db, w.t.id, on=False)
    llm = _LLM(answer="x")
    assert sa.answer(db, w.t.id, w.caretaker, "What is the wifi password?", complete=llm) is None
    assert llm.seen == [] and _audits(db, w.t.id) == []


def test_rate_limit_per_staff_member(db, w):
    llm = _LLM(found=False)
    for _ in range(sa.RATE_LIMIT_PER_HOUR):
        sa.answer(db, w.t.id, w.caretaker, "Any towels left?", complete=llm)
    db.commit()
    assert sa.answer(db, w.t.id, w.caretaker, "Any towels left?", complete=llm).startswith("That is a lot of questions")
    assert sa.answer(db, w.t.id, w.caretaker, "Any towels left?", complete=llm) is None  # told once per hour
    assert len(llm.seen) == sa.RATE_LIMIT_PER_HOUR
    other = staff(db, w.t.id, "Ravi", "housekeeping", property_id=w.a.id)
    assert sa.answer(db, w.t.id, other, "Any towels left?", complete=llm) == "I don't have that. Ask Boss."


def test_tenant_isolation(db, w):
    t2 = tenant(db)
    p2 = prop(db, t2.id, "Other Business Villa")
    p2.faqs = [{"question": "Wi-Fi", "answer": "OtherTenantWifi"}]
    db.commit()
    everywhere = staff(db, w.t.id, "Anil", "maintenance")  # a duty with no property = every property
    llm = _LLM(found=False)
    sa.answer(db, w.t.id, everywhere, "What is the wifi?", complete=llm)
    seen = json.dumps(llm.seen[0])
    assert "OtherTenantWifi" not in seen and WIFI_A in seen and WIFI_B in seen
    assert sa.enabled(db, t2.id) is False
    assert _audits(db, t2.id) == []


def test_todays_job_comes_from_their_own_stay_file(db):
    from app.services import ops_trip_service as trips
    from tests.test_ops_files import _stay, _tenant

    t = _tenant(db, "villa_resort")
    p = prop(db, t.id, "Villa Amara")
    stay = _stay(db, t, p, start=0, nights=3, total="60000")
    cook = staff(db, t.id, "Lakshmi", "fnb")
    f = trips.ensure_file(db, t.id, stay)
    from app.services import ops_money as money

    d = money.details(f)
    d.cook_staff_id = cook.id
    money.save_details(f, d)
    db.commit()
    _on(db, t.id)
    llm = _LLM(found=False)
    sa.answer(db, t.id, cook, "When do the guests check in?", complete=llm)
    job = llm.seen[0]["facts"]["your_job_now"]
    assert job["unit"] == "Villa Amara" and job["check_in"] == stay.check_in.isoformat()
    blob = json.dumps(job)
    assert "phone" not in blob and "email" not in blob and "60000" not in blob


def test_question_detection():
    assert sa.is_question("wifi password?") and sa.is_question("What time is check-out")
    assert sa.is_question("kya gas cylinder aaya")
    assert not sa.is_question("ok") and not sa.is_question("done, room cleaned") and not sa.is_question("")


# ── Webhook: only a question is queued; older staff flows unchanged ─────────


def _msg(**over):
    return {
        "from": "919800000000",
        "id": "wamid.s1",
        "type": "text",
        "text": {"body": "What is the wifi password?"},
        **over,
    }


def _run(db, w, msg, who=None):
    from app.workers.tasks.whatsapp import _handle_staff_message

    with (
        patch("app.core.cache.get_cached", return_value=None),
        patch("app.core.cache.set_cached"),
        patch("app.workers.tasks.ops_intake.staff_assistant_answer.delay") as ask,
        patch("app.workers.tasks.ops_intake.process_staff_photo.delay") as photo,
        patch("app.workers.tasks.ops_escalation.queue_delivery"),
        patch("app.services.lead_alert_sender.send_text") as sent,
        patch("app.services.ops_escalation_service.handle_staff_inbound", wraps=esc.handle_staff_inbound) as inbound,
    ):
        _handle_staff_message(db, w.t, who or w.caretaker, msg, msg["type"])
    return ask, photo, sent, inbound


def test_webhook_queues_a_question_when_on(db, w):
    ask, photo, _sent, inbound = _run(db, w, _msg())
    ask.assert_called_once_with(w.t.id, w.caretaker.id, "What is the wifi password?", "wamid.s1")
    inbound.assert_called_once()  # still logged on their latest alert exactly as before
    photo.assert_not_called()


def test_webhook_switch_off_or_not_a_question_queues_nothing(db, w):
    assert _run(db, w, _msg(text={"body": "done, room cleaned"}))[0].call_count == 0
    _on(db, w.t.id, on=False)
    ask, _photo, _sent, inbound = _run(db, w, _msg())
    ask.assert_not_called()
    inbound.assert_called_once()


def test_webhook_photo_is_unchanged(db, w):
    ask, photo, _sent, inbound = _run(
        db, w, {"from": "1", "id": "wamid.p", "type": "image", "image": {"id": "media1", "caption": "what is this?"}}
    )
    photo.assert_called_once_with(w.t.id, w.caretaker.id, "media1", "what is this?", "wamid.p")
    ask.assert_not_called()
    inbound.assert_not_called()


def test_webhook_issue_is_unchanged(db, w):
    from app.services import ops_photo_intake

    with patch.object(ops_photo_intake, "handle_text", wraps=ops_photo_intake.handle_text) as ht:
        ask, _photo, sent, inbound = _run(db, w, _msg(text={"body": "issue: what do I do, pool pump stopped?"}))
    ht.assert_called_once()
    sent.assert_called_once()  # "No trip found ... call the manager" (no file in this test)
    ask.assert_not_called()
    inbound.assert_not_called()


def test_webhook_ok_from_the_cook_is_unchanged(db, w):
    from app.services import ops_stay_meals

    with patch.object(ops_stay_meals, "cook_reply", return_value="Thank you. 2 meals confirmed.") as cr:
        ask, _photo, sent, inbound = _run(db, w, _msg(text={"body": "OK"}))
    cr.assert_called_once()
    assert sent.call_args[0][3] == "Thank you. 2 meals confirmed."
    ask.assert_not_called()
    inbound.assert_not_called()


def test_webhook_acknowledge_and_cant_take_it_buttons_are_unchanged(db, w):
    for day in range(7):
        shift(db, w.t.id, w.caretaker.id, "caretaker", day, 0, 24, property_id=w.a.id)
    item, _ids = esc.create_item(
        db,
        w.t.id,
        title="AC not working",
        severity="high",
        duty="caretaker",
        property_id=w.a.id,
        summary="Guest says AC stopped",
    )
    db.commit()
    send = db.query(OpsAlertSend).filter_by(item_id=item.id, staff_id=w.caretaker.id).first()
    assert send is not None
    tap = {
        "from": "1",
        "id": "wamid.b1",
        "type": "button",
        "button": {"text": "Acknowledge", "payload": f"ops:ack:{send.id}:{send.nonce}"},
    }
    ask, _photo, _sent, inbound = _run(db, w, tap)
    inbound.assert_called_once()
    ask.assert_not_called()
    db.refresh(item)
    assert item.status == "acknowledged"
    decline = {
        "from": "1",
        "id": "wamid.b2",
        "type": "interactive",
        "interactive": {"button_reply": {"id": f"ops:decline:{send.id}:{send.nonce}", "title": "Can't take it"}},
    }
    ask, *_ = _run(db, w, decline)
    ask.assert_not_called()
    assert db.query(OpsItem).filter_by(id=item.id).one().status in ("acknowledged", "open")


# ── Task + switch endpoint ──────────────────────────────────────────────────


def test_task_answers_and_replies_once(db, w):
    from app.workers.tasks.ops_intake import staff_assistant_answer

    cache: dict = {}
    with (
        patch("app.workers.tasks.ops_intake.SessionLocal", return_value=_Ctx(db)),
        patch("app.workers.tasks.ops_intake.set_tenant_context"),
        patch("app.core.cache.get_cached", side_effect=cache.get),
        patch("app.core.cache.set_cached", side_effect=lambda k, v, ttl=None: cache.__setitem__(k, v)),
        patch.object(sa, "_default_complete", _LLM(answer=f"Password: {WIFI_A}")),
        patch("app.services.lead_alert_sender.send_text") as sent,
    ):
        staff_assistant_answer(w.t.id, w.caretaker.id, "wifi password?", "wamid.t1")
        staff_assistant_answer(w.t.id, w.caretaker.id, "wifi password?", "wamid.t1")  # Meta redelivery
    sent.assert_called_once_with(db, w.t.id, w.caretaker.phone_e164, f"Password: {WIFI_A}")


class _Ctx:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        return False


def test_only_the_owner_turns_the_switch(client, db):
    t = tenant(db)
    seed_capabilities(db, t.id)
    owner, mgr = _user(db, t.id, UserRole.OWNER), _user(db, t.id, UserRole.MANAGER)
    assert client.get("/api/v1/ops/settings", headers=_h(mgr)).json()["staff_assistant_enabled"] is False
    r = client.put("/api/v1/ops/settings", json={"staff_assistant_enabled": True}, headers=_h(mgr))
    assert r.status_code == 403
    r = client.put("/api/v1/ops/settings", json={"staff_assistant_enabled": True}, headers=_h(owner))
    assert r.status_code == 200 and r.json()["staff_assistant_enabled"] is True
    other = tenant(db)
    assert sa.enabled(db, other.id) is False
