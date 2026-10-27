"""Delivers queued ops alerts (ops_alert_sends): WhatsApp template from the tenant's own WABA, or a PWA push.

Called only from Celery (workers/tasks/ops_escalation.py). A WhatsApp send that cannot go out — template not approved,
WhatsApp not connected, Meta rejection (including the tenant's Meta billing failing) — is marked failed with the real reason and
handed to ops_escalation_service.on_send_failed, which escalates. Nothing here fails silently.
"""

from __future__ import annotations

import asyncio
import re

import structlog
from sqlalchemy.orm import Session

from app.models.ops import OpsAlertSend, OpsItem
from app.services import ops_escalation_service as esc
from app.services import roster_service
from app.services.ops_templates import ACK_INDEX, DECLINE_INDEX

log = structlog.get_logger()

# Meta error codes that mean the WABA cannot send business-initiated messages because of billing/eligibility.
_META_BILLING_CODES = {131042, 131031}
_STATUS_RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}


def _clean(value: str | None, limit: int = 120) -> str:
    """Meta rejects template parameters that are empty or contain newlines, tabs or 4+ consecutive spaces."""
    text = re.sub(r"\s+", " ", (value or "").strip())
    return (text[: limit - 1] + "…") if len(text) > limit else (text or "-")


def _property_name(db: Session, item: OpsItem) -> str:
    if not item.property_id:
        return "-"
    from app.models.property import Property

    return db.query(Property.name).filter_by(id=item.property_id, tenant_id=item.tenant_id).scalar() or "-"


def _due_text(db: Session, item: OpsItem) -> str:
    due = esc._aware(item.ack_due_at or item.resolve_due_at)
    if due is None:
        return "-"
    local = due.astimezone(roster_service.tenant_tz(db, item.tenant_id))
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}, {local.day} {local.strftime('%b')}"


def template_components(db: Session, item: OpsItem, send: OpsAlertSend) -> list[dict]:
    body = [
        item.severity.upper(),
        item.title,
        _property_name(db, item),
        item.summary or item.category or "-",
        _due_text(db, item),
    ]
    return [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": _clean(v)} for v in body],
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": str(ACK_INDEX),
            "parameters": [{"type": "payload", "payload": esc.button_payload(send, "ack")}],
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": str(DECLINE_INDEX),
            "parameters": [{"type": "payload", "payload": esc.button_payload(send, "decline")}],
        },
    ]


def _template_approved(db: Session, tenant_id: str, name: str) -> bool:
    from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate

    row = db.query(WATemplate).filter_by(tenant_id=tenant_id, name=name).first()
    return bool(row and row.status == TemplateStatus.APPROVED)


def _wa_credentials(db: Session, tenant_id: str) -> tuple[str | None, str | None]:
    from app.models.integration import Integration
    from app.workers.tasks.whatsapp import _get_wa_access_token

    integration = (
        db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp_meta").first()
        or db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp").first()
    )
    if integration is None:
        return None, None
    return (integration.config or {}).get("phone_number_id"), _get_wa_access_token(db, tenant_id)


def _meta_error(exc: Exception) -> tuple[int | None, str]:
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            err = resp.json().get("error") or {}
            return (
                err.get("code"),
                f"Meta {err.get('code')}: {err.get('message') or err.get('error_user_msg') or resp.text[:200]}",
            )
        except Exception:
            return None, f"Meta HTTP {resp.status_code}"
    return None, str(exc)[:300]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _fail(db: Session, send: OpsAlertSend, reason: str) -> list[str]:
    send.status = "failed"
    send.error = reason
    db.flush()
    log.error(
        "ops_alert_send_failed",
        tenant_id=send.tenant_id,
        item_id=send.item_id,
        send_id=send.id,
        reason=reason,
    )
    return esc.on_send_failed(db, send)


def deliver(db: Session, send_id: str, tenant_id: str) -> list[str]:
    """Send one queued alert. Returns follow-up send ids (from escalation after a failure) to deliver next."""
    send = db.query(OpsAlertSend).filter_by(id=send_id, tenant_id=tenant_id).first()
    if send is None or send.status != "queued":
        return []
    item = db.query(OpsItem).filter_by(id=send.item_id, tenant_id=tenant_id).first()
    if item is None:
        return []
    if item.status in ("resolved", "cancelled") or (item.status == "acknowledged" and send.step >= 0):
        send.status = "skipped"
        send.error = f"item already {item.status}"
        db.flush()
        return []

    if send.channel == "push":
        from app.services.push_service import send_to_tenant

        send_to_tenant(
            db,
            tenant_id,
            title=f"Ops {item.severity.upper()}: {item.title}",
            body=_clean(item.summary or _property_name(db, item), 120),
            url=f"/dashboard/ops?item={item.id}",
            tag=f"ops-{item.id}",
            user_id=send.user_id,
        )
        send.status = "sent"  # push is best-effort; send_to_tenant never raises
        db.flush()
        return []

    if not send.phone_e164:
        return _fail(db, send, "no phone number")
    if not _template_approved(db, tenant_id, send.template or ""):
        return _fail(
            db,
            send,
            f"template {send.template} is not approved on this WhatsApp account yet",
        )
    phone_number_id, token = _wa_credentials(db, tenant_id)
    if not phone_number_id or not token:
        return _fail(db, send, "WhatsApp is not connected for this workspace")

    from app.adapters.whatsapp.meta_cloud import get_wa_adapter

    language = esc.effective_settings(db, tenant_id)["template_language"]
    try:
        result = _run(
            get_wa_adapter(phone_number_id, token).send_template(
                to=send.phone_e164,
                template_name=send.template,
                language_code=language,
                components=template_components(db, item, send),
            )
        )
    except Exception as exc:
        code, reason = _meta_error(exc)
        if code in _META_BILLING_CODES:
            log.error("ops_alert_meta_billing_issue", tenant_id=tenant_id, code=code)
            reason = f"{reason} (the WhatsApp Business Account's Meta payment method needs attention)"
        return _fail(db, send, reason)

    send.wamid = (result.get("messages") or [{}])[0].get("id")
    send.status = "sent"
    send.error = None
    db.flush()
    log.info(
        "ops_alert_sent",
        tenant_id=tenant_id,
        item_id=item.id,
        send_id=send.id,
        step=send.step,
    )
    return []


def apply_status_callback(db: Session, tenant_id: str, status_obj: dict) -> tuple[bool, list[str]]:
    """Meta delivery status for an ops alert. Returns (matched, follow-up send ids)."""
    wamid = status_obj.get("id")
    if not wamid:
        return False, []
    send = db.query(OpsAlertSend).filter_by(tenant_id=tenant_id, wamid=wamid).first()
    if send is None:
        return False, []
    status = status_obj.get("status", "")
    if status == "failed":
        errors = status_obj.get("errors") or [{}]
        reason = (
            f"Meta {errors[0].get('code')}: {errors[0].get('title') or errors[0].get('message') or 'delivery failed'}"
        )
        if send.status != "failed":
            return True, _fail(db, send, reason)
        return True, []
    if status in _STATUS_RANK and _STATUS_RANK[status] > _STATUS_RANK.get(send.status, -1):
        send.status = status
        db.flush()
    return True, []
