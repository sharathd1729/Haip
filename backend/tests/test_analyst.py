"""AI business analyst: statistics, number grounding, facts, the brief (LLM scripted, deterministic fallback), storage, the
schedule tick, endpoints (happy / wrong role / other tenant), delivery tokens + the signed page + tap-to-assign, follow-ups."""
import json
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


from app.models.analyst import AnalystReport
from app.models.audit_event import AuditEvent
from app.models.inquiry import Inquiry
from app.services.analyst import ask, brief, delivery, facts, grounding, reports, settings as asettings, stats
from app.services.analyst.periods import windows
from app.services.date_presets import IST
from tests.analyst_world import world
from tests.test_increment1_defect_specs import _h

R = "/api/v1/analyst"


def _llm(content: str):
    class _L:
        provider = "scripted"

        async def complete(self, **kw):
            return {"content": content, "model": "scripted-model"}
    return lambda task, *a, **k: _L()


# ── statistics ────────────────────────────────────────────────────────────────────────────────────────────────

def test_stats_wilson_and_two_proportion():
    lo, hi = stats.wilson(20, 50)
    assert lo < 0.4 < hi and stats.wilson(0, 0) is None
    t = stats.two_proportion(10, 100, 30, 100)
    assert t["diff"] == 0.2 and t["p_two_sided"] < 0.01 and t["p_lower"] > 0.99
    assert stats.compare(5, 20, 10, 20)["verdict"] == "too_few"
    assert stats.compare(10, 100, 30, 100)["verdict"] == "up"
    assert stats.compare(30, 100, 31, 100)["verdict"] == "steady"
    assert stats.compare_counts(5, 50)["verdict"] == "too_few"
    assert stats.compare_counts(20, 60, prev_days=7, cur_days=7)["verdict"] == "up"


# ── grounding ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_grounding_drops_sentences_with_invented_numbers():
    f = {"leads": 12, "rate": 0.4235, "value": 125000.0, "period": {"from": "2026-10-19"}}
    allowed = grounding.allowed_numbers(f)
    dropped = []
    text = grounding.clean_text("12 new leads. 42% gave a number. Revenue ₹1,25,000 on 19 Oct. We could get 99 more.",
                                allowed, "x", dropped)
    assert "99" not in text and "12 new leads." in text and "₹1,25,000" in text
    assert dropped and dropped[0]["numbers"] == ["99"]


def test_brief_validate_drops_and_keeps():
    f = {"findings": [], "leads": 7}
    b, dropped = brief.validate({"headline": "7 leads came in.", "working": ["Replies were fast at 3 minutes."],
                                 "recommendations": [{"action": "Call 15 leads", "owner_role": "sales"},
                                                     {"action": "Call every lead", "owner_role": "sales"}]}, f)
    assert b["headline"] == "7 leads came in." and b["working"] == []
    assert [r["action"] for r in b["recommendations"]] == ["Call every lead"] and len(dropped) == 2
    assert brief.validate({"headline": "Up 50%."}, f)[0] is None             # nothing usable left
    assert brief.inr(125000) == "₹1,25,000" and brief.inr(12345678) == "₹1,23,45,678"


# ── facts + brief + storage ───────────────────────────────────────────────────────────────────────────────────

def test_facts_for_the_daily_pulse(db):
    w = world(db)
    today = datetime.now(IST).date()
    out = facts.build(db, w.t, "daily_pulse", today)
    j = out["journey"]
    assert j["contacts"]["to_lead"] == {"n": 4, "x": 2, "rate": 0.5}
    assert j["leads"]["new"] == 2 and j["revenue"]["bookings"] == 1 and j["revenue"]["booked_value"] == 125000.0
    assert {c["key"] for c in out["health"]} == {"pricing", "routes_packages", "communication", "response_time",
                                                  "team_activity", "follow_ups"}
    team = {r["name"]: r for r in out["team"]}
    assert team["manager"]["calls_received"] == 1 and team["manager"]["missed_not_returned"] == 1
    assert out["period"]["from"] == (today - timedelta(days=1)).isoformat()
    assert not any(k.startswith("_") for k in json.dumps(out) if False)
    assert "_workflow_agents" not in out["journey"] and "_evidence" not in out["pricing"]
    comm = next(c for c in out["health"] if c["key"] == "communication")
    quote = comm["evidence"]["quotes"][0]
    assert quote["who"].startswith("Guest") and "Kumar" not in quote["who"] and "98456" not in quote["text"]
    assert out["demand"]["routes_asked"][0] == {"label": "Goa", "count": 2}


