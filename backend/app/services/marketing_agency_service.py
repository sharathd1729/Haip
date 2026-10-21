"""The AI marketing agency: roles, autonomy per role, kill switch, approvals inbox, alerts.

Autonomy levels (owner decision Q1, plan 18 Oct 2026), modelled on the concierge's off/shadow/autonomous:
  * internal roles (research, strategy, copy, design): `autopilot` = runs in the weekly cycle,
    `suggest` = only when someone presses Run, `off` = never.
  * public role (publish): `suggest` = a person schedules every approved post, `autopilot` = approved posts are
    scheduled automatically (approval itself is always a person).
  * kill switch (`paused`): no step of any run executes (weekly or manual) and nothing is posted.
Only roles with working code behind them are listed (video, reporting, comments and reviews come with later phases);
levels stored for retired roles are ignored.
Settings live in brand_config["marketing_studio"]["agency"]; every change is owner-only and audited.
"""
import json
from typing import Optional

import structlog
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import append_audit
from app.models.marketing import MarketingContent
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

LEVELS = ("off", "suggest", "autopilot")
SETTINGS_KEY = "marketing_studio"

# role -> (label, what it does, public?, default level)
ROLES: dict[str, tuple[str, str, bool, str]] = {
    "research":   ("Research analyst", "Audits your account and, once connected, competitors' public posts", False, "autopilot"),
    "strategy":   ("Strategist", "Turns research into a weekly plan, themes and calendar", False, "autopilot"),
    "copy":       ("Copywriter", "Writes captions, carousels, stories and promos for each calendar slot", False, "autopilot"),
    "design":     ("Designer", "Picks a photo for every slide, lays the text on it and, if switched on, requests AI images",
                   False, "autopilot"),
    "publish":    ("Scheduler & publisher", "Schedules and posts approved content to Instagram", True, "suggest"),
}


def _section(tenant: Tenant) -> dict:
    cfg = (tenant.brand_config or {}).get(SETTINGS_KEY) if tenant is not None else None
    agency = (cfg or {}).get("agency") if isinstance(cfg, dict) else None
    return agency if isinstance(agency, dict) else {}


def get_agency(tenant: Tenant) -> dict:
    stored = _section(tenant)
    roles = stored.get("roles") if isinstance(stored.get("roles"), dict) else {}
    return {
        "paused": bool(stored.get("paused")),
        "roles": {r: (roles.get(r) if roles.get(r) in LEVELS else default) for r, (_, _, _, default) in ROLES.items()},
    }


def level(tenant: Tenant, role: str) -> str:
    """The level in force right now, after the kill switch."""
    agency = get_agency(tenant)
    lvl = agency["roles"].get(role, "off")
    if agency["paused"]:
        return "off" if lvl == "off" else "suggest"
    return lvl


def update_agency(db: Session, tenant: Tenant, actor_id: str, *, roles: Optional[dict] = None,
                  paused: Optional[bool] = None) -> dict:
    before = get_agency(tenant)
    after = {"paused": before["paused"], "roles": dict(before["roles"])}
    for role, lvl in (roles or {}).items():
        if role not in ROLES:
            raise MarketingError(422, "unknown_role", f"Unknown role: {role}")
        if lvl not in LEVELS:
            raise MarketingError(422, "bad_level", f"Level must be one of {', '.join(LEVELS)}.")
        after["roles"][role] = lvl
    if paused is not None:
        after["paused"] = bool(paused)
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get(SETTINGS_KEY) or {})
    section["agency"] = after
    cfg[SETTINGS_KEY] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.agency.updated", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": after})
    return after


def roster(tenant: Tenant) -> list[dict]:
    agency = get_agency(tenant)
    return [{"role": r, "label": label, "does": does, "public": public, "level": agency["roles"][r],
             "effective_level": level(tenant, r)} for r, (label, does, public, _) in ROLES.items()]


# ── Approvals inbox (derived from the domain tables; nothing is copied) ─────────────────────────────────────────────

def pending_approvals(db: Session, tenant_id: str) -> list[dict]:
    items = (db.query(MarketingContent).filter_by(tenant_id=tenant_id, status="in_review")
             .order_by(MarketingContent.updated_at.asc()).limit(100).all())
    assets = (db.query(MediaAsset).filter_by(tenant_id=tenant_id, status="pending_review")
              .order_by(MediaAsset.created_at.asc()).limit(100).all())
    from app.models.marketing import MarketingReview
    latest: dict[str, MarketingReview] = {}
    if items:
        for r in (db.query(MarketingReview).filter(MarketingReview.tenant_id == tenant_id,
                                                   MarketingReview.content_id.in_([c.id for c in items]))
                  .order_by(MarketingReview.updated_at.asc())):
            latest[r.content_id] = r                       # newest wins

    def counts(c):
        r = latest.get(c.id)
        found = [*(r.findings or []), *(r.advice or [])] if r is not None else []
        return {"high": sum(f["severity"] == "high" for f in found), "medium": sum(f["severity"] == "medium" for f in found),
                "reviewed": r is not None}
    out = [{"type": "content", "id": c.id, "title": c.title, "kind": c.kind, "version_id": c.current_version_id,
            "planned_for": c.planned_for, "waiting_since": c.updated_at, "created_by": c.created_by,
            "review": counts(c)} for c in items]
    out += [{"type": "ai_image", "id": a.id, "title": ((a.provenance or {}).get("prompt") or "AI image")[:120], "kind": "image",
             "version_id": None, "planned_for": None, "waiting_since": a.created_at, "created_by": a.created_by} for a in assets]
    return sorted(out, key=lambda x: str(x["waiting_since"]))


def pending_count(db: Session, tenant_id: str) -> int:
    return (db.query(MarketingContent).filter_by(tenant_id=tenant_id, status="in_review").count()
            + db.query(MediaAsset).filter_by(tenant_id=tenant_id, status="pending_review").count())


def notify_needs_approval(db: Session, tenant_id: str, title: str, body: str) -> None:
    """Push to the workspace's devices and nudge open Studio tabs. Best-effort; never raises."""
    try:
        from app.services.push_service import send_to_tenant
        send_to_tenant(db, tenant_id, title, body, url="/dashboard/marketing/studio", tag="marketing-approval")
    except Exception as exc:  # noqa: BLE001
        log.warning("marketing_push_failed", tenant_id=tenant_id, error=str(exc))
    try:
        import redis
        from app.core.config import settings
        r = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2)
        r.publish(f"sse:{tenant_id}", json.dumps({"event": "marketing.approval_needed", "count": pending_count(db, tenant_id)}))
    except Exception as exc:  # noqa: BLE001
        log.info("marketing_sse_failed", tenant_id=tenant_id, error=str(exc))
