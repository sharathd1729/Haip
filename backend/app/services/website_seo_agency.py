"""Website SEO agency (owner doc "HAIP Website Growth", fixes #9 and #11): a second agency team inside the website module.

Same two patterns as before, no new framework:
* Marketing Studio's agency (marketing_agency_service / marketing_agency_run): roles with autonomy off | suggest |
  autopilot, ONE weekly run (Monday from 09:00 workspace time), a kill switch. Run records reuse ``marketing_tasks``
  (parent step ``seo_run``, one ``weekly`` row per role); the Studio's own run/history read step ``run`` only.
* Dynamic SOPs (services/sops): code decides the steps, the AI writes only words, a PERSON does anything on another
  platform. HAIP never posts, logs in, scrapes or pays anywhere for this agency.

Levels: ``off`` = the role is skipped. ``suggest`` ("asks first") = the role prepares its work (a brief, a guide draft,
fixes, checklist steps, messages) and stops before anything changes; a person decides. ``autopilot`` = the role may also
apply the internal HAIP change it is allowed to make (only the technical checker has one: photo descriptions from
photo tags and missing page titles in the site DRAFT; publishing the site still needs a person). Roles whose work
reaches guests, the public site's words or another platform are capped at ``suggest`` (ROLES' last field).

The kill switch ``paused`` stops everything: no weekly run, no manual run (409), and a run in progress stops before its
next role. Settings live in ``brand_config.seo_agency`` (owner/manager via PUT /websites/seo-agency, audited; PATCH
/tenants/me refuses the key).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import append_audit
from app.core.tenant_tz import get_tenant_now
from app.models.marketing import MarketingTask
from app.models.module import Module, WorkspaceModule
from app.models.tenant import Tenant
from app.services.marketing_agency_service import LEVELS
from app.services.website_service import WebsiteError

log = structlog.get_logger(__name__)

SETTINGS_KEY = "seo_agency"
RUN_STEP, ROLE_STEP, PARENT_ROLE = "seo_run", "weekly", "seo_agency"
RUN_WEEKDAY, RUN_HOUR = 0, 9  # the Studio's Monday slot (marketing_agency_run)

# role -> (label, what it does, default level, highest level allowed)
ROLES: dict[str, tuple[str, str, str, str]] = {
    "search_analyst": (
        "Search analyst",
        "Weekly brief: searches rising and falling, pages losing clicks, sources that booked.",
        "autopilot",
        "autopilot",
    ),
    "content_writer": (
        "Content writer",
        "Drafts guides for searches that show you but get few clicks. A person approves each one.",
        "suggest",
        "suggest",
    ),
    "technical_checker": (
        "Technical checker",
        "Checks titles, photo descriptions, links, structured data, sitemap and speed. Fixes only what HAIP draws.",
        "autopilot",
        "autopilot",
    ),
    "local_profile": (
        "Local profile manager",
        "Google Business checklists and review reply drafts. A person does each step on Google.",
        "suggest",
        "suggest",
    ),
    "listings": (
        "Listings manager",
        "Airbnb, Booking.com, MakeMyTrip, Agoda and TripAdvisor checklists with copy. A person updates each site.",
        "suggest",
        "suggest",
    ),
    "links_citations": (
        "Links and citations",
        "Local tourism sites, partners and creators: a checklist and messages a person sends. Never buys links.",
        "suggest",
        "suggest",
    ),
    "ads_analyst": (
        "Ads analyst",
        "Ad cost against booked value, with budget suggestions and their rupee effect. A person changes the ads.",
        "suggest",
        "suggest",
    ),
}
ORDER = tuple(ROLES)


def _section(tenant: Tenant) -> dict:
    return dict((tenant.brand_config or {}).get(SETTINGS_KEY) or {})


def get_settings(tenant: Tenant) -> dict:
    sec = _section(tenant)
    stored = sec.get("roles") or {}
    roles = {}
    for r, (_, _, default, cap) in ROLES.items():
        lvl = stored.get(r, default)
        roles[r] = lvl if lvl in LEVELS and LEVELS.index(lvl) <= LEVELS.index(cap) else default
    return {"paused": bool(sec.get("paused")), "roles": roles}


def level(tenant: Tenant, role: str) -> str:
    """Effective level: the kill switch turns every role off."""
    s = get_settings(tenant)
    return "off" if s["paused"] else s["roles"][role]


def roster(tenant: Tenant) -> list[dict]:
    s = get_settings(tenant)
    return [
        {
            "role": r,
            "label": label,
            "does": does,
            "level": s["roles"][r],
            "max_level": cap,
            "effective_level": "off" if s["paused"] else s["roles"][r],
        }
        for r, (label, does, _, cap) in ROLES.items()
    ]


def update_settings(
    db: Session, tenant: Tenant, actor_id: str, *, roles: dict | None = None, paused: bool | None = None
) -> dict:
    before = get_settings(tenant)
    sec = _section(tenant)
    if roles is not None:
        merged = dict(sec.get("roles") or {})
        for r, lvl in roles.items():
            if r not in ROLES:
                raise WebsiteError(422, "unknown_role", f"There is no role called {r}.")
            if lvl not in LEVELS:
                raise WebsiteError(422, "bad_level", "Choose off, asks first or on its own.")
            if LEVELS.index(lvl) > LEVELS.index(ROLES[r][3]):
                raise WebsiteError(
                    422, "level_too_high", f"{ROLES[r][0]} only prepares work for a person; it cannot act on its own."
                )
            merged[r] = lvl
        sec["roles"] = merged
    if paused is not None:
        sec["paused"] = bool(paused)
    tenant.brand_config = {**(tenant.brand_config or {}), SETTINGS_KEY: sec}
    flag_modified(tenant, "brand_config")
    after = get_settings(tenant)
    append_audit(
        db,
        tenant_id=tenant.id,
        actor_user_id=actor_id,
        action="website.seo_agency_changed",
        target_type="tenant",
        target_id=tenant.id,
        payload={"before": before, "after": after},
    )
    return after


# ── weekly run ──────────────────────────────────────────────────────────────────────────────────────────────────────


def module_enabled(db: Session, tenant_id: str) -> bool:
    return (
        db.query(WorkspaceModule.id)
        .join(Module, Module.id == WorkspaceModule.module_id)
        .filter(WorkspaceModule.workspace_id == tenant_id, WorkspaceModule.enabled.is_(True), Module.code == "website")
        .first()
        is not None
    )


def ran_this_week(db: Session, tenant: Tenant) -> bool:
    now = get_tenant_now(tenant)
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    return (
        db.query(MarketingTask.id)
        .filter(
            MarketingTask.tenant_id == tenant.id,
            MarketingTask.step == RUN_STEP,
            MarketingTask.trigger == "schedule",
            MarketingTask.created_at >= start,
        )
        .first()
        is not None
    )


def due(db: Session, tenant: Tenant) -> bool:
    """Monday from 09:00 local, once a week (a missed hourly tick still runs later that Monday)."""
    now = get_tenant_now(tenant)
    return (
        now.weekday() == RUN_WEEKDAY
        and now.hour >= RUN_HOUR
        and not get_settings(tenant)["paused"]
        and module_enabled(db, tenant.id)
        and not ran_this_week(db, tenant)
    )


def run_week(db: Session, tenant: Tenant, *, trigger: str, actor_id: str | None) -> tuple[MarketingTask, list]:
    """Every role in ORDER, each in its own savepoint. Returns (the run row, Celery work to queue AFTER commit as
    (task name, args) pairs). Raises WebsiteError 409 while paused. The caller commits."""
    from app.services import website_seo_roles as roles_mod

    if get_settings(tenant)["paused"]:
        raise WebsiteError(409, "agency_paused", "The SEO agency is paused. Switch it back on to run it.")
    run_id = str(uuid.uuid4())
    parent = MarketingTask(
        tenant_id=tenant.id,
        run_id=run_id,
        role=PARENT_ROLE,
        step=RUN_STEP,
        status="running",
        trigger=trigger,
        created_by=actor_id,
        detail={},
    )
    db.add(parent)
    db.flush()
    ctx = roles_mod.Ctx(db=db, tenant=tenant, today=get_tenant_now(tenant).date())
    queue: list = []
    summary: dict[str, str] = {}
    for role in ORDER:
        db.refresh(tenant)  # the kill switch may have been pressed while the run was going
        lvl = level(tenant, role)
        row = MarketingTask(
            tenant_id=tenant.id,
            run_id=run_id,
            role=f"seo_{role}",
            step=ROLE_STEP,
            status="running",
            trigger=trigger,
            created_by=actor_id,
            detail={"level": lvl},
        )
        db.add(row)
        db.flush()
        if lvl == "off":
            reason = "paused" if get_settings(tenant)["paused"] else "off"
            row.status, row.detail = "skipped", {"level": lvl, "reason": reason}
        else:
            try:
                with db.begin_nested():
                    out = getattr(roles_mod, role)(ctx, lvl)
                queue += out.pop("_queue", [])
                row.status, row.detail = "done", {"level": lvl, **out}
            except Exception as exc:  # noqa: BLE001 -- one role failing never stops the others
                log.warning("seo_agency_role_failed", tenant_id=tenant.id, role=role, error=str(exc)[:300])
                row.status, row.error, row.detail = "failed", f"{type(exc).__name__}: {str(exc)[:500]}", {"level": lvl}
        row.finished_at = datetime.now(UTC)
        summary[role] = row.status
    parent.status, parent.detail, parent.finished_at = "done", {"roles": summary}, datetime.now(UTC)
    append_audit(
        db,
        tenant_id=tenant.id,
        actor_user_id=actor_id,
        action="website.seo_agency_run",
        target_type="marketing_task",
        target_id=parent.id,
        payload={"trigger": trigger, "roles": summary, **({} if actor_id else {"actor": "seo_agency"})},
    )
    return parent, queue


def last_run(db: Session, tenant_id: str) -> tuple[MarketingTask | None, dict[str, MarketingTask]]:
    parent = (
        db.query(MarketingTask)
        .filter_by(tenant_id=tenant_id, step=RUN_STEP)
        .order_by(MarketingTask.created_at.desc())
        .first()
    )
    if parent is None:
        return None, {}
    rows = db.query(MarketingTask).filter_by(tenant_id=tenant_id, run_id=parent.run_id, step=ROLE_STEP).all()
    return parent, {r.role.removeprefix("seo_"): r for r in rows}


# ── Website > Grow ──────────────────────────────────────────────────────────────────────────────────────────────────


def score(db: Session, tenant: Tenant, today, checker: dict | None) -> dict:
    """Visibility score 0-100: four parts of 25, each explained (the Studio health score's shape)."""
    from app.services import google_metrics
    from app.services.sops import service as sops
    from app.services.sops.checks import _active

    gb, sc = _active(db, tenant.id, "google_business"), _active(db, tenant.id, "search_console")
    setup = 12.5 * bool(gb) + 12.5 * bool(sc)
    ok_share = (checker or {}).get("ok_share")
    insts = sops.list_view(db, tenant)["instances"]
    done, total = sum(i["done"] for i in insts), sum(i["total"] for i in insts)
    vis = google_metrics.summary(db, tenant.id, today, 28)["visibility"]
    if vis["total"] is None:
        search, search_why = 0.0, "No Google numbers yet."
    elif vis["change_pct"] is None:
        search, search_why = 12.5, "First period with Google numbers; next month shows the trend."
    else:
        search = max(0.0, min(25.0, 12.5 + vis["change_pct"] / 4))
        search_why = f"Times shown on Google changed {vis['change_pct']}% against the 28 days before."
    parts = [
        {
            "key": "setup",
            "label": "Google connected",
            "points": round(setup),
            "max": 25,
            "why": "Business Profile "
            + ("connected" if gb else "not connected")
            + ", Search Console "
            + ("connected." if sc else "not connected."),
        },
        {
            "key": "technical",
            "label": "Site health",
            "points": round(25 * ok_share) if ok_share is not None else 0,
            "max": 25,
            "why": f"{round(ok_share * 100)}% of the technical checks pass."
            if ok_share is not None
            else "The technical check has not run yet.",
        },
        {
            "key": "found",
            "label": "Get found steps",
            "points": round(25 * done / total) if total else 0,
            "max": 25,
            "why": f"{done} of {total} checklist steps done." if total else "No Get found checklist started yet.",
        },
        {"key": "search", "label": "Search trend", "points": round(search), "max": 25, "why": search_why},
    ]
    return {
        "total": sum(p["points"] for p in parts),
        "parts": parts,
        "google": {"times_shown": vis["total"], "change_pct": vis["change_pct"]},
    }


def grow(db: Session, tenant: Tenant, *, show_money: bool, show_ads_money: bool) -> dict:
    """One read for Website > Grow: score, this week's tasks for people, results in rupees, the agency's roster."""
    from app.models.marketing import MarketingContent, MarketingGuestReview
    from app.services import website_report
    from app.services import website_seo_roles as R
    from app.services.sops.catalogue_ota import OTA_TEMPLATES
    from app.services.website_service import get_site

    today = get_tenant_now(tenant).date()
    parent, rows = last_run(db, tenant.id)
    det = {r: dict(row.detail or {}) for r, row in rows.items() if row.status == "done"}
    ctx = R.Ctx(db=db, tenant=tenant, today=today)
    tasks: list[dict] = []
    for role, keys in (
        ("local_profile", R.LOCAL_KEYS),
        ("listings", {t.key for t in OTA_TEMPLATES}),
        ("links_citations", R.LINKS_KEYS),
    ):
        cl = R._checklists(ctx, keys)
        tasks += [{"kind": "sop_step", "role": role, **s} for s in cl["steps"]]
        tasks += [{"kind": "start_checklist", "role": role, **a} for a in cl["to_start"][:2]]
    for c in (
        db.query(MarketingContent)
        .filter(
            MarketingContent.tenant_id == tenant.id,
            MarketingContent.kind == "article",
            MarketingContent.status.in_(("draft", "in_review")),
        )
        .order_by(MarketingContent.created_at.desc())
        .limit(10)
    ):
        tasks.append(
            {"kind": "guide_draft", "role": "content_writer", "id": c.id, "title": c.title, "status": c.status}
        )
    n_replies = (
        db.query(MarketingGuestReview.id)
        .filter(MarketingGuestReview.tenant_id == tenant.id, MarketingGuestReview.reply_status == "draft")
        .count()
    )
    if n_replies:
        tasks.append({"kind": "review_replies", "role": "local_profile", "count": n_replies})
    checker = det.get("technical_checker") or {}
    fixes = checker.get("fixes") or {}
    if not checker.get("applied") and (fixes.get("alt") or fixes.get("titles")):
        tasks.append(
            {
                "kind": "fixes",
                "role": "technical_checker",
                "alt": len(fixes.get("alt") or []),
                "titles": len(fixes.get("titles") or []),
            }
        )
    for m in (det.get("links_citations") or {}).get("outreach") or []:
        tasks.append({"kind": "outreach", "role": "links_citations", **m})
    ads = det.get("ads_analyst") or {}
    for s in ads.get("suggestions") or []:
        tasks.append(
            {
                "kind": "ads",
                "role": "ads_analyst",
                "campaign": s["campaign"],
                "action": s["action"],
                **({"why": s["why"], "effect_inr": s["effect_inr"]} if show_ads_money else {}),
            }
        )
    site = get_site(db, tenant.id)
    sc = score(db, tenant, today, checker)
    results: dict = {
        "days": 28,
        "website": None,
        "ads": None,
        "money_restricted": not show_money,
        "google": sc.pop("google"),
    }
    if site is not None:
        rep = website_report.build(db, site, today=today, days=28, show_money=show_money)
        results["website"] = {
            **rep["total"],
            **({"value": sum(r.get("value") or 0 for r in rep["rows"])} if show_money else {}),
        }
    if ads.get("totals"):
        results["ads"] = ads["totals"] if show_ads_money else {"bookings": ads["totals"].get("bookings")}
    analyst = det.get("search_analyst") or {}
    return {
        "settings": get_settings(tenant),
        "roster": roster(tenant),
        "last_run": (
            {
                "id": parent.id,
                "at": parent.created_at.isoformat() if parent.created_at else None,
                "trigger": parent.trigger,
                "roles": (parent.detail or {}).get("roles"),
            }
            if parent
            else None
        ),
        "score": sc,
        "brief": {"text": analyst.get("brief"), "actions": analyst.get("actions") or [], "facts": analyst.get("facts")}
        if analyst
        else None,
        "checker": {k: checker.get(k) for k in ("scores", "problems", "slow_pages", "sitemap", "links", "applied")}
        if checker
        else None,
        "tasks": tasks,
        "results": results,
    }
