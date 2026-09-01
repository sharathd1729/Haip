"""Personal/Business-app WhatsApp bridge -- Phase 1: read-only capture.

Session lifecycle (pairing, QR, status) and inbound-message ingestion for
agents who keep guest conversations on their own personal WhatsApp /
WhatsApp Business app instead of the tenant's official Cloud API number.

Deliberately unofficial (whatsmeow's multi-device protocol, not Meta's
Business API) -- see CLAUDE.md's WhatsApp integration notes on ban risk.
Phase 1 scope only: capture into HAIP's Inbox/Leads360 for visibility and
tracking. No AI drafting and no send-through-bridge yet (Phase 2/3).
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.encryption import encrypt_credentials, decrypt_credentials
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import InquirySource
from app.models.whatsapp_personal_session import WhatsAppPersonalSession, WhatsAppPersonalSessionStatus
from app.services.identity_service import resolve_gid
from app.services.leads_service import trigger_summary_refresh

log = structlog.get_logger()


def _phone_token(phone: str) -> str:
    """One-way hash for log correlation without exposing PII phone numbers
    -- same helper shape as whatsapp.py's official-path equivalent."""
    return hashlib.sha256(phone.encode()).hexdigest()[:12]


def _bridge_base_url() -> str:
    return settings.WHATSAPP_BRIDGE_URL.rstrip("/")


def get_session(db: Session, tenant_id: str, user_id: str) -> Optional[WhatsAppPersonalSession]:
    return (
        db.query(WhatsAppPersonalSession)
        .filter_by(tenant_id=tenant_id, user_id=user_id)
        .first()
    )


def list_sessions(db: Session, tenant_id: str) -> list[WhatsAppPersonalSession]:
    """Tenant-wide view for the Ops directory -- owner/manager only, gated
    at the endpoint layer, not here."""
    return db.query(WhatsAppPersonalSession).filter_by(tenant_id=tenant_id).all()


def _decrypt_secret(session: WhatsAppPersonalSession) -> str:
    if not session.webhook_secret_enc:
        return ""
    blob = bytes(session.webhook_secret_enc) if isinstance(session.webhook_secret_enc, memoryview) else session.webhook_secret_enc
    return decrypt_credentials(blob).get("webhook_secret", "")


def verify_bridge_secret(session: WhatsAppPersonalSession, provided_secret: str) -> bool:
    real = _decrypt_secret(session)
    if not real or not provided_secret:
        return False
    return secrets.compare_digest(real, provided_secret)


