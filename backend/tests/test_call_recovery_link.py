"""Tests for Phase 2.5 agent-accountability instrumentation
(HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.3): linking a missed
inbound call to the outbound call that recovered it, so "did we call
them back" is answerable from the schema.
"""
import uuid
from datetime import datetime, timezone, timedelta

from app.models.call import Call, CallDirection
from app.models.guest import Guest
from app.workers.tasks.call_ingest import _link_recovered_call


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_guest(db, tenant_id):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Recovery Guest", phone="+919999022334")
    db.add(guest); db.commit()
    return guest


def _make_call(db, tenant_id, guest_id, direction, duration_seconds, created_at):
    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        ivr_provider="acefone", ivr_call_id=str(uuid.uuid4()),
        direction=direction, from_number="+910000000000", to_number="+910000000001",
        duration_seconds=duration_seconds,
    )
    db.add(call)
    db.flush()
    call.created_at = created_at  # override TimestampMixin's default(now)
    db.commit()
    db.refresh(call)
    return call


class TestLinkRecoveredCall:
    def test_links_missed_inbound_to_later_outbound_within_window(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)
        now = datetime.now(timezone.utc)

        missed = _make_call(db, tenant_id, guest.id, CallDirection.INBOUND, 0, now - timedelta(hours=1))
        outbound = _make_call(db, tenant_id, guest.id, CallDirection.OUTBOUND, 45, now)

        _link_recovered_call(db, tenant_id, guest.id, outbound)

        db.refresh(missed)
        assert missed.recovered_by_call_id == outbound.id

    def test_does_not_link_when_no_missed_call_exists(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)
        now = datetime.now(timezone.utc)

        # Only an answered inbound call -- nothing "missed" to recover.
        _make_call(db, tenant_id, guest.id, CallDirection.INBOUND, 120, now - timedelta(hours=1))
        outbound = _make_call(db, tenant_id, guest.id, CallDirection.OUTBOUND, 30, now)

        _link_recovered_call(db, tenant_id, guest.id, outbound)  # should no-op, not raise

        still_unrecovered = (
            db.query(Call)
            .filter_by(tenant_id=tenant_id, guest_id=guest.id, direction=CallDirection.INBOUND)
            .filter(Call.recovered_by_call_id.is_(None))
            .count()
        )
        assert still_unrecovered == 1

    def test_ignores_missed_call_outside_the_recovery_window(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)
        now = datetime.now(timezone.utc)

        # 30h ago -- outside the 24h window.
        missed = _make_call(db, tenant_id, guest.id, CallDirection.INBOUND, 0, now - timedelta(hours=30))
        outbound = _make_call(db, tenant_id, guest.id, CallDirection.OUTBOUND, 20, now)

        _link_recovered_call(db, tenant_id, guest.id, outbound)

        db.refresh(missed)
        assert missed.recovered_by_call_id is None

    def test_tenant_isolation_only_matches_within_same_tenant(self, db, tenant_and_user):
        from app.models.tenant import Tenant

        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)
        now = datetime.now(timezone.utc)
        missed = _make_call(db, tenant_id, guest.id, CallDirection.INBOUND, 0, now - timedelta(hours=1))

        other_tenant = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(other_tenant); db.commit()
        other_outbound = _make_call(db, other_tenant.id, guest.id, CallDirection.OUTBOUND, 15, now)

        _link_recovered_call(db, other_tenant.id, guest.id, other_outbound)

        db.refresh(missed)
        assert missed.recovered_by_call_id is None  # not linked across tenants
