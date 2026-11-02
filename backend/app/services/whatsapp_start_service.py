"""Start (or continue) a guest's chat on the official WhatsApp number with an approved template.

Built for leads who came in on Instagram and gave their number there (owner, 26 Oct 2026: "what is the use of taking the
number?"): before this, a guest with a phone but no WhatsApp conversation could not be messaged on WhatsApp at all.

``start`` is the one way a PERSON does it (``POST /guests/{guest_id}/whatsapp/start``):
* the number must pass the same check as every WhatsApp send (``send_whatsapp._bad_number_reason``);
* the guest's open official WhatsApp conversation is reused, else ONE is opened (``wa_booking_messages._open_conversation``;
  the unique index ``ix_conversations_one_open_per_guest_channel`` decides a race, the loser reuses the winner's row);
* never into a personal-WhatsApp mirror thread (read-only, 409 ``personal_bridge_read_only``);
* the WhatsApp signal goes on the guest only through ``identity_service.add_signal``;
* the Message row is written like ``POST /conversations/{id}/send-template`` (template text, QUEUED, the same Celery task)
  and the start is audited ``conversation.whatsapp_started``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection

log = structlog.get_logger()


class Refused(Exception):
    """A start (or template send) that must not go, with the HTTP status and plain words for the person."""

    def __init__(self, status: int, detail):
        super().__init__(str(detail))
        self.status, self.detail = status, detail


def template_message(db: Session, tenant_id: str, template_id: str, variables: list | None) -> tuple:
    """(template, the text shown in the thread) for an approved template whose values match. Refuses in words what Meta
    would refuse later. Shared by send-template and start."""
    from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
    from app.services import wa_template_service as wts

    tmpl = db.query(WATemplate).filter_by(id=template_id, tenant_id=tenant_id).first()
    if not tmpl:
        raise Refused(404, "Template not found")
    if tmpl.status != TemplateStatus.APPROVED:
        raise Refused(422, "Only approved templates can be sent")
    needed = wts.template_variables(tmpl.components)
    if needed.get("header"):
        raise Refused(422, "This template has a variable in its header, which can't be filled in from the inbox yet.")
    expected, given = len(needed.get("body", [])), len(variables or [])
    if given != expected:
        raise Refused(
            422, f"This template needs {expected} value{'s' if expected != 1 else ''} to fill in; {given} given."
        )
    body = next((c for c in (tmpl.components or []) if c.get("type") == "BODY"), None)
    text = body.get("text", "") if body else tmpl.name
    for i, var in enumerate(variables or [], start=1):
        text = text.replace(f"{{{{{i}}}}}", str(var))
    return tmpl, text


def _open_official_conversation(db: Session, tenant, guest_id: str) -> tuple[Conversation, bool]:
    """(the guest's open WhatsApp conversation, created now?). Never a second open one."""
    from app.services.wa_booking_messages import _open_conversation

    existing = (
        db.query(Conversation.id)
        .filter_by(tenant_id=tenant.id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
        .first()
    )
    try:
        with db.begin_nested():
            conv = _open_conversation(db, tenant, guest_id)
    except IntegrityError:  # another request opened it a moment ago: use theirs
        conv = (
            db.query(Conversation)
            .filter_by(tenant_id=tenant.id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
            .first()
        )
        existing = True
        if conv is None:
            raise
    return conv, existing is None


def _has_whatsapp_signal(db: Session, tenant_id: str, guest_id: str) -> bool:
    from app.models.guest_identity import GuestIdentity

    return (
        db.query(GuestIdentity.id)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id, identity_type="whatsapp_number")
        .first()
        is not None
    )


def start(
    db: Session,
    *,
    tenant_id: str,
    guest_id: str,
    template_id: str,
    variables: list | None,
    user,
    inquiry_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Queue an approved template to the guest's number on the official WhatsApp number. Commits.
    Returns {"conversation_id", "created", "message"}. Raises Refused."""
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry
    from app.models.tenant import Tenant
    from app.services import identity_service
    from app.workers.tasks.send_whatsapp import _bad_number_reason

    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id, is_deleted=False).first()
    if guest is None:
        raise Refused(404, "Guest not found")
    inquiry = None
    if inquiry_id:
        inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id, guest_id=guest.id).first()
        if inquiry is None:
            raise Refused(404, "Lead not found")
    phone = (guest.phone or "").strip()
    bad = _bad_number_reason("" if phone.startswith("DELETED_") else phone)
    if bad:
        raise Refused(422, bad)
    tmpl, text = template_message(db, tenant_id, template_id, variables)

    open_wa = (
        db.query(Conversation)
        .filter_by(tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        .first()
    )
    if open_wa is not None and open_wa.is_personal_bridge:
        raise Refused(
            409,
            {
                "code": "personal_bridge_read_only",
                "message": "This guest's WhatsApp chat is on a team member's personal WhatsApp. Message them "
                "from that phone, or close that chat first.",
            },
        )

    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    conv, created = _open_official_conversation(db, tenant, guest.id)
    if inquiry is not None and not conv.inquiry_id:
        conv.inquiry_id = inquiry.id
    if not _has_whatsapp_signal(db, tenant_id, guest.id):
        # No actor: the number came from the guest (Instagram, a call), so no "agent_manual" consent row is written for it.
        identity_service.add_signal(db, tenant_id, guest.id, "whatsapp_number", phone, source="agent_whatsapp_start")

    msg = Message(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND,
        channel=ChannelType.WHATSAPP,
        body=text,
        sender_id=user.id,
        sender_name=user.name,
        was_approved=True,
        delivery_state=MessageDeliveryState.QUEUED,
        channel_status="queued",
        idempotency_key=idempotency_key,
        channel_metadata={"template_id": tmpl.id, "template_name": tmpl.name, "source": "whatsapp_start"},
        sender_kind="human",
    )
    db.add(msg)
    conv.last_message_at = datetime.now(UTC).isoformat()
    from app.services.lead_assignment_service import claim_on_first_touch

    claim_on_first_touch(db, tenant_id, guest.id, user.id)
    append_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="conversation.whatsapp_started",
        target_type="conversation",
        target_id=conv.id,
        payload={
            "guest_id": guest.id,
            "inquiry_id": getattr(inquiry, "id", None),
            "template": tmpl.name,
            "message_id": msg.id,
            "created": created,
        },
    )
    db.commit()
    db.refresh(msg)

    from app.workers.tasks.send_whatsapp import send_whatsapp_template

    send_whatsapp_template.delay(
        message_id=msg.id,
        tenant_id=tenant_id,
        template_name=tmpl.name,
        language_code=tmpl.language or "en_US",
        variables=variables or [],
    )
    log.info(
        "whatsapp_start_queued",
        tenant_id=tenant_id,
        conversation_id=conv.id,
        message_id=msg.id,
        created=created,
        template=tmpl.name,
    )
    return {"conversation_id": conv.id, "created": created, "message": msg}
