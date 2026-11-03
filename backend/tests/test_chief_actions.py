"""AI Executive E2: plans from findings, owner-only approval bound to the plan, the executor (wait for Meta, playbooks on,
cap, kill switch, failures), WhatsApp Approve / Reject taps, one approvals inbox, and the other plans (balance reminders,
KB entry from staff answers, lead autopilot). Every external call (Meta, WhatsApp, push) is patched: nothing leaves."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.models.agent_consult import AgentConsult
from app.models.audit_event import AuditEvent
from app.models.chief import ChiefProposal
from app.models.conversation import ChannelType, Conversation
from app.models.insight import Insight
from app.models.knowledge import KnowledgeEntry
from app.services import lead_alert_service, lead_playbook_settings, wa_lead_pack
from app.services.chief import approvals, detectors, detectors_more, executor, plans
from app.services.lead_playbook_catalog import NEW_LEAD_ALERT, SLA_ESCALATION
from tests.analyst_world import world
from tests.test_increment1_defect_specs import _h

R = "/api/v1/chief"
ON = {"chief": {"enabled": True}}
PUSH = "app.services.push_service.send_to_tenant"


def _finding(db, w, code, *, evidence=None, target_id=None, role="sales_manager") -> Insight:
    row = Insight(
        tenant_id=w.t.id,
        category_code=code,
        target_id=target_id,
        category="urgency",
        role=role,
        severity="high",
        title=f"{code} finding",
        body=f"{code} body",
        numbers={"waiting": 4},
        evidence=evidence or [],
    )
    db.add(row)
    db.commit()
    return row


def _set_templates(db, w, status, names=None):
    from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate

    wa_lead_pack.create_drafts(db, w.t.id, None)
    for t in db.query(WATemplate).filter(WATemplate.tenant_id == w.t.id).all():
        if names is None or t.name in names:
            t.status = TemplateStatus(status)
    db.commit()


def _fake_submit(db, tmpl, template_id):
    from app.api.v1.endpoints.messaging import TemplateStatus

    tmpl.status = TemplateStatus.PENDING
    return {"status": "pending", "meta_template_id": "m1", "rejection_reason": None}


def _sa1(db, w) -> ChiefProposal:
    _finding(db, w, "SA1")
    new = plans.propose_for_tenant(db, w.t)
    db.commit()
    return next(p for p in new if p.code == "SA1")


# ── planning ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_sa1_plan_reads_the_live_setup_and_is_made_once(db):
    w = world(db, brand_config=ON)
    p = _sa1(db, w)
    assert [s["type"] for s in p.steps] == [
        "templates.create_drafts",
        "templates.submit",
        "wait.templates_approved",
        "playbooks.set",
        "notify.staff_opt_in",
    ]
    assert p.risk_tier == "R2" and p.status == "awaiting_approval" and len(p.plan_sha) == 64
    assert any("Meta" in line for line in p.preview)
    assert plans.propose_for_tenant(db, w.t) == []  # one open proposal per finding
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.proposal_created").count() == 1


def test_sa1_with_everything_ready_makes_no_proposal(db):
    w = world(
        db,
        brand_config={
            **ON,
            "lead_playbooks": {
                "enabled": True,
                "playbooks": {NEW_LEAD_ALERT: {"enabled": True}, SLA_ESCALATION: {"enabled": True}},
            },
        },
    )
    _set_templates(db, w, "approved")
    w.mgr.phone, w.mgr.whatsapp_alerts_opt_in_at = "+919845011111", datetime.now(UTC)
    db.commit()
    _finding(db, w, "SA1")
    assert plans.propose_for_tenant(db, w.t) == []


def test_turning_the_workspace_switch_on_names_guest_playbooks_and_is_r3(db):
    from app.services.lead_playbook_catalog import MISSED_INBOUND_CALL

    w = world(
        db,
        brand_config={
            **ON,
            "lead_playbooks": {"enabled": False, "playbooks": {MISSED_INBOUND_CALL: {"enabled": True}}},
        },
    )
    p = _sa1(db, w)
    assert p.risk_tier == "R3" and any("Also starts" in line for line in p.preview)


def test_a_rejected_template_is_not_resubmitted(db):
    w = world(db, brand_config=ON)
    _set_templates(db, w, "rejected", names=[wa_lead_pack.STAFF_ALERT])
    _finding(db, w, "SA1")
    assert plans.propose_for_tenant(db, w.t) == []


def test_expired_when_the_finding_goes_away_and_rejected_not_reproposed(db):
    w = world(db, brand_config=ON)
    p = _sa1(db, w)
    f = db.get(Insight, p.finding_id)
    f.is_auto_resolved = True
    db.commit()
    plans.propose_for_tenant(db, w.t)
    db.commit()
    db.refresh(p)
    assert p.status == "expired"
    f2 = _finding(db, w, "SA1")
    p2 = next(x for x in plans.propose_for_tenant(db, w.t) if x.finding_id == f2.id)
    executor.reject(db, w.t, p2, w.owner.id, "not_worth_it")
    db.commit()
    f2.is_auto_resolved = True
    _finding(db, w, "SA1")
    assert plans.propose_for_tenant(db, w.t) == []  # same code rejected within 7 days


# ── approval + execution ─────────────────────────────────────────────────────────────────────────────────────


def test_endpoints_owner_only_bound_to_the_plan_and_cross_tenant(client, db):
    w = world(db, brand_config=ON)
    p = _sa1(db, w)
    assert client.get(f"{R}/proposals", headers=_h(w.mgr)).json()[0]["id"] == p.id
    assert client.get(f"{R}/proposals", headers=_h(w.foh)).status_code == 403
    body = {"plan_sha": p.plan_sha}
    assert client.post(f"{R}/proposals/{p.id}/approve", json=body, headers=_h(w.mgr)).status_code == 403
    assert (
        client.post(f"{R}/proposals/{p.id}/approve", json={"plan_sha": "0" * 64}, headers=_h(w.owner)).status_code
        == 409
    )
    other = world(db, brand_config=ON)
    assert client.get(f"{R}/proposals/{p.id}", headers=_h(other.owner)).status_code == 404
    assert client.post(f"{R}/proposals/{p.id}/approve", json=body, headers=_h(other.owner)).status_code == 404
    with patch("app.workers.tasks.chief_tasks.execute_proposal.delay") as d:
        got = client.post(f"{R}/proposals/{p.id}/approve", json=body, headers=_h(w.owner))
    assert got.status_code == 200 and got.json()["status"] == "approved" and d.call_args.args == (w.t.id, p.id)
    assert client.post(f"{R}/proposals/{p.id}/approve", json=body, headers=_h(w.owner)).status_code == 409
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.proposal_approved").count() == 1
    home = client.get(f"{R}/home", headers=_h(w.mgr)).json()
    assert home["proposals"] == [] and home["activity"][0]["id"] == p.id


def test_executor_waits_for_meta_then_switches_on_alerts(db):
    w = world(db, brand_config=ON)
    p = _sa1(db, w)
    executor.approve(db, w.t, p, w.owner.id, p.plan_sha)
    db.commit()
    with patch("app.api.v1.endpoints.messaging.submit_to_meta", side_effect=_fake_submit), patch(PUSH) as push:
        assert executor.run(db, w.t, p) == "waiting"
        assert p.status == "waiting" and p.step_index == 2 and p.steps[1]["status"] == "done"
        assert (
            executor.run(db, w.t, p, now=datetime.now(UTC) + timedelta(minutes=1)) == "waiting"
        )  # still pending at Meta
        _set_templates(db, w, "approved", names=[wa_lead_pack.STAFF_ALERT, wa_lead_pack.STAFF_ESCALATION])
        assert executor.run(db, w.t, p) == "done"
    assert lead_playbook_settings.playbook(w.t, NEW_LEAD_ALERT)["active"] is True
    assert lead_playbook_settings.get(w.t)["staff_whatsapp"] is True
    assert p.status == "done" and p.check_due_at is not None and push.call_count >= 2  # staff asked + owner told
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.step_done").count() == 5


def test_meta_rejection_fails_the_plan_and_tells_the_owner(db):
    from app.api.v1.endpoints.messaging import TemplateStatus

    w = world(db, brand_config=ON)
    p = _sa1(db, w)
    executor.approve(db, w.t, p, w.owner.id, p.plan_sha)

    def _rejected(db_, tmpl, tid):
        tmpl.status = TemplateStatus.REJECTED
        return {"status": "rejected", "rejection_reason": "Too promotional", "meta_template_id": None}

    with patch("app.api.v1.endpoints.messaging.submit_to_meta", side_effect=_rejected), patch(PUSH) as push:
        assert executor.run(db, w.t, p) == "failed"
    assert "Too promotional" in p.failure and push.called
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.step_failed").count() == 1


def test_kill_switch_and_daily_cap(db):
    w = world(db, brand_config={"chief": {"enabled": True, "daily_action_cap": 1}})
    p = _sa1(db, w)
    executor.approve(db, w.t, p, w.owner.id, p.plan_sha)
    db.commit()
    w.t.brand_config = {"chief": {"enabled": True, "paused": True, "daily_action_cap": 1}}
    assert executor.run(db, w.t, p) == "paused" and p.step_index == 0
    w.t.brand_config = {"chief": {"enabled": True, "daily_action_cap": 1}}
    with patch("app.api.v1.endpoints.messaging.submit_to_meta", side_effect=_fake_submit):
        assert executor.run(db, w.t, p) == "capped"
    assert p.step_index == 1 and p.status == "approved" and p.next_check_at is not None


def test_r3_cannot_be_approved_on_whatsapp(db):
    from app.services.lead_playbook_catalog import MISSED_INBOUND_CALL

    w = world(
        db,
        brand_config={
            **ON,
            "lead_playbooks": {"enabled": False, "playbooks": {MISSED_INBOUND_CALL: {"enabled": True}}},
        },
    )
    p = _sa1(db, w)
    try:
        executor.approve(db, w.t, p, w.owner.id, p.plan_sha, via="whatsapp")
        raise AssertionError("approved an R3 plan on WhatsApp")
    except executor.DecisionError as exc:
        assert exc.status == 403


# ── WhatsApp approvals ───────────────────────────────────────────────────────────────────────────────────────


def _owner_on_whatsapp(db, w):
    w.owner.phone, w.owner.whatsapp_alerts_opt_in_at = "+919845022222", datetime.now(UTC)
    db.commit()
    return lead_alert_service.staff_phone(w.owner)


def test_whatsapp_request_and_taps(db):
    w = world(db, brand_config={"chief": {"enabled": True, "whatsapp_approvals": True}})
    phone = _owner_on_whatsapp(db, w)
    p = _sa1(db, w)
    sent = {}

    def _deliver(db_, action, to, values, **kw):
        sent.update(action=action, to=to, values=values, payloads=kw["payloads"])
        action.status = "done"
        return True

    with (
        patch("app.services.lead_alert_sender.template_approved", return_value="en"),
        patch("app.services.lead_alert_sender.deliver", side_effect=_deliver),
        patch("app.services.lead_alert_service.in_quiet_hours", return_value=False),
        patch(PUSH),
    ):
        out = approvals.notify_new(db, w.t, [p])
    db.commit()
    assert out["whatsapp"] == 1 and sent["to"] == phone and sent["values"][0] == p.title
    approve_tap, reject_tap = sent["payloads"]
    assert approve_tap.startswith("ex:") and approve_tap.endswith(sent["action"].payload["nonce"])
    with (
        patch("app.services.lead_alert_sender.send_text") as reply,
        patch("app.workers.tasks.chief_tasks.execute_proposal.delay") as run,
    ):
        assert approvals.handle_tap(db, w.t.id, "+919800000000", approve_tap) == "wrong_person"
        forged = approve_tap.rsplit(":", 1)[0] + ":forged"
        assert approvals.handle_tap(db, w.t.id, phone, forged) == "wrong_person"
        assert approvals.handle_tap(db, w.t.id, phone, approve_tap) == "approved"
        assert approvals.handle_tap(db, w.t.id, phone, reject_tap) == "refused"  # already decided
    db.refresh(p)
    assert p.status == "approved" and p.decided_via == "whatsapp" and run.call_count == 1 and reply.call_count == 2


def test_no_whatsapp_for_r3_or_when_switched_off(db):
    w = world(db, brand_config=ON)
    _owner_on_whatsapp(db, w)
    p = _sa1(db, w)
    with patch("app.services.lead_alert_sender.deliver") as d, patch(PUSH) as push:
        assert approvals.notify_new(db, w.t, [p])["whatsapp"] == 0
    assert d.call_count == 0 and push.call_count == 1


def test_webhook_routes_ex_taps_to_the_executive(db):
    from app.workers.tasks import whatsapp

    w = world(db, brand_config=ON)
    msg = {"id": f"wamid.{uuid.uuid4().hex}", "type": "button", "button": {"payload": "ex:abc:approve:n1"}}
    with (
        patch("app.services.chief.approvals.handle_tap", return_value="unknown") as tap,
        patch("app.core.cache.get_cached", return_value=None),
        patch("app.core.cache.set_cached"),
    ):
        assert whatsapp._staff_reply(db, w.t, msg, "button", "+919811111111") is True
    assert tap.call_args.args[2:] == ("+919811111111", "ex:abc:approve:n1")


# ── the other plans ──────────────────────────────────────────────────────────────────────────────────────────


def test_arrivals_plan_needs_the_template_and_respects_quiet_hours(db):
    w = world(db, brand_config=ON)
    _finding(db, w, "OP1", evidence=[{"type": "stay", "id": w.stay.id}], role="finance")
    assert plans.propose_for_tenant(db, w.t) == []  # balance template not approved
    with patch("app.services.balance_reminder_service.blocker", return_value=None):
        p = plans.propose_for_tenant(db, w.t)[0]
        assert p.risk_tier == "R3"
        executor.approve(db, w.t, p, w.owner.id, p.plan_sha)
        with patch("app.services.lead_alert_service.in_quiet_hours", return_value=True):
            assert executor.run(db, w.t, p) == "waiting"
        with (
            patch("app.services.lead_alert_service.in_quiet_hours", return_value=False),
            patch(
                "app.services.balance_reminder_service.send_for_stays",
                return_value={"status": "ok", "sent": 1, "skipped": 0},
            ) as send,
            patch(PUSH),
        ):
            assert executor.run(db, w.t, p) == "done"
    assert [s.id for s in send.call_args.args[2]] == [w.stay.id] and p.steps[0]["result"] == {"sent": 1, "skipped": 0}


def _consults(db, w, n=3):
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=w.guests[0].id, channel=ChannelType.WHATSAPP, is_open=True
    )
    db.add(conv)
    db.flush()
    now = datetime.now(UTC)
    rows = []
    for i in range(n):
        c = AgentConsult(
            id=str(uuid.uuid4()),
            tenant_id=w.t.id,
            conversation_id=conv.id,
            question="Is a pet dog allowed in the caravan?",
            reason_codes=["unpublished_data"],
            status="answered",
            sla_due_at=now,
            answered_at=now - timedelta(days=i),
            answer_text="Yes, one small pet is fine. Please bring its bedding." if i == 0 else None,
            answer_mode="edited",
        )
        db.add(c)
        rows.append(c)
    db.commit()
    return rows


def test_repeat_question_becomes_a_pending_kb_entry(db):
    w = world(db, brand_config=ON)
    rows = _consults(db, w)
    hits = detectors_more.concierge_repeat_questions(detectors.Ctx(db, w.t))
    assert len(hits) == 1 and hits[0]["numbers"] == {"asked": 3} and "pet" not in hits[0]["title"].lower()
    _finding(db, w, "CO1", evidence=hits[0]["evidence"], target_id=hits[0]["target_id"], role="concierge")
    p = plans.propose_for_tenant(db, w.t)[0]
    assert p.risk_tier == "R2" and any("one small pet" in line for line in p.preview)
    executor.approve(db, w.t, p, w.owner.id, p.plan_sha)
    with patch(PUSH):
        assert executor.run(db, w.t, p) == "done"
    entry = db.query(KnowledgeEntry).filter_by(tenant_id=w.t.id, source_ref=f"chief:{p.id}").one()
    assert entry.review_status == "pending" and entry.question.startswith("Is a pet") and "bedding" in entry.content
    rows[0].saved_to_kb_entry_id = entry.id
    db.commit()
    assert detectors_more.concierge_repeat_questions(detectors.Ctx(db, w.t)) == []


def test_ignored_autopilot_suggestions_plan(db):
    from app.services import lead_autopilot_service

    w = world(db, brand_config=ON)
    _finding(db, w, "SA9")
    p = plans.propose_for_tenant(db, w.t)[0]
    assert p.steps[0]["args"] == {"mode": "autopilot"}
    executor.approve(db, w.t, p, w.owner.id, p.plan_sha)
    with patch(PUSH):
        assert executor.run(db, w.t, p) == "done"
    assert lead_autopilot_service.get_settings(db, w.t.id)["mode"] == "autopilot"


def test_one_approvals_inbox_and_tenant_isolation(client, db):
    w = world(db, brand_config=ON)
    p = _sa1(db, w)
    other = world(db, brand_config=ON)
    items = client.get(f"{R}/approvals", headers=_h(w.mgr)).json()
    assert [i["id"] for i in items if i["source"] == "executive"] == [p.id]
    assert client.get(f"{R}/approvals", headers=_h(other.owner)).json() == []
    assert client.get(f"{R}/approvals", headers=_h(w.foh)).status_code == 403


def test_approval_template_is_only_a_draft(client, db):
    w = world(db)
    got = client.post(f"{R}/templates", headers=_h(w.mgr)).json()
    assert got["created"] == [wa_lead_pack.CHIEF_APPROVAL] and got["templates"][0]["status"] == "draft"
    assert client.post(f"{R}/templates", headers=_h(w.mgr)).json()["created"] == []
