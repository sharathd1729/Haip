"""Meta's template webhooks (WhatsApp step 1d): message_template_status_update applies an approval, rejection, pause or
disable the moment Meta sends it, instead of waiting for the 30-minute sync. Quality and category updates queue an
immediate template sync (sync_wa_templates), which already knows how to apply them.

These events are per WhatsApp Business Account: they carry the WABA id (entry.id), not a phone number, so the
workspace is found by the waba_id saved on its WhatsApp integration. The owner's Meta app must be subscribed to the
"message_template_status_update" field (and optionally the quality/category fields) in its webhook settings.
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

log = structlog.get_logger()

TEMPLATE_FIELDS = ("message_template_status_update", "message_template_quality_update", "template_category_update")

_REASONS = {
    "PAUSED": "Paused by Meta because recipients reported or ignored it. It can be sent again once Meta lifts the pause.",
    "DISABLED": "Disabled by Meta after repeated low quality. Create a new version of the template.",
    "LIMIT_EXCEEDED": "Meta's limit on templates for this account was reached.",
}


def tenant_for_waba(db: Session, waba_id: str):
    """The workspace whose active WhatsApp integration is this WABA, or None."""
    if not waba_id:
        return None
    from app.models.integration import Integration
    from app.models.tenant import Tenant

    for intg in db.query(Integration).filter(Integration.kind.in_(["whatsapp_meta", "whatsapp"]),
                                             Integration.status == "active").all():
        if str((intg.config or {}).get("waba_id") or "") == str(waba_id):
            return db.query(Tenant).filter_by(id=intg.tenant_id).first()
    return None


def handle(db: Session, waba_id: str, field: str, value: dict) -> str:
    """Apply one template event. Returns what happened. Commits."""
    tenant = tenant_for_waba(db, waba_id)
    if tenant is None:
        log.warning("wa_template_event_no_tenant", waba_id=waba_id, field=field)
        return "no workspace"
    if field != "message_template_status_update":
        _queue_sync(tenant.id)
        return "sync queued"

    from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
    from app.services.wa_template_sync import _STATUS

    meta_id = str(value.get("message_template_id") or "")
    name, lang = value.get("message_template_name"), (value.get("message_template_language") or "").lower()
    q = db.query(WATemplate).filter(WATemplate.tenant_id == tenant.id)
    tmpl = (q.filter(WATemplate.meta_template_id == meta_id).first() if meta_id else None) or next(
        (t for t in q.filter(WATemplate.name == name).all() if (t.language or "").lower() == lang), None)
    if tmpl is None:
        _queue_sync(tenant.id)  # made in WhatsApp Manager: the sync imports it
        return "unknown template, sync queued"
    event = str(value.get("event") or "").upper()
    mapped = _STATUS.get(event)
    if mapped is None:
        return f"ignored event {event}"
    tmpl.status = TemplateStatus[mapped]
    if meta_id and not tmpl.meta_template_id:
        tmpl.meta_template_id = meta_id
    other = value.get("other_info") if isinstance(value.get("other_info"), dict) else {}
    reason = value.get("reason") or other.get("description")
    if mapped == "REJECTED":
        tmpl.rejection_reason = (_REASONS.get(event) or str(reason or "Rejected by Meta").replace("_", " ").capitalize())[:500]
    elif mapped == "APPROVED":
        tmpl.rejection_reason = None
    db.commit()
    log.info("wa_template_event_applied", tenant_id=tenant.id, template_id=tmpl.id, meta_event=event)
    return f"{tmpl.name}: {event}"


def _queue_sync(tenant_id: str) -> None:
    try:
        from app.workers.tasks.sync_wa_templates import sync_tenant_templates

        sync_tenant_templates.delay(tenant_id)
    except Exception as exc:  # noqa: BLE001 -- the 30-minute sync still runs
        log.warning("wa_template_event_sync_not_queued", tenant_id=tenant_id, error=str(exc)[:200])
