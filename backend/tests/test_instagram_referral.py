"""Instagram ad referrals that arrive as their own event (no message attached).

Before this, such an event matched no branch of the webhook handler and was dropped: 4 of 481 Instagram leads
in a live 30-day window had an ad recorded."""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.base import gen_uuid
from app.models.conversation import ChannelType, Conversation
from app.models.inquiry import Inquiry
from app.models.integration import Integration
from app.models.lead_attribution import LeadAttribution
from app.services import attribution_service as svc

IG_ACCOUNT = "17841400000000000"
SENDER = "5550001112"
REFERRAL = {"ref": "r", "source": "ADS", "type": "OPEN_THREAD", "ad_id": "ad-123",
            "ads_context_data": {"ad_title": "Caravan weekend in Coorg"}}


class _FakeRedis:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def setex(self, k, ttl, v):
        self.d[k] = v

    def ping(self):
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    from app.core import cache
    r = _FakeRedis()
    monkeypatch.setattr(cache, "_client", lambda: r)
    return r


def _setup(db, tenant_id, *, conversation=True, inquiry=False):
    from app.services.identity_service import resolve_gid
    db.add(Integration(id=gen_uuid(), tenant_id=tenant_id, kind="instagram", status="active",
                       config={"instagram_business_account_id": IG_ACCOUNT}))
    db.commit()
    guest_id, _ = resolve_gid(db=db, tenant_id=tenant_id, signal_type="instagram_user_id", value=SENDER,
                              source="instagram", guest_fields={"name": "IG User 001112"})
    conv = inq = None
    if conversation:
        if inquiry:
            inq = Inquiry(id=gen_uuid(), tenant_id=tenant_id, guest_id=guest_id)
            db.add(inq); db.flush()
        conv = Conversation(id=gen_uuid(), tenant_id=tenant_id, guest_id=guest_id, channel=ChannelType.INSTAGRAM,
                            is_open=True, inquiry_id=inq.id if inq else None)
        db.add(conv)
    db.commit()
    return guest_id, conv, inq


def _run(db, payload):
    from app.workers.tasks.process_instagram_referral import process_instagram_referral
    with patch("app.workers.tasks.process_instagram_referral.SessionLocal", return_value=db):
        return process_instagram_referral.run(payload)


# ── the webhook handler ──────────────────────────────────────────────────────

def test_a_referral_only_event_is_queued_not_dropped():
    from app.api.v1.endpoints import webhooks_instagram as wh
    with patch("app.workers.tasks.process_instagram_referral.process_instagram_referral.delay") as ref_task, \
         patch("app.workers.tasks.process_instagram_dm.process_instagram_dm.delay") as dm_task:
        wh._handle_messaging_event(IG_ACCOUNT, {"sender": {"id": SENDER}, "recipient": {"id": IG_ACCOUNT},
                                               "timestamp": 1, "referral": REFERRAL})
    assert ref_task.call_count == 1 and dm_task.call_count == 0
    sent = ref_task.call_args.args[0]
    assert sent["sender_id"] == SENDER and sent["referral"]["ad_id"] == "ad-123" and sent["ig_account_id"] == IG_ACCOUNT


def test_a_message_that_carries_its_referral_still_goes_to_the_dm_worker():
    from app.api.v1.endpoints import webhooks_instagram as wh
    ev = {"sender": {"id": SENDER}, "message": {"mid": "m1", "text": "hi"}, "referral": REFERRAL}
    with patch("app.workers.tasks.process_instagram_referral.process_instagram_referral.delay") as ref_task, \
         patch("app.workers.tasks.process_instagram_dm.process_instagram_dm.delay") as dm_task:
        wh._handle_messaging_event(IG_ACCOUNT, ev)
    assert dm_task.call_count == 1 and ref_task.call_count == 0


# ── the task ─────────────────────────────────────────────────────────────────

def test_referral_for_an_existing_chat_is_recorded_and_linked_to_its_lead(db, tenant_and_user, fake_redis):
    tid = tenant_and_user["tenant"].id
    guest_id, conv, inq = _setup(db, tid, inquiry=True)
    conv_id, inq_id = conv.id, inq.id                                # the task closes the shared test session
    payload = {"ig_account_id": IG_ACCOUNT, "sender_id": SENDER, "referral": REFERRAL}

    assert _run(db, payload)["status"] == "recorded"
    row = db.query(LeadAttribution).filter_by(tenant_id=tid, conversation_id=conv_id).one()
    assert row.ad_id == "ad-123" and row.inquiry_id == inq_id and row.destination_channel == "instagram"
    assert row.headline == "Caravan weekend in Coorg" and row.source_type == "ad"

    _run(db, payload)                                                # a retried delivery adds nothing
    assert db.query(LeadAttribution).filter_by(tenant_id=tid, conversation_id=conv_id).count() == 1


def test_referral_that_arrives_before_the_chat_is_held_once(db, tenant_and_user, fake_redis):
    tid = tenant_and_user["tenant"].id
    _setup(db, tid, conversation=False)
    assert _run(db, {"ig_account_id": IG_ACCOUNT, "sender_id": SENDER, "referral": REFERRAL})["status"] == "stashed"
    assert db.query(LeadAttribution).filter_by(tenant_id=tid).count() == 0

    first = svc.take_stashed_referral(tid, SENDER)
    assert first and first["ad_id"] == "ad-123"
    assert svc.take_stashed_referral(tid, SENDER) is None            # used once


def test_a_held_referral_belongs_to_one_workspace_only(db, tenant_and_user, fake_redis):
    svc.stash_referral("tenant-a", SENDER, REFERRAL)
    assert svc.take_stashed_referral("tenant-b", SENDER) is None
    assert svc.take_stashed_referral("tenant-a", SENDER)["ad_id"] == "ad-123"


def test_unknown_account_or_empty_referral_is_skipped(db, tenant_and_user, fake_redis):
    assert _run(db, {"ig_account_id": "nope", "sender_id": SENDER, "referral": REFERRAL})["status"] == "skipped"
    assert _run(db, {"ig_account_id": IG_ACCOUNT, "sender_id": SENDER, "referral": {}})["status"] == "skipped"


def test_referral_fields_read_the_ads_context():
    f = svc.referral_fields(REFERRAL)
    assert f["ad_id"] == "ad-123" and f["headline"] == "Caravan weekend in Coorg" and f["source_type"] == "ad"
    assert svc.referral_fields({"ref": "x"})["source_type"] == "post"
