"""The sales agent's endpoints: owner settings (audited), the model report, and staff decisions on prepared quotes.

Per endpoint: happy path, a role that may not (403), another tenant (404 / untouched). Razorpay, Celery and WhatsApp are mocked.
"""
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.audit_event import AuditEvent
from app.models.sales_action import SalesAction
from app.models.task import Task
from app.models.user import UserRole
from app.services import quote_service as qs
from app.services import sales_action_service
from tests.test_increment1_defect_specs import _h, _user
from tests.test_quote_builder_pricing import price, ratha
from tests.test_quote_send import approve_quote_template, connect_razorpay, rzp  # noqa: F401  (rzp is a fixture)
from tests.test_quotes_api import lead

S = "/api/v1/ai/sales-agent"
A = "/api/v1/sales-actions"


@pytest.fixture()
def w(db):
    w = ratha(db)
    w.res = _user(db, w.t.id, UserRole.RESERVATIONS)
    w.foh = _user(db, w.t.id, UserRole.FOH)
    w.comp = _user(db, w.t.id, UserRole.COMPLIANCE)
    return w


def _action(db, w, *, stay_check="confirmed", package="day-rate"):
    inq = lead(db, w.t.id)
    q = price(db, w, package, nights=1, adults=4, destination_key="krs")
    assert q.ok, q.message
    (row,) = qs.issue_options(db, w.t.id, inq.id, q, None, None, meta={"stay_check": stay_check, "source": "sales_agent"})
    a = sales_action_service.create(db, w.t.id, inquiry_id=inq.id, conversation_id=None, primary=row, fallback=None, mode="suggest",
                                    requirement_key="k" * 64, hold_reasons=[])
    db.commit()
    return inq, row, a


# ─── settings ────────────────────────────────────────────────────────────────────────────────────────────

def test_owner_reads_and_changes_the_settings_and_each_change_is_audited(client, db, w):
    got = client.get(S, headers=_h(w.owner)).json()
    assert got["price_disclosure"] == "handoff" and got["sales_agent_mode"] == "off"                 # the defaults
    assert got["readiness"]["published_packages"] == 4 and got["readiness"]["razorpay_connected"] is False
    res = client.put(S, json={"price_disclosure": "grounded", "sales_agent_mode": "suggest"}, headers=_h(w.owner))
    assert res.status_code == 200, res.text
    assert res.json()["changed"] == {"price_disclosure": {"from": "handoff", "to": "grounded"},
                                     "sales_agent_mode": {"from": "off", "to": "suggest"}}
    db.refresh(w.t)
    assert w.t.brand_config["price_disclosure"] == "grounded" and w.t.brand_config["sales_agent"] == {"mode": "suggest"}
    (ev,) = db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="ai.sales_settings_changed").all()
    assert ev.actor_user_id == w.owner.id and ev.payload["changes"]["sales_agent_mode"]["to"] == "suggest"
    assert client.put(S, json={"sales_agent_mode": "suggest"}, headers=_h(w.owner)).json()["changed"] == {}   # no-op: no audit
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="ai.sales_settings_changed").count() == 1
    assert client.put(S, json={"sales_agent_mode": "always"}, headers=_h(w.owner)).status_code == 422


def test_only_the_owner_changes_the_settings(client, db, w):
    assert client.get(S, headers=_h(w.mgr)).status_code == 200
    assert client.put(S, json={"sales_agent_mode": "autopilot"}, headers=_h(w.mgr)).status_code == 403
    assert client.get(S, headers=_h(w.foh)).status_code == 403
    # The generic tenant update cannot change them behind the audit trail.
    res = client.patch("/api/v1/tenants/me", json={"brand_config": {"price_disclosure": "grounded"}}, headers=_h(w.owner))
    assert res.status_code == 422
    db.refresh(w.t)
    assert "price_disclosure" not in (w.t.brand_config or {})


def test_settings_are_per_tenant(client, db, w):
    other = ratha(db)
    assert client.put(S, json={"sales_agent_mode": "autopilot"}, headers=_h(other.owner)).status_code == 200
    db.refresh(w.t)
    assert client.get(S, headers=_h(w.owner)).json()["sales_agent_mode"] == "off"


# ─── routing report ──────────────────────────────────────────────────────────────────────────────────────

def test_routing_report_names_the_guest_reply_model_and_never_a_key(client, db, w, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "sk-secret-gemini-value")
    w.t.llm_provider_override = "nvidia"
    db.commit()
    res = client.get("/api/v1/ai/routing", headers=_h(w.owner))
    assert res.status_code == 200
    body = res.json()
    assert body["guest_reply"]["provider"] == "gemini" and body["guest_reply"]["model"] == "gemini-3.6-flash"
    assert body["keys"]["GEMINI_API_KEY"] == "present" and "sk-secret-gemini-value" not in res.text
    assert body["tenant_override"] == "nvidia" and body["override_applied"] is False
    classify = next(t for t in body["tasks"] if t["task"] == "quick_classify")
    assert classify["provider"] == "nvidia" and classify["gemini_fallback_active"] is True
    assert client.get("/api/v1/ai/routing", headers=_h(w.mgr)).status_code == 403


