"""Performance marketer (agency M5): ads settings, ad drafts from approved content, approvals and the money caps.

Money rules, in order, checked again right before anything reaches Meta (marketing_ads_push):
  1. the workspace's monthly cap (brand_config.marketing_studio.ads.monthly_cap_inr) is 0 until the OWNER sets it, and
     the committed caps of this month's ads (spend so far for finished ones) may never exceed it;
  2. every ad has its own hard cap (= daily budget x days, or a boost rule's lower total), also set on Meta as the
     campaign spend_cap, so Meta itself stops at it;
  3. the agency kill switch and the `ads` role (off by default) stop new ads;
  4. a draft runs only after a person with marketing.approve approves it (not the person who made it, unless owner),
     or when an owner-approved boost rule made it and the `ads` role is on autopilot.
An ad shows exactly one APPROVED content version (its sha is pinned); a later edit of the post never changes a running ad.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import append_audit
from app.models.ad_metrics import AdMetric
from app.models.marketing import MarketingContent
from app.models.marketing_ads import MarketingAdDraft
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.marketing_ads import AdDraftIn, AdSettings
from app.services import marketing_agency_service as agency
from app.services import marketing_content_service as content_svc
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

KEY = "ads"
IST = ZoneInfo("Asia/Kolkata")
AD_KINDS = ("post", "carousel", "promo", "reel")          # stories are not turned into ads
COMMITTED = ("approved", "pushing", "live", "paused", "ended")
FINISHED = ("paused", "ended")


# ── Settings ────────────────────────────────────────────────────────────────────────────────────────────────────────

def get_settings(tenant: Optional[Tenant]) -> dict:
    section = ((tenant.brand_config or {}).get("marketing_studio") or {}) if tenant is not None else {}
    raw = section.get(KEY) if isinstance(section, dict) else None
    try:
        return AdSettings.model_validate(raw or {}).model_dump()
    except ValueError:
        return AdSettings().model_dump()


def put_settings(db: Session, tenant: Tenant, data: dict, actor_id: str) -> dict:
    try:
        clean = AdSettings.model_validate(data).model_dump()
    except ValueError as exc:
        raise MarketingError(422, "bad_ads_settings", "Check the ads settings.", [str(exc)[:300]])
    before = get_settings(tenant)
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get("marketing_studio") or {})
    section[KEY] = clean
    cfg["marketing_studio"] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.ads.settings_updated", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": clean})
    return clean


# ── Money ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def month_start(now: Optional[datetime] = None) -> datetime:
    local = (now or datetime.now(timezone.utc)).astimezone(IST)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def committed_this_month(db: Session, tenant_id: str, *, exclude_id: Optional[str] = None,
                         now: Optional[datetime] = None) -> int:
    """Rupees this month's ads may still spend or already spent: a finished ad counts what it spent, others their cap."""
    rows = (db.query(MarketingAdDraft).filter(MarketingAdDraft.tenant_id == tenant_id,
                                              MarketingAdDraft.status.in_(COMMITTED),
                                              MarketingAdDraft.approved_at >= month_start(now)).all())
    total = 0
    for r in rows:
        if r.id == exclude_id:
            continue
        if r.status in FINISHED and r.spent_inr is not None:
            total += min(int(Decimal(r.spent_inr).to_integral_value()), r.spend_cap_inr)
        else:
            total += r.spend_cap_inr
    return total


def budget_left(db: Session, tenant: Tenant, *, exclude_id: Optional[str] = None) -> int:
    return max(0, get_settings(tenant)["monthly_cap_inr"] - committed_this_month(db, tenant.id, exclude_id=exclude_id))


def money_problems(db: Session, tenant: Tenant, draft: MarketingAdDraft) -> list[str]:
    out = []
    cap = get_settings(tenant)["monthly_cap_inr"]
    if cap <= 0:
        out.append("The owner has not set a monthly ads budget yet, so HAIP will not spend anything.")
    elif draft.spend_cap_inr > budget_left(db, tenant, exclude_id=draft.id):
        out.append(f"This ad's cap of Rs {draft.spend_cap_inr:,} is more than is left of this month's ads budget "
                   f"(Rs {budget_left(db, tenant, exclude_id=draft.id):,}).")
    lvl = agency.level(tenant, "ads")
    if agency.get_agency(tenant)["paused"]:
        out.append("The agency is paused.")
    elif lvl == "off":
        out.append("The performance marketer is switched off in the Agency tab.")
    return out


