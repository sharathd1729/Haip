"""The public case study: an owner-approved SNAPSHOT of the impact view's aggregate numbers.

Nothing is public until the owner clicks "Publish to case study". Publishing freezes the numbers as they are now (a later change
in the data never alters the page), keeps only aggregates (no guest, staff, phone, message or booking data; the baseline's
free-text source note is left out too, only its period label is kept) and money only when the owner asks for it. "Withdraw"
takes the page back to "coming soon". Both are audited. The public page reads published snapshots only, through the SECURITY
DEFINER function ``impact_published_case_study`` on PostgreSQL (no tenant context is needed or set).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.impact import ImpactProfile
from app.services import impact_service as svc

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
SNAPSHOT_VERSION = 1
_CHANNEL_LABELS = {"whatsapp_cloud": "WhatsApp (business number)", "personal_whatsapp": "WhatsApp (team phones)", "instagram": "Instagram"}


def _public_tile(t: dict) -> dict:
    owner = t["before"]["owner"]
    measured = t["before"]["measured"]
    if owner is not None:
        before = {"value": owner["value"], "source": "owner_entered", "period": owner["period_label"]}
    elif measured["value"] is not None:
        p = measured["period"]
        before = {"value": measured["value"], "source": "measured", "period": f"{p['from']} to {p['to']}"}
    else:
        before = None
    p = t["with"]["period"]
    return {"key": t["key"], "label": t["label"], "unit": t["unit"], "definition": t["definition"],
            "before": before, "with": {"value": t["with"]["value"], "period": f"{p['from']} to {p['to']}"},
            "change": t["change"]}


def public_snapshot(view: dict, *, brand_name: str, headline: Optional[str], summary: Optional[str], include_revenue: bool) -> dict:
    """The only data the public page ever gets. Built from aggregates by WHITELIST, so a field added to the view later is not
    published by accident."""
    tiles = [_public_tile(t) for t in view["tiles"]
             if not t.get("restricted") and (include_revenue or t["unit"] != "inr") and t["with"]["value"] is not None]
    channels = []
    for key, s in view["with"]["replies"]["by_channel"].items():
        if s["turns"]:
            channels.append({"channel": key, "label": _CHANNEL_LABELS[key], "turns": s["turns"], "answered_pct": s["answered_pct"],
                             "median_minutes": svc._minutes(s["median_seconds"]), "within_15_pct": s["within_pct"]["15"]})
    ah = view["with"]["replies"]["after_hours"]
    return {"version": SNAPSHOT_VERSION, "brand_name": brand_name, "headline": headline, "summary": summary,
            "go_live": view["go_live"], "windows": view["windows"], "tiles": tiles, "channels": channels,
            "after_hours": {"turns": ah["turns"], "within_15_pct": ah["within_15_pct"], "ai_share_pct": ah["ai_share_pct"]},
            "includes_revenue": bool(include_revenue), "measured_through": view["windows"]["with"]["to"]}


def status(db: Session, tenant_id: str) -> dict:
    p = svc.get_profile(db, tenant_id)
    if p is None:
        return {"status": "draft", "slug": None, "published_at": None, "snapshot": None}
    return {"status": p.case_study_status, "slug": p.case_study_slug,
            "published_at": p.published_at.isoformat() if p.published_at else None, "snapshot": p.case_study_snapshot}


def publish(db: Session, tenant, user, *, slug: str, brand_name: str, headline: Optional[str], summary: Optional[str],
            include_revenue: bool, can_revenue: bool) -> dict:
    slug = (slug or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise svc.ImpactError("The link name may use lowercase letters, digits and dashes (2-40 characters)")
    if include_revenue and not can_revenue:
        raise svc.ImpactError("Publishing money figures needs revenue access")
    taken = db.query(ImpactProfile.id).filter(ImpactProfile.case_study_slug == slug, ImpactProfile.tenant_id != tenant.id).first()
    if taken:
        raise svc.ImpactError("That link name is already used by another workspace")
    view = svc.build(db, tenant, go_live=None, days=None, can_revenue=can_revenue)
    if view.get("needs_go_live"):
        raise svc.ImpactError("Set the go-live date before publishing")
    snapshot = public_snapshot(view, brand_name=brand_name, headline=headline, summary=summary, include_revenue=include_revenue)
    profile = svc.get_profile(db, tenant.id)
    before = {"status": profile.case_study_status, "slug": profile.case_study_slug}
    profile.case_study_slug = slug
    profile.case_study_status = "published"
    profile.case_study_snapshot = snapshot
    profile.published_at = datetime.now(timezone.utc)
    profile.published_by = user.id
    db.flush()
    append_audit(db, tenant_id=tenant.id, action="impact.case_study_published", actor_user_id=user.id, target_type="impact_profile",
                 target_id=profile.id, payload={"before": before, "after": {"status": "published", "slug": slug},
                                                "snapshot": snapshot})
    db.commit()
    return status(db, tenant.id)


def withdraw(db: Session, tenant_id: str, user_id: str) -> dict:
    profile = svc.get_profile(db, tenant_id)
    if profile is None or profile.case_study_status != "published":
        raise svc.ImpactError("Nothing is published")
    profile.case_study_status = "withdrawn"
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="impact.case_study_withdrawn", actor_user_id=user_id, target_type="impact_profile",
                 target_id=profile.id, payload={"before": {"status": "published", "slug": profile.case_study_slug},
                                                "after": {"status": "withdrawn"}})
    db.commit()
    return status(db, tenant_id)


# ── public read (no authentication) ──────────────────────────────────────────────────────────────────────────

def published(db: Session, slug: Optional[str] = None) -> list[dict]:
    """Published snapshots only: [{slug, snapshot, published_at}]. ``slug`` narrows to one."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        rows = db.execute(text("SELECT slug, snapshot, published_at FROM impact_published_case_study(:s)"), {"s": slug}).all()
    else:
        q = db.query(ImpactProfile.case_study_slug, ImpactProfile.case_study_snapshot, ImpactProfile.published_at).filter(
            ImpactProfile.case_study_status == "published", ImpactProfile.case_study_snapshot.isnot(None),
            ImpactProfile.case_study_slug.isnot(None))
        if slug:
            q = q.filter(ImpactProfile.case_study_slug == slug)
        rows = q.order_by(ImpactProfile.published_at.desc()).all()
    return [{"slug": r[0], "snapshot": r[1], "published_at": r[2].isoformat() if r[2] else None} for r in rows]
