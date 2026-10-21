"""Boost rules (agency M5): "if a weekend is under 50% booked 10 days out, boost the latest reel, max Rs 3,000".

A rule is approved once by the OWNER; the approval binds to the sha of its body, so any edit sends it back to draft.
The hourly check (Celery `marketing_ads.evaluate`) looks at every weekend (Fri + Sat nights) or long weekend that is
`days_ahead` days away or closer (and at least two days off, so the ad has time to work), measures how booked it is
from HAIP's own calendar (marketing_demand.free_nights: bookings, blocks, shared-vehicle shortages), and for the
nearest one under the threshold makes ONE ad draft (unique per rule + weekend). The draft runs by itself only on
autopilot and within the monthly budget (marketing_ads_service.approve_by_rule); otherwise it waits for a person.
The ad stops by noon on the Friday it sells: advertising a weekend that has started is wasted money.
"""
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Optional

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.marketing import MarketingContent
from app.models.marketing_ads import MarketingAdDraft, MarketingBoostRule
from app.models.tenant import Tenant
from app.schemas.marketing_ads import BoostRuleIn
from app.services import marketing_ads_service as ads
from app.services import marketing_agency_service as agency
from app.services import marketing_demand as demand
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

LIVE_STATUSES = ("approved", "scheduled", "published")