def test_generate_with_the_model_and_without(db):
    w = world(db)
    good = json.dumps({"headline": "2 of 4 people gave a phone number.", "working": ["1 booking came in."],
                       "not_working": ["Invented 777 figure here."], "recommendations": []})
    with patch("app.adapters.llm.get_llm", _llm(good)):
        r = reports.generate(db, w.t, "daily_pulse")
    assert r.brief_source == "llm" and r.brief["headline"].startswith("2 of 4")
    assert r.brief["not_working"] == [] and r.validation["dropped"][0]["numbers"] == ["777"]
    assert r.prompt_version == "analyst-brief-v1"
    # the period's report exists: a second scheduled run is a no-op, a manual run recomputes in place
    with patch("app.adapters.llm.get_llm", side_effect=RuntimeError("down")):
        assert reports.generate(db, w.t, "daily_pulse").id == r.id
        again = reports.generate(db, w.t, "daily_pulse", force=True)
    assert again.id == r.id and again.brief_source == "deterministic" and again.validation["llm"].startswith("failed")
    assert db.query(AnalystReport).filter_by(tenant_id=w.t.id).count() == 1
    other = world(db)
    assert reports.list_reports(db, other.t.id) == []


def test_tick_queues_only_due_enabled_workspaces(db):
    on = world(db, brand_config={"analyst": {"enabled": True}})
    world(db)                                                                # off by default
    s = asettings.get(on.t)
    nine = datetime(2026, 10, 19, 9, 5, tzinfo=IST)                          # a Monday
    assert asettings.is_due(s, "daily_pulse", nine) and asettings.is_due(s, "weekly_brief", nine)
    assert not asettings.is_due(s, "daily_pulse", nine.replace(hour=8))
    assert not asettings.is_due(asettings.get(world(db).t), "daily_pulse", nine)
    from app.workers.tasks import analyst_tasks
    with patch.object(analyst_tasks.run_report, "delay") as delay, \
            patch("app.services.analyst.periods.local_now", return_value=nine), \
            patch("app.workers.tasks.analyst_tasks.SessionLocal", return_value=db), patch.object(db, "close"):
        analyst_tasks.tick()
    queued = {(c.args[0], c.args[1]) for c in delay.call_args_list}
    assert (on.t.id, "daily_pulse") in queued and all(tid == on.t.id for tid, _ in queued)


def test_windows():
    from datetime import date
    cur, prev, base = windows("weekly_brief", date(2026, 10, 21))
    assert (cur.d_from, cur.d_to) == (date(2026, 10, 12), date(2026, 10, 18)) and prev.d_to == date(2026, 10, 11)
    cur, prev, base = windows("monthly_review", date(2026, 10, 1))
    assert (cur.d_from, cur.d_to, prev.d_from, base.d_from) == (date(2026, 9, 1), date(2026, 9, 30), date(2026, 8, 1),
                                                                date(2026, 6, 1))


# ── endpoints ─────────────────────────────────────────────────────────────────────────────────────────────────

def _report(db, w):
    with patch("app.adapters.llm.get_llm", side_effect=RuntimeError("off")):
        return reports.generate(db, w.t, "daily_pulse")