# ── Drafts ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def ad_payload(db: Session, tenant_id: str, item: MarketingContent) -> tuple[str, str, dict]:
    """(version_id, sha, payload) of the content's APPROVED version. Posted content can be promoted too."""
    if item.status not in ("approved", "scheduled", "published") or not item.approved_version_id:
        raise MarketingError(409, "not_approved", "Only approved content can become an ad.")
    version = content_svc.get_version(db, tenant_id, item.approved_version_id)
    if version is None or version.sha256 != item.approved_sha256 or content_svc.sha_of(version.payload) != version.sha256:
        raise MarketingError(409, "integrity_failed", "The approved content no longer matches what was approved.")
    if item.kind not in AD_KINDS:
        raise MarketingError(422, "kind_not_supported", "Stories cannot be turned into ads; use a post, carousel, promo or reel.")
    return version.id, version.sha256, version.payload


def create_draft(db: Session, tenant: Tenant, data: dict, actor_id: Optional[str], *, origin: str = "manual",
                 rule_id: Optional[str] = None, window_key: Optional[str] = None,
                 max_total_inr: Optional[int] = None) -> MarketingAdDraft:
    try:
        body = AdDraftIn.model_validate(data)
    except ValueError as exc:
        raise MarketingError(422, "bad_ad", "Check the ad budget and length.", [str(exc)[:300]])
    item = content_svc.get_item(db, tenant.id, body.content_id)
    version_id, sha, _ = ad_payload(db, tenant.id, item)
    settings = get_settings(tenant)
    audience = (body.audience.model_dump() if body.audience else None) or settings["audience"]
    if not audience:
        raise MarketingError(422, "no_audience", "Set who the ads reach (a place and a radius) in the ads settings first.")
    cap = body.daily_budget_inr * body.days
    if max_total_inr is not None:
        cap = min(cap, max_total_inr)
    draft = MarketingAdDraft(tenant_id=tenant.id, content_id=item.id, version_id=version_id, content_sha=sha,
                             origin=origin, rule_id=rule_id, window_key=window_key,
                             destination=body.destination or settings["destination"],
                             daily_budget_inr=body.daily_budget_inr, days=body.days, spend_cap_inr=cap,
                             audience=audience, status="draft", created_by=actor_id)
    db.add(draft)
    db.flush()
    append_audit(db, tenant_id=tenant.id, action="marketing.ad.drafted", actor_user_id=actor_id,
                 target_type="marketing_ad_draft", target_id=draft.id,
                 payload={"content_id": item.id, "version_id": version_id, "origin": origin, "rule_id": rule_id,
                          "daily_budget_inr": draft.daily_budget_inr, "days": draft.days, "spend_cap_inr": cap,
                          **({"actor": "agency"} if actor_id is None else {})})
    return draft


def get_draft(db: Session, tenant_id: str, draft_id: str) -> MarketingAdDraft:
    row = db.query(MarketingAdDraft).filter_by(id=draft_id, tenant_id=tenant_id).first()
    if row is None:
        raise MarketingError(404, "not_found", "No such ad in this workspace.")
    return row


def _guarded(db: Session, draft: MarketingAdDraft, from_statuses: tuple, values: dict) -> bool:
    n = (db.query(MarketingAdDraft).filter(MarketingAdDraft.id == draft.id, MarketingAdDraft.status.in_(from_statuses))
         .update(values, synchronize_session=False))
    db.flush()
    db.refresh(draft)
    return n == 1


def approve(db: Session, tenant: Tenant, draft_id: str, actor: User, note: Optional[str] = None) -> MarketingAdDraft:
    """A person approves spending on this ad. Re-checks the content approval and every money rule."""
    draft = get_draft(db, tenant.id, draft_id)
    if content_svc._role(actor) != "owner" and draft.created_by == actor.id:
        raise MarketingError(403, "self_approval", "You made this ad, so someone else must approve it.")
    item = content_svc.get_item(db, tenant.id, draft.content_id)
    _, sha, _ = ad_payload(db, tenant.id, item)
    if sha != draft.content_sha:
        raise MarketingError(409, "content_changed", "The post was approved again with new content; make a new ad.")
    problems = money_problems(db, tenant, draft)
    if problems:
        raise MarketingError(409, "cannot_spend", problems[0], problems)
    if not _guarded(db, draft, ("draft",), {"status": "approved", "approved_by": actor.id, "error": None,
                                            "approved_at": datetime.now(timezone.utc), "approval_note": (note or None)}):
        raise MarketingError(409, "wrong_state", "Only a draft ad can be approved.")
    append_audit(db, tenant_id=tenant.id, action="marketing.ad.approved", actor_user_id=actor.id,
                 target_type="marketing_ad_draft", target_id=draft.id,
                 payload={"spend_cap_inr": draft.spend_cap_inr, "budget_left_inr": budget_left(db, tenant, exclude_id=draft.id)})
    return draft


