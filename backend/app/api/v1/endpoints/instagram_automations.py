"""Instagram automations: the post/reel picker, per-automation stats, and the tracked-link redirect.

Rules themselves are created and edited through /automations (validated by schemas/ig_automation.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db, set_tenant_context
from app.models.automation import AutomationRule
from app.models.guest import Guest
from app.models.ig_automation import IgAutomationEvent, IgTrackedLink
from app.models.tenant import Tenant
from app.models.user import User, UserRole

router = APIRouter(tags=["instagram-automations"])

_MEDIA_FIELDS = "id,caption,media_type,media_product_type,thumbnail_url,media_url,permalink,timestamp,comments_count"


@router.get("/instagram/media")
def list_media(
    after: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=24, ge=1, le=50),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """The account's posts and reels, newest first, fetched live (Meta's image links expire, so nothing is stored)."""
    from app.services.ig_automation import _adapter

    adapter = _adapter(db, current_user.tenant_id)
    if adapter is None:
        raise HTTPException(status_code=409, detail="Connect Instagram first (Settings → Integrations).")
    params = {"fields": _MEDIA_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    try:
        data = adapter._get(f"/{adapter._account_id}/media", params=params)
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail="Instagram did not return your posts. Try again in a minute."
        ) from None
    paging = data.get("paging") or {}
    items = [
        {
            "id": m.get("id"),
            "caption": (m.get("caption") or "")[:300],
            "type": "reel" if m.get("media_product_type") == "REELS" else (m.get("media_type") or "").lower(),
            "thumbnail": m.get("thumbnail_url") or m.get("media_url"),
            "permalink": m.get("permalink"),
            "timestamp": m.get("timestamp"),
            "comments": m.get("comments_count"),
        }
        for m in data.get("data", [])
    ]
    return {"items": items, "next": (paging.get("cursors") or {}).get("after") if paging.get("next") else None}


@router.get("/instagram/automations/stats")
def automation_stats(
    days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Per automation over the last `days`: triggered, DMs sent, final messages / links sent, link clicks, follows,
    people reached, skipped, failed, and leads (people reached who shared a phone number after it)."""
    tenant_id = current_user.tenant_id
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        db.query(IgAutomationEvent.rule_id, IgAutomationEvent.kind, func.count())
        .filter(IgAutomationEvent.tenant_id == tenant_id, IgAutomationEvent.created_at >= since)
        .group_by(IgAutomationEvent.rule_id, IgAutomationEvent.kind)
        .all()
    )
    out: dict[str, dict] = {}
    for rule_id, kind, n in rows:
        out.setdefault(rule_id, {})[kind] = n

    people = (
        db.query(IgAutomationEvent.rule_id, IgAutomationEvent.guest_id, func.min(IgAutomationEvent.created_at))
        .filter(
            IgAutomationEvent.tenant_id == tenant_id,
            IgAutomationEvent.created_at >= since,
            IgAutomationEvent.kind.in_(("dm_sent", "link_sent")),
            IgAutomationEvent.guest_id.isnot(None),
        )
        .group_by(IgAutomationEvent.rule_id, IgAutomationEvent.guest_id)
        .all()
    )
    identified = dict(
        db.query(Guest.id, Guest.lead_identified_at)
        .filter(
            Guest.tenant_id == tenant_id,
            Guest.id.in_({g for _, g, _ in people} or {""}),
            Guest.lead_identified_at.isnot(None),
        )
        .all()
    )
    for rule_id, guest_id, first_at in people:
        s = out.setdefault(rule_id, {})
        s["people"] = s.get("people", 0) + 1
        at = identified.get(guest_id)
        if at is not None:
            at = at if at.tzinfo else at.replace(tzinfo=UTC)
            first = first_at if first_at.tzinfo else first_at.replace(tzinfo=UTC)
            if at >= first:
                s["leads"] = s.get("leads", 0) + 1

    names = dict(db.query(AutomationRule.id, AutomationRule.name).filter(AutomationRule.tenant_id == tenant_id).all())
    return {
        "days": days,
        "automations": [
            {
                "rule_id": rid,
                "name": names.get(rid, "Deleted automation"),
                **{
                    k: s.get(k, 0)
                    for k in (
                        "triggered",
                        "dm_sent",
                        "link_sent",
                        "clicked",
                        "followed",
                        "gate_asked",
                        "people",
                        "leads",
                        "skipped",
                        "dm_failed",
                    )
                },
            }
            for rid, s in out.items()
        ],
    }


@router.get("/l/{slug}/{code}", include_in_schema=False)
def follow_link(slug: str, code: str, db: Session = Depends(get_db)):
    """A DM button's tracked link: count the click, then send the person on. Only stored codes resolve (no open
    redirect)."""
    tenant = db.query(Tenant).filter(Tenant.slug == slug[:100]).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Link not found")
    set_tenant_context(db, tenant.id)
    link = db.query(IgTrackedLink).filter_by(tenant_id=tenant.id, code=code[:16]).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    db.add(IgAutomationEvent(tenant_id=tenant.id, rule_id=link.rule_id, kind="clicked"))
    db.commit()
    return RedirectResponse(link.target_url, status_code=302)