def body_sha(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _clean(data: dict) -> tuple[str, dict]:
    try:
        rule = BoostRuleIn.model_validate(data)
    except ValueError as exc:
        raise MarketingError(422, "bad_rule", "Check the rule.", [str(exc)[:300]])
    return rule.name, rule.model_dump(include={"condition", "action"})


def get_rule(db: Session, tenant_id: str, rule_id: str) -> MarketingBoostRule:
    row = db.query(MarketingBoostRule).filter_by(id=rule_id, tenant_id=tenant_id).first()
    if row is None:
        raise MarketingError(404, "not_found", "No such boost rule in this workspace.")
    return row


def create_rule(db: Session, tenant: Tenant, data: dict, actor_id: str) -> MarketingBoostRule:
    name, body = _clean(data)
    rule = MarketingBoostRule(tenant_id=tenant.id, name=name, body=body, body_sha=body_sha(body), status="draft",
                              created_by=actor_id)
    db.add(rule)
    db.flush()
    append_audit(db, tenant_id=tenant.id, action="marketing.boost_rule.created", actor_user_id=actor_id,
                 target_type="marketing_boost_rule", target_id=rule.id, payload={"name": name, "body": body})
    return rule


def update_rule(db: Session, tenant: Tenant, rule_id: str, data: dict, actor_id: str) -> MarketingBoostRule:
    rule = get_rule(db, tenant.id, rule_id)
    name, body = _clean(data)
    before = {"name": rule.name, "body": rule.body, "status": rule.status}
    rule.name, rule.body, rule.body_sha = name, body, body_sha(body)
    rule.status, rule.approved_by, rule.approved_at, rule.approved_sha = "draft", None, None, None   # an edit voids it
    append_audit(db, tenant_id=tenant.id, action="marketing.boost_rule.updated", actor_user_id=actor_id,
                 target_type="marketing_boost_rule", target_id=rule.id, payload={"before": before, "after": body})
    return rule


def approve_rule(db: Session, tenant: Tenant, rule_id: str, actor_id: str) -> MarketingBoostRule:
    rule = get_rule(db, tenant.id, rule_id)
    if body_sha(rule.body) != rule.body_sha:
        raise MarketingError(409, "integrity_failed", "The rule changed; open it again.")
    rule.status, rule.approved_by, rule.approved_at, rule.approved_sha = ("approved", actor_id, datetime.now(timezone.utc),
                                                                          rule.body_sha)
    append_audit(db, tenant_id=tenant.id, action="marketing.boost_rule.approved", actor_user_id=actor_id,
                 target_type="marketing_boost_rule", target_id=rule.id, payload={"sha": rule.body_sha, "body": rule.body})
    return rule


def pause_rule(db: Session, tenant: Tenant, rule_id: str, actor_id: str) -> MarketingBoostRule:
    rule = get_rule(db, tenant.id, rule_id)
    rule.status = "paused"
    append_audit(db, tenant_id=tenant.id, action="marketing.boost_rule.paused", actor_user_id=actor_id,
                 target_type="marketing_boost_rule", target_id=rule.id, payload={})
    return rule


def as_dict(r: MarketingBoostRule) -> dict:
    return {"id": r.id, "name": r.name, **r.body, "status": r.status, "approved_by": r.approved_by,
            "approved_at": r.approved_at, "in_force": r.status == "approved" and r.approved_sha == r.body_sha,
            "last_checked_at": r.last_checked_at, "last_result": r.last_result, "created_by": r.created_by}


# ── The check ───────────────────────────────────────────────────────────────────────────────────────────────────────

def windows(db: Session, tenant: Tenant, condition: dict, today: date) -> list[dict]:
    """The weekends a rule looks at today: {key, label, nights, starts}."""
    first, last = today + timedelta(days=2), today + timedelta(days=condition["days_ahead"])
    out = []
    if condition["window"] == "weekend":
        d = first + timedelta(days=(4 - first.weekday()) % 7)            # the first Friday on or after `first`
        while d <= last:
            out.append({"key": f"weekend:{d.isoformat()}", "label": f"weekend of {d.strftime('%d %b')}",
                        "nights": [d, d + timedelta(days=1)], "starts": d})
            d += timedelta(days=7)
    else:
        for lw in demand.long_weekends(demand.home_state(db, tenant), first, last + timedelta(days=4)):
            s, e = date.fromisoformat(lw["start"]), date.fromisoformat(lw["end"])
            if first <= s <= last:
                out.append({"key": f"long_weekend:{s.isoformat()}", "label": f"long weekend from {s.strftime('%d %b')}",
                            "nights": [s + timedelta(days=i) for i in range((e - s).days)] or [s], "starts": s})
    return out


def occupancy(db: Session, tenant_id: str, nights: list[date]) -> Optional[float]:
    """Percent of vehicle/property nights booked or blocked, from HAIP's own calendar. None = nothing to measure."""
    if not nights:
        return None
    free = demand.free_nights(db, tenant_id, min(nights), max(nights) + timedelta(days=1))
    total = len(free) * len(nights)
    if total == 0:
        return None
    open_nights = sum(1 for days in free.values() for d in days if d in nights)
    return round(100 * (total - open_nights) / total, 1)


def pick_content(db: Session, tenant_id: str, action: dict) -> Optional[MarketingContent]:
    q = db.query(MarketingContent).filter(MarketingContent.tenant_id == tenant_id,
                                          MarketingContent.status.in_(LIVE_STATUSES))
    if action["content"] == "specific":
        return q.filter(MarketingContent.id == action["content_id"]).first()
    kinds = ("reel",) if action["content"] == "latest_reel" else ("post", "carousel", "promo")
    return q.filter(MarketingContent.kind.in_(kinds)).order_by(MarketingContent.updated_at.desc()).first()


def latest_end_for(window_key: Optional[str]) -> Optional[datetime]:
    """Noon IST on the first day of the weekend the ad sells."""
    if not window_key or ":" not in window_key:
        return None
    try:
        day = date.fromisoformat(window_key.split(":", 1)[1])
    except ValueError:
        return None
    return datetime.combine(day, time(12, 0), tzinfo=ads.IST).astimezone(timezone.utc)


def check_rule(db: Session, tenant: Tenant, rule: MarketingBoostRule, *, today: date, dry_run: bool = False,
               queue_push: Optional[Callable[[str, str], None]] = None) -> dict:
    cond, action = rule.body["condition"], rule.body["action"]
    seen = []
    for w in windows(db, tenant, cond, today):
        pct = occupancy(db, tenant.id, w["nights"])
        seen.append({"window": w["label"], "booked_pct": pct})
        if pct is None or pct >= cond["occupancy_below_pct"]:
            continue
        if db.query(MarketingAdDraft.id).filter_by(tenant_id=tenant.id, rule_id=rule.id, window_key=w["key"]).first():
            continue                                             # this weekend was already boosted (or offered)
        item = pick_content(db, tenant.id, action)
        if item is None:
            return {"seen": seen, "action": "none", "reason": "No approved content of that kind to boost."}
        result = {"seen": seen, "window": w["label"], "booked_pct": pct, "content_id": item.id, "content": item.title}
        if dry_run:
            return {**result, "action": "would_boost"}
        try:
            with db.begin_nested():
                draft = ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": action["daily_budget_inr"],
                                                      "days": action["days"], "destination": action.get("destination")},
                                         None, origin="rule", rule_id=rule.id, window_key=w["key"],
                                         max_total_inr=action["max_total_inr"])
        except IntegrityError:
            continue                                             # another worker made it a moment ago
        except MarketingError as exc:
            return {**result, "action": "none", "reason": exc.message}
        if ads.approve_by_rule(db, tenant, draft, rule):
            db.commit()
            if queue_push:
                queue_push(tenant.id, draft.id)
            return {**result, "action": "boosted", "draft_id": draft.id}
        db.commit()
        problems = ads.money_problems(db, tenant, draft)
        agency.notify_needs_approval(db, tenant.id, "Marketing: a boost is waiting for you",
                                     f"{w['label'].capitalize()} is {pct:.0f}% booked. Approve the ad to run it.")
        return {**result, "action": "waiting_for_approval", "draft_id": draft.id,
                "reason": problems[0] if problems else "The performance marketer is on suggest, so a person approves."}
    return {"seen": seen, "action": "none", "reason": "Every weekend in range is booked above the threshold."
            if seen else "No weekend in range yet."}


def evaluate(db: Session, tenant: Tenant, *, today: Optional[date] = None,
             queue_push: Optional[Callable[[str, str], None]] = None) -> list[dict]:
    today = today or datetime.now(ads.IST).date()
    out = []
    rules = db.query(MarketingBoostRule).filter_by(tenant_id=tenant.id, status="approved").all()
    for rule in rules:
        if rule.approved_sha != rule.body_sha:
            continue
        result = check_rule(db, tenant, rule, today=today, queue_push=queue_push)
        rule.last_checked_at, rule.last_result = datetime.now(timezone.utc), result
        db.commit()
        out.append({"rule_id": rule.id, **result})
    return out
