"""backfill_missing_instagram_inquiries -- the hourly safety net for the
process_instagram_dm.py gate fix (commit b72565e)."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.workers.tasks import backfill_missing_inquiries as mod
from app.workers.tasks.backfill_missing_inquiries import backfill_missing_instagram_inquiries


class _NoCloseSessionWrapper:
    """The task opens its own SessionLocal() internally, which a second
    real connection can't see mid-transaction -- same technique
    test_process_instagram_dm_phase3.py already uses for this."""
    def __init__(self, real_session):
        self._s = real_session
    def __getattr__(self, name):
        return getattr(self._s, name)
    def close(self):
        pass


def _run_backfill(db):
    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        return backfill_missing_instagram_inquiries.run()


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Test Villa", slug=f"villa-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_guest(db, tenant_id, name="Guest"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone="")
    db.add(g)
    db.flush()
    return g


def _make_conversation(db, tenant_id, guest_id, inquiry_id=None):
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        channel=ChannelType.INSTAGRAM, is_open=True, inquiry_id=inquiry_id,
    )
    db.add(conv)
    db.flush()
    return conv


def _add_inbound(db, tenant_id, conversation_id, body, offset_seconds=0):
    m = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation_id,
        direction=MessageDirection.INBOUND, channel=ChannelType.INSTAGRAM, body=body,
        created_at=datetime.now(timezone.utc) + timedelta(seconds=offset_seconds),
    )
    db.add(m)
    db.flush()
    return m


def test_creates_inquiry_for_conversation_with_real_text_and_no_inquiry_id(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    conv = _make_conversation(db, tenant.id, guest.id, inquiry_id=None)
    _add_inbound(db, tenant.id, conv.id, "[ig_post]", offset_seconds=0)
    real_msg = _add_inbound(db, tenant.id, conv.id, "How much do your services cost?", offset_seconds=1)
    db.commit()

    result = _run_backfill(db)

    assert result["created"] == 1
    db.refresh(conv)
    assert conv.inquiry_id is not None


def test_backdates_inquiry_to_the_qualifying_messages_real_date(db):
    """Real bug, caught live: the first real run of this exact pattern
    left created_at at "now" (get_or_create_from_chat's default) instead
    of when the guest actually sent the message -- 348 inquiries backdated
    up to 7 weeks all showed as created today, inflating every last-24h
    dashboard metric until caught and corrected by hand."""
    from app.models.inquiry import Inquiry

    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    conv = _make_conversation(db, tenant.id, guest.id, inquiry_id=None)
    old_timestamp = datetime.now(timezone.utc) - timedelta(days=45)
    m = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction=MessageDirection.INBOUND, channel=ChannelType.INSTAGRAM,
        body="How much do your services cost?", created_at=old_timestamp,
    )
    db.add(m)
    db.commit()

    result = _run_backfill(db)

    assert result["created"] == 1
    db.refresh(conv)
    inquiry = db.query(Inquiry).filter_by(id=conv.inquiry_id).first()
    # SQLite (this test DB) drops tzinfo on round-trip, unlike Postgres
    # (prod) -- compare naive to naive, the values themselves must match.
    assert inquiry.created_at.replace(tzinfo=None) == old_timestamp.replace(tzinfo=None)
    assert inquiry.current_stage_entered_at.replace(tzinfo=None) == old_timestamp.replace(tzinfo=None)


def test_skips_conversation_with_no_real_text(db):
    """Only an attachment marker to route from -- correctly left alone,
    not counted as a failure."""
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    conv = _make_conversation(db, tenant.id, guest.id, inquiry_id=None)
    _add_inbound(db, tenant.id, conv.id, "[ig_post]")
    db.commit()

    result = _run_backfill(db)

    assert result["created"] == 0
    db.refresh(conv)
    assert conv.inquiry_id is None


def test_leaves_conversation_with_existing_inquiry_id_untouched(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    # conversations.inquiry_id is a foreign key: the conversation's existing inquiry has to exist
    from app.models.inquiry import Inquiry, InquirySource, InquiryStage
    existing = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
                       stage=InquiryStage.NEW, source=InquirySource.META_IG)
    db.add(existing)
    db.flush()
    existing_inquiry_id = existing.id
    conv = _make_conversation(db, tenant.id, guest.id, inquiry_id=existing_inquiry_id)
    _add_inbound(db, tenant.id, conv.id, "Hello there")
    db.commit()

    result = _run_backfill(db)

    assert result["created"] == 0
    db.refresh(conv)
    assert conv.inquiry_id == existing_inquiry_id


def test_tenant_isolation(db):
    """Sweeps every tenant in one pass -- confirm it doesn't cross tenant_id
    boundaries when creating the inquiry."""
    tenant_a = _make_tenant(db)
    tenant_b = _make_tenant(db)
    guest_a = _make_guest(db, tenant_a.id, "Guest A")
    guest_b = _make_guest(db, tenant_b.id, "Guest B")
    conv_a = _make_conversation(db, tenant_a.id, guest_a.id, inquiry_id=None)
    conv_b = _make_conversation(db, tenant_b.id, guest_b.id, inquiry_id=None)
    _add_inbound(db, tenant_a.id, conv_a.id, "What are your rates?")
    _add_inbound(db, tenant_b.id, conv_b.id, "Do you have availability?")
    db.commit()

    result = _run_backfill(db)

    assert result["created"] == 2
    db.refresh(conv_a)
    db.refresh(conv_b)
    from app.models.inquiry import Inquiry
    inq_a = db.query(Inquiry).filter_by(id=conv_a.inquiry_id).first()
    inq_b = db.query(Inquiry).filter_by(id=conv_b.inquiry_id).first()
    assert inq_a.tenant_id == tenant_a.id
    assert inq_b.tenant_id == tenant_b.id
