"""Why a lead was won / lost (lead_outcome). Pinned: a PERSON closing a lead through EITHER stage path must give a reason
(422 outcome_reason_required), an older client's lost_reason still counts; automatic closings need none; the autopilot's
dates-passed rule records dates_unavailable (source rule); a person picking the AI's proposal is ai_confirmed; the AI's quotes
must be verbatim (a made-up one is dropped) and imported chats are evidence; the proposal is queued, never run inline; the
"Why we win / lose" report keeps confirmed apart from proposed; roles and other workspaces are refused."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.inquiry import Inquiry, InquiryStage, LostReason
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import inquiry_service, lead_outcome, lead_outcome_report
from tests.conftest import seed_capabilities
from tests.test_lead_feed import _lead, _owner_headers, _user


def _stages(db, tid):
    active = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key="active", label="Active", category="valid", order=3)
    lost = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key="lost", label="Lost", category="valid", is_closed_lost=True, order=9)
    sold = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key="sold", label="Sold", category="valid", is_closed_won=True, order=10)
    db.add_all([active, lost, sold])
    db.flush()
    return active, lost, sold


def _setup(db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    active, lost, sold = _stages(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    inq.stage_id = active.id
    db.commit()
    return tenant, owner, g, inq, active, lost, sold


def _patch(client, h, inq, **body):
    return client.patch(f"/api/v1/inquiries/{inq.id}", headers=h, json=body)


def test_a_person_must_say_why_on_both_paths(client, db, tenant_and_user):
    tenant, owner, g, inq, active, lost, sold = _setup(db, tenant_and_user)
    h = _owner_headers(tenant_and_user)
    r = _patch(client, h, inq, stage_id=lost.id)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "outcome_reason_required"
    assert "why the lead was lost" in r.json()["detail"]["message"] and "price" in r.json()["detail"]["reasons"]
    assert _patch(client, h, inq, stage_id=lost.id, outcome_reason="weather").status_code == 422
    r = _patch(client, h, inq, stage_id=lost.id, outcome_reason="price", outcome_reason_note="Found it costly vs a Tempo")
    assert r.status_code == 200, r.text
    db.refresh(inq)
    assert (inq.outcome_reason, inq.outcome_reason_source, inq.outcome_decided_by) == ("price", "person", owner.id)
    assert inq.lost_reason == LostReason.BUDGET_MISMATCH and inq.outcome_reason_note == "Found it costly vs a Tempo"
    assert db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="lead.outcome_recorded", target_id=inq.id).count() == 1

    _, inq2 = _lead(db, tenant.id, owner.id, phone="+919845011111")
    inq2.stage = InquiryStage.QUOTED
    db.commit()
    r = _patch(client, h, inq2, stage="booked")                                     # the legacy enum path
    assert r.status_code == 422 and r.json()["detail"]["kind"] == "won"
    assert _patch(client, h, inq2, stage="booked", outcome_reason="occasion").status_code == 200
    db.refresh(inq2)
    assert inq2.outcome_reason == "occasion" and inq2.stage == InquiryStage.BOOKED


def test_an_older_clients_lost_reason_still_counts(client, db, tenant_and_user):
    tenant, owner, g, inq, active, lost, sold = _setup(db, tenant_and_user)
    r = _patch(client, _owner_headers(tenant_and_user), inq, stage_id=lost.id, lost_reason="wrong_dates")
    assert r.status_code == 200
    db.refresh(inq)
    assert inq.outcome_reason == "dates_unavailable" and inq.lost_reason == LostReason.WRONG_DATES


def test_automatic_closings_need_no_reason_and_a_rule_records_its_own(db, tenant_and_user):
    tenant, owner, g, inq, active, lost, sold = _setup(db, tenant_and_user)
    inquiry_service.update_stage_by_id(db, tenant_id=tenant.id, inquiry_id=inq.id, new_stage_id=sold.id, actor_user_id=None, actor_role="system")
    assert inq.outcome_reason is None
    _, inq2 = _lead(db, tenant.id, owner.id, phone="+919845022222")
    inq2.stage_id = active.id
    db.flush()
    inquiry_service.update_stage_by_id(db, tenant_id=tenant.id, inquiry_id=inq2.id, new_stage_id=lost.id, actor_user_id=None,
                                       actor_role="system", outcome={"reason": lead_outcome.AUTOPILOT_LOST["dates"], "source": "rule"})
    assert (inq2.outcome_reason, inq2.outcome_reason_source, inq2.outcome_decided_by) == ("dates_unavailable", "rule", None)
    _, inq3 = _lead(db, tenant.id, owner.id, phone="+919845022333")
    inq3.stage_id = active.id
    db.flush()
    with pytest.raises(inquiry_service.OutcomeReasonRequired):
        inquiry_service.update_stage_by_id(db, tenant_id=tenant.id, inquiry_id=inq3.id, new_stage_id=sold.id, actor_user_id=owner.id,
                                           actor_role="owner", by_person=True)
    assert inq3.stage_id == active.id                                       # refused before anything moved


def test_autopilot_dates_passed_rule_records_dates_unavailable(db):
    from app.services import lead_autopilot_service
    from tests.services._autopilot_fixtures import NOW, lead, tenant
    t, s = tenant(db, mode="autopilot")
    _, inq, _ = lead(db, t.id, s["active"], check_in="2026-10-01")
    ev = lead_autopilot_service.evaluate(db, t.id, inq.id, now=NOW)
    db.commit()
    db.refresh(inq)
    assert ev.status == "applied" and inq.stage_id == s["lost"].id
    assert (inq.outcome_reason, inq.outcome_reason_source) == ("dates_unavailable", "rule")


def _evidence(db, tid, g):
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, source="personal_bridge")
    db.add(conv)
    db.flush()
    m = Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                channel=ChannelType.WHATSAPP, body="Honestly the price is too high for us, we found a cheaper option",
                sender_kind="chat_export", created_at=datetime.now(timezone.utc) - timedelta(days=2))
    db.add(m)
    db.commit()
    return m


def test_the_ai_proposal_keeps_only_verbatim_quotes_and_reads_imported_chats(db, tenant_and_user):
    tenant, owner, g, inq, active, lost, sold = _setup(db, tenant_and_user)
    m = _evidence(db, tenant.id, g)
    seen = {}

    def fake(system, user):
        seen["user"] = user
        return {"content": '{"reason": "price", "confidence": 0.82, "quotes": ['
                           f'{{"ref": "m:{m.id}", "text": "the price is too high for us"}}, '
                           f'{{"ref": "m:{m.id}", "text": "we will never book"}}, '
                           '{"ref": "m:made-up", "text": "too high"}]}', "model": "test-model"}
    out = lead_outcome.propose(db, tenant.id, inq.id, "lost", complete=fake)
    assert "the price is too high" in seen["user"]                          # the imported chat line is evidence
    assert out["status"] == "ready" and out["reason"] == "price" and out["prompt_version"] == "lead-outcome-reason-v1"
    assert out["quotes"] == [{"source": "message", "id": m.id, "text": "the price is too high for us"}] and out["dropped_quotes"] == 2

    db.commit()
    r = inquiry_service.update_stage_by_id(db, tenant_id=tenant.id, inquiry_id=inq.id, new_stage_id=lost.id, actor_user_id=owner.id,
                                           actor_role="owner", outcome={"reason": "price"}, by_person=True)
    assert r.outcome_reason_source == "ai_confirmed"
    assert lead_outcome.propose(db, tenant.id, inq.id, "won", complete=lambda s, u: {"content": "not json"})["status"] == "failed"
    _, empty = _lead(db, tenant.id, owner.id, phone="+919845033333")
    db.commit()
    assert lead_outcome.propose(db, tenant.id, empty.id, "lost", complete=fake)["status"] == "no_evidence"


def test_the_dialog_queues_the_proposal_once_and_polls_it(client, db, tenant_and_user, monkeypatch):
    tenant, owner, g, inq, active, lost, sold = _setup(db, tenant_and_user)
    queued = []
    monkeypatch.setattr("app.workers.tasks.lead_outcome.propose.delay", lambda **kw: queued.append(kw))
    h = _owner_headers(tenant_and_user)
    r = client.post(f"/api/v1/leads/{inq.id}/outcome/propose", headers=h, json={"kind": "lost"})
    assert r.status_code == 202 and r.json()["proposal"]["status"] == "pending"
    client.post(f"/api/v1/leads/{inq.id}/outcome/propose", headers=h, json={"kind": "lost"})
    assert queued == [{"inquiry_id": inq.id, "tenant_id": tenant.id, "kind": "lost"}]
    got = client.get(f"/api/v1/leads/{inq.id}/outcome", headers=h).json()
    assert got["proposal"]["status"] == "pending" and [c["key"] for c in got["catalogue"]["won"]][0] == "package_fit"
    assert client.put(f"/api/v1/leads/{inq.id}/outcome", headers=h, json={"reason": "price"}).status_code == 409   # still open


def test_confirming_a_closed_leads_reason_and_permissions(client, db, tenant_and_user, monkeypatch):
    tenant, owner, g, inq, active, lost, sold = _setup(db, tenant_and_user)
    inquiry_service.update_stage_by_id(db, tenant_id=tenant.id, inquiry_id=inq.id, new_stage_id=sold.id, actor_user_id=None, actor_role="system")
    db.commit()
    h = _owner_headers(tenant_and_user)
    assert client.put(f"/api/v1/leads/{inq.id}/outcome", headers=h, json={"reason": "price"}).status_code == 422   # a lost reason
    r = client.put(f"/api/v1/leads/{inq.id}/outcome", headers=h, json={"reason": "package_fit"})
    assert r.status_code == 200 and r.json()["reason"] == "package_fit" and r.json()["source"] == "person"
    _, ro = _user(db, tenant.id, UserRole.READ_ONLY)
    monkeypatch.setattr("app.workers.tasks.lead_outcome.propose.delay", lambda **kw: None)
    assert client.post(f"/api/v1/leads/{inq.id}/outcome/propose", headers=ro, json={"kind": "won"}).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    _, oinq = _lead(db, other.id, None, phone="+919845099999")
    assert client.get(f"/api/v1/leads/{oinq.id}/outcome", headers=h).status_code == 404
    assert client.post(f"/api/v1/leads/{oinq.id}/outcome/propose", headers=h, json={"kind": "won"}).status_code == 404


def test_why_we_win_and_lose_report_keeps_confirmed_apart_from_proposed(client, db, tenant_and_user):
    tenant, owner, g, inq, active, lost, sold = _setup(db, tenant_and_user)
    h = _owner_headers(tenant_and_user)
    _patch(client, h, inq, stage_id=lost.id, outcome_reason="price")
    _, inq2 = _lead(db, tenant.id, owner.id, phone="+919845044444")
    inq2.stage_id = active.id
    db.flush()
    inquiry_service.update_stage_by_id(db, tenant_id=tenant.id, inquiry_id=inq2.id, new_stage_id=lost.id, actor_user_id=None, actor_role="system")
    inq2.outcome_proposal = {"kind": "lost", "status": "ready", "reason": "price", "quotes": []}
    _, inq3 = _lead(db, tenant.id, owner.id, phone="+919845055555")
    inq3.stage_id = active.id
    db.flush()
    inquiry_service.update_stage_by_id(db, tenant_id=tenant.id, inquiry_id=inq3.id, new_stage_id=sold.id, actor_user_id=None, actor_role="system")
    db.commit()
    assert [i.id for i, _ in lead_outcome.unconfirmed_closed(db, tenant.id)] == [inq3.id]   # the sweep's work list
    res = client.get("/api/v1/reports/outcome-reasons", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    price = next(r for r in body["lost"]["reasons"] if r["reason"] == "price")
    assert (price["confirmed"], price["proposed"]) == (1, 1) and body["lost"]["total"] == 2
    assert body["won"]["not_recorded"] == 1 and body["basis"] == "closed"
    _, concierge = _user(db, tenant.id, UserRole.CONCIERGE)
    assert client.get("/api/v1/reports/outcome-reasons", headers=concierge).status_code == 403
    assert lead_outcome_report.build(db, str(uuid.uuid4()), datetime.now().date(), datetime.now().date())["lost"]["total"] == 0
