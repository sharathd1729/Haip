"""AI-draft approve / reject: the state machine, its audit trail and its failure handling (Sales Agent Increment 1, PR-1).

pending (AI-written, outbound, not approved, not rejected, not sent)
   --approve--> approved (QUEUED, exactly one send)       --reject--> 409
   --reject --> rejected                                    --approve--> 409
Everything that is not a pending AI draft (inbound, human-written, sent, rejected) is refused and left unchanged. The race between
two requests is decided by one guarded UPDATE; the broader cases (read-only role, sent message, double approve, stale hash,
concurrent approvals on PostgreSQL) are in test_increment1_defect_specs.py.
"""
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.api.v1.endpoints import conversations as conv_mod
from app.models.audit_event import AuditEvent
from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.conversation import Message, MessageDeliveryState
from app.models.user import UserRole
from tests.test_increment1_defect_specs import (  # noqa: F401  (world is a fixture)
    DELAY, _conv, _draft, _h, _msg, _tenant, _url, _user, world,
)


def _audit(db, tenant_id, action):
    return db.query(AuditEvent).filter_by(tenant_id=tenant_id, action=action).all()


def test_approve_writes_a_chained_audit_row_without_the_message_text(db, client, world):
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    with patch(DELAY):
        r = client.post(_url(c, d, "approve"), json={"text": "Our check-in is from 2 pm."}, headers=_h(world.owner))
    assert r.status_code == 200
    (row,) = _audit(db, world.t.id, "ai_draft.approved")
    assert row.actor_user_id == world.owner.id and row.target_id == d.id and len(row.hash) == 64                  # first row of a tenant's chain: prev_hash is empty
    assert row.payload["edited"] is True and len(row.payload["body_sha256"]) == 64 and len(row.payload["original_body_sha256"]) == 64
    assert "check-in" not in str(row.payload) and "caravan" not in str(row.payload)            # hashes only, never the text
    db.expire_all()
    stored = db.get(Message, d.id)
    assert stored.body == "Our check-in is from 2 pm." and stored.delivery_state == MessageDeliveryState.QUEUED and stored.sender_id == world.owner.id
    assert db.query(AIDraftOutcome).filter_by(draft_message_id=d.id).one().outcome == "sent_edited"


def test_reject_writes_an_audit_row_and_one_outcome(db, client, world):
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    r = client.post(_url(c, d, "reject"), json={"reason": "wrong dates"}, headers=_h(world.owner))
    assert r.status_code == 200 and r.json() == {"status": "rejected"}
    (row,) = _audit(db, world.t.id, "ai_draft.rejected")
    assert row.payload["reason"] == "wrong dates" and row.actor_user_id == world.owner.id
    assert [o.outcome for o in db.query(AIDraftOutcome).filter_by(draft_message_id=d.id)] == ["rejected"]


def test_rejecting_twice_is_idempotent_and_does_not_double_count(db, client, world):
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    assert client.post(_url(c, d, "reject"), headers=_h(world.owner)).json() == {"status": "rejected"}
    assert client.post(_url(c, d, "reject"), headers=_h(world.owner)).json() == {"status": "already_rejected"}
    assert db.query(AIDraftOutcome).filter_by(draft_message_id=d.id).count() == 1
    assert len(_audit(db, world.t.id, "ai_draft.rejected")) == 1


def test_a_draft_approved_by_one_person_cannot_be_rejected_or_approved_again_by_another(db, client, world):
    manager = _user(db, world.t.id, UserRole.MANAGER)
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    with patch(DELAY) as send:
        assert client.post(_url(c, d, "approve"), json={}, headers=_h(world.owner)).status_code == 200
        second = client.post(_url(c, d, "approve"), json={}, headers=_h(manager))
        rej = client.post(_url(c, d, "reject"), headers=_h(manager))
    assert second.status_code == 409 and second.json()["detail"]["code"] == "draft_already_approved"
    assert rej.status_code == 409
    assert send.call_count == 1
    assert len(_audit(db, world.t.id, "ai_draft.approved")) == 1 and not _audit(db, world.t.id, "ai_draft.rejected")


def test_approving_the_same_text_again_by_the_same_person_is_idempotent(db, client, world):
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    with patch(DELAY) as send:
        first = client.post(_url(c, d, "approve"), json={"text": "Edited once"}, headers=_h(world.owner))
        again = client.post(_url(c, d, "approve"), json={"text": "Edited once"}, headers=_h(world.owner))
        different = client.post(_url(c, d, "approve"), json={"text": "Edited again"}, headers=_h(world.owner))
    assert first.json() == {"status": "approved_and_queued"} and again.json() == {"status": "already_approved"}
    assert different.status_code == 409 and send.call_count == 1                      # a different text is never silently accepted


def test_a_matching_hash_approves_and_a_stale_hash_changes_nothing(db, client, world):
    import hashlib
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    good = hashlib.sha256(d.body.encode()).hexdigest()
    with patch(DELAY) as send:
        stale = client.post(_url(c, d, "approve"), json={"expected_body_sha256": "a" * 64}, headers=_h(world.owner))
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "draft_changed" and send.call_count == 0
        db.expire_all()
        assert db.get(Message, d.id).was_approved is None
        ok = client.post(_url(c, d, "approve"), json={"expected_body_sha256": good}, headers=_h(world.owner))
    assert ok.status_code == 200 and send.call_count == 1