def approve_by_rule(db: Session, tenant: Tenant, draft: MarketingAdDraft, rule) -> bool:
    """A boost rule's draft runs without a person only if the rule is approved as it stands and the ads role is on
    autopilot. Returns True if approved; otherwise the draft waits in the inbox."""
    if rule.status != "approved" or rule.approved_sha != rule.body_sha or agency.level(tenant, "ads") != "autopilot":
        return False
    if money_problems(db, tenant, draft):
        return False
    ok = _guarded(db, draft, ("draft",), {"status": "approved", "approved_by": rule.approved_by,
                                          "approved_at": datetime.now(timezone.utc),
                                          "approval_note": f"Boost rule \"{rule.name}\" (approved once)"[:300]})
    if ok:
        append_audit(db, tenant_id=tenant.id, action="marketing.ad.approved", actor_user_id=None,
                     target_type="marketing_ad_draft", target_id=draft.id,
                     payload={"actor": "agency", "rule_id": rule.id, "rule_sha": rule.approved_sha,
                              "spend_cap_inr": draft.spend_cap_inr})
    return ok


def cancel(db: Session, tenant_id: str, draft_id: str, actor_id: str) -> MarketingAdDraft:
    draft = get_draft(db, tenant_id, draft_id)
    if not _guarded(db, draft, ("draft", "approved", "failed"), {"status": "cancelled"}):
        raise MarketingError(409, "wrong_state", "A running ad is paused, not cancelled.")
    append_audit(db, tenant_id=tenant_id, action="marketing.ad.cancelled", actor_user_id=actor_id,
                 target_type="marketing_ad_draft", target_id=draft.id, payload={})
    return draft


def spent_by_ad(db: Session, tenant_id: str, ad_ids: list[str]) -> dict[str, Decimal]:
    if not ad_ids:
        return {}
    return {a: Decimal(s or 0) for a, s in db.query(AdMetric.ad_id, func.sum(AdMetric.spend))
            .filter(AdMetric.tenant_id == tenant_id, AdMetric.ad_id.in_(ad_ids)).group_by(AdMetric.ad_id)}


def as_dict(d: MarketingAdDraft) -> dict:
    return {"id": d.id, "content_id": d.content_id, "version_id": d.version_id, "origin": d.origin, "rule_id": d.rule_id,
            "window_key": d.window_key, "destination": d.destination, "daily_budget_inr": d.daily_budget_inr,
            "days": d.days, "spend_cap_inr": d.spend_cap_inr, "audience": d.audience, "status": d.status,
            "created_by": d.created_by, "approved_by": d.approved_by, "approved_at": d.approved_at,
            "approval_note": d.approval_note, "meta": d.meta or {}, "starts_at": d.starts_at, "ends_at": d.ends_at,
            "spent_inr": float(d.spent_inr) if d.spent_inr is not None else None, "error": d.error,
            "created_at": d.created_at}


def list_drafts(db: Session, tenant_id: str, limit: int = 100) -> list[dict]:
    rows = (db.query(MarketingAdDraft).filter_by(tenant_id=tenant_id)
            .order_by(MarketingAdDraft.created_at.desc()).limit(limit).all())
    titles = dict(db.query(MarketingContent.id, MarketingContent.title).filter(
        MarketingContent.tenant_id == tenant_id, MarketingContent.id.in_({r.content_id for r in rows}))) if rows else {}
    return [{**as_dict(r), "content_title": titles.get(r.content_id)} for r in rows]


def overview(db: Session, tenant: Tenant) -> dict:
    s = get_settings(tenant)
    return {"settings": s, "committed_inr": committed_this_month(db, tenant.id), "budget_left_inr": budget_left(db, tenant),
            "ads_level": agency.level(tenant, "ads"), "paused": agency.get_agency(tenant)["paused"],
            "window_ends": (month_start() + timedelta(days=32)).astimezone(IST).replace(day=1).date().isoformat()}