# ─── sales actions ───────────────────────────────────────────────────────────────────────────────────────

def test_staff_see_the_pending_quote_and_approve_sends_that_quote(client, db, w, rzp):
    connect_razorpay(db, w.t.id)
    approve_quote_template(db, w.t.id)
    inq, row, a = _action(db, w)
    listed = client.get(A, params={"inquiry_id": inq.id}, headers=_h(w.res)).json()
    assert [x["id"] for x in listed] == [a.id] and listed[0]["can_decide"] is True
    assert listed[0]["readiness"]["can_send"] is True and listed[0]["summary"]["quote_number"].startswith("Q-")
    assert client.get(A, params={"inquiry_id": inq.id}, headers=_h(w.foh)).json()[0]["can_decide"] is False
    res = client.post(f"{A}/{a.id}/approve", headers=_h(w.res))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "sent" and rzp.create.call_count == 1 and rzp.task.call_count == 1
    assert rzp.create.call_args.kwargs["notes"]["haip_inquiry_quote_id"] == row.id
    again = client.post(f"{A}/{a.id}/approve", headers=_h(w.res))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "not_pending" and rzp.task.call_count == 1
    assert {e.action for e in db.query(AuditEvent).filter_by(tenant_id=w.t.id).all()} >= {"sales_action.approved", "sales_action.sent", "quote.sent"}


def test_a_refused_send_keeps_the_action_pending_with_the_reason(client, db, w, rzp):
    _, _, a = _action(db, w)                                                                 # Razorpay not connected
    res = client.post(f"{A}/{a.id}/approve", headers=_h(w.owner))
    assert res.status_code == 422 and res.json()["detail"]["code"] == "razorpay_not_connected"
    db.expire_all()
    row = db.query(SalesAction).filter_by(id=a.id).one()
    assert row.status == "pending" and "Razorpay" in row.last_error and rzp.create.call_count == 0


def test_reject_dismisses_and_roles_without_quotes_write_cannot_decide(client, db, w, rzp):
    _, _, a = _action(db, w)
    assert client.post(f"{A}/{a.id}/approve", headers=_h(w.foh)).status_code == 403
    assert client.post(f"{A}/{a.id}/reject", headers=_h(w.foh)).status_code == 403
    assert client.get(A, params={"inquiry_id": a.inquiry_id}, headers=_h(w.comp)).status_code == 403
    res = client.post(f"{A}/{a.id}/reject", json={"reason": "guest went quiet"}, headers=_h(w.res))
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    assert client.post(f"{A}/{a.id}/approve", headers=_h(w.res)).status_code == 409
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="sales_action.rejected").count() == 1
    rzp.create.assert_not_called()


def test_another_tenants_actions_are_not_found(client, db, w, rzp):
    inq, _, a = _action(db, w)
    other = ratha(db)
    assert client.get(A, params={"inquiry_id": inq.id}, headers=_h(other.owner)).json() == []
    assert client.post(f"{A}/{a.id}/approve", headers=_h(other.owner)).status_code == 404
    assert client.post(f"{A}/{a.id}/reject", headers=_h(other.owner)).status_code == 404
    assert client.get(A, headers=_h(w.owner)).status_code == 422                            # a lead or conversation is required
    rzp.create.assert_not_called()


def test_the_agents_own_send_that_fails_gives_staff_a_task(db, w, rzp):
    connect_razorpay(db, w.t.id)
    approve_quote_template(db, w.t.id)
    _, _, a = _action(db, w, stay_check="not_checked")                                      # overnight stay not confirmed
    assert sales_action_service.start_autopilot(db, w.t.id, a.id)
    db.commit()
    assert sales_action_service.deliver_autopilot(db, w.t.id, a.id) == {"status": "failed"}
    db.expire_all()
    assert db.query(SalesAction).filter_by(id=a.id).one().status == "failed"
    assert db.query(Task).filter(Task.tenant_id == w.t.id, Task.title.like("Send the quote yourself%")).count() == 1
    rzp.create.assert_not_called()


def test_the_send_task_is_routed_and_never_runs_on_another_tenant(db, w):
    from app.workers.celery_app import celery_app
    assert celery_app.conf.task_routes["sales_agent.send_quote"] == {"queue": "whatsapp"}
    _, _, a = _action(db, w)
    other = ratha(db)
    with patch("app.services.quote_send_service.send_as_agent", side_effect=AssertionError("never")):
        assert sales_action_service.deliver_autopilot(db, other.t.id, a.id) == {"status": "ignored"}