def test_a_rewrite_that_lands_between_the_read_and_the_update_is_never_sent_unreviewed(db, client, world):
    """rewrite_draft edits Message.body in place. If it lands after the approver's request read the draft, the guarded UPDATE
    (which includes the text that was read) matches no row: the approval is refused and the rewritten text is NOT sent."""
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    original = conv_mod._load_ai_draft
    calls = {"n": 0}

    def load(db_, tenant_id, conversation_id, message_id):
        msg = original(db_, tenant_id, conversation_id, message_id)
        calls["n"] += 1
        if calls["n"] == 1:                                    # only the first read is followed by the rewrite
            db_.execute(text("UPDATE messages SET body = :b WHERE id = :i"),
                        {"b": "REWRITTEN BY THE AI AFTER THE AGENT LOOKED", "i": message_id})
        return msg

    with patch(DELAY) as send, patch.object(conv_mod, "_load_ai_draft", side_effect=load):
        r = client.post(_url(c, d, "approve"), json={}, headers=_h(world.owner))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "draft_changed" and send.call_count == 0
    db.expire_all()
    assert db.get(Message, d.id).was_approved is None


def test_a_broker_failure_after_approval_leaves_a_visible_failed_message_not_a_silent_queued_one(db, client, world):
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    with patch(DELAY, side_effect=ConnectionError("broker down")):
        r = client.post(_url(c, d, "approve"), json={}, headers=_h(world.owner))
    assert r.status_code == 503
    db.expire_all()
    m = db.get(Message, d.id)
    assert m.delivery_state == MessageDeliveryState.FAILED and "queue" in (m.delivery_error or "").lower()


def test_an_empty_edit_is_refused_and_the_draft_stays_pending(db, client, world):
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    with patch(DELAY) as send:
        r = client.post(_url(c, d, "approve"), json={"text": "   "}, headers=_h(world.owner))
    assert r.status_code == 422 and send.call_count == 0
    db.expire_all()
    assert db.get(Message, d.id).was_approved is None


def test_another_tenants_draft_is_a_404_for_both_actions(db, client, world):
    other = _tenant(db)
    og, oc = _conv(db, other.id)
    od = _draft(db, other.id, oc)
    with patch(DELAY) as send:
        a = client.post(_url(oc, od, "approve"), json={}, headers=_h(world.owner))
        r = client.post(_url(oc, od, "reject"), headers=_h(world.owner))
    assert a.status_code == 404 and r.status_code == 404 and send.call_count == 0
    db.expire_all()
    assert db.get(Message, od.id).was_approved is None


@pytest.mark.parametrize("role,allowed", [
    (UserRole.OWNER, True), (UserRole.MANAGER, True), (UserRole.RESERVATIONS, True), (UserRole.CONCIERGE, True), (UserRole.FOH, True),
    (UserRole.MARKETING, False), (UserRole.COMPLIANCE, False), (UserRole.READ_ONLY, False),
])
def test_approve_reject_and_ai_draft_follow_the_tenants_send_capability(db, client, world, role, allowed):
    """Same default matrix as sending a message and the rewrite endpoints (conversations.send)."""
    u = _user(db, world.t.id, role)
    g, c = _conv(db, world.t.id)
    d1, d2 = _draft(db, world.t.id, c), _draft(db, world.t.id, c)
    with patch(DELAY), patch("app.api.v1.endpoints.conversations.concierge_draft.delay"):
        approve = client.post(_url(c, d1, "approve"), json={}, headers=_h(u))
        reject = client.post(_url(c, d2, "reject"), headers=_h(u))
        ai_draft = client.post(f"/api/v1/conversations/{c.id}/messages/ai-draft", json={}, headers=_h(u))
    expected = (200, 200, 200) if allowed else (403, 403, 403)
    assert (approve.status_code, reject.status_code, ai_draft.status_code) == expected


def test_a_tenant_with_no_capability_matrix_is_denied_not_opened_up(db, client):
    from app.core.security import create_access_token, get_password_hash
    from app.models.tenant import Tenant
    from app.models.user import User
    t = Tenant(id=str(uuid.uuid4()), name="Bare", slug=f"bare-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    u = User(id=str(uuid.uuid4()), tenant_id=t.id, name="o", email=f"o-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password=get_password_hash("pw"), role=UserRole.OWNER, is_active=True)
    db.add(u)
    db.commit()
    g, c = _conv(db, t.id)
    d = _draft(db, t.id, c)
    with patch(DELAY) as send:
        assert client.post(_url(c, d, "reject"), headers=_h(u)).status_code == 403          # fails closed, as send does
        assert client.post(_url(c, d, "approve"), json={}, headers=_h(u)).status_code == 403
    assert send.call_count == 0


def test_the_mcp_approve_tool_reports_the_reason_in_plain_words(db, world):
    from app.mcp.tools import ToolError, _approve_and_send_draft
    g, c = _conv(db, world.t.id)
    m = _msg(db, world.t.id, c, is_ai_generated=False)                                      # a human-written message
    with pytest.raises(ToolError) as exc:
        _approve_and_send_draft(db, world.owner, world.t.id, {"conversation_id": c.id, "message_id": m.id})
    assert "AI draft" in str(exc.value)