def test_endpoints_roles_and_tenants(client, db):
    w = world(db)
    r = _report(db, w)
    rows = client.get(f"{R}/reports", headers=_h(w.mgr)).json()
    assert rows[0]["id"] == r.id and len(rows[0]["health"]) == 6
    one = client.get(f"{R}/reports/{r.id}", headers=_h(w.owner)).json()
    assert one["brief"]["headline"] and one["facts"]["journey"]["revenue"]["bookings"] == 1
    assert client.get(f"{R}/reports", headers=_h(w.foh)).status_code == 403
    other = world(db)
    assert client.get(f"{R}/reports/{r.id}", headers=_h(other.owner)).status_code == 404
    with patch("app.workers.tasks.analyst_tasks.run_report.delay") as d:
        assert client.post(f"{R}/reports/run", json={"kind": "weekly_brief"}, headers=_h(w.mgr)).status_code == 202
    assert d.call_args.args == (w.t.id, "weekly_brief") and d.call_args.kwargs["force"] is True
    assert client.post(f"{R}/reports/run", json={"kind": "weekly_brief"}, headers=_h(w.foh)).status_code == 403
    with patch("app.workers.tasks.analyst_tasks.answer_followup.delay") as d:
        item = client.post(f"{R}/ask", json={"report_id": r.id, "question": "Why did leads drop?"}, headers=_h(w.mgr)).json()
        assert client.post(f"{R}/ask", json={"report_id": r.id, "question": "Why?"}, headers=_h(other.owner)).status_code == 404
    assert item["status"] == "queued" and d.call_count == 1


def test_settings_owner_only_and_patch_refused(client, db):
    w = world(db)
    body = {"enabled": True, "daily": {"on": True, "time": "09:00"}, "weekly": {"on": False, "time": "08:30"},
            "monthly": {"on": True, "time": "08:30"}, "delivery": {"email": True, "whatsapp": False}}
    assert client.put(f"{R}/settings", json=body, headers=_h(w.mgr)).status_code == 403
    got = client.put(f"{R}/settings", json=body, headers=_h(w.owner)).json()
    assert got["settings"]["enabled"] is True and "weekly" in got["changed"]
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="analyst.settings_changed").count() == 1
    assert client.put(f"{R}/settings", json={**body, "daily": {"on": True, "time": "25:00"}}, headers=_h(w.owner)).status_code == 422
    for key in ("analyst", "learning"):
        res = client.patch("/api/v1/tenants/me", json={"brand_config": {key: {"enabled": True}}}, headers=_h(w.owner))
        assert res.status_code == 422, key


# ── delivery + signed page ────────────────────────────────────────────────────────────────────────────────────

def test_signed_page_pdf_and_assign(client, db):
    w = world(db)
    r = _report(db, w)
    token = delivery.make_token(r, w.mgr.id)
    page = client.get(f"/api/v1/public/analyst/{token}").json()
    assert page["brief"]["headline"] and page["viewer"]["first_name"] == "manager" and "validation" not in page
    pdf = client.get(f"/api/v1/public/analyst/{token}/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get("/api/v1/public/analyst/not-a-token").status_code == 404
    expired = delivery.make_token(r, w.mgr.id, now=datetime.now(timezone.utc) - timedelta(days=8))
    assert client.get(f"/api/v1/public/analyst/{expired}").status_code == 404

    inq = w.inqs[1]
    sent = []

    async def _send(to, subject, html, text=None, **kw):
        sent.append(text or html)
        return True
    with patch("app.services.email_service._send", _send), \
            patch("app.services.lead_assignment_service.eligible_agents", return_value=[w.mgr, w.owner]):
        start = client.post(f"/api/v1/public/analyst/{token}/assign/start", json={"inquiry_id": inq.id, "user_id": w.owner.id}).json()
        code = re.search(r"(\d{6})", sent[0]).group(1)
        wrong = "000000" if code != "000000" else "111111"
        assert client.post(f"/api/v1/public/analyst/{token}/assign/confirm",
                           json={"nonce": start["nonce"], "code": wrong}).status_code == 422
        # the nonce was single-use: start again
        start = client.post(f"/api/v1/public/analyst/{token}/assign/start", json={"inquiry_id": inq.id, "user_id": w.owner.id}).json()
        code = re.search(r"(\d{6})", sent[1]).group(1)
        ok = client.post(f"/api/v1/public/analyst/{token}/assign/confirm", json={"nonce": start["nonce"], "code": code})
        assert ok.status_code == 200, ok.text
        assert client.post(f"/api/v1/public/analyst/{token}/assign/confirm",
                           json={"nonce": start["nonce"], "code": code}).status_code == 410
    db.expire_all()
    assert db.query(Inquiry).filter_by(id=inq.id).one().assigned_to == w.owner.id
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="analyst.lead_assigned").count() == 1


