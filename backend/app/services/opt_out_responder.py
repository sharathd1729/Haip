"""
D1 + D2 — Opt-out responder + propagation.

When an inbound message matches an opt-out keyword:
1. Find or create a Consent row for the guest (marketing scope).
2. Set marketing_consent=False / True, record withdrawal proof.
3. Write an AuditEvent.
4. Queue a WhatsApp confirmation template (utility, pre-approved) through wa_booking_messages.send_guest_template,
   the service every system-initiated template send uses: APPROVED templates only, one per guest per direction per day,
   a Message row in the inbox, audited. Never into a personal-bridge thread. A failure is logged, never raised.
"""
from datetime import datetime, timezone
import uuid
import structlog
from sqlalchemy.orm import Session

from app.models.consent import Consent
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.core.audit import append_audit
from app.services import wa_booking_messages as wbm
from app.workers.tasks.send_whatsapp import _phone_token

log = structlog.get_logger()

OPT_OUT_REPLY_TEMPLATE = "haip_optout_confirm_v1"   # Pre-approved META utility template name
OPT_IN_REPLY_TEMPLATE  = "haip_optin_confirm_v1"


def _upsert_marketing_consent(
    db: Session,
    tenant_id: str,
    guest_id: str,
    granted: bool,
    reason: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Consent:
    """Create or update the marketing consent row for this guest."""
    now = datetime.now(timezone.utc)

    consent = (
        db.query(Consent)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id, scope="marketing")
        .first()
    )
    if consent is None:
        consent = Consent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            guest_id=guest_id,
            channel="whatsapp",
            scope="marketing",
            source="user_keyword",
            recorded_at=now.isoformat(),
        )
        db.add(consent)

    consent.granted = granted
    consent.recorded_at = now.isoformat()

    # D3: proof fields (may be None if not captured)
    if hasattr(consent, "proof_ip"):
        consent.proof_ip = ip
        consent.proof_user_agent = user_agent
        consent.withdrawn_at = now.isoformat() if not granted else None
        consent.withdrawal_reason = reason if not granted else None

    db.flush()
    return consent


def _sync_subscriber_list(db: Session, tenant_id: str, phone: str, granted: bool) -> None:
    from app.api.v1.endpoints.messaging import WASubscriber
    now = datetime.now(timezone.utc).isoformat()
    for sub in db.query(WASubscriber).filter_by(tenant_id=tenant_id, phone=phone).all():
        sub.opted_in = granted
        if granted:
            sub.opt_in_at, sub.opt_out_at = now, None
        else:
            sub.opt_out_at = now


def process_opt_out_event(
    db: Session,
    tenant_id: str,
    guest_id: str,
    guest_phone: str,
    direction: str,          # "opt_out" | "opt_in"
    matched_keyword: str,
    actor_user_id: str | None = None,
) -> None:
    """
    Apply consent change, write audit, queue confirmation template.
    Call this after detect_opt_out() returns matched=True.
    """
    granted = direction == "opt_in"
    action_label = "opt_out" if not granted else "opt_in"

    consent = _upsert_marketing_consent(
        db=db,
        tenant_id=tenant_id,
        guest_id=guest_id,
        granted=granted,
        reason="user_keyword",
    )

    # The WhatsApp subscriber list is a second record of who may be messaged;
    # a STOP reply used to update only the guest's consent, so the same person
    # stayed in every subscriber campaign. Keep the two in step.
    _sync_subscriber_list(db, tenant_id, guest_phone, granted)

    # Write audit event
    append_audit(
        db=db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=f"consent.{action_label}",
        target_type="guest",
        target_id=guest_id,
        payload={
            "matched_keyword": matched_keyword,
            "scope": "marketing",
            "channel": "whatsapp",
            "phone": guest_phone[-4:],   # D13: only last 4 digits in audit log
        },
    )

    db.commit()

    _send_confirmation(db, tenant_id, guest_id, guest_phone, direction)

    log.info(
        "opt_out_event_processed",
        tenant_id=tenant_id,
        direction=direction,
        keyword=matched_keyword,
    )


def _send_confirmation(db: Session, tenant_id: str, guest_id: str, guest_phone: str, direction: str) -> dict | None:
    """Queue the confirmation template. Returns send_guest_template's result, or None when nothing was tried.
    Never raises: the consent change is already committed and the webhook must still switch the AI off."""
    template = OPT_IN_REPLY_TEMPLATE if direction == "opt_in" else OPT_OUT_REPLY_TEMPLATE
    try:
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
        if guest is None:
            log.warning("opt_out_confirm_not_sent", tenant_id=tenant_id, phone=_phone_token(guest_phone), reason="guest not found")
            return None
        conv = (db.query(Conversation).filter_by(tenant_id=tenant_id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
                .order_by(Conversation.last_message_at.desc()).first())
        if conv is not None and conv.is_personal_bridge:   # read-only mirror: never answered from the official number
            log.warning("opt_out_confirm_not_sent", tenant_id=tenant_id, phone=_phone_token(guest_phone), reason="personal_bridge")
            return None
        target = wbm.Target("guest", guest_id, "oo:", {"source": "opt_out_confirm", "consent_event": direction}, "consent")
        result = wbm.send_guest_template(db, tenant_id, guest, template, [], target=target,
                                         event=f"{direction}:{datetime.now(timezone.utc):%Y-%m-%d}")
        if result["status"] == "skipped":   # send_guest_template already logged + audited the reason (e.g. template not approved)
            log.warning("opt_out_confirm_not_sent", tenant_id=tenant_id, phone=_phone_token(guest_phone), template=template,
                        reason=result["reason"])
        return result
    except Exception as exc:  # noqa: BLE001 -- consent is saved; a failed confirmation must not stop the webhook
        db.rollback()
        log.error("opt_out_confirm_failed", tenant_id=tenant_id, phone=_phone_token(guest_phone), template=template,
                  error=str(exc)[:200])
        return None
