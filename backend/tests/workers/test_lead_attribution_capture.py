"""
Dashboard Metrics Plan Phase 1 — Click-to-Message ad-attribution capture.

Tests:
  WhatsApp inbound WITH referral -> LeadAttribution row, source=CLICK_TO_WA,
    ctwa_clid persisted, inquiry_id linked
  WhatsApp inbound WITHOUT referral -> no row, source stays WA_DIRECT
  Replayed/duplicate referral in the same conversation -> exactly one row
    (idempotency guard)
  Instagram DM WITH referral -> LeadAttribution row, destination=instagram
  Instagram comment on a running ad -> LeadAttribution row, source_type=ad
  Destination split: WhatsApp + Instagram leads group correctly by channel
  Cross-tenant isolation on get_channel_attribution
"""
import os
import uuid
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.models.tenant import Tenant
from app.models.integration import Integration
from app.models.inquiry import Inquiry, InquirySource
from app.models.lead_attribution import LeadAttribution
from app.core.encryption import encrypt_credentials
from app.workers.tasks import whatsapp as wa_mod
from app.workers.tasks import process_instagram_dm as dm_mod
from app.workers.tasks import process_instagram_comment as comment_mod
from app.services import attribution_service


class _NoCloseSessionWrapper:
    def __init__(self, real_db):
        self._real_db = real_db

    def __getattr__(self, name):
        return getattr(self._real_db, name)

    def close(self):
        pass


def _make_tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_ig_integration(db, tenant_id, ig_account_id="ig-biz-001"):
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="instagram", status="active",
        credentials_kms_blob=encrypt_credentials({"access_token": "tok"}),
        config={"instagram_business_account_id": ig_account_id},
    )
    db.add(integration)
    db.flush()
    return integration


_WA_REFERRAL = {
    "source_url": "https://fb.me/ad123",
    "source_id": "ad_987654321",
    "source_type": "ad",
    "headline": "Book your Goa villa",
    "body": "Limited offer",
    "media_type": "image",
    "ctwa_clid": "clid.abc123xyz",
}


# ── WhatsApp ──────────────────────────────────────────────────────────────────

