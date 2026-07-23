"""Tests for update_stage_by_id — Leads360 restructure Phase 1 §2.2."""
import uuid
import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.services.inquiry_service import update_stage_by_id, InvalidStageTransition


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_stage(db, tenant_id, key, order, **kwargs):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key=key, label=key.title(), order=order, **kwargs)
    db.add(s)
    db.flush()
    return s


def _make_inquiry(db, tenant_id, stage_id):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone="")
    db.add(g)
    db.flush()
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id,
        stage=InquiryStage.NEW, stage_id=stage_id, source=InquirySource.WA_DIRECT,
    )
    db.add(inq)
    db.flush()
    return inq


def _setup(db):
    t = _make_tenant(db)
    s_new = _make_stage(db, t.id, "new", 0, is_default_entry=True)
    s_negotiation = _make_stage(db, t.id, "negotiation", 1)   # custom, no enum equivalent
    s_won = _make_stage(db, t.id, "won", 2, is_closed_won=True)
    s_lost = _make_stage(db, t.id, "lost", 3, is_closed_lost=True)
    return t, s_new, s_negotiation, s_won, s_lost


def test_forward_transition_custom_stage(db):
    t, s_new, s_negotiation, s_won, s_lost = _setup(db)
    inq = _make_inquiry(db, t.id, s_new.id)
    update_stage_by_id(
        db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=s_negotiation.id,
        actor_user_id="u1", actor_role="concierge",
    )
    assert inq.stage_id == s_negotiation.id


def test_exit_transition_allowed_from_any_active_stage(db):
    t, s_new, s_negotiation, s_won, s_lost = _setup(db)
    inq = _make_inquiry(db, t.id, s_new.id)
    update_stage_by_id(
        db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=s_lost.id,
        actor_user_id="u1", actor_role="concierge",
    )
    assert inq.stage_id == s_lost.id


def test_terminal_stage_blocks_further_transitions(db):
    t, s_new, s_negotiation, s_won, s_lost = _setup(db)
    inq = _make_inquiry(db, t.id, s_won.id)
    with pytest.raises(InvalidStageTransition):
        update_stage_by_id(
            db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=s_new.id,
            actor_user_id="u1", actor_role="owner", reason="oops",
        )


def test_backward_transition_requires_role_and_reason(db):
    t, s_new, s_negotiation, s_won, s_lost = _setup(db)
    inq = _make_inquiry(db, t.id, s_negotiation.id)

    with pytest.raises(InvalidStageTransition):
        update_stage_by_id(
            db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=s_new.id,
            actor_user_id="u1", actor_role="concierge", reason="wrong role",
        )

    with pytest.raises(InvalidStageTransition):
        update_stage_by_id(
            db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=s_new.id,
            actor_user_id="u1", actor_role="owner",
        )

    update_stage_by_id(
        db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=s_new.id,
        actor_user_id="u1", actor_role="owner", reason="mistake",
    )
    assert inq.stage_id == s_new.id


# ── "Sold" leads become real bookings ───────────────────────────────────────
# A lead moved to a closed_won stage represents a booking with no PMS
# counterpart (nothing to sync from Hostaway), so this is the only path
# that ever turns it into a Stay row shown on the property calendar.

def test_won_transition_creates_stay_when_booking_fields_present(db):
    from app.models.property import Stay

    t, s_new, s_negotiation, s_won, s_lost = _setup(db)
    inq = _make_inquiry(db, t.id, s_new.id)
    inq.property_id = "prop-1"
    inq.check_in = "2026-08-01"
    inq.check_out = "2026-08-03"
    inq.quoted_amount = 15000
    db.flush()

    update_stage_by_id(
        db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=s_won.id,
        actor_user_id="u1", actor_role="concierge",
    )

    stay = db.query(Stay).filter_by(inquiry_id=inq.id).first()
    assert stay is not None
    assert stay.tenant_id == t.id
    assert stay.guest_id == inq.guest_id
    assert stay.property_id == "prop-1"
    assert stay.check_in == "2026-08-01"
    assert stay.check_out == "2026-08-03"
    assert stay.total_amount == 15000
    assert stay.channel_source == "direct"
    assert stay.hostaway_booking_id is None


def test_won_transition_skips_stay_when_booking_fields_missing(db):
    """Most chat/WhatsApp leads never get property_id/check_in/check_out --
    the stage move must still succeed, just without a Stay (Stay.property_id
    is NOT NULL so a half-populated row can't be written)."""
    from app.models.property import Stay

    t, s_new, s_negotiation, s_won, s_lost = _setup(db)
    inq = _make_inquiry(db, t.id, s_new.id)  # no property_id/check_in/check_out

    update_stage_by_id(
        db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=s_won.id,
        actor_user_id="u1", actor_role="concierge",
    )

    assert inq.stage_id == s_won.id
    assert db.query(Stay).filter_by(inquiry_id=inq.id).first() is None


def test_won_transition_stay_creation_is_idempotent(db):
    """Re-entering a won stage (e.g. reversed then re-applied) must not
    create a second Stay for the same inquiry."""
    from app.models.property import Stay

    t, s_new, s_negotiation, s_won, s_lost = _setup(db)
    inq = _make_inquiry(db, t.id, s_new.id)
    inq.property_id = "prop-1"
    inq.check_in = "2026-08-01"
    inq.check_out = "2026-08-03"
    db.flush()

    update_stage_by_id(
        db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=s_won.id,
        actor_user_id="u1", actor_role="concierge",
    )
    from app.services.inquiry_service import _create_stay_for_won_inquiry
    _create_stay_for_won_inquiry(db, inq)  # simulate a second call

    assert db.query(Stay).filter_by(inquiry_id=inq.id).count() == 1


def test_tenant_isolation_rejects_cross_tenant_stage(db):
    t1, s_new, s_negotiation, s_won, s_lost = _setup(db)
    t2 = _make_tenant(db)
    other_stage = _make_stage(db, t2.id, "new", 0, is_default_entry=True)
    inq = _make_inquiry(db, t1.id, s_new.id)

    with pytest.raises(ValueError):
        update_stage_by_id(
            db, tenant_id=t1.id, inquiry_id=inq.id, new_stage_id=other_stage.id,
            actor_user_id="u1", actor_role="owner",
        )
