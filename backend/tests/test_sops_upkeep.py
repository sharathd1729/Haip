"""Get found phase S3 (docs/sops/DYNAMIC_SOPS_PLAN.md): recurring cycles, tasks for due steps, reminders (assignee, then
managers; push always, staff WhatsApp only when allowed; quiet hours hold), the nightly refresh, the upkeep checks, the
AI Executive signals and their API (happy path, wrong role, cross-tenant)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.marketing import MarketingContent, MarketingGuestReview, MarketingPublishAttempt
from app.models.sop import SopStepProgress
from app.models.task import Task
from app.models.user import UserRole
from app.schemas.sops import StartIn
from app.services import lead_alert_sender, marketing_demand, task_service
from app.services.sops import catalogue, checks, generate, signals, upkeep
from app.services.sops import service as svc
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, tenant
from tests.test_increment1_defect_specs import _h, _user

NOON_IST = datetime(2026, 11, 4, 6, 30, tzinfo=UTC)  # 12:00 IST, outside the default 22-8 quiet hours


@pytest.fixture()
def w(db, monkeypatch):
    t = tenant(db)
    t.business_type, t.brand_name = "villa", "Palm Villas"
    t.brand_config = {"business_profile": {"description": "Two pool villas near Nandi Hills."}}
    prop(db, t.id, "Villa One")
    owner, mgr = _user(db, t.id, UserRole.OWNER), _user(db, t.id, UserRole.MANAGER)
    pushes = []
    monkeypatch.setattr(
        "app.services.push_service.send_to_tenant",
        lambda db, tid, title, body, url="", tag="", user_id=None: pushes.append((user_id, title)),
    )
    db.commit()
    return type("W", (), {"t": t, "owner": owner, "mgr": mgr, "pushes": pushes})()


def _start(db, w, key, now=NOON_IST, monkeypatch=None):
    if monkeypatch:
        monkeypatch.setattr(svc, "_now", lambda: now)
    inst = svc.start(db, w.t, StartIn(template_key=key), w.owner.id)
    generate.make_version(db, w.t, inst, reason="first", actor_id=w.owner.id, use_ai=False)
    db.commit()
    return inst


def _prog(db, inst, key):
    return db.query(SopStepProgress).filter_by(instance_id=inst.id, cycle_no=inst.cycle_no, step_key=key).one()


def test_weekly_cycle_dates_and_the_next_cycle(db, w, monkeypatch):
    inst = _start(db, w, "gbp_upkeep", monkeypatch=monkeypatch)
    assert upkeep._aware(inst.next_cycle_at) == NOON_IST + timedelta(days=7)
    assert all(
        upkeep._aware(p.due_at) <= NOON_IST + timedelta(days=6)
        for p in db.query(SopStepProgress).filter_by(instance_id=inst.id)
    )
    svc.mark(db, inst, "photos", "done", w.owner.id)
    upkeep.make_tasks(db, w.t, NOON_IST + timedelta(days=5))
    open_task = _prog(db, inst, "reviews").task_id
    assert upkeep.open_cycles(db, w.t, NOON_IST + timedelta(days=8)) == 1
    assert inst.cycle_no == 2 and inst.status == "active"
    assert _prog(db, inst, "photos").status == "todo"  # a new week starts fresh
    assert db.get(Task, open_task).is_done  # last week's task closed


def test_seasonal_cycle_opens_21_days_before_the_next_long_weekend(db, w, monkeypatch):
    monkeypatch.setattr(
        marketing_demand,
        "long_weekends",
        lambda *a: [{"start": "2027-01-23", "end": "2027-01-26", "days": 4, "reason": "Republic Day"}],
    )
    nxt = upkeep.next_cycle_at(db, w.t, catalogue.BY_KEY["airbnb_promos"], NOON_IST)
    assert nxt.date().isoformat() == "2027-01-02" and nxt.hour == 9
    assert upkeep.next_cycle_at(db, w.t, catalogue.BY_KEY["gbp_setup"], NOON_IST) is None


def test_due_steps_become_one_task_and_ticking_closes_it(db, w, monkeypatch):
    inst = _start(db, w, "gbp_upkeep", monkeypatch=monkeypatch)
    assert upkeep.make_tasks(db, w.t, NOON_IST) == 0  # nothing due within a day yet
    later = NOON_IST + timedelta(days=5)
    n = upkeep.make_tasks(db, w.t, later)
    assert n >= 2 and upkeep.make_tasks(db, w.t, later) == 0  # never twice
    t = db.get(Task, _prog(db, inst, "photos").task_id)
    assert t.kind == "sop" and t.assigned_to == w.owner.id and "Add one or two new photos" in t.title
    task_service.toggle_task(db, w.t.id, t.id, actor_id=w.owner.id)  # closed from My day: a manual step ticks
    assert _prog(db, inst, "photos").status == "done"
    auto = db.get(Task, _prog(db, inst, "reviews").task_id)
    task_service.toggle_task(db, w.t.id, auto.id, actor_id=w.owner.id)  # HAIP checks this one: stays open
    assert _prog(db, inst, "reviews").status == "todo"
    svc.add_evidence_link(db, inst, "post", "https://example.com/p", w.owner.id)
    svc.mark(db, inst, "post", "done", w.owner.id)
    assert db.get(Task, _prog(db, inst, "post").task_id).is_done


def test_reminders_climb_from_assignee_to_managers_and_respect_quiet_hours(db, w, monkeypatch):
    inst = _start(db, w, "gbp_monthly", monkeypatch=monkeypatch)
    overdue = NOON_IST + timedelta(days=8)
    quiet = overdue.replace(hour=18)  # 23:30 IST
    assert upkeep.remind(db, w.t, quiet) == 0 and w.pushes == []
    assert upkeep.remind(db, w.t, overdue) == 1
    assert w.pushes[0][0] == w.owner.id and _prog(db, inst, "info").reminder_level == 1
    assert upkeep.remind(db, w.t, overdue + timedelta(hours=1)) == 0  # once per level
    upkeep.remind(db, w.t, overdue + timedelta(days=3))  # "info" is now 3 days past the first nudge
    assert w.mgr.id in {u for u, _ in w.pushes[1:]} and _prog(db, inst, "info").reminder_level == 2


def test_staff_whatsapp_only_when_opted_in_and_template_approved(db, w, monkeypatch):
    sent = []
    monkeypatch.setattr(
        lead_alert_sender,
        "deliver",
        lambda db, a, phone, values, with_buttons=True: sent.append((a.playbook_key, phone, values)) or True,
    )
    monkeypatch.setattr(lead_alert_sender, "template_approved", lambda db, tid, name: None)
    w.owner.phone, w.owner.whatsapp_alerts_opt_in_at = "+919845012345", NOON_IST
    _start(db, w, "gbp_monthly", monkeypatch=monkeypatch)
    upkeep.remind(db, w.t, NOON_IST + timedelta(days=8))
    assert sent == [] and len(w.pushes) == 1  # not approved yet: push only
    monkeypatch.setattr(lead_alert_sender, "template_approved", lambda db, tid, name: "en")
    _start(db, w, "maps_hygiene", monkeypatch=monkeypatch)
    upkeep.remind(db, w.t, NOON_IST + timedelta(days=9))
    assert sent and sent[0][0] == "sop" and sent[0][1] == "+919845012345"


def test_nightly_refresh_only_when_the_facts_changed(db, w, monkeypatch):
    inst = _start(db, w, "gbp_setup", monkeypatch=monkeypatch)
    assert upkeep.stale_reason(db, w.t, inst) is None
    w.t.brand_config = {"business_profile": {"description": "Three pool villas near Nandi Hills."}}
    db.flush()
    assert upkeep.refresh(db, w.t) == [(inst.id, "data_changed")] and inst.generating == "queued"


def test_upkeep_checks(db, w, monkeypatch):
    inst = _start(db, w, "reviews_reply", monkeypatch=monkeypatch)
    assert checks.run("google_reviews_answered", db, w.t, inst)["result"] == "unknown"  # Google not connected
    from app.models.integration import Integration

    db.add(Integration(tenant_id=w.t.id, kind="google_business", status="active", config={}))
    db.add(
        MarketingGuestReview(
            tenant_id=w.t.id,
            source="google",
            external_id="r1",
            rating=4,
            reviewed_at=(datetime.now(UTC) - timedelta(days=5)).isoformat(),
        )
    )
    db.flush()
    assert checks.run("google_reviews_answered", db, w.t, inst)["result"] == "fail"
    assert checks.run("gbp_posted_7d", db, w.t, inst)["result"] == "fail"
    content = MarketingContent(tenant_id=w.t.id, kind="post", title="Weekend post")
    db.add(content)
    db.flush()  # marketing_publish_attempts.content_id is a real FK on PostgreSQL
    db.add(
        MarketingPublishAttempt(
            tenant_id=w.t.id,
            content_id=content.id,
            version_id="v1",
            sha256="0" * 64,
            scheduled_for=datetime.now(UTC),
            status="published",
            channel="google",
            published_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    db.flush()
    assert checks.run("gbp_posted_7d", db, w.t, inst)["result"] == "ok"
    assert checks.run("website_live", db, w.t, inst)["result"] == "fail"


def test_signals_for_the_ai_executive(db, w, monkeypatch):
    w.t.created_at = NOON_IST - timedelta(days=30)
    inst = _start(db, w, "gbp_setup", monkeypatch=monkeypatch)
    inst.created_at = NOON_IST - timedelta(days=20)
    db.flush()
    sig = {s["code"]: s for s in signals.signals(db, w.t, NOON_IST + timedelta(days=20))}
    assert sig["gbp_unverified"]["days"] == 40 and sig["gbp_unverified"]["instance_id"] == inst.id
    assert sig["sop_overdue"]["platform"] == "google_business" and sig["sop_overdue"]["numbers"]["steps"] >= 1
    assert sig["gbp_no_post"]["platform"] == "google_business"
    assert sig["sop_not_started"]["numbers"]["template"] == "instagram_profile"


def test_signals_and_templates_api(client, db, w, monkeypatch):
    seed_capabilities(db, w.t.id)
    _start(db, w, "gbp_setup", monkeypatch=monkeypatch)
    r = client.get("/api/v1/sops/signals", headers=_h(w.mgr))
    assert r.status_code == 200 and isinstance(r.json(), list)
    assert client.get("/api/v1/sops/signals", headers=_h(_user(db, w.t.id, UserRole.COMPLIANCE))).status_code == 403
    other = tenant(db)
    seed_capabilities(db, other.id)
    om = _user(db, other.id, UserRole.MANAGER)
    assert all(s["instance_id"] is None for s in client.get("/api/v1/sops/signals", headers=_h(om)).json())
    assert client.post("/api/v1/sops/templates", headers=_h(_user(db, w.t.id, UserRole.FOH))).status_code == 403
    r = client.post("/api/v1/sops/templates", headers=_h(w.mgr))
    assert r.status_code == 201 and r.json()["created"] == ["haip_staff_sop_due_v1"]
    assert client.post("/api/v1/sops/templates", headers=_h(w.mgr)).json()["created"] == []