def test_whatsapp_referral_creates_click_to_wa_attribution(db):
    tenant = _make_tenant(db)
    msg = {
        "from": "919876543210", "id": "wamid.ref1", "type": "text",
        "text": {"body": "Hi, saw your ad"},
        "referral": _WA_REFERRAL,
    }

    with patch.object(wa_mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        wa_mod._handle_inbound_message(db, tenant, msg, contacts=[])
        db.commit()

    inquiry = db.query(Inquiry).filter_by(tenant_id=tenant.id).first()
    assert inquiry is not None
    assert inquiry.source == InquirySource.CLICK_TO_WA

    row = db.query(LeadAttribution).filter_by(tenant_id=tenant.id).first()
    assert row is not None
    assert row.destination_channel == "whatsapp"
    assert row.ad_id == "ad_987654321"
    assert row.ctwa_clid == "clid.abc123xyz"
    assert row.inquiry_id == inquiry.id


def test_whatsapp_no_referral_stays_wa_direct(db):
    tenant = _make_tenant(db)
    msg = {
        "from": "919876500000", "id": "wamid.noref1", "type": "text",
        "text": {"body": "Hi, is the villa available?"},
    }

    with patch.object(wa_mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        wa_mod._handle_inbound_message(db, tenant, msg, contacts=[])
        db.commit()

    inquiry = db.query(Inquiry).filter_by(tenant_id=tenant.id).first()
    assert inquiry.source == InquirySource.WA_DIRECT
    assert db.query(LeadAttribution).filter_by(tenant_id=tenant.id).count() == 0


def test_whatsapp_referral_replay_creates_exactly_one_row(db):
    """A retried/duplicated webhook for the same conversation's referral
    must never create a second lead_attribution row -- Meta sends it once,
    and (tenant_id, conversation_id) is unique."""
    tenant = _make_tenant(db)
    msg1 = {
        "from": "919876511111", "id": "wamid.replay1", "type": "text",
        "text": {"body": "Hi from the ad"}, "referral": _WA_REFERRAL,
    }
    msg2 = {
        # Different wa_msg_id (as a retried delivery with a fresh envelope
        # might carry) but same sender -> same conversation.
        "from": "919876511111", "id": "wamid.replay2", "type": "text",
        "text": {"body": "still here"}, "referral": _WA_REFERRAL,
    }

    with patch.object(wa_mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        wa_mod._handle_inbound_message(db, tenant, msg1, contacts=[])
        db.commit()
        wa_mod._handle_inbound_message(db, tenant, msg2, contacts=[])
        db.commit()

    assert db.query(LeadAttribution).filter_by(tenant_id=tenant.id).count() == 1


# ── Instagram DM ──────────────────────────────────────────────────────────────

def _dm_payload(sender_id="ig-sender-1", referral=None, message_id=None):
    return {
        "ig_account_id": "ig-biz-001",
        "sender_id": sender_id,
        "message_id": message_id or f"mid-{uuid.uuid4().hex[:8]}",
        "text": "hi, saw your reel",
        "attachments": [],
        "referral": referral,
    }


def test_instagram_dm_referral_creates_attribution(db):
    tenant = _make_tenant(db)
    _make_ig_integration(db, tenant.id)
    db.commit()

    referral = {"ad_id": "ad_ig_555", "headline": "Book now", "media_type": "video"}

    with patch.object(dm_mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter") as mock_adapter_cls, \
         patch("app.workers.tasks.concierge_draft.concierge_draft") as mock_concierge, \
         patch.object(dm_mod, "backfill_instagram_guest_name") as mock_backfill:
        mock_adapter_cls.return_value.send_text.return_value = {"message_id": "wamid.x"}
        mock_concierge.apply_async.return_value = None
        mock_backfill.apply_async.return_value = None
        dm_mod.process_instagram_dm.run(_dm_payload(referral=referral))

    row = db.query(LeadAttribution).filter_by(tenant_id=tenant.id).first()
    assert row is not None
    assert row.destination_channel == "instagram"
    assert row.ad_id == "ad_ig_555"
    assert row.source_type == "ad"

    inquiry = db.query(Inquiry).filter_by(tenant_id=tenant.id).first()
    assert inquiry is not None
    assert row.inquiry_id == inquiry.id


# ── Instagram comment ─────────────────────────────────────────────────────────

def _comment_payload(comment_id="c1", media_ad_id="", media_ad_title=""):
    return {
        "ig_account_id": "ig-biz-001",
        "sender_id": "ig-commenter-1",
        "comment_id": comment_id,
        "text": "how much per night?",
        "media_id": "media-1",
        "media_ad_id": media_ad_id,
        "media_ad_title": media_ad_title,
        "sender_username": "curious_traveler",
    }


def test_instagram_comment_on_ad_creates_attribution(db):
    tenant = _make_tenant(db)
    _make_ig_integration(db, tenant.id)
    db.commit()

    with patch.object(comment_mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.workers.tasks.process_instagram_dm.backfill_instagram_guest_name") as mock_backfill:
        mock_backfill.apply_async.return_value = None
        comment_mod.process_instagram_comment.run(
            _comment_payload(media_ad_id="ad_comment_777", media_ad_title="Villa Sale")
        )

    row = db.query(LeadAttribution).filter_by(tenant_id=tenant.id).first()
    assert row is not None
    assert row.destination_channel == "instagram"
    assert row.ad_id == "ad_comment_777"
    assert row.source_type == "ad"
    assert row.headline == "Villa Sale"


def test_instagram_comment_without_ad_creates_no_attribution(db):
    tenant = _make_tenant(db)
    _make_ig_integration(db, tenant.id)
    db.commit()

    with patch.object(comment_mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.workers.tasks.process_instagram_dm.backfill_instagram_guest_name") as mock_backfill:
        mock_backfill.apply_async.return_value = None
        comment_mod.process_instagram_comment.run(_comment_payload())

    assert db.query(LeadAttribution).filter_by(tenant_id=tenant.id).count() == 0


# ── Destination split + cross-tenant isolation ────────────────────────────────

def test_destination_channel_grouping(db):
    """One ad running on both WhatsApp and Instagram destinations must group
    into two distinct channel rows, not merge or overwrite each other."""
    tenant = _make_tenant(db)

    with patch.object(wa_mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        wa_mod._handle_inbound_message(
            db, tenant,
            {"from": "919876522222", "id": "wamid.split1", "type": "text",
             "text": {"body": "hi"}, "referral": _WA_REFERRAL},
            contacts=[],
        )
        db.commit()

    _make_ig_integration(db, tenant.id)
    db.commit()
    with patch.object(dm_mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter") as mock_adapter_cls, \
         patch("app.workers.tasks.concierge_draft.concierge_draft") as mock_concierge, \
         patch.object(dm_mod, "backfill_instagram_guest_name") as mock_backfill:
        mock_adapter_cls.return_value.send_text.return_value = {"message_id": "wamid.x"}
        mock_concierge.apply_async.return_value = None
        mock_backfill.apply_async.return_value = None
        dm_mod.process_instagram_dm.run(_dm_payload(
            sender_id="ig-split-1", referral={"ad_id": "ad_987654321", "headline": "Same ad"},
        ))

    result = attribution_service.get_channel_attribution(db, tenant.id, days=30)
    by_channel = {c.destination_channel: c for c in result.channels}
    assert set(by_channel.keys()) == {"whatsapp", "instagram"}
    assert by_channel["whatsapp"].lead_count == 1
    assert by_channel["instagram"].lead_count == 1
    assert result.total_attributed_leads == 2


def test_get_channel_attribution_cross_tenant_isolation(db):
    tenant_a = _make_tenant(db, "TenantA")
    tenant_b = _make_tenant(db, "TenantB")

    with patch.object(wa_mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        wa_mod._handle_inbound_message(
            db, tenant_a,
            {"from": "919876533333", "id": "wamid.iso1", "type": "text",
             "text": {"body": "hi"}, "referral": _WA_REFERRAL},
            contacts=[],
        )
        db.commit()

    result_a = attribution_service.get_channel_attribution(db, tenant_a.id, days=30)
    result_b = attribution_service.get_channel_attribution(db, tenant_b.id, days=30)
    assert result_a.total_attributed_leads == 1
    assert result_b.total_attributed_leads == 0
