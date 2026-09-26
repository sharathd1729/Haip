"""A campaign's template message shows in the guest's inbox thread.

Real case (Ratha, Sep 2026): a broadcast was delivered but appeared nowhere in
the inbox; the agent had no idea what the guest's reply referred to.
"""
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.services import wa_campaign_inbox as inbox
from tests.workers.test_run_campaign_tracking import (  # noqa: F401  (fixtures/helpers)
    FakeAdapter, Recipient, _rows, _run, world, WACampaign,
)


def _msgs(db, tid):
    db.expire_all()
    return db.query(Message).filter_by(tenant_id=tid).all()


def test_render_fills_the_values_that_were_sent():
    comps = [{"type": "HEADER", "format": "TEXT", "text": "Hello {{1}}"},
             {"type": "BODY", "text": "Hi {{1}}, two spots on {{2}}"}, {"type": "FOOTER", "text": "Reply STOP"}]
    sent = [{"type": "header", "parameters": [{"type": "text", "text": "Priya"}]},
            {"type": "body", "parameters": [{"type": "text", "text": "Priya"}, {"type": "text", "text": "Oct 3"}]}]
    assert inbox.render_text(comps, sent) == "Hello Priya\n\nHi Priya, two spots on Oct 3\n\nReply STOP"


def test_every_sent_guest_gets_the_message_in_their_thread(db, world):
    _run(db, world, FakeAdapter())
    msgs = _msgs(db, world.tid)
    assert len(msgs) == 3
    m = next(x for x in msgs if x.body == "Hi Priya")
    assert m.direction == MessageDirection.OUTBOUND and m.channel == ChannelType.WHATSAPP
    assert m.delivery_state == MessageDeliveryState.SENT and m.channel_message_id.startswith("wamid.")
    assert m.channel_metadata["campaign_id"] == world.camp_id
    conv = db.query(Conversation).filter_by(id=m.conversation_id).first()
    assert conv.channel == ChannelType.WHATSAPP and conv.first_response_at      # not counted as "waiting on us"


def test_a_failed_send_leaves_nothing_in_the_inbox(db, world):
    from tests.workers.test_run_campaign_tracking import _meta_error
    _run(db, world, FakeAdapter(fail={"+919800000001": _meta_error(131026)}))
    assert len(_msgs(db, world.tid)) == 2


def test_the_existing_thread_is_reused(db, world):
    _run(db, world, FakeAdapter())
    first = {m.conversation_id for m in _msgs(db, world.tid)}
    db.query(WACampaign).filter_by(id=world.camp_id).update({"status": "running"})
    db.query(Recipient).filter_by(campaign_id=world.camp_id).delete()
    db.commit()
    _run(db, world, FakeAdapter())
    assert {m.conversation_id for m in _msgs(db, world.tid)} == first
    assert db.query(Guest).filter_by(tenant_id=world.tid).count() == 3


def test_a_bookkeeping_failure_never_breaks_the_campaign(db, world):
    from unittest.mock import patch
    with patch.object(inbox, "_guest_id", side_effect=RuntimeError("db hiccup")):
        _run(db, world, FakeAdapter())
    assert all(r.status == "sent" for r in _rows(db, world).values())
    assert _msgs(db, world.tid) == []


def test_delivery_callback_updates_both_the_message_and_the_report(db, world):
    from app.models.tenant import Tenant
    from app.workers.tasks import whatsapp as wa_mod
    _run(db, world, FakeAdapter())
    row = _rows(db, world)["+919800000000"]
    tenant = db.query(Tenant).filter_by(id=world.tid).first()
    wa_mod._handle_status_update(db, tenant, {"id": row.wa_message_id, "status": "delivered", "timestamp": "1790000000"})
    db.commit()                      # the webhook caller commits
    db.expire_all()
    m = db.query(Message).filter_by(channel_message_id=row.wa_message_id).first()
    assert m.delivery_state == MessageDeliveryState.DELIVERED
    assert _rows(db, world)["+919800000000"].status == "delivered"


def test_backfill_adds_earlier_broadcasts_once(db, world):
    from datetime import datetime, timezone
    # A broadcast from before inbox recording existed: report rows, no messages.
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(inbox, "record_send", return_value=None):
        _run(db, world, FakeAdapter())
    assert _msgs(db, world.tid) == []
    sent_at = datetime(2026, 9, 25, 6, 0, tzinfo=timezone.utc)
    for r in _rows(db, world).values():
        r.sent_at = sent_at
    row = _rows(db, world)["+919800000000"]
    row.status = "read"
    db.commit()

    out = inbox.backfill(db, world.tid)
    assert out == {"added": 3, "already_there": 0, "failed": 0}
    msgs = _msgs(db, world.tid)
    m = next(x for x in msgs if x.body == "Hi Priya")
    assert m.delivery_state == MessageDeliveryState.READ and m.created_at.replace(tzinfo=timezone.utc) == sent_at

    assert inbox.backfill(db, world.tid) == {"added": 0, "already_there": 3, "failed": 0}
    assert len(_msgs(db, world.tid)) == 3


def test_backfill_is_tenant_scoped(db, world):
    from unittest.mock import patch
    with patch.object(inbox, "record_send", return_value=None):
        _run(db, world, FakeAdapter())
    assert inbox.backfill(db, "another-tenant") == {"added": 0, "already_there": 0, "failed": 0}
