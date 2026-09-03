"""
T3.3 — Phase 3 gating tests for process_instagram_dm.py

Tests:
  A message matching a keyword rule never produces a concierge_draft row
  A message matching no rule, ai_mode != "off", produces exactly one concierge_draft dispatch
  A message matching no rule, ai_mode == "off", produces no reply at all
  Tenant isolation on the new AI config columns
"""

import uuid
from unittest.mock import MagicMock, patch

from app.models.tenant import Tenant
from app.models.integration import Integration
from app.models.guest import Guest
from app.models.conversation import Conversation
from app.models.automation import AutomationRule
from app.core.encryption import encrypt_credentials


def _make_tenant(db, ig_ai_mode_default="shadow"):
    t = Tenant(
        id=str(uuid.uuid4()), name="Test Villa", slug=f"villa-{uuid.uuid4().hex[:6]}", plan="growth",
        ig_ai_mode_default=ig_ai_mode_default,
    )
    db.add(t)
    db.flush()
    return t


def _make_ig_integration(db, tenant_id, ig_account_id="ig-biz-001"):
    import os
    os.environ.setdefault("ENCRYPTION_KEY", "test-fernet-key-must-be-32-urlsafe=")
    from cryptography.fernet import Fernet
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

    integration = Integration(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        kind="instagram",
        status="active",
        credentials_kms_blob=encrypt_credentials({"app_secret": "s", "access_token": "test-token"}),
        config={"instagram_business_account_id": ig_account_id},
    )
    db.add(integration)
    db.flush()
    return integration


def _make_rule(db, tenant_id, keywords):
    rule = AutomationRule(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name="Price rule",
        trigger="ig_dm_received",
        trigger_config={"keywords": keywords},
        action="send_instagram_quick_reply",
        action_config={"message": "Our villas start at 18000/night"},
        is_active=True,
    )
    db.add(rule)
    db.flush()
    return rule


def _run_dm_task(db, tenant, integration, sender_id, text):
    """
    Invoke process_instagram_dm with the task's own SessionLocal patched to
    the shared test session (same technique as test_webhooks_instagram_comment.py
    -- the task creates its own SessionLocal() internally, so a second real
    connection can't see this test's uncommitted transaction).
    """
    from app.workers.tasks import process_instagram_dm as mod

    class _NoCloseSessionWrapper:
        def __init__(self, real_session):
            self._s = real_session
        def __getattr__(self, name):
            return getattr(self._s, name)
        def close(self):
            pass

    payload = {
        "ig_account_id": integration.config["instagram_business_account_id"],
        "sender_id": sender_id,
        "message_id": f"mid-{uuid.uuid4().hex[:8]}",
        "text": text,
        "attachments": [],
    }

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter") as mock_adapter_cls, \
         patch("app.workers.tasks.concierge_draft.concierge_draft") as mock_concierge, \
         patch.object(mod, "backfill_instagram_guest_name") as mock_backfill:
        mock_adapter_cls.return_value.send_text.return_value = {"message_id": "wamid.x"}
        mock_adapter_cls.return_value.reply_to_comment.return_value = {}
        mock_concierge.apply_async = MagicMock()
        mock_backfill.apply_async = MagicMock()

        result = mod.process_instagram_dm.run(payload)

    return result, mock_concierge.apply_async


# ── Keyword match never produces a concierge_draft dispatch ─────────────────

def test_keyword_matched_dm_never_queues_concierge_draft(db):
    tenant = _make_tenant(db)
    integration = _make_ig_integration(db, tenant.id)
    _make_rule(db, tenant.id, keywords=["price"])

    result, mock_apply_async = _run_dm_task(db, tenant, integration, sender_id="guest-001", text="what's the price?")

    assert result["status"] == "ok"
    mock_apply_async.assert_not_called()


# ── No match, ai_mode != off -> exactly one concierge_draft dispatch ────────

def test_unmatched_dm_ai_mode_on_queues_concierge_draft_once(db):
    tenant = _make_tenant(db, ig_ai_mode_default="shadow")
    integration = _make_ig_integration(db, tenant.id)
    # No automation rule at all -- nothing can match.

    result, mock_apply_async = _run_dm_task(db, tenant, integration, sender_id="guest-002", text="hello there!")

    assert result["status"] == "ok"
    assert mock_apply_async.call_count == 1


# ── No match, ai_mode == off -> no reply at all ──────────────────────────────

def test_unmatched_dm_ai_mode_off_produces_no_reply(db):
    tenant = _make_tenant(db, ig_ai_mode_default="off")
    integration = _make_ig_integration(db, tenant.id)

    result, mock_apply_async = _run_dm_task(db, tenant, integration, sender_id="guest-003", text="hello there!")

    assert result["status"] == "ok"
    mock_apply_async.assert_not_called()

    # Confirm the new conversation actually inherited ai_mode="off" from the tenant.
    conv = db.query(Conversation).filter_by(tenant_id=tenant.id).first()
    assert conv is not None
    assert conv.ai_mode == "off"


# ── Tenant isolation on the new AI config columns ────────────────────────────

def test_tenant_ai_config_columns_are_isolated(db):
    tenant_a = _make_tenant(db, ig_ai_mode_default="autonomous")
    tenant_b = _make_tenant(db, ig_ai_mode_default="shadow")
    db.commit()

    refreshed_a = db.query(Tenant).filter_by(id=tenant_a.id).first()
    refreshed_b = db.query(Tenant).filter_by(id=tenant_b.id).first()

    assert refreshed_a.ig_ai_mode_default == "autonomous"
    assert refreshed_b.ig_ai_mode_default == "shadow"
    assert refreshed_a.ig_ai_confidence_threshold == 0.78
    assert refreshed_b.ig_ai_confidence_threshold == 0.78


