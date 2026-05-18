"""
Tests for B2: Inquiry stage transition state machine.

Covers:
- Every allowed forward transition
- 3 explicitly disallowed forward paths
- Terminal stage blocks further transitions
- Exit transitions (→ LOST / GHOSTED) from any active stage
- Backward transition: allowed with reason + owner role
- Backward transition: blocked without reason
- Backward transition: blocked for non-manager/owner role
- No-op: same stage → no error
"""

import uuid
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry, InquiryStage
from app.services.inquiry_service import (
    update_stage,
    InvalidStageTransition,
    ALLOWED_FORWARD,
    EXIT_STAGES,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_inquiry(stage: InquiryStage, tenant_id: str = "t1") -> MagicMock:
    """Return a lightweight mock that behaves like an Inquiry row."""
    inq = MagicMock(spec=Inquiry)
    inq.id = str(uuid.uuid4())
    inq.tenant_id = tenant_id
    inq.stage = stage
    return inq


def _mock_db(inquiry: Inquiry) -> MagicMock:
    db = MagicMock(spec=Session)
    db.query.return_value.filter_by.return_value.first.return_value = inquiry
    return db


OWNER = "owner"
MANAGER = "manager"
CONCIERGE = "concierge"
ACTOR_ID = "user-001"


# ── Allowed forward transitions ───────────────────────────────────────────────

@pytest.mark.parametrize("from_stage,to_stage", [
    (InquiryStage.NEW,        InquiryStage.RESPONDING),
    (InquiryStage.RESPONDING, InquiryStage.QUOTED),
    (InquiryStage.QUOTED,     InquiryStage.SITE_VISIT),
    (InquiryStage.QUOTED,     InquiryStage.BOOKED),
    (InquiryStage.SITE_VISIT, InquiryStage.BOOKED),
])
def test_allowed_forward_transitions(from_stage, to_stage):
    inq = _make_inquiry(from_stage)
    db = _mock_db(inq)
    with patch("app.core.audit.append_audit"):
        result = update_stage(
            db,
            tenant_id="t1",
            inquiry_id=inq.id,
            new_stage=to_stage,
            actor_user_id=ACTOR_ID,
            actor_role=CONCIERGE,
        )
    assert result.stage == to_stage


# ── Exit transitions (→ LOST / GHOSTED) ──────────────────────────────────────

@pytest.mark.parametrize("from_stage", [
    InquiryStage.NEW,
    InquiryStage.RESPONDING,
    InquiryStage.QUOTED,
    InquiryStage.SITE_VISIT,
    InquiryStage.BOOKED,
])
@pytest.mark.parametrize("exit_stage", [InquiryStage.LOST, InquiryStage.GHOSTED])
def test_exit_transitions_always_allowed(from_stage, exit_stage):
    inq = _make_inquiry(from_stage)
    db = _mock_db(inq)
    with patch("app.core.audit.append_audit"):
        result = update_stage(
            db, tenant_id="t1", inquiry_id=inq.id,
            new_stage=exit_stage, actor_user_id=ACTOR_ID, actor_role=CONCIERGE,
        )
    assert result.stage == exit_stage


# ── Disallowed forward transitions ────────────────────────────────────────────

@pytest.mark.parametrize("from_stage,to_stage", [
    (InquiryStage.NEW,        InquiryStage.BOOKED),      # skip RESPONDING + QUOTED
    (InquiryStage.NEW,        InquiryStage.QUOTED),       # skip RESPONDING
    (InquiryStage.RESPONDING, InquiryStage.BOOKED),      # skip QUOTED
])
def test_disallowed_skip_transitions_raise(from_stage, to_stage):
    inq = _make_inquiry(from_stage)
    db = _mock_db(inq)
    with pytest.raises(InvalidStageTransition) as exc_info:
        update_stage(
            db, tenant_id="t1", inquiry_id=inq.id,
            new_stage=to_stage, actor_user_id=ACTOR_ID, actor_role=OWNER,
        )
    assert exc_info.value.from_stage == from_stage.value
    assert exc_info.value.to_stage == to_stage.value


# ── Terminal stages block all moves ───────────────────────────────────────────

@pytest.mark.parametrize("terminal", [InquiryStage.LOST, InquiryStage.GHOSTED])
def test_terminal_stage_blocks_any_move(terminal):
    inq = _make_inquiry(terminal)
    db = _mock_db(inq)
    with pytest.raises(InvalidStageTransition):
        update_stage(
            db, tenant_id="t1", inquiry_id=inq.id,
            new_stage=InquiryStage.NEW, actor_user_id=ACTOR_ID, actor_role=OWNER,
        )


# ── Backward transitions ──────────────────────────────────────────────────────

def test_backward_allowed_for_owner_with_reason():
    inq = _make_inquiry(InquiryStage.QUOTED)
    db = _mock_db(inq)
    with patch("app.core.audit.append_audit") as mock_audit:
        result = update_stage(
            db, tenant_id="t1", inquiry_id=inq.id,
            new_stage=InquiryStage.RESPONDING,
            actor_user_id=ACTOR_ID, actor_role=OWNER,
            reason="Guest asked to re-negotiate pricing",
        )
    assert result.stage == InquiryStage.RESPONDING
    mock_audit.assert_called_once()


def test_backward_allowed_for_manager_with_reason():
    inq = _make_inquiry(InquiryStage.BOOKED)
    db = _mock_db(inq)
    with patch("app.core.audit.append_audit"):
        result = update_stage(
            db, tenant_id="t1", inquiry_id=inq.id,
            new_stage=InquiryStage.QUOTED,
            actor_user_id=ACTOR_ID, actor_role=MANAGER,
            reason="Booking fell through — back to quote stage",
        )
    assert result.stage == InquiryStage.QUOTED


def test_backward_blocked_without_reason():
    inq = _make_inquiry(InquiryStage.QUOTED)
    db = _mock_db(inq)
    with pytest.raises(InvalidStageTransition) as exc_info:
        update_stage(
            db, tenant_id="t1", inquiry_id=inq.id,
            new_stage=InquiryStage.RESPONDING,
            actor_user_id=ACTOR_ID, actor_role=OWNER,
            reason=None,
        )
    assert "reason" in exc_info.value.detail.lower()


def test_backward_blocked_for_concierge_role():
    inq = _make_inquiry(InquiryStage.QUOTED)
    db = _mock_db(inq)
    with pytest.raises(InvalidStageTransition) as exc_info:
        update_stage(
            db, tenant_id="t1", inquiry_id=inq.id,
            new_stage=InquiryStage.RESPONDING,
            actor_user_id=ACTOR_ID, actor_role=CONCIERGE,
            reason="I want to move it back",
        )
    assert "owner or manager" in exc_info.value.detail.lower()


# ── No-op: same stage ─────────────────────────────────────────────────────────

def test_same_stage_is_noop():
    inq = _make_inquiry(InquiryStage.RESPONDING)
    db = _mock_db(inq)
    result = update_stage(
        db, tenant_id="t1", inquiry_id=inq.id,
        new_stage=InquiryStage.RESPONDING,
        actor_user_id=ACTOR_ID, actor_role=CONCIERGE,
    )
    assert result.stage == InquiryStage.RESPONDING


# ── Audit event written on every valid transition ─────────────────────────────

def test_audit_event_written_on_forward_transition():
    inq = _make_inquiry(InquiryStage.NEW)
    db = _mock_db(inq)
    with patch("app.core.audit.append_audit") as mock_audit:
        update_stage(
            db, tenant_id="t1", inquiry_id=inq.id,
            new_stage=InquiryStage.RESPONDING,
            actor_user_id=ACTOR_ID, actor_role=CONCIERGE,
        )
    mock_audit.assert_called_once()
    call_kwargs = mock_audit.call_args.kwargs
    assert call_kwargs["action"] == "inquiry.stage_changed"
    assert call_kwargs["payload"]["from_stage"] == "new"
    assert call_kwargs["payload"]["to_stage"] == "responding"


def test_inquiry_not_found_raises_value_error():
    db = MagicMock(spec=Session)
    db.query.return_value.filter_by.return_value.first.return_value = None
    with pytest.raises(ValueError, match="not found"):
        update_stage(
            db, tenant_id="t1", inquiry_id="nonexistent",
            new_stage=InquiryStage.RESPONDING,
            actor_user_id=ACTOR_ID, actor_role=OWNER,
        )