def start_or_restart_pairing(db: Session, tenant_id: str, user_id: str) -> tuple[WhatsAppPersonalSession, str]:
    """Create (or reuse) this agent's session row, mint a fresh webhook
    secret, and ask the bridge service to start a whatsmeow client for it.

    Returns (session, qr_code_data_url). The QR is single-use and expires
    quickly on WhatsApp's side -- never persisted, only returned once.
    """
    session = get_session(db, tenant_id, user_id)
    new_secret = secrets.token_hex(32)

    if session is None:
        session = WhatsAppPersonalSession(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            status=WhatsAppPersonalSessionStatus.PENDING_PAIRING,
        )
        db.add(session)

    session.status = WhatsAppPersonalSessionStatus.PENDING_PAIRING
    session.webhook_secret_enc = encrypt_credentials({"webhook_secret": new_secret})
    session.last_qr_at = datetime.now(timezone.utc)
    db.flush()

    callback_base = settings.PUBLIC_API_BASE_URL.rstrip("/")
    try:
        resp = httpx.post(
            f"{_bridge_base_url()}/sessions",
            json={
                "session_id": session.id,
                "webhook_secret": new_secret,
                "message_callback_url": f"{callback_base}/api/v1/webhooks/whatsapp-personal/{session.id}/message",
                "status_callback_url": f"{callback_base}/api/v1/webhooks/whatsapp-personal/{session.id}/status",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        qr = data.get("qr_code_data_url", "")
    except Exception as exc:
        log.error("wa_personal_bridge_start_failed", session_id=session.id, error=str(exc))
        raise

    db.commit()
    log.info("wa_personal_pairing_started", tenant_id=tenant_id, user_id=user_id, session_id=session.id)
    return session, qr


def logout_session(db: Session, tenant_id: str, user_id: str) -> bool:
    session = get_session(db, tenant_id, user_id)
    if not session:
        return False
    try:
        httpx.delete(f"{_bridge_base_url()}/sessions/{session.id}", timeout=10.0)
    except Exception as exc:
        log.warning("wa_personal_bridge_logout_call_failed", session_id=session.id, error=str(exc))
    session.status = WhatsAppPersonalSessionStatus.LOGGED_OUT
    db.commit()
    return True


def apply_status_update(
    db: Session, session: WhatsAppPersonalSession, *,
    status: str, phone_number: Optional[str] = None, device_jid: Optional[str] = None,
) -> None:
    """Bridge reports its own connection state -- HAIP's DB is a mirror,
    never the source of truth for whether the socket is actually alive."""
    try:
        session.status = WhatsAppPersonalSessionStatus(status)
    except ValueError:
        log.warning("wa_personal_unknown_status", session_id=session.id, status=status)
        return
    if phone_number:
        session.phone_number = phone_number
    if device_jid:
        session.device_jid = device_jid
    session.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    log.info("wa_personal_status_updated", session_id=session.id, status=status)


def ingest_inbound_message(
    db: Session, session: WhatsAppPersonalSession, *,
    bridge_message_id: str, from_phone: str, from_name: Optional[str], body: str,
) -> Optional[Message]:
    """Mirrors whatsapp.py's `_handle_inbound_message` (the official Cloud
    API path) as closely as possible so Inbox/Leads360/Guest 360 all behave
    identically regardless of which pipe a message came through. The only
    real differences: tenant/agent come from the paired session (not a
    Meta phone_number_id lookup), and no concierge_draft trigger -- Phase 1
    is read-only capture, HAIP has no send capability on this pipe yet.
    """
    existing = db.query(Message).filter_by(channel_message_id=bridge_message_id).first()
    if existing:
        return None

    guest_id, _created = resolve_gid(
        db=db,
        tenant_id=session.tenant_id,
        signal_type="phone",
        value=from_phone,
        source="whatsapp_personal",
        guest_fields={"name": from_name or "Unknown", "phone": from_phone},
    )
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=session.tenant_id).first()

    conversation = (
        db.query(Conversation)
        .filter_by(tenant_id=session.tenant_id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
        .first()
    )
    is_new_conversation = conversation is None
    if not conversation:
        conversation = Conversation(
            id=str(uuid.uuid4()),
            tenant_id=session.tenant_id,
            guest_id=guest_id,
            channel=ChannelType.WHATSAPP,
            is_open=True,
            assigned_to=session.user_id,
            # "shadow" (never auto-sent), not the tenant's wa_ai_mode_default --
            # HAIP has no way to send on this number at all in Phase 1, and
            # even once Phase 2 adds AI-drafted suggestions, they're read by
            # the agent and sent from their own WhatsApp app, never
            # autonomously -- this must never resolve to "autonomous".
            ai_mode="shadow",
        )
        db.add(conversation)
        db.flush()

    conversation.last_message_at = datetime.now(timezone.utc).isoformat()

    message = Message(
        id=str(uuid.uuid4()),
        tenant_id=session.tenant_id,
        conversation_id=conversation.id,
        direction=MessageDirection.INBOUND,
        channel=ChannelType.WHATSAPP,
        body=body,
        channel_message_id=bridge_message_id,
        channel_status="received",
        channel_metadata={"source": "personal_bridge", "session_id": session.id},
    )
    db.add(message)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        log.info("wa_personal_message_duplicate_skipped", bridge_message_id=bridge_message_id)
        return None

    log.info(
        "wa_personal_message_stored",
        guest_token=_phone_token(from_phone), conversation=conversation.id, session_id=session.id,
    )

    if is_new_conversation and body:
        try:
            from app.services.inquiry_service import get_or_create_from_chat
            lead_inquiry = get_or_create_from_chat(
                db, session.tenant_id, guest_id, source=InquirySource.WA_DIRECT.value, message_text=body,
            )
            conversation.inquiry_id = lead_inquiry.id
            if not lead_inquiry.assigned_to:
                lead_inquiry.assigned_to = session.user_id
            db.flush()
        except Exception as exc:
            log.warning("wa_personal_lead_auto_create_failed", tenant_id=session.tenant_id, error=str(exc))

    if conversation.inquiry_id:
        try:
            trigger_summary_refresh(db, conversation.inquiry_id, session.tenant_id, source="message")
        except Exception as exc:
            log.warning("wa_personal_summary_refresh_failed", error=str(exc))

    try:
        from app.services.push_service import send_to_tenant
        send_to_tenant(
            db=db, tenant_id=session.tenant_id,
            title="New WhatsApp message (personal)",
            body=f"{guest.name or 'Guest'}: {(body or '')[:80]}",
            url=f"/dashboard/inbox?id={conversation.id}",
            tag="haip-message",
            user_id=session.user_id,
        )
    except Exception as exc:
        log.warning("wa_personal_push_notify_failed", error=str(exc))

    db.commit()
    return message