# ── Push notification (regression: SSE-only, mobile never got notified) ─────

def test_inbound_dm_sends_push_notification(db):
    """SSE alone only reaches an already-open tab -- confirmed live, an
    inbound Instagram DM showed up in the in-app bell but never reached a
    phone with the app backgrounded/closed, because this call was missing
    entirely (present for WhatsApp -- see whatsapp.py -- never for
    Instagram)."""
    from app.workers.tasks import process_instagram_dm as mod

    tenant = _make_tenant(db, ig_ai_mode_default="off")
    integration = _make_ig_integration(db, tenant.id)

    class _NoCloseSessionWrapper:
        def __init__(self, real_session):
            self._s = real_session
        def __getattr__(self, name):
            return getattr(self._s, name)
        def close(self):
            pass

    payload = {
        "ig_account_id": integration.config["instagram_business_account_id"],
        "sender_id": "guest-push-001",
        "message_id": f"mid-{uuid.uuid4().hex[:8]}",
        "text": "hi, are villas available this weekend?",
        "attachments": [],
    }

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter") as mock_adapter_cls, \
         patch.object(mod, "backfill_instagram_guest_name"), \
         patch("app.services.push_service.send_to_tenant") as mock_push:
        mock_adapter_cls.return_value.send_text.return_value = {"message_id": "wamid.x"}
        result = mod.process_instagram_dm.run(payload)

    assert result["status"] == "ok"
    mock_push.assert_called_once()
    _, kwargs = mock_push.call_args
    assert kwargs["tenant_id"] == tenant.id
    assert kwargs["title"] == "New Instagram DM"
    assert "hi, are villas available" in kwargs["body"]


# ── Phone-in-text is captured, but never forces the thread to shadow mode
# (policy reversed after live reports -- see process_instagram_dm.py) ──────

def test_guest_sharing_phone_number_does_not_set_human_owned(db):
    """Sharing a phone number is still captured as an identity signal (and
    still promotes a stuck default-stage inquiry, see the test below), but
    no longer forces this conversation into shadow mode -- an autonomous
    tenant keeps auto-replying on this thread regardless."""
    tenant = _make_tenant(db, ig_ai_mode_default="autonomous")
    integration = _make_ig_integration(db, tenant.id)

    result, _ = _run_dm_task(db, tenant, integration, sender_id="guest-phone-001", text="You can reach me at 9876543210")

    assert result["status"] == "ok"
    conv = db.query(Conversation).filter_by(tenant_id=tenant.id).first()
    assert conv is not None
    assert conv.human_owned is False


def test_message_without_phone_number_does_not_set_human_owned(db):
    tenant = _make_tenant(db, ig_ai_mode_default="autonomous")
    integration = _make_ig_integration(db, tenant.id)

    result, _ = _run_dm_task(db, tenant, integration, sender_id="guest-nophone-001", text="What destinations do you cover?")

    assert result["status"] == "ok"
    conv = db.query(Conversation).filter_by(tenant_id=tenant.id).first()
    assert conv is not None
    assert conv.human_owned is False


def test_phone_shared_on_a_later_message_promotes_stuck_default_stage_inquiry(db):
    """Real bug, reported live: an opener with no phone lands the inquiry in
    the tenant's default (invalid-category) entry stage -- lead_auto_create
    only routes at inquiry-creation time. If the guest then shares their
    phone number a message or two later (the common case), nothing used to
    re-evaluate the stage: the lead stayed stuck as e.g. "Unqualified"
    forever even though it now has exactly the info that stage was waiting
    on, and never surfaced in the "Shared their details" dashboard widget
    (which only counts valid-category stages)."""
    from app.services.pipeline_stage_service import seed_default_pipeline_stages
    from app.models.pipeline_stage import PipelineStage
    from app.models.conversation import Conversation as Conv

    tenant = _make_tenant(db, ig_ai_mode_default="autonomous")
    integration = _make_ig_integration(db, tenant.id)
    seed_default_pipeline_stages(db, tenant.id)
    db.commit()

    result, _ = _run_dm_task(db, tenant, integration, sender_id="guest-latephone-001", text="Hi, are villas available?")
    assert result["status"] == "ok"

    conv = db.query(Conv).filter_by(tenant_id=tenant.id).first()
    assert conv is not None and conv.inquiry_id is not None
    from app.models.inquiry import Inquiry
    inquiry = db.query(Inquiry).filter_by(id=conv.inquiry_id).first()
    default_stage = db.query(PipelineStage).filter_by(tenant_id=tenant.id, is_default_entry=True).first()
    assert inquiry.stage_id == default_stage.id  # confirms it landed stuck, per the bug

    result2, _ = _run_dm_task(db, tenant, integration, sender_id="guest-latephone-001", text="You can reach me at 9876543210")
    assert result2["status"] == "ok"

    db.refresh(inquiry)
    valid_stage = db.query(PipelineStage).filter_by(tenant_id=tenant.id, is_valid_lead_entry=True).first()
    assert inquiry.stage_id == valid_stage.id
    assert conv.human_owned is False  # phone capture no longer forces shadow mode
