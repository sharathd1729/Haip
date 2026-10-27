"""Personal/Business-app WhatsApp bridge -- read-only capture (Phase 1, widened Oct 2026 to a WhatsApp-Web-style mirror).

Session lifecycle (pairing, QR, status) and inbound-message ingestion for
agents who keep guest conversations on their own personal WhatsApp /
WhatsApp Business app instead of the tenant's official Cloud API number.

Deliberately unofficial (whatsmeow's multi-device protocol, not Meta's
Business API) -- see CLAUDE.md's WhatsApp integration notes on ban risk.
Mirrors guest messages, the agent's own replies, group chats, media and recent history into HAIP's Inbox. Read-only: HAIP never
sends through it and there is no AI drafting on these threads. Only a LIVE inbound 1:1 message makes a lead; mirrored chats
(history, own messages, groups) are guests with no phone signal, so they never count as leads.
"""
import hashlib
import secrets
import uuid
import base64
import binascii
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.cache import get_cached, set_cached
from app.core.config import settings
from app.core.encryption import encrypt_credentials, decrypt_credentials
from app.models.conversation import Conversation, Message, ChannelType, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import InquirySource
from app.models.user import User
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


def start_or_restart_pairing(
    db: Session, tenant_id: str, user_id: str, phone_number: Optional[str] = None,
) -> tuple[WhatsAppPersonalSession, str, str]:
    """Create (or reuse) this agent's session row, mint a fresh webhook
    secret, and ask the bridge service to start a whatsmeow client for it.

    Returns (session, qr_code_data_url, pairing_code) -- exactly one of the
    last two is populated, depending on whether phone_number was given.
    Both are single-use / short-lived on WhatsApp's side -- never
    persisted, only returned once (the QR additionally gets cached for
    rotation pickup, see get_cached_qr).
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
        payload = {
            "session_id": session.id,
            "webhook_secret": new_secret,
            "message_callback_url": f"{callback_base}/api/v1/webhooks/whatsapp-personal/{session.id}/message",
            "status_callback_url": f"{callback_base}/api/v1/webhooks/whatsapp-personal/{session.id}/status",
        }
        if phone_number:
            payload["phone_number"] = phone_number
        resp = httpx.post(f"{_bridge_base_url()}/sessions", json=payload, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        qr = data.get("qr_code_data_url", "")
        pairing_code = data.get("pairing_code", "")
    except Exception as exc:
        log.error("wa_personal_bridge_start_failed", session_id=session.id, error=str(exc))
        raise

    if qr:
        # Cache the initial code too, not just later rotations -- keeps
        # /sessions/me authoritative from the very first poll rather than
        # briefly returning null until the bridge's first rotation webhook
        # arrives (the frontend already has this exact value from this
        # call's own return value, so this only matters for a second tab
        # or a page reload during the same pairing attempt).
        set_cached(_qr_cache_key(session.id), qr, ttl=60)

    db.commit()
    log.info(
        "wa_personal_pairing_started", tenant_id=tenant_id, user_id=user_id, session_id=session.id,
        via="phone_code" if phone_number else "qr",
    )
    return session, qr, pairing_code


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


def _qr_cache_key(session_id: str) -> str:
    return f"haip:wa_personal_qr:{session_id}"


def get_cached_qr(session_id: str) -> Optional[str]:
    """The QR the agent is currently looking at, if pairing is still in
    progress. WhatsApp rotates the code roughly every 20-30s; the bridge
    pushes each rotation here so a polling frontend can refresh the image
    instead of showing one that's already expired -- a real pairing
    attempt failed ("Couldn't link device") from exactly that gap."""
    return get_cached(_qr_cache_key(session_id))


def apply_status_update(
    db: Session, session: WhatsAppPersonalSession, *,
    status: str, phone_number: Optional[str] = None, device_jid: Optional[str] = None,
    qr_code_data_url: Optional[str] = None,
) -> None:
    """Bridge reports its own connection state -- HAIP's DB is a mirror,
    never the source of truth for whether the socket is actually alive."""
    if qr_code_data_url:
        # A rotated code during an ongoing pairing attempt -- status is
        # already "pending_pairing" in the DB, cache the fresh QR
        # alongside it rather than writing to the DB on every rotation.
        set_cached(_qr_cache_key(session.id), qr_code_data_url, ttl=60)

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


MEDIA_KINDS = ("image", "video", "audio", "document", "sticker")
MAX_MEDIA_BYTES = 16 * 1024 * 1024
_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "video/mp4": "mp4", "video/3gpp": "3gp",
        "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "aac", "application/pdf": "pdf"}
_PLACEHOLDER = {"image": "[photo]", "video": "[video]", "audio": "[voice message]", "document": "[document]", "sticker": "[sticker]"}


def _thread_value(chat_jid: str) -> str:
    return f"wapersonal:{chat_jid}".lower()


def _existing_guest_by_phone(db: Session, tenant_id: str, phone: str) -> Optional[str]:
    """A guest already known by this number, WITHOUT creating one (creating a guest with a phone makes them a lead)."""
    from app.models.guest_identity import GuestIdentity
    from app.services import phone_identity

    good = phone_identity.normalize(phone, phone_identity.region_for_tenant(db, tenant_id))
    if not good:
        return None
    row = (db.query(GuestIdentity).filter(GuestIdentity.tenant_id == tenant_id, GuestIdentity.identity_value == good,
                                          GuestIdentity.identity_type.in_(["phone", "whatsapp_number"])).first())
    return row.guest_id if row else None


_GENERIC_NAMES = ("", "unknown", "whatsapp contact", "whatsapp group")


def fill_mirror_identity(guest: Optional[Guest], phone: Optional[str], name: Optional[str]) -> None:
    """Show what we know about a MIRRORED contact (a chat that is not a lead): its number for display and its real name. The phone
    goes on the guest row only, never as an identity signal, so the contact does not become a lead. Never overwrites a real value."""
    if guest is None:
        return
    if phone and not (guest.phone or "").strip():
        guest.phone = phone
    n = (guest.name or "").strip()
    if name and (n.lower() in _GENERIC_NAMES or n.lstrip("+").isdigit()):
        guest.name = name[:255]


def _store_media(session: WhatsAppPersonalSession, message_id: str, kind: str, mime: Optional[str], data_b64: str) -> tuple[Optional[str], Optional[str]]:
    """(storage key, kind) or (None, None). Never raises: a failed file must not cost the message."""
    try:
        raw = base64.b64decode(data_b64, validate=False)
    except (binascii.Error, ValueError):
        return None, None
    if not raw or len(raw) > MAX_MEDIA_BYTES:
        return None, None
    try:
        from app.services.media_storage import upload_personal_whatsapp_media
        ext = _EXT.get((mime or "").split(";")[0].strip().lower(), "")
        key = upload_personal_whatsapp_media(session.tenant_id, session.id, message_id, raw, mime or "application/octet-stream", ext)
        return key, kind
    except Exception as exc:  # noqa: BLE001
        log.warning("wa_personal_media_store_failed", session_id=session.id, error=str(exc)[:200])
        return None, None


def ingest_chat_message(
    db: Session, session: WhatsAppPersonalSession, *,
    bridge_message_id: str, from_phone: str = "", from_name: Optional[str] = None, body: str = "",
    occurred_at: Optional[datetime] = None, chat_jid: Optional[str] = None, chat_type: str = "user", chat_name: Optional[str] = None,
    direction: str = "inbound", history: bool = False, media_kind: Optional[str] = None, media_mime: Optional[str] = None,
    media_filename: Optional[str] = None, media_base64: Optional[str] = None, media_skipped: Optional[str] = None,
) -> Optional[Message]:
    """One message from the paired phone: a guest's, the agent's own, a group's, or an older one from the history sync.

    Mirrors whatsapp.py's `_handle_inbound_message` (the official Cloud API path) so Inbox/Leads360/Guest 360 behave the same
    whichever pipe a message came through. What differs: tenant and agent come from the paired session, nothing is ever sent or
    AI-drafted, and a chat is only treated as a LEAD when the guest messages live (see the module docstring)."""
    existing = db.query(Message).filter_by(channel_message_id=bridge_message_id, tenant_id=session.tenant_id).first()
    if existing:
        return None

    outbound = direction == "outbound"
    is_group = chat_type == "group"
    # A lead needs a usable phone number: WhatsApp sometimes shows only an internal @lid id, and that chat is mirrored, not a lead.
    live_guest_message = (not outbound) and (not history) and (not is_group) and bool(from_phone)
    if live_guest_message:
        # Staff are not guests (docs/ops/OPS_MODULE_PLAN.md §0.1): a staff member's chat is still mirrored, but never becomes a lead.
        from app.services.staff_service import find_active_staff_by_phone
        if find_active_staff_by_phone(db, session.tenant_id, from_phone) is not None:
            live_guest_message = False
    chat_jid = chat_jid or (f"{from_phone.lstrip('+')}@s.whatsapp.net" if from_phone else None)
    if not chat_jid and not from_phone:
        log.warning("wa_personal_message_without_chat", session_id=session.id)
        return None

    # -- which guest (a person, or for a group the group itself) -----------------
    conversation = None
    if chat_jid:
        conversation = (db.query(Conversation).filter_by(tenant_id=session.tenant_id, channel=ChannelType.WHATSAPP, source="personal_bridge",
                                                         channel_conversation_id=chat_jid).first())
    promoted = False
    if conversation is not None:
        guest_id = conversation.guest_id
        if live_guest_message and from_phone:
            guest_row = db.query(Guest).filter_by(id=guest_id, tenant_id=session.tenant_id).first()
            if guest_row is not None and guest_row.lead_identified_at is None:
                # A chat we only mirrored so far: this person has now written to the agent, so they become a lead (the same
                # as every first live message always did).
                from app.services.identity_service import add_signal
                try:
                    add_signal(db, session.tenant_id, guest_id, "phone", from_phone, source="whatsapp_personal")
                    promoted = True
                except Exception as exc:  # noqa: BLE001
                    log.warning("wa_personal_promote_failed", session_id=session.id, error=str(exc)[:200])
    else:
        if is_group:
            guest_id, _ = resolve_gid(db=db, tenant_id=session.tenant_id, signal_type="channel_thread_id", value=_thread_value(chat_jid),
                                      source="whatsapp_personal", guest_fields={"name": chat_name or "WhatsApp group"})
        elif live_guest_message:
            guest_id, _ = resolve_gid(db=db, tenant_id=session.tenant_id, signal_type="phone", value=from_phone, source="whatsapp_personal",
                                      guest_fields={"name": from_name or "Unknown", "phone": from_phone})
        else:
            guest_id = _existing_guest_by_phone(db, session.tenant_id, from_phone) if from_phone else None
            if guest_id is None:
                guest_id, _ = resolve_gid(db=db, tenant_id=session.tenant_id, signal_type="channel_thread_id", value=_thread_value(chat_jid or from_phone),
                                          source="whatsapp_personal", guest_fields={"name": chat_name or from_name or from_phone or "WhatsApp contact"})
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=session.tenant_id).first()
    if not live_guest_message and not is_group:
        fill_mirror_identity(guest, from_phone, chat_name or from_name)

    if conversation is None and not is_group:
        # A guest can have only ONE open WhatsApp conversation (unique index): a known lead's own thread is reused, for history and
        # own replies too, never a second one beside it.
        conversation = (db.query(Conversation).filter_by(tenant_id=session.tenant_id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True).first())
    is_new_conversation = conversation is None
    if conversation is None:
        conversation = Conversation(
            id=str(uuid.uuid4()), tenant_id=session.tenant_id, guest_id=guest_id, channel=ChannelType.WHATSAPP,
            source="personal_bridge", channel_conversation_id=chat_jid, is_open=True, assigned_to=session.user_id,
            # Never autonomous and never drafting: HAIP cannot send on this number. Live guest chats stay "shadow" as before;
            # mirrored chats (own messages, groups, history) are "off" so the concierge is never asked about them.
            ai_mode="shadow" if live_guest_message else "off",
        )
        db.add(conversation)
        db.flush()
    elif conversation.source == "personal_bridge" and not conversation.channel_conversation_id and chat_jid:
        conversation.channel_conversation_id = chat_jid

    when = occurred_at if occurred_at is not None else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    previous = conversation.last_message_at
    if not previous or previous < when.isoformat():
        conversation.last_message_at = when.isoformat()
    if outbound and not history and not conversation.first_response_at:
        conversation.first_response_at = when.isoformat()          # a reply typed on the agent's own phone is a reply

    # -- the message ---------------------------------------------------------------
    media_key = media_type = None
    if media_kind in MEDIA_KINDS and media_base64:
        media_key, media_type = _store_media(session, bridge_message_id, media_kind, media_mime, media_base64)
    text = body or ""
    if media_kind in MEDIA_KINDS and not text:
        text = _PLACEHOLDER[media_kind] if (media_key is None or media_skipped) else ""
    meta = {"source": "personal_bridge", "session_id": session.id, "chat_jid": chat_jid, "chat_type": chat_type}
    if is_group:
        meta.update({"sender_name": from_name, "sender_phone": from_phone or None})
    if media_filename:
        meta["filename"] = media_filename[:200]
    if media_skipped:
        meta["media_skipped"] = media_skipped
    if history:
        meta["history"] = True
    message = Message(
        id=str(uuid.uuid4()), tenant_id=session.tenant_id, conversation_id=conversation.id,
        direction=MessageDirection.OUTBOUND if outbound else MessageDirection.INBOUND, channel=ChannelType.WHATSAPP,
        body=text, media_url=media_key, media_type=media_type, channel_message_id=bridge_message_id,
        channel_status="sent" if outbound else "received", channel_metadata=meta, created_at=when,
        # Mirrored history is never fresh contact; a live reply from the agent's own phone is (work_queue_signals.touch_rows).
        sender_kind="bridge_history" if history else ("bridge_live" if outbound else None),
    )
    if outbound:
        message.sender_id = session.user_id
        message.sender_name = (db.query(User.name).filter_by(id=session.user_id).scalar() or "Agent") if session.user_id else "Agent"
        message.delivery_state = MessageDeliveryState.SENT
        message.is_ai_generated = False
    elif is_group:
        message.sender_name = from_name or from_phone or "Member"
    db.add(message)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        log.info("wa_personal_message_duplicate_skipped", bridge_message_id=bridge_message_id)
        return None

    log.info("wa_personal_message_stored", guest_token=_phone_token(from_phone or chat_jid or ""), conversation=conversation.id,
             session_id=session.id, direction=direction, group=is_group, history=history, media=bool(media_key))

    # -- a Lost lead comes back on live contact (lead_reopen): the guest wrote, or the agent replied from their phone ----
    if live_guest_message:
        from app.services import lead_reopen
        lead_reopen.on_contact(db, session.tenant_id, guest_id, trigger="personal_whatsapp_message", by_guest=True)
    elif outbound and not history and not is_group:
        from app.services import lead_reopen
        lead_reopen.on_contact(db, session.tenant_id, guest_id, trigger="team_message", by_guest=False,
                               actor_user_id=session.user_id)

    # -- lead, summary and push: only for a live guest message ------------------------
    if live_guest_message and (is_new_conversation or promoted) and text:
        try:
            from app.services.inquiry_service import get_or_create_from_chat
            lead_inquiry = get_or_create_from_chat(db, session.tenant_id, guest_id, source=InquirySource.WA_DIRECT.value, message_text=text)
            conversation.inquiry_id = lead_inquiry.id
            if not lead_inquiry.assigned_to:
                lead_inquiry.assigned_to = session.user_id
            db.flush()
        except Exception as exc:
            log.warning("wa_personal_lead_auto_create_failed", tenant_id=session.tenant_id, error=str(exc))

    if live_guest_message and conversation.inquiry_id:
        try:
            trigger_summary_refresh(db, conversation.inquiry_id, session.tenant_id, source="message")
        except Exception as exc:
            log.warning("wa_personal_summary_refresh_failed", error=str(exc))

    if live_guest_message:
        try:
            from app.services.push_service import send_to_tenant
            send_to_tenant(
                db=db, tenant_id=session.tenant_id,
                title="New WhatsApp message (personal)",
                body=f"{(guest.name if guest else None) or 'Guest'}: {(text or '')[:80]}",
                url=f"/dashboard/inbox?id={conversation.id}",
                tag="haip-message",
                user_id=session.user_id,
            )
        except Exception as exc:
            log.warning("wa_personal_push_notify_failed", error=str(exc))

    db.commit()
    return message


def ingest_inbound_message(
    db: Session, session: WhatsAppPersonalSession, *,
    bridge_message_id: str, from_phone: str, from_name: Optional[str], body: str,
) -> Optional[Message]:
    """The original Phase 1 entry point (a live 1:1 guest text), kept for older callers and tests."""
    return ingest_chat_message(db, session, bridge_message_id=bridge_message_id, from_phone=from_phone, from_name=from_name, body=body)
