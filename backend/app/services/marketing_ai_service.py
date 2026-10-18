"""Marketing Studio: business profile, measured Instagram snapshot, and the three AI runs (audit, plan, content).

AI never runs in a request handler: endpoints create a `pending` row and queue a Celery task
(workers/tasks/marketing_studio.py), which calls run_audit / run_plan / run_content here.

Failure handling: a transient provider error (timeout, connection, 5xx) raises LLMTransientError so the task can retry
with backoff; anything else (unparseable output, schema violation, a price in a handoff workspace) marks the row
`failed` with a readable error and is not retried.
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import append_audit
from app.core.prompt_versions import get_version
from app.models.marketing import MarketingAudit, MarketingContent, MarketingPlan
from app.models.property import Property
from app.models.tenant import Tenant
from app.schemas.marketing import AuditAssessment, BusinessProfile, MarketingPlanBody
from app.services import marketing_content_service as content_svc
from app.services import marketing_prompts as prompts
from app.services import price_policy, usage_service

log = structlog.get_logger()

MODULE = "marketing_studio"
PROFILE_KEY = "business_profile"


class LLMTransientError(Exception):
    """Provider unavailable for now; safe to retry."""


# ── Profile ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def get_profile(tenant: Optional[Tenant]) -> dict:
    raw = ((tenant.brand_config or {}).get(PROFILE_KEY) if tenant is not None else None) or {}
    try:
        return BusinessProfile.model_validate(raw).model_dump(mode="json")
    except ValidationError:
        log.warning("business_profile_invalid_stored", tenant_id=getattr(tenant, "id", None))
        return BusinessProfile().model_dump(mode="json")


def put_profile(db: Session, tenant: Tenant, data: dict, actor_id: str) -> dict:
    clean = BusinessProfile.model_validate(data).model_dump(mode="json")
    before = (tenant.brand_config or {}).get(PROFILE_KEY)
    cfg = dict(tenant.brand_config or {})
    cfg[PROFILE_KEY] = clean
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.profile.updated", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": clean})
    return clean


def _facts(db: Session, tenant: Tenant, property_id: Optional[str] = None) -> dict:
    """What the AI may rely on. No prices, no availability: those belong to the booking system and a person."""
    from app.services.vehicle_pool import is_placeholder_name

    q = db.query(Property).filter(Property.tenant_id == tenant.id, Property.is_active.is_(True))
    if property_id:
        q = q.filter(Property.id == property_id)
    props = [
        {"name": p.name, "type": p.type, "city": p.city, "state": p.state, "description": (p.description or "")[:1200],
         "amenities": p.amenities or [], "max_adults": p.max_adults, "bedrooms": p.bedrooms, "home_base": p.home_base}
        for p in q.limit(10).all() if not is_placeholder_name(p.name)
    ]
    return {"brand_name": tenant.brand_name or tenant.name, "business_type": tenant.business_type,
            "profile": get_profile(tenant), "properties": props}


# ── Measured data ───────────────────────────────────────────────────────────────────────────────────────────────────

_ACCOUNT_FIELDS = ("followers_count", "following_count", "media_count", "reach", "profile_views", "accounts_engaged",
                   "total_interactions", "likes", "comments", "shares", "saves", "replies", "profile_links_taps")
_POST_FIELDS = ("media_id", "media_type", "posted_at", "like_count", "comments_count", "reach", "saved", "shares",
                "total_interactions")


_BASELINE_METRICS = ("reach", "like_count", "comments_count", "saved", "shares", "total_interactions")
MIN_POSTS_FOR_BASELINE = 3


def post_baseline(posts: list[dict]) -> dict:
    """The account's own medians, and each post's multiple of them, computed here (never by the AI).

    Judging posts against the account's own median, not generic benchmarks, follows the content-audit technique in
    Ootto-AI/claude-content-skills (MIT; docs/marketing-website/THIRD_PARTY_NOTICES.md)."""
    from statistics import median

    def med(rows: list[dict], m: str):
        vals = [r[m] for r in rows if isinstance(r.get(m), (int, float))]
        return float(median(vals)) if len(vals) >= MIN_POSTS_FOR_BASELINE else None

    medians = {m: med(posts, m) for m in _BASELINE_METRICS}
    by_post = []
    for p in posts:
        mult = {m: round(p[m] / medians[m], 2) for m in _BASELINE_METRICS
                if medians[m] and isinstance(p.get(m), (int, float))}
        by_post.append({"media_id": p.get("media_id"), "media_type": p.get("media_type"), "multiples": mult})
    by_type: dict[str, dict] = {}
    for t in sorted({p.get("media_type") for p in posts if p.get("media_type")}):
        rows = [p for p in posts if p.get("media_type") == t]
        by_type[t] = {"posts": len(rows), "median_reach": med(rows, "reach"),
                      "median_interactions": med(rows, "total_interactions")}
    return {"posts_counted": len(posts), "enough_signal": any(v is not None for v in medians.values()),
            "min_posts": MIN_POSTS_FOR_BASELINE, "medians": medians, "by_post": by_post, "by_media_type": by_type}


def measured_snapshot(db: Session, tenant_id: str) -> dict:
    """A frozen copy of the latest numbers the daily Instagram poller stored (instagram_insights_poll.py)."""
    from app.workers.tasks.instagram_insights_poll import InstagramInsightsSnapshot, InstagramPostSnapshot

    snap = (db.query(InstagramInsightsSnapshot).filter_by(tenant_id=tenant_id)
            .order_by(InstagramInsightsSnapshot.created_at.desc()).first())
    posts = (db.query(InstagramPostSnapshot).filter_by(tenant_id=tenant_id)
             .order_by(InstagramPostSnapshot.posted_at.desc()).limit(12).all())
    if snap is None and not posts:
        return {"source": "instagram_graph_api", "available": False, "captured_at": None, "account": {}, "posts": []}
    post_rows = [{f: getattr(p, f) for f in _POST_FIELDS} | {"caption": (p.caption or "")[:300]} for p in posts]
    return {
        "source": "instagram_graph_api",
        "available": True,
        "captured_at": snap.created_at.isoformat() if snap is not None and snap.created_at else None,
        "account": {f: getattr(snap, f) for f in _ACCOUNT_FIELDS} if snap is not None else {},
        "demographics": snap.demographics if snap is not None else None,
        "posts": post_rows,
        "baseline": post_baseline(post_rows),
    }


# ── LLM call ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, asyncio.TimeoutError)):
        return True
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    name = type(exc).__name__.lower()
    return (isinstance(status, int) and (status == 429 or status >= 500)) or "timeout" in name or "connection" in name


def _call(task: str, tenant_id: str, system: str, user: str, tool: dict) -> tuple[dict, dict, str]:
    """Run one tool-calling completion. Returns (tool input, raw response, provider)."""
    from app.adapters.llm import get_llm

    adapter = get_llm(task, tenant_id)
    loop = asyncio.new_event_loop()
    try:
        raw = loop.run_until_complete(adapter.complete(system_prompt=system, user_message=user, max_tokens=3000, tools=[tool]))
    except Exception as exc:  # noqa: BLE001 -- classified below
        if _is_transient(exc):
            raise LLMTransientError(f"{type(exc).__name__}: {exc}") from exc
        raise ValueError(f"AI provider error: {type(exc).__name__}: {str(exc)[:300]}") from exc
    finally:
        loop.close()
    data = raw.get("tool_use")   # adapters return the tool's input dict itself (see nvidia_nim.py)
    if not isinstance(data, dict) or not data:
        raise ValueError("The AI did not return structured output.")
    return data, raw, getattr(adapter, "provider", None) or "unknown"


def _errors(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:8])


def _system(template: str, tenant: Tenant) -> str:
    return template.format(**prompts.rules(price_policy.price_mode(tenant)))


# ── Runs ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def run_audit(db: Session, tenant_id: str, audit_id: str) -> MarketingAudit:
    audit = db.query(MarketingAudit).filter_by(id=audit_id, tenant_id=tenant_id).one()
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    audit.prompt_version = get_version("marketing_audit")
    try:
        if not (audit.measured or {}).get("available"):
            raise ValueError("No Instagram insights have been collected yet; connect Instagram and wait for the daily poll.")
        user = f"Business facts:\n{_facts(db, tenant)}\n\nMEASURED Instagram data:\n{audit.measured}"
        data, raw, provider = _call("marketing_audit", tenant_id, _system(prompts.AUDIT_SYSTEM, tenant), user, prompts.AUDIT_TOOL)
        usage_service.record_llm(db, tenant_id, MODULE, raw, provider=provider, ref_type="marketing_audit", ref_id=audit.id)
        known = set(_ACCOUNT_FIELDS) | set(_POST_FIELDS) | {"demographics", "baseline", "medians", "multiples"}
        assessment = AuditAssessment.model_validate(data).model_dump(mode="json")
        for f in assessment["findings"]:
            f["metric_keys"] = [k for k in f["metric_keys"] if k in known]
        audit.assessment, audit.model, audit.status, audit.error = assessment, raw.get("model"), "ready", None
    except ValidationError as exc:
        audit.status, audit.error = "failed", f"The AI's answer did not fit the audit format: {_errors(exc)}"
    except ValueError as exc:
        audit.status, audit.error = "failed", str(exc)
    return audit


def run_plan(db: Session, tenant_id: str, plan_id: str) -> MarketingPlan:
    plan = db.query(MarketingPlan).filter_by(id=plan_id, tenant_id=tenant_id).one()
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    plan.prompt_version = get_version("marketing_plan")
    audit = db.query(MarketingAudit).filter_by(id=plan.audit_id, tenant_id=tenant_id).first() if plan.audit_id else None
    try:
        user = (f"Business facts:\n{_facts(db, tenant)}\n\nPeriod: {plan.period_start} to {plan.period_end}\n"
                f"Owner's brief: {plan.brief or '(none)'}\n"
                f"Audit findings: {audit.assessment if audit is not None and audit.status == 'ready' else '(no audit)'}")
        data, raw, provider = _call("marketing_plan", tenant_id, _system(prompts.PLAN_SYSTEM, tenant), user, prompts.PLAN_TOOL)
        usage_service.record_llm(db, tenant_id, MODULE, raw, provider=provider, ref_type="marketing_plan", ref_id=plan.id)
        body = MarketingPlanBody.model_validate(data).model_dump(mode="json")
        body["calendar"] = [e for e in body["calendar"] if plan.period_start <= e["date"] <= plan.period_end]
        problems = content_svc.check_text(db, tenant_id, body)
        if problems:
            raise ValueError("; ".join(problems))
        plan.body, plan.model, plan.status, plan.error = body, raw.get("model"), "ready", None
    except ValidationError as exc:
        plan.status, plan.error = "failed", f"The AI's answer did not fit the plan format: {_errors(exc)}"
    except ValueError as exc:
        plan.status, plan.error = "failed", str(exc)
    return plan


def run_content(db: Session, tenant_id: str, item_id: str, actor_id: Optional[str], brief: Optional[str]) -> MarketingContent:
    item = content_svc.get_item(db, tenant_id, item_id)
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    try:
        user = (f"Business facts:\n{_facts(db, tenant, item.property_id)}\n\nKind: {item.kind}\nTitle: {item.title}\n"
                f"Brief: {brief or '(none)'}")
        data, raw, provider = _call("marketing_content", tenant_id, _system(prompts.CONTENT_SYSTEM, tenant), user,
                                    prompts.content_tool(item.kind))
        usage_service.record_llm(db, tenant_id, MODULE, raw, provider=provider, ref_type="marketing_content", ref_id=item.id)
        data.pop("kind", None)
        content_svc.add_version(db, tenant_id, item.id, data, origin="ai", actor_id=actor_id,
                                note=(brief or "")[:500] or None, prompt_version=get_version("marketing_content"),
                                model=raw.get("model"))
    except content_svc.MarketingError as exc:
        item.generation_status = "failed"
        item.generation_error = "; ".join([exc.message, *exc.problems])[:2000]
    except ValueError as exc:
        item.generation_status, item.generation_error = "failed", str(exc)[:2000]
    return item


def mark_failed(db: Session, model, row_id: str, tenant_id: str, error: str) -> None:
    """Final state after retries ran out. `model` is MarketingAudit, MarketingPlan or MarketingContent."""
    row = db.query(model).filter_by(id=row_id, tenant_id=tenant_id).first()
    if row is None:
        return
    if model is MarketingContent:
        row.generation_status, row.generation_error = "failed", error[:2000]
    else:
        row.status, row.error = "failed", error[:2000]
    row.updated_at = datetime.now(timezone.utc)
