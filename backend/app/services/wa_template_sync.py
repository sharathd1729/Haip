"""Keep the CRM's template list equal to the WhatsApp Business Account's.

Real case (Ratha, Sep 2026): a template created in Meta's WhatsApp Manager never
appeared here, and one deleted there stayed here. The old sync only refreshed
the status of templates already PENDING locally, so Meta was never the source
of truth for what exists.

Meta is the source of truth for existence, status and content of anything that
has been submitted. Local drafts (never submitted) are never touched.
"""
from __future__ import annotations

from typing import Optional

import httpx
import structlog
from sqlalchemy.orm import Session

log = structlog.get_logger()

GRAPH = "https://graph.facebook.com/v20.0"
_FIELDS = "id,name,language,status,category,components,rejected_reason"
_MAX_PAGES = 20

_STATUS = {
    "APPROVED": "APPROVED",
    "PENDING": "PENDING", "IN_APPEAL": "PENDING", "PENDING_DELETION": "PENDING",
    "REJECTED": "REJECTED", "DISABLED": "REJECTED", "PAUSED": "REJECTED",
    "LIMIT_EXCEEDED": "REJECTED",
}


class SyncError(Exception):
    """Meta couldn't be read. Nothing was changed."""


def fetch_meta_templates(waba_id: str, token: str) -> list[dict]:
    """Every template on the account, following pagination. Raises SyncError on
    any failure so a half-read list is never mistaken for 'deleted on Meta'."""
    url: Optional[str] = f"{GRAPH}/{waba_id}/message_templates"
    params: Optional[dict] = {"fields": _FIELDS, "limit": 100}
    out: list[dict] = []
    for _ in range(_MAX_PAGES):
        try:
            resp = httpx.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=20)
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise SyncError(f"Couldn't reach Meta ({type(exc).__name__}).") from exc
        if not isinstance(data, dict) or data.get("error"):
            err = (data or {}).get("error") or {}
            from app.services.wa_template_service import explain_meta_error
            raise SyncError(explain_meta_error(err, waba_id)[0])
        out.extend(data.get("data") or [])
        url = (data.get("paging") or {}).get("next")
        params = None                       # the next-page URL already carries them
        if not url:
            return out
    raise SyncError("Meta returned more templates than could be read in one sync.")


def _match(local: list, meta: dict):
    for t in local:
        if t.meta_template_id and t.meta_template_id == str(meta.get("id")):
            return t
    same_name = [t for t in local if t.name == meta.get("name")]
    for t in same_name:
        if (t.language or "").lower() == (meta.get("language") or "").lower():
            return t
    return same_name[0] if len(same_name) == 1 and not same_name[0].meta_template_id else None


def apply(db: Session, tenant_id: str, meta_templates: list[dict]) -> dict:
    """Bring local templates in line with `meta_templates`. Returns counts."""
    from app.api.v1.endpoints.messaging import (
        TemplateCategory, TemplateStatus, WACampaign, WATemplate,
    )

    local = db.query(WATemplate).filter_by(tenant_id=tenant_id).all()
    used_by_campaign = {c.template_id for c in db.query(WACampaign).filter_by(tenant_id=tenant_id).all() if c.template_id}
    seen: set[str] = set()
    added = updated = removed = 0

    for m in meta_templates:
        if not m.get("id") or not m.get("name"):
            continue
        status = TemplateStatus[_STATUS.get(str(m.get("status", "")).upper(), "PENDING")]
        try:
            category = TemplateCategory(str(m.get("category", "MARKETING")).upper())
        except ValueError:
            category = TemplateCategory.MARKETING
        reason = (m.get("rejected_reason") or None) if status == TemplateStatus.REJECTED else None
        if status == TemplateStatus.REJECTED and reason in (None, "NONE"):
            reason = str(m.get("status", "")).capitalize() + " by Meta"

        row = _match(local, m)
        if row is None:
            row = WATemplate(
                tenant_id=tenant_id, name=m["name"], language=(m.get("language") or "en")[:10],
                category=category, status=status, components=m.get("components") or [],
                meta_template_id=str(m["id"]), rejection_reason=reason,
            )
            db.add(row)
            db.flush()                      # assigns row.id, needed below
            local.append(row)
            added += 1
        else:
            before = (row.status, row.category, row.rejection_reason, row.meta_template_id, row.components)
            row.status, row.category, row.rejection_reason = status, category, reason
            row.meta_template_id = str(m["id"])
            if m.get("components"):
                row.components = m["components"]
            if before != (row.status, row.category, row.rejection_reason, row.meta_template_id, row.components):
                updated += 1
        seen.add(row.id)

    # Submitted here (has a Meta id) but no longer on the account: deleted on Meta.
    for row in local:
        if row.id in seen or not row.meta_template_id:
            continue
        if row.id in used_by_campaign:
            # Past campaigns still point at it: keep the record, say why it can't be used.
            if row.status != TemplateStatus.REJECTED:
                row.status = TemplateStatus.REJECTED
                row.rejection_reason = "Deleted on Meta. Campaigns that used it are kept."
                updated += 1
        else:
            db.delete(row)
            removed += 1

    db.commit()
    log.info("wa_templates_synced", tenant_id=tenant_id, added=added, updated=updated, removed=removed)
    return {"added": added, "updated": updated, "removed": removed, "total": len(meta_templates)}


def sync_tenant(db: Session, tenant_id: str, waba_id: str, token: str) -> dict:
    return apply(db, tenant_id, fetch_meta_templates(waba_id, token))
