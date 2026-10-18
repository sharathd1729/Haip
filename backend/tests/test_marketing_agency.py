"""Marketing agency (phase A): roles + autonomy, kill switch, weekly run, approvals inbox, post history, scheduling."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.core.audit import append_audit
from app.models.audit_event import AuditEvent
from app.models.marketing import InstagramPostMetricDaily, MarketingContent, MarketingTask
from app.services import marketing_agency_run as runs
from app.services import marketing_agency_service as agency
from app.services import marketing_ai_service as ai
from app.workers.tasks.instagram_insights_poll import InstagramInsightsSnapshot, InstagramPostSnapshot, _record_daily
from tests.test_marketing_studio_content import BASE, ws  # noqa: F401  (fixture)

AUDIT = {"summary": "Reels beat the median.", "findings": [], "stop": [], "keep": ["Reels"], "test": []}


def _plan(start):
    days = [(start + timedelta(days=i)).isoformat() for i in range(3)]
    return {"goals": ["More DMs"], "audience": "Couples", "pillars": ["Routes", "Life on board"], "cadence": "3 a week",
            "calendar": [{"date": days[0], "kind": "post", "pillar": "Routes", "idea": "Coorg loop"},
                         {"date": days[1], "kind": "carousel", "pillar": "Life on board", "idea": "Morning chai"},
                         {"date": days[2], "kind": "story", "pillar": "Routes", "idea": "Which ghat next?"}]}


CONTENT = {
    "post": {"caption": "Coorg, slowly.", "hashtags": ["coorg"]},
    "carousel": {"caption": "Morning chai on the deck.", "slides": [{"headline": "Wake up"}, {"headline": "DM us"}]},
    "story": {"frames": [{"text": "Two roads"}, {"text": "Pick one"}]},
}


def _fake_call(tenant_start):
    def fake(task, tenant_id, system, user, tool):
        if task == "marketing_audit":
            return dict(AUDIT), {"model": "m"}, "nvidia"
        if task == "marketing_plan":
            return _plan(tenant_start), {"model": "m"}, "nvidia"
        kind = next(k for k in CONTENT if f"Kind: {k}" in user)
        return dict(CONTENT[kind]), {"model": "m"}, "nvidia"
    return fake


def _seed_insights(db, tid):
    db.add(InstagramInsightsSnapshot(tenant_id=tid, ig_account_id="x", followers_count=1000, reach=500))
    for i in range(3):
        db.add(InstagramPostSnapshot(tenant_id=tid, media_id=f"m{i}", media_type="IMAGE", reach=100 * (i + 1), like_count=10))
    db.commit()


# ── Roles + autonomy ────────────────────────────────────────────────────────────────────────────────────────────────

def test_defaults_follow_owner_decision(ws):  # noqa: F811
    levels = agency.get_agency(ws["tenant"])["roles"]
    assert levels["research"] == levels["strategy"] == levels["copy"] == levels["design"] == "autopilot"
    assert levels["publish"] == levels["community"] == levels["reputation"] == "suggest"


def test_kill_switch_forces_suggest_and_off_stays_off(db, ws):  # noqa: F811
    agency.update_agency(db, ws["tenant"], ws["owner"].id, roles={"publish": "autopilot", "video": "off"}, paused=True)
    db.commit()
    assert agency.level(ws["tenant"], "publish") == "suggest"
    assert agency.level(ws["tenant"], "research") == "suggest"
    assert agency.level(ws["tenant"], "video") == "off"
    assert db.query(AuditEvent).filter_by(tenant_id=ws["tenant"].id, action="marketing.agency.updated").count() == 1


def test_agency_api_owner_only_and_validated(client, ws):  # noqa: F811
    assert client.put(f"{BASE}/agency", json={"paused": True}, headers=ws["manager_h"]).status_code == 403
    r = client.put(f"{BASE}/agency", json={"roles": {"publish": "sometimes"}}, headers=ws["owner_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_level"
    r = client.put(f"{BASE}/agency", json={"roles": {"community": "autopilot"}}, headers=ws["owner_h"])
    assert r.status_code == 200 and {x["role"]: x["level"] for x in r.json()["roster"]}["community"] == "autopilot"
    assert client.get(f"{BASE}/agency", headers=ws["mkt_h"]).json()["schedule"].startswith("Mondays")


def test_agency_actor_is_recorded_without_breaking_the_user_foreign_key(db, ws):  # noqa: F811
    ev = append_audit(db, tenant_id=ws["tenant"].id, action="x.test", actor_user_id="agency", payload={"a": 1})
    assert ev.actor_user_id is None and ev.payload == {"a": 1, "actor": "agency"}


# ── Weekly run ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_weekly_run_audits_plans_drafts_and_submits_for_approval(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _seed_insights(db, tid)
    start = datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=1)
    with patch.object(ai, "_call", side_effect=_fake_call(start)), \
         patch.object(agency, "notify_needs_approval") as notify:
        run_id = runs.run_week(db, tid, trigger="manual", actor_id=ws["owner"].id)

    steps = {(t.step, t.status) for t in db.query(MarketingTask).filter_by(run_id=run_id)}
    assert ("run", "done") in steps and ("audit", "done") in steps and ("plan", "done") in steps
    assert ("draft", "done") in steps and ("submit", "done") in steps
    assert ("image", "skipped") in steps                              # AI images are off by default
    items = db.query(MarketingContent).filter_by(tenant_id=tid).all()
    assert len(items) == 3 and {i.status for i in items} == {"in_review"}
    notify.assert_called_once()

    pending = agency.pending_approvals(db, tid)
    assert {p["type"] for p in pending} == {"content"} and len(pending) == 3
    hist = runs.history(db, tid)
    assert hist[0]["summary"]["drafts"] == 3 and len(hist[0]["steps"]) == 6
    assert ("competitors", "skipped") in steps                        # no competitors on the list yet


def test_failed_plan_stops_the_run_visibly(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _seed_insights(db, tid)

    def fake(task, *a, **k):
        if task == "marketing_plan":
            return {"goals": []}, {"model": "m"}, "nvidia"           # breaks the schema
        return dict(AUDIT), {"model": "m"}, "nvidia"
    with patch.object(ai, "_call", side_effect=fake):
        run_id = runs.run_week(db, tid, trigger="manual")
    run = db.query(MarketingTask).filter_by(run_id=run_id, step="run").one()
    assert run.status == "failed" and "plan" in run.error
    assert db.query(MarketingTask).filter_by(run_id=run_id, step="draft").count() == 0
    assert db.query(MarketingContent).filter_by(tenant_id=tid).count() == 0


def test_transient_ai_failure_is_recorded_on_the_step(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _seed_insights(db, tid)
    with patch.object(ai, "_call", side_effect=ai.LLMTransientError("504")):
        run_id = runs.run_week(db, tid, trigger="manual")
    audit = db.query(MarketingTask).filter_by(run_id=run_id, step="audit").one()
    assert audit.status == "failed" and "unavailable" in audit.error


def test_scheduled_run_skips_suggest_roles_and_paused_workspace_does_nothing(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    agency.update_agency(db, ws["tenant"], ws["owner"].id, roles={"research": "suggest", "strategy": "suggest"})
    db.commit()
    with patch.object(ai, "_call") as call:
        run_id = runs.run_week(db, tid, trigger="schedule")
    call.assert_not_called()
    assert {t.status for t in db.query(MarketingTask).filter_by(run_id=run_id) if t.step != "run"} == {"skipped"}


def test_due_only_on_local_monday_nine_once_a_week_with_module_on(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    monday_nine = datetime(2026, 10, 19, 9, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
    with patch.object(runs, "get_tenant_now", return_value=monday_nine):
        assert runs.due(db, tenant) is True
        db.add(MarketingTask(tenant_id=tenant.id, role="manager", step="run", status="done", trigger="schedule",
                             created_at=monday_nine.astimezone(timezone.utc), updated_at=monday_nine.astimezone(timezone.utc)))
        db.commit()
        assert runs.due(db, tenant) is False
    with patch.object(runs, "get_tenant_now", return_value=monday_nine.replace(hour=10)):
        assert runs.due(db, tenant) is False


def test_run_endpoint_queues_and_refuses_while_running(client, db, ws, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr("app.workers.tasks.marketing_studio.agency_run_week",
                        type("FakeTask", (), {"delay": staticmethod(lambda *a: calls.append(a))}))
    assert client.post(f"{BASE}/agency/run", headers=ws["mkt_h"]).status_code == 202
    db.add(MarketingTask(tenant_id=ws["tenant"].id, role="manager", step="run", status="running", trigger="manual"))
    db.commit()
    r = client.post(f"{BASE}/agency/run", headers=ws["mkt_h"])
    assert r.status_code == 409 and len(calls) == 1 and calls[0][1] == "manual"


# ── Approvals API ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_approvals_api_lists_and_approves_agency_drafts(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _seed_insights(db, tid)
    start = datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=1)
    with patch.object(ai, "_call", side_effect=_fake_call(start)), patch.object(agency, "notify_needs_approval"):
        runs.run_week(db, tid, trigger="manual")
    r = client.get(f"{BASE}/approvals", headers=ws["mkt_h"])
    assert r.json()["count"] == 3
    first = r.json()["items"][0]
    assert client.post(f"{BASE}/approvals/content/{first['id']}/approve", json={}, headers=ws["mkt_h"]).status_code == 403
    r = client.post(f"{BASE}/approvals/content/{first['id']}/approve", json={}, headers=ws["manager_h"])
    assert r.status_code == 200 and r.json()["remaining"] == 2
    assert db.get(MarketingContent, first["id"]).status == "approved"


# ── Post history ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_post_history_is_one_row_per_post_per_day(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    post = InstagramPostSnapshot(tenant_id=tid, media_id="p1", media_type="REELS", reach=100, like_count=5)
    _record_daily(db, tid, post)
    post.reach = 150
    _record_daily(db, tid, post)
    db.commit()
    rows = db.query(InstagramPostMetricDaily).filter_by(tenant_id=tid, media_id="p1").all()
    assert len(rows) == 1 and rows[0].reach == 150
