"""Lead scenarios the owner decided on 1 Nov 2026, end to end through the ONE work queue (work_queue_service.build):

  S1 a Lost lead whose guest writes / calls again -> Active, "came_back" on My day, counted from the return
  S2 our one-way outreach keeps a Lost lead Lost; the guest picking up our call reopens it (test_lead_reopen.py too)
  S3 a reply to a WhatsApp campaign (any days later) -> Active from a not-engaged stage, "campaign_reply"; never from Sold
  S4 the bot answered but a person is needed -> "handover" until a person contacts the guest; S5 a full answer is not listed
  S8 autopilot "travel date passed" waits while the guest wrote in the last 3 days
  S9 a Sold guest writing again stays Sold and is a "reply"
  S10 unowned leads first, and "Take it" (POST /work-queue/take) claims one, audited
plus tenant isolation, My day / Home counts / alerts reading the same items, and both stage paths closing a returned lead.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.api.v1.endpoints.messaging import WACampaign
from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage
from app.models.inquiry_360 import InquiryStageLog
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.wa_campaign_recipient import WACampaignRecipient
from app.services import dashboard_service, inquiry_service, lead_reopen
from app.services import work_queue_service as wq
from app.services.pipeline_stage_service import seed_default_pipeline_stages

API = "/api/v1"


def _now():
    return datetime.now(UTC)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Demo Caravans", slug=f"sc-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    seed_default_pipeline_stages(db, t.id)
    db.commit()
    return t


def _stages(db, tid):
    return {s.key: s for s in db.query(PipelineStage).filter_by(tenant_id=tid)}


def _user(db, tid, role=UserRole.CONCIERGE, name="Asha Agent"):
    u = User(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        name=name,
        email=f"{uuid.uuid4().hex[:8]}@t.com",
        role=role,
        hashed_password=get_password_hash("x" * 12),
        is_active=True,
    )
    db.add(u)
    db.commit()
    return u


def _lead(db, tid, stage_key="active", name="Kiran Rao", lead_days_ago=1, assigned_to=None, closed_by=None, **kw):
    st = _stages(db, tid)[stage_key]
    g = Guest(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        name=name,
        phone=f"+9198{uuid.uuid4().int % 10**8:08d}",
        lead_identified_at=_now() - timedelta(days=lead_days_ago),
    )
    db.add(g)
    db.flush()
    legacy = (
        InquiryStage.BOOKED if st.is_closed_won else InquiryStage.LOST if st.is_closed_lost else InquiryStage.RESPONDING
    )
    inq = Inquiry(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        guest_id=g.id,
        stage_id=st.id,
        stage=legacy,
        assigned_to=assigned_to,
        created_at=_now() - timedelta(days=lead_days_ago),
        **kw,
    )
    db.add(inq)
    if closed_by:
        db.add(
            InquiryStageLog(
                tenant_id=tid,
                inquiry_id=inq.id,
                from_stage="active",
                to_stage=st.key,
                changed_by=closed_by,
                changed_at=_now() - timedelta(days=5),
                reason="closed",
            )
        )
    conv = Conversation(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        guest_id=g.id,
        channel=ChannelType.WHATSAPP,
        is_open=True,
        inquiry_id=inq.id,
        assigned_to=assigned_to,
    )
    db.add(conv)
    db.commit()
    return g, inq, conv


def _msg(db, conv, direction, minutes_ago, body="Is the caravan free on the 12th?", **kw):
    m = Message(
        id=str(uuid.uuid4()),
        tenant_id=conv.tenant_id,
        conversation_id=conv.id,
        direction=direction,
        channel=ChannelType.WHATSAPP,
        body=body,
        created_at=_now() - timedelta(minutes=minutes_ago),
        **kw,
    )
    db.add(m)
    db.commit()
    return m


def _worked(db, conv, minutes_ago=180):
    """A person spoke to this lead earlier, so it is no longer a new lead (new_lead outranks handover)."""
    return _msg(db, conv, MessageDirection.OUTBOUND, minutes_ago, body="Hi, Asha here from the team")


def _bot(db, conv, minutes_ago, body, **kw):
    return _msg(
        db,
        conv,
        MessageDirection.OUTBOUND,
        minutes_ago,
        body=body,
        is_ai_generated=True,
        sent_autonomously=True,
        was_approved=True,
        sender_kind="ai_auto",
        **kw,
    )


def _person(db, conv, minutes_ago=0):
    return _msg(db, conv, MessageDirection.OUTBOUND, minutes_ago, body="Hi, this is Asha from the team")


def _item(db, tenant, guest, scope=None):
    return next((i for i in wq.build(db, tenant, scope)["items"] if i["guest_id"] == guest.id), None)


# ── S1 / S2 ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_s1_lost_lead_that_writes_again_is_active_and_came_back_counted_from_the_return(db):
    t = _tenant(db)
    # a person closed it, and the lead is older than LEAD_WINDOW: it must still show, from the return
    g, inq, conv = _lead(db, t.id, "lost", lead_days_ago=40, closed_by=_user(db, t.id).id)
    _msg(db, conv, MessageDirection.INBOUND, 40)
    assert lead_reopen.on_contact(db, t.id, g.id, trigger="whatsapp_message", by_guest=True) is not None
    db.commit()
    db.refresh(inq)
    assert inq.stage_id == _stages(db, t.id)["active"].id and inq.returned_via == "came_back"
    item = _item(db, t, g)
    assert item["kind"] == "came_back" and "Came back" in item["detail"] and "Came back" in item["reasons"]
    assert wq._aware(datetime.fromisoformat(item["since"])) > _now() - timedelta(minutes=5)
    _person(db, conv)  # a person contacts them: off My day
    assert _item(db, t, g) is None


def test_s2_one_way_outreach_keeps_lost_and_off_my_day(db):
    t = _tenant(db)
    g, inq, conv = _lead(db, t.id, "lost", closed_by="system")
    assert lead_reopen.on_contact(db, t.id, g.id, trigger="team_message", by_guest=False) is None
    db.refresh(inq)
    assert inq.stage_id == _stages(db, t.id)["lost"].id and inq.returned_at is None and _item(db, t, g) is None


# ── S3 ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _campaign(db, tid, phone, days_ago=20, name="Monsoon offer"):
    c = WACampaign(id=str(uuid.uuid4()), tenant_id=tid, name=name)
    db.add(c)
    db.flush()
    db.add(
        WACampaignRecipient(
            tenant_id=tid, campaign_id=c.id, phone=phone, status="read", sent_at=_now() - timedelta(days=days_ago)
        )
    )
    db.commit()
    return c


def test_s3_campaign_reply_moves_a_general_enquiry_to_active_and_shows_the_campaign(db):
    t = _tenant(db)
    g, inq, conv = _lead(db, t.id, "general_enquiry", lead_days_ago=60)
    c = _campaign(db, t.id, g.phone, days_ago=20)  # 20 days later: beyond the report's 7-day window, still a reply
    reply = _msg(db, conv, MessageDirection.INBOUND, 1, body="Is this offer still on?")
    assert lead_reopen.on_campaign_reply(db, t.id, g.id, reply) is not None
    db.commit()
    db.refresh(inq)
    assert inq.stage_id == _stages(db, t.id)["active"].id
    assert (inq.returned_via, inq.returned_campaign_id) == ("campaign_reply", c.id)
    ev = db.query(AuditEvent).filter_by(tenant_id=t.id, action="lead.campaign_reply", target_id=inq.id).one()
    assert ev.payload["campaign_id"] == c.id and ev.payload["to_stage"] == "active"
    item = _item(db, t, g)
    assert item["kind"] == "campaign_reply" and "Monsoon offer" in item["detail"]
    again = _msg(db, conv, MessageDirection.INBOUND, 0, body="Hello?")
    assert lead_reopen.campaign_replied_to(db, t.id, g.id, again) is None  # only the first reply counts


def test_s3_campaign_reply_from_lost_reopens_and_never_from_sold(db):
    t = _tenant(db)
    g, inq, conv = _lead(db, t.id, "lost", closed_by="system")
    _campaign(db, t.id, g.phone)
    reply = _msg(db, conv, MessageDirection.INBOUND, 1)
    lead_reopen.on_contact(db, t.id, g.id, trigger="whatsapp_message", by_guest=True)  # the webhook's order
    lead_reopen.on_campaign_reply(db, t.id, g.id, reply)
    db.commit()
    db.refresh(inq)
    assert inq.stage_id == _stages(db, t.id)["active"].id and inq.returned_via == "campaign_reply"

    g2, sold, conv2 = _lead(db, t.id, "sold")
    _campaign(db, t.id, g2.phone)
    assert lead_reopen.on_campaign_reply(db, t.id, g2.id, _msg(db, conv2, MessageDirection.INBOUND, 1)) is None
    db.refresh(sold)
    assert sold.stage_id == _stages(db, t.id)["sold"].id and sold.returned_at is None


# ── S4 / S5 ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_s4_bot_promise_flag_or_held_draft_is_a_handover_until_a_person_contacts(db):
    t = _tenant(db)
    g1, _, c1 = _lead(db, t.id, name="Promise")
    _worked(db, c1)
    _msg(db, c1, MessageDirection.INBOUND, 60)
    _bot(db, c1, 59, "Thanks! Our team will call you shortly with the details.")
    g2, _, c2 = _lead(db, t.id, name="Flagged")
    _worked(db, c2)
    _msg(db, c2, MessageDirection.INBOUND, 60)
    _bot(db, c2, 59, "Here are our packages.", ai_needs_human_reason="Custom route needs a quote")
    g3, _, c3 = _lead(db, t.id, name="Draft")
    _worked(db, c3)
    _msg(db, c3, MessageDirection.INBOUND, 60)
    _bot(db, c3, 58, "Sure, sharing the menu.")  # an answer went out...
    _msg(
        db, c3, MessageDirection.OUTBOUND, 57, body="We can do 6 guests.", is_ai_generated=True
    )  # ...and a draft is held
    g4, _, c4 = _lead(db, t.id, name="Answered")  # S5: a full answer
    _worked(db, c4)
    _msg(db, c4, MessageDirection.INBOUND, 60)
    _bot(db, c4, 59, "Yes, it sleeps 4. Check-in is at noon.")

    kinds = {i["title"]: (i["kind"], i["detail"], i["has_draft"]) for i in wq.build(db, t, None)["items"]}
    assert kinds["Promise"][0] == "handover" and "promised" in kinds["Promise"][1]
    assert kinds["Flagged"][0] == "handover" and "Custom route" in kinds["Flagged"][1]
    assert kinds["Draft"][0] == "handover" and kinds["Draft"][2] is True
    assert "Answered" not in kinds
    _person(db, c1)
    assert _item(db, t, g1) is None
    res = wq.build(db, t, None)
    assert res["counts"]["handover"] == 2 and wq.severity_for("handover", _now() - timedelta(minutes=45)) == "late"


# ── S8 ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_s8_date_passed_lost_waits_while_the_guest_wrote_in_the_last_3_days(db):
    from app.services import lead_autopilot_rules as rules
    from app.services.lead_autopilot_service import get_settings

    t = _tenant(db)
    g, inq, conv = _lead(db, t.id, "active", lead_days_ago=20, check_in=(_now() - timedelta(days=4)).date().isoformat())
    inq.current_stage_entered_at = _now() - timedelta(days=15)
    _msg(db, conv, MessageDirection.INBOUND, 60 * 24)  # wrote yesterday
    decide = lambda: rules.evaluate(db, t.id, inq, rules.StageMap.load(db, t.id), get_settings(db, t.id))  # noqa: E731
    assert (decide() or rules.Decision(None, "none", "")).rule != "dates_passed"
    db.query(Message).filter_by(conversation_id=conv.id).update({Message.created_at: _now() - timedelta(days=5)})
    db.commit()
    assert decide().rule == "dates_passed"


# ── S9 ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_s9_sold_guest_writing_again_stays_sold_and_is_a_reply(db):
    t = _tenant(db)
    g, inq, conv = _lead(db, t.id, "sold")
    _msg(db, conv, MessageDirection.INBOUND, 45, body="What time is pickup tomorrow?")
    assert lead_reopen.on_contact(db, t.id, g.id, trigger="whatsapp_message", by_guest=True) is None
    db.refresh(inq)
    assert inq.stage_id == _stages(db, t.id)["sold"].id
    assert _item(db, t, g)["kind"] == "reply"


# ── S10 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _h(u):
    return {
        "Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": u.tenant_id, "role": u.role.value})
    }


def test_s10_unowned_first_and_take_it_claims_once_audited(client, db):
    from tests.conftest import seed_capabilities

    t = _tenant(db)
    seed_capabilities(db, t.id)
    agent, other = _user(db, t.id), _user(db, t.id, name="Ravi Agent")
    owned_g, _, oc = _lead(db, t.id, name="Owned", assigned_to=agent.id, check_in="2026-12-01", adults=6)
    _msg(db, oc, MessageDirection.INBOUND, 40)
    free_g, free, fc = _lead(db, t.id, name="Nobody's")
    _msg(db, fc, MessageDirection.INBOUND, 40)
    items = wq.build(db, t, agent.id)["items"]
    assert [i["title"] for i in items][:2] == ["Nobody's", "Owned"] and items[0]["unowned"] is True

    r = client.post(f"{API}/work-queue/take/{free.id}", headers=_h(agent))
    assert r.status_code == 200 and r.json()["owner_id"] == agent.id
    assert client.post(f"{API}/work-queue/take/{free.id}", headers=_h(other)).status_code == 409
    db.refresh(free)
    assert free.assigned_to == agent.id and free.assignment_method == "claimed"
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="lead.claimed", target_id=free.id).count() == 1
    assert db.get(Conversation, fc.id).assigned_to == agent.id
    foh = _user(db, t.id, role=UserRole.FOH)
    assert client.post(f"{API}/work-queue/take/{free.id}", headers=_h(foh)).status_code == 403

    t2 = _tenant(db)
    seed_capabilities(db, t2.id)
    _, theirs, _ = _lead(db, t2.id, name="Elsewhere")
    assert client.post(f"{API}/work-queue/take/{theirs.id}", headers=_h(agent)).status_code == 404


# ── Isolation, agreement, both stage paths ───────────────────────────────────────────────────────────────────────────


def test_tenant_isolation_of_the_new_kinds(db):
    a, b = _tenant(db), _tenant(db)
    g, _, conv = _lead(db, a.id, "lost", closed_by="system")
    lead_reopen.on_contact(db, a.id, g.id, trigger="whatsapp_message", by_guest=True)
    g2, _, c2 = _lead(db, a.id, name="Promise")
    _worked(db, c2)
    _msg(db, c2, MessageDirection.INBOUND, 60)
    _bot(db, c2, 59, "Our team will call you.")
    db.commit()
    assert {i["kind"] for i in wq.build(db, a, None)["items"]} >= {"came_back", "handover"}
    assert wq.build(db, b, None)["items"] == []
    assert lead_reopen.on_contact(db, b.id, g.id, trigger="whatsapp_message", by_guest=True) is None


def test_my_day_home_and_alerts_read_the_same_items(db):
    from app.services import lead_alert_service, lead_playbook_settings
    from app.services import lead_playbook_catalog as cat

    t = _tenant(db)
    g, _, conv = _lead(db, t.id, name="Promise")
    _worked(db, conv)
    _msg(db, conv, MessageDirection.INBOUND, 60)
    _bot(db, conv, 50, "Our team will call you shortly.")  # 50 min: late
    res = wq.build(db, t, None)
    assert wq.counts(db, t, None)["counts"] == res["counts"]  # My day badge / Calls
    home = dashboard_service.needs_you_now(db, t, None)  # Home cards
    assert home["people"] == res["people"] == 1 and home["breached"] == 1 and res["severity"]["late"] == 1
    _user(db, t.id, role=UserRole.OWNER, name="Owner")
    lead_playbook_settings.update(db, t, None, {"playbooks": {cat.SLA_ESCALATION: {"enabled": True}}})
    db.commit()
    with (
        patch.object(lead_alert_service, "in_quiet_hours", return_value=False),
        patch("app.services.push_service.send_to_tenant") as push,
    ):
        out = lead_alert_service.tick(db, t)
    assert out["fired"] == 1 and push.call_count == 1  # the owner (no managers)


def test_a_returned_lead_closed_again_by_either_stage_path_leaves_the_queue(db):
    t = _tenant(db)
    st = _stages(db, t.id)
    owner = _user(db, t.id, role=UserRole.OWNER, name="Owner")
    for path in ("by_id", "legacy"):
        g, inq, conv = _lead(db, t.id, "lost", closed_by="system", name=f"Back {path}")
        lead_reopen.on_contact(db, t.id, g.id, trigger="whatsapp_message", by_guest=True)
        db.commit()
        assert _item(db, t, g)["kind"] == "came_back"
        if path == "by_id":
            inquiry_service.update_stage_by_id(
                db,
                tenant_id=t.id,
                inquiry_id=inq.id,
                new_stage_id=st["unsuitable"].id,
                actor_user_id=owner.id,
                actor_role="owner",
            )
        else:
            inquiry_service.update_stage(
                db,
                tenant_id=t.id,
                inquiry_id=inq.id,
                new_stage=InquiryStage.GHOSTED,
                actor_user_id=owner.id,
                actor_role="owner",
            )
        db.commit()
        assert _item(db, t, g) is None, path


def test_diagnose_script_counts_the_scenarios_and_writes_nothing(db):
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "diagnose_lead_scenarios.py"
    spec = importlib.util.spec_from_file_location("diagnose_lead_scenarios", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    t = _tenant(db)
    g, _, conv = _lead(db, t.id, "lost", closed_by="system", name="Still Lost")
    _msg(db, conv, MessageDirection.INBOUND, 30)  # wrote after the close, never reopened (old code)
    g2, _, c2 = _lead(db, t.id, name="Promise")
    _worked(db, c2)
    _msg(db, c2, MessageDirection.INBOUND, 60)
    _bot(db, c2, 59, "Our team will call you shortly.")
    before = db.query(AuditEvent).count()
    out = mod.find(db, t, 30)
    assert [r["guest"] for r in out["lost_came_back"]] == ["Still"]
    assert out["bot_handover"][0]["why"] == "promised" and out["bot_handover"][0]["on_my_day"] == "handover"
    assert {r["guest"] for r in out["unowned"]} == {"Promise"}
    assert db.query(AuditEvent).count() == before
    assert "+91" not in str(out)
