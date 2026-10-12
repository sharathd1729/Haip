"""Tests for migration 063's backfill logic: any Guest with a Call but zero
Conversation rows gets a channel=voice Conversation created retroactively,
with last_message_at seeded from their most recent call so it sorts
correctly immediately. Exercises the same SQL the migration runs, directly
against the test DB (migrations themselves aren't run under the SQLite test
harness -- see conftest.py), rather than invoking Alembic. Booleans are written as
true/false exactly as migration 063 does: PostgreSQL rejects 1/0 for a boolean column."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, ChannelType
from app.models.guest import Guest


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_guest(db, tenant_id, phone):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Backfill Guest", phone=phone)
    db.add(guest); db.commit()
    return guest


def _make_call(db, tenant_id, guest_id, started_at):
    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        ivr_provider="mcube", ivr_call_id=f"mc-{uuid.uuid4().hex[:8]}",
        direction=CallDirection.INBOUND, from_number="+918012345678", to_number="+919876543210",
        duration_seconds=90, started_at=started_at,
    )
    db.add(call); db.commit()
    return call


def _run_backfill(db, tenant_id):
    """Same query shape as migration 063's upgrade(), run directly."""
    orphaned = db.execute(text(
        """
        SELECT DISTINCT c.tenant_id, c.guest_id
        FROM calls c
        WHERE NOT EXISTS (
            SELECT 1 FROM conversations conv
            WHERE conv.guest_id = c.guest_id AND conv.tenant_id = c.tenant_id
        )
        AND c.tenant_id = :t
        """
    ), {"t": tenant_id}).fetchall()

    for t_id, guest_id in orphaned:
        latest = db.execute(text(
            "SELECT started_at FROM calls WHERE tenant_id = :t AND guest_id = :g ORDER BY started_at DESC LIMIT 1"
        ), {"t": t_id, "g": guest_id}).fetchone()
        db.execute(text(
            """
            INSERT INTO conversations (id, tenant_id, guest_id, channel, is_open, is_sample, last_message_at, created_at, updated_at)
            VALUES (:id, :tenant_id, :guest_id, 'VOICE', true, false, :last_message_at, :now, :now)
            """
        ), {
            "id": str(uuid.uuid4()), "tenant_id": t_id, "guest_id": guest_id,
            "last_message_at": latest[0] if latest else None,
            "now": datetime.now(timezone.utc),
        })
    db.commit()


class TestBackfillVoiceConversations:
    def test_creates_conversation_for_orphaned_guest(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id, "+919999011223")
        call_time = datetime.now(timezone.utc) - timedelta(days=3)
        _make_call(db, tenant_id, guest.id, call_time.isoformat())

        _run_backfill(db, tenant_id)

        conv = db.query(Conversation).filter_by(guest_id=guest.id, tenant_id=tenant_id).one()
        assert conv.channel == ChannelType.VOICE
        assert conv.last_message_at == call_time.isoformat()

    def test_seeds_last_message_at_from_most_recent_call(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id, "+919999022334")
        older = datetime.now(timezone.utc) - timedelta(days=5)
        newer = datetime.now(timezone.utc) - timedelta(days=1)
        _make_call(db, tenant_id, guest.id, older.isoformat())
        _make_call(db, tenant_id, guest.id, newer.isoformat())

        _run_backfill(db, tenant_id)

        conv = db.query(Conversation).filter_by(guest_id=guest.id, tenant_id=tenant_id).one()
        assert conv.last_message_at == newer.isoformat()

    def test_skips_guest_who_already_has_a_conversation(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id, "+919999033445")
        _make_call(db, tenant_id, guest.id, datetime.now(timezone.utc).isoformat())
        existing = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(existing); db.commit()

        _run_backfill(db, tenant_id)

        all_convs = db.query(Conversation).filter_by(guest_id=guest.id, tenant_id=tenant_id).all()
        assert len(all_convs) == 1
        assert all_convs[0].channel == ChannelType.WHATSAPP

    def test_idempotent_on_second_run(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id, "+919999044556")
        _make_call(db, tenant_id, guest.id, datetime.now(timezone.utc).isoformat())

        _run_backfill(db, tenant_id)
        _run_backfill(db, tenant_id)

        all_convs = db.query(Conversation).filter_by(guest_id=guest.id, tenant_id=tenant_id).all()
        assert len(all_convs) == 1
