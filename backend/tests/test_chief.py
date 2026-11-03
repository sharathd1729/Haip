"""AI Executive E1 (services/chief): detectors raise / update / resolve findings in the insights table, a failing rule changes
nothing, dismissal snoozes, explanations are number-grounded, the analyst brief carries the block, endpoints (happy / wrong
role / other tenant), settings owner-only and refused through PATCH /tenants/me."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.models.audit_event import AuditEvent
from app.models.ical_feed import ICalFeed
from app.models.insight import Insight
from app.models.property import Stay
from app.services import booking_agenda_service
from app.services.analyst import brief, facts
from app.services.chief import catalogue, detectors, explain, findings
from tests.analyst_world import world
from tests.test_increment1_defect_specs import _h

R = "/api/v1/chief"
ON = {"chief": {"enabled": True}}


def _feed(db, w, status="error") -> ICalFeed:
    f = ICalFeed(
        id=str(uuid.uuid4()),
        tenant_id=w.t.id,
        property_id=w.prop.id,
        name="Airbnb",
        export_token=uuid.uuid4().hex,
        is_active=True,
        last_status=status,
        last_error="HTTP 404" if status == "error" else None,
    )
    db.add(f)
    db.commit()
    return f


def _open(db, tenant_id, code):
    return (
        db.query(Insight)
        .filter_by(tenant_id=tenant_id, category_code=code, is_dismissed=False, is_auto_resolved=False)
        .all()
    )


def _llm(content: str):
    class _L:
        provider = "scripted"

        async def complete(self, **kw):
            return {"content": content, "model": "scripted-model"}

    return lambda task, *a, **k: _L()


def test_off_by_default_runs_nothing(db):
    w = world(db)
    _feed(db, w)
    out = findings.run(db, w.t, "daily")
    assert out["skipped"] is True and out["ran"] == 0
    assert _open(db, w.t.id, "TE4") == []


def test_raise_update_resolve_with_audit(db):
    w = world(db, brand_config=ON)
    f = _feed(db, w)
    out = findings.run(db, w.t, "urgent")
    db.commit()
    rows = _open(db, w.t.id, "TE4")
    assert out["failed"] == [] and len(rows) == 1
    row = rows[0]
    assert (
        row.role == "it_monitor" and row.numbers == {"feeds": 1} and row.evidence == [{"type": "ical_feed", "id": f.id}]
    )
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.finding_raised").count() >= 1
    findings.run(db, w.t, "urgent")  # same condition: the same row, not a second one
    db.commit()
    assert len(_open(db, w.t.id, "TE4")) == 1
    f.last_status = "ok"
    db.commit()
    findings.run(db, w.t, "urgent")
    db.commit()
    db.refresh(row)
    assert row.is_auto_resolved is True
    assert (
        db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.finding_resolved", target_id=row.id).count() == 1
    )


def test_a_failing_rule_changes_nothing(db):
    w = world(db, brand_config=ON)
    _feed(db, w)
    findings.run(db, w.t, "urgent")
    db.commit()
    det = catalogue.BY_CODE["TE4"]
    broken = catalogue.Detector(
        det.code,
        det.role,
        det.cadence,
        det.category,
        det.next_step,
        lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with patch.object(catalogue, "CATALOGUE", (broken,)):
        out = findings.run(db, w.t, "urgent")
    db.commit()
    assert out["failed"] == ["TE4"] and len(_open(db, w.t.id, "TE4")) == 1


def test_roles_and_detectors_switched_off_are_skipped(db):
    w = world(db, brand_config={"chief": {"enabled": True, "roles_off": ["it_monitor"]}})
    _feed(db, w)
    findings.run(db, w.t, "urgent")
    assert _open(db, w.t.id, "TE4") == []


def test_sales_unattended_rule_names_the_missing_setup(db):
    w = world(db, brand_config=ON)
    ctx = detectors.Ctx(db, w.t)
    item = {
        "kind": "new_lead",
        "severity": "urgent",
        "inquiry_id": w.inqs[0].id,
        "guest_id": w.guests[0].id,
        "href": "/x",
    }
    ctx._queue = {"items": [item, {**item, "severity": "critical"}, {**item, "kind": "reply"}]}
    hits = detectors.sales_unattended(ctx)
    assert len(hits) == 1 and hits[0]["severity"] == "critical"
    assert hits[0]["numbers"] == {"waiting": 3, "critical": 1, "staff_opted_in": 0}
    assert "switched off" in hits[0]["body"] and "not approved by Meta" in hits[0]["body"]
    assert hits[0]["evidence"][0] == {"type": "inquiry", "id": w.inqs[0].id, "href": f"/dashboard/leads/{w.inqs[0].id}"}
    ctx._queue = {"items": [item, item]}  # fewer than three: nothing
    assert detectors.sales_unattended(ctx) == []


def test_arrivals_tomorrow_with_a_balance(db):
    w = world(db, brand_config=ON)
    tomorrow = booking_agenda_service.tenant_today(db, w.t.id) + timedelta(days=1)
    s = Stay(
        id=str(uuid.uuid4()),
        tenant_id=w.t.id,
        guest_id=w.guests[0].id,
        property_id=w.prop.id,
        check_in=tomorrow,
        check_out=tomorrow + timedelta(days=2),
        status="confirmed",
        total_amount=40000,
    )
    db.add(s)
    db.commit()
    hits = detectors.finance_arrivals_owing(detectors.Ctx(db, w.t))
    assert hits[0]["numbers"] == {"bookings": 1} and hits[0]["evidence"][0]["id"] == s.id


def test_dismiss_snoozes_seven_days(client, db):
    w = world(db, brand_config=ON)
    _feed(db, w)
    findings.run(db, w.t, "urgent")
    db.commit()
    row = _open(db, w.t.id, "TE4")[0]
    got = client.post(f"{R}/findings/{row.id}/dismiss", json={"reason": "already_handled"}, headers=_h(w.mgr))
    assert (
        got.status_code == 200
        and got.json()["status"] == "dismissed"
        and got.json()["dismiss_reason"] == "already_handled"
    )
    assert client.post(f"{R}/findings/{row.id}/dismiss", json={"reason": "wrong"}, headers=_h(w.mgr)).status_code == 409
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.finding_dismissed").count() == 1
    findings.run(db, w.t, "urgent")
    assert _open(db, w.t.id, "TE4") == []  # snoozed
    findings.run(db, w.t, "urgent", now=datetime.now(UTC) + timedelta(days=8))
    assert len(_open(db, w.t.id, "TE4")) == 1  # back after the snooze


def test_endpoints_roles_and_tenants(client, db):
    w = world(db, brand_config=ON)
    _feed(db, w)
    findings.run(db, w.t, "urgent")
    db.commit()
    home = client.get(f"{R}/home", headers=_h(w.mgr)).json()
    it = next(r for r in home["roles"] if r["key"] == "it_monitor")
    assert it["findings"][0]["code"] == "TE4" and it["findings"][0]["next_step"] and home["counts"]["open"] >= 1
    assert client.get(f"{R}/home", headers=_h(w.foh)).status_code == 403
    assert client.get(f"{R}/findings", headers=_h(w.foh)).status_code == 403
    other = world(db, brand_config=ON)
    assert client.get(f"{R}/findings", headers=_h(other.owner)).json() == []
    row = _open(db, w.t.id, "TE4")[0]
    assert (
        client.post(f"{R}/findings/{row.id}/dismiss", json={"reason": "wrong"}, headers=_h(other.owner)).status_code
        == 404
    )
    assert client.get(f"{R}/findings", params={"role": "nobody"}, headers=_h(w.mgr)).status_code == 422
    with patch("app.workers.tasks.chief_tasks.detect_tenant.delay") as d:
        assert client.post(f"{R}/run", headers=_h(w.mgr)).status_code == 202
        assert client.post(f"{R}/run", headers=_h(w.foh)).status_code == 403
    assert d.call_args.args == (w.t.id, "daily")


def test_tenant_isolation_in_the_service(db):
    a, b = world(db, brand_config=ON), world(db, brand_config=ON)
    _feed(db, a)
    findings.run(db, a.t, "urgent")
    findings.run(db, b.t, "urgent")
    db.commit()
    assert len(_open(db, a.t.id, "TE4")) == 1 and _open(db, b.t.id, "TE4") == []
    row = _open(db, a.t.id, "TE4")[0]
    assert findings.get(db, b.t.id, row.id) is None


def test_settings_owner_only_and_patch_refused(client, db):
    w = world(db)
    body = {"enabled": True, "paused": False, "roles_off": [], "detectors_off": ["OW3"]}
    assert client.put(f"{R}/settings", json=body, headers=_h(w.mgr)).status_code == 403
    with patch("app.workers.tasks.chief_tasks.detect_tenant.delay") as d:
        got = client.put(f"{R}/settings", json=body, headers=_h(w.owner)).json()
    assert (
        got["settings"]["enabled"] is True and set(got["changed"]) == {"enabled", "detectors_off"} and d.call_count == 1
    )
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.settings_changed").count() == 1
    assert client.put(f"{R}/settings", json={**body, "detectors_off": ["NOPE"]}, headers=_h(w.owner)).status_code == 422
    res = client.patch("/api/v1/tenants/me", json={"brand_config": {"chief": {"enabled": False}}}, headers=_h(w.owner))
    assert res.status_code == 422
    assert client.get(f"{R}/settings", headers=_h(w.mgr)).json()["detectors"]


def test_run_when_off_is_refused(client, db):
    w = world(db)
    assert client.post(f"{R}/run", headers=_h(w.owner)).status_code == 409


def test_explanations_are_grounded_and_paused_skips(db):
    w = world(db, brand_config=ON)
    _feed(db, w)
    findings.run(db, w.t, "urgent")
    db.commit()
    row = _open(db, w.t.id, "TE4")[0]
    bad = json.dumps({"items": [{"id": row.id, "why": "37 bookings are at risk.", "next_step": "Fix it."}]})
    with patch("app.adapters.llm.get_llm", side_effect=_llm(bad)):
        out = explain.explain_tenant(db, w.t)
    assert out["explained"] == 0 and row.explanation["source"] == "rule" and findings.view(row)["why"] == row.body
    row.explanation = None
    good = json.dumps(
        {"items": [{"id": row.id, "why": "1 calendar is not blocking dates.", "next_step": "Paste a fresh link."}]}
    )
    with patch("app.adapters.llm.get_llm", side_effect=_llm(good)):
        assert explain.explain_tenant(db, w.t)["explained"] == 1
    v = findings.view(row)
    assert v["why"] == "1 calendar is not blocking dates." and v["explained_by"] == "ai"
    with patch("app.adapters.llm.get_llm", side_effect=_llm(good)) as m:
        assert explain.explain_tenant(db, w.t) == {"explained": 0}  # numbers unchanged: not asked again
    assert m.call_count == 0
    w.t.brand_config = {"chief": {"enabled": True, "paused": True}}
    row.explanation = None
    with patch("app.adapters.llm.get_llm", side_effect=_llm(good)) as m:
        assert explain.explain_tenant(db, w.t)["skipped"] == "paused"
    assert m.call_count == 0


def test_explain_survives_a_provider_error(db):
    w = world(db, brand_config=ON)
    _feed(db, w)
    findings.run(db, w.t, "urgent")
    with patch("app.adapters.llm.get_llm", side_effect=RuntimeError("down")):
        out = explain.explain_tenant(db, w.t)
    assert out["explained"] == 0 and out["fallback"] == 1


def test_analyst_daily_pulse_carries_the_executive_block(db):
    w = world(db, brand_config=ON)
    _feed(db, w)
    findings.run(db, w.t, "urgent")
    db.commit()
    f = facts.build(db, w.t, "daily_pulse", booking_agenda_service.tenant_today(db, w.t.id))
    assert f["executive"]["open"] >= 1 and f["executive"]["by_role"]["IT monitor"] == 1
    assert any(line.startswith("IT monitor:") for line in brief.deterministic(f)["not_working"])
    w.t.brand_config = {}
    assert "executive" not in facts.build(db, w.t, "daily_pulse", booking_agenda_service.tenant_today(db, w.t.id))


def test_celery_tasks_run_and_respect_the_switch(db):
    from app.workers.tasks import chief_tasks

    w = world(db, brand_config=ON)
    off = world(db)
    _feed(db, w)
    with (
        patch.object(chief_tasks.detect_tenant, "delay") as d,
        patch("app.workers.tasks.chief_tasks.SessionLocal", return_value=db),
        patch.object(db, "close"),
    ):
        chief_tasks.detect_all_tenants("urgent")
        queued = [c.args[0] for c in d.call_args_list]
        with (
            patch.object(chief_tasks.explain_tenant, "delay") as e,
            patch("app.workers.tasks.chief_tasks.set_tenant_context"),
        ):
            out = chief_tasks.detect_tenant(w.t.id, "urgent")
    assert w.t.id in queued and off.t.id not in queued
    assert out["open"] >= 1 and e.call_count == 1