def test_deliver_email_and_whatsapp_needs_approved_template(db):
    w = world(db, brand_config={"analyst": {"enabled": True, "delivery": {"email": True, "whatsapp": True}}})
    r = _report(db, w)
    sent = []

    async def _send(to, subject, html, text=None, **kw):
        sent.append((to, html))
        return True
    with patch("app.services.email_service._send", _send):
        out = delivery.deliver(db, w.t, r)
    assert out["email"]["sent"] == 2 and "/r/analyst/" in sent[0][1]
    assert out["whatsapp"]["status"] == "not_sent" and "not approved" in out["whatsapp"]["reason"]
    assert r.delivery["at"]


def test_followup_answer_is_grounded_and_audited(db):
    from app.models.ask_haip import AskHaipFreeformQuery
    AskHaipFreeformQuery.__table__.create(bind=db.get_bind(), checkfirst=True)     # migration 052's table (not in create_all)
    w = world(db)
    r = _report(db, w)
    item = ask.queue(db, r, w.mgr.id, "How many leads?")
    db.commit()
    with patch("app.adapters.llm.get_llm", _llm(json.dumps({"answer": "2 new leads. Maybe 55 next week."}))):
        assert ask.answer(db, r, item["id"])["status"] == "answered"
    got = next(f for f in r.followups if f["id"] == item["id"])
    assert got["answer"] == "2 new leads." and got["dropped"] == 1
    assert db.query(AskHaipFreeformQuery).filter_by(tenant_id=w.t.id, status="ok").count() == 1


def test_delivery_template_is_only_a_draft(client, db):
    w = world(db)
    got = client.post(f"{R}/templates", headers=_h(w.mgr)).json()
    assert got["created"] == ["haip_analyst_brief_v1"] and got["templates"][0]["status"] == "draft"
    assert client.post(f"{R}/templates", headers=_h(w.mgr)).json()["created"] == []
    assert client.post(f"{R}/templates", headers=_h(w.foh)).status_code == 403


def test_assign_a_recommendation(client, db):
    w = world(db)
    r = _report(db, w)
    r.brief = {**r.brief, "recommendations": [{"action": "Return missed calls", "owner_role": "sales", "due": "today",
                                               "expected_effect": "", "change_proposal": None}]}
    db.commit()
    url = f"{R}/reports/{r.id}/recommendations/0/assign"
    with patch("app.services.push_service.send_to_tenant") as push:
        got = client.post(url, json={"user_id": w.mgr.id}, headers=_h(w.owner))
    assert got.status_code == 200 and got.json()["assigned_to"] == w.mgr.id and push.call_args.kwargs["user_id"] == w.mgr.id
    assert client.post(f"{R}/reports/{r.id}/recommendations/5/assign", json={"user_id": w.mgr.id}, headers=_h(w.owner)).status_code == 404
    assert client.post(url, json={"user_id": w.mgr.id}, headers=_h(w.foh)).status_code == 403
    other = world(db)
    assert client.post(url, json={"user_id": other.mgr.id}, headers=_h(other.owner)).status_code == 404
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="analyst.recommendation_assigned").count() == 1
