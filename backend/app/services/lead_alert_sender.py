"""Sends one team alert (a playbook_actions row with action "staff_wa") as a WhatsApp template from the workspace's own
number to a staff member's personal number. Ported from the ops branch's ops_alert_sender (same Meta call, parameter
cleaning and error reading), but for lead alerts.

Staff are not guests: no Message row, no conversation, no inbox entry. The action row is the record (wa_message_id for the
delivery receipts, status, reason). Each send carries its own quick-reply payloads "la:{action_id}:ack" and
"la:{action_id}:take", so a tap on the staff member's phone comes back to exactly this alert (lead_alert_service.
handle_staff_inbound). Nothing fails silently: a send that cannot go out is marked failed with the real reason, and the
caller pushes the person instead.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.lead_workflow import PlaybookAction
from app.services import wa_lead_pack as pack

log = structlog.get_logger()

PAYLOAD_PREFIX = "la:"
_META_BILLING_CODES = {131042, 131031}
_DELIVERY_RANK = {"sent": 1, "delivered": 2, "read": 3}


def clean(value: Optional[str], limit: int = 120) -> str:
    """Meta rejects template parameters that are empty or contain newlines, tabs or 4+ consecutive spaces."""
    text = re.sub(r"\s+", " ", (value or "").strip())
    return (text[: limit - 1] + "…") if len(text) > limit else (text or "-")


def button_payload(action_id: str, verb: str) -> str:
    return f"{PAYLOAD_PREFIX}{action_id}:{verb}"


def parse_payload(payload: Optional[str]) -> Optional[tuple[str, str]]:
    """"la:{action_id}:ack" -> (action_id, "ack"); anything else -> None."""
    if not payload or not payload.startswith(PAYLOAD_PREFIX):
        return None
    parts = payload[len(PAYLOAD_PREFIX):].split(":")
    if len(parts) != 2 or parts[1] not in ("ack", "take") or not parts[0]:
        return None
    return parts[0], parts[1]


def components(action: PlaybookAction, values: list[str], with_buttons: bool = True) -> list[dict]:
    out = [{"type": "body", "parameters": [{"type": "text", "text": clean(v)} for v in values]}]
    if with_buttons:
        out += [
            {"type": "button", "sub_type": "quick_reply", "index": str(pack.ACK_INDEX),
             "parameters": [{"type": "payload", "payload": button_payload(action.id, "ack")}]},
            {"type": "button", "sub_type": "quick_reply", "index": str(pack.TAKE_INDEX),
             "parameters": [{"type": "payload", "payload": button_payload(action.id, "take")}]},
        ]
    return out


def template_approved(db: Session, tenant_id: str, name: str) -> Optional[str]:
    """The approved template's language, or None when this workspace has no approved template of that name."""
    from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
    row = (db.query(WATemplate).filter_by(tenant_id=tenant_id, name=name, status=TemplateStatus.APPROVED)
           .order_by(WATemplate.language).first())
    return (row.language or "en") if row else None


def wa_credentials(db: Session, tenant_id: str) -> tuple[Optional[str], Optional[str]]:
    from app.models.integration import Integration
    from app.workers.tasks.whatsapp import _get_wa_access_token
    integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp_meta").first() \
        or db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp").first()
    if integration is None:
        return None, None
    return (integration.config or {}).get("phone_number_id"), _get_wa_access_token(db, tenant_id)


def meta_error(exc: Exception) -> tuple[Optional[int], str]:
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            err = resp.json().get("error") or {}
            return err.get("code"), f"Meta {err.get('code')}: {err.get('message') or err.get('error_user_msg') or resp.text[:200]}"
        except Exception:  # noqa: BLE001
            return None, f"Meta HTTP {resp.status_code}"
    return None, str(exc)[:300]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _adapter(phone_number_id: str, token: str):
    from app.adapters.whatsapp.meta_cloud import get_wa_adapter
    return get_wa_adapter(phone_number_id, token)


def deliver(db: Session, action: PlaybookAction, phone_e164: str, values: list[str], *, with_buttons: bool = True) -> bool:
    """Send this alert now. True = Meta accepted it (status "done", wa_message_id kept); False = failed with the reason in
    ``action.reason``. Flushes; the caller commits."""
    template = action.template_name or ""
    language = template_approved(db, action.tenant_id, template)
    if language is None:
        return _fail(db, action, f"template {template} is not approved on this WhatsApp number yet")
    phone_number_id, token = wa_credentials(db, action.tenant_id)
    if not phone_number_id or not token:
        return _fail(db, action, "WhatsApp is not connected for this workspace")
    try:
        result = _run(_adapter(phone_number_id, token).send_template(
            to=phone_e164, template_name=template, language_code=language,
            components=components(action, values, with_buttons)))
    except Exception as exc:  # noqa: BLE001 -- the reason is kept on the row and the person is pushed instead
        code, reason = meta_error(exc)
        if code in _META_BILLING_CODES:
            reason = f"{reason} (the WhatsApp Business Account's Meta payment method needs attention)"
        return _fail(db, action, reason)
    action.wa_message_id = ((result or {}).get("messages") or [{}])[0].get("id")
    action.status, action.reason = "done", None
    action.payload = {**(action.payload or {}), "delivery": "sent"}
    db.flush()
    log.info("lead_alert_sent", tenant_id=action.tenant_id, action_id=action.id, template=template)
    return True


def send_text(db: Session, tenant_id: str, phone_e164: str, text: str) -> None:
    """A short confirmation after a staff member taps a button (their own message just opened the 24-hour window).
    Best-effort: a failure is logged, nothing else depends on it."""
    phone_number_id, token = wa_credentials(db, tenant_id)
    if not phone_number_id or not token:
        return
    try:
        _run(_adapter(phone_number_id, token).send_text(to=phone_e164, body=text))
    except Exception as exc:  # noqa: BLE001
        log.warning("lead_alert_confirm_failed", tenant_id=tenant_id, error=meta_error(exc)[1])


def _fail(db: Session, action: PlaybookAction, reason: str) -> bool:
    action.status, action.reason = "failed", reason[:500]
    db.flush()
    log.error("lead_alert_send_failed", tenant_id=action.tenant_id, action_id=action.id, reason=reason)
    return False


def apply_status_callback(db: Session, tenant_id: str, status_obj: dict) -> bool:
    """A Meta delivery receipt for a team alert (no Message row). True when it matched one of ours."""
    wamid = status_obj.get("id")
    if not wamid:
        return False
    action = db.query(PlaybookAction).filter_by(tenant_id=tenant_id, wa_message_id=wamid).first()
    if action is None:
        return False
    status = status_obj.get("status", "")
    if status == "failed":
        errors = status_obj.get("errors") or [{}]
        if action.status != "failed":
            _fail(db, action, f"Meta {errors[0].get('code')}: {errors[0].get('title') or errors[0].get('message') or 'delivery failed'}")
            from app.services.lead_alert_service import push_fallback
            push_fallback(db, action)
        return True
    current = (action.payload or {}).get("delivery")
    if status in _DELIVERY_RANK and _DELIVERY_RANK[status] > _DELIVERY_RANK.get(current or "", 0):
        action.payload = {**(action.payload or {}), "delivery": status}
        db.flush()
    return True
