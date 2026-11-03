"""Get found status as signals for the AI Executive's detectors (docs/ai/AI_EXECUTIVE_PLAN.md, branch bold-merkle) and
GET /sops/signals. Read-only, code only: each signal says what is wrong, for how long, and which checklist.

  gbp_unverified       the Google setup's "verify" step not done 14+ days after it started
  gbp_no_post          a Google checklist exists, and no Google post from HAIP and no upkeep "post" step done in 30 days
  sop_overdue          steps more than 7 days overdue, per platform
  promo_window_missed  a promotions checklist still open with a long weekend starting within 14 days
  sop_not_started      Google setup / Instagram profile never started, workspace older than 7 days
Google reviews without a reply are the Executive's own MK7 (same table); not repeated here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.marketing import MarketingPublishAttempt
from app.models.sop import SopInstance, SopStepProgress
from app.models.tenant import Tenant
from app.services.sops.catalogue import BY_KEY
from app.services.sops.upkeep import _aware

UNVERIFIED_DAYS, NO_POST_DAYS, OVERDUE_DAYS, PROMO_WINDOW_DAYS, NOT_STARTED_DAYS = 14, 30, 7, 14, 7


def _sig(code: str, platform: str, inst: SopInstance | None, days: int | None, **numbers) -> dict:
    return {
        "code": code,
        "platform": platform,
        "instance_id": inst.id if inst else None,
        "days": days,
        "numbers": numbers,
        "refs": [{"type": "sop_instance", "id": inst.id}] if inst else [],
    }


def signals(db: Session, tenant: Tenant, now: datetime) -> list[dict]:
    insts = db.query(SopInstance).filter(SopInstance.tenant_id == tenant.id, SopInstance.status != "archived").all()
    by_key = {i.template_key: i for i in insts if not i.property_id}
    prog = defaultdict(dict)
    for p in db.query(SopStepProgress).filter(
        SopStepProgress.tenant_id == tenant.id, SopStepProgress.instance_id.in_([i.id for i in insts] or [""])
    ):
        prog[(p.instance_id, p.cycle_no)][p.step_key] = p
    out: list[dict] = []

    g = by_key.get("gbp_setup")
    if g is not None:
        v = prog[(g.id, g.cycle_no)].get("verify")
        age = (now - _aware(g.created_at)).days
        if (v is None or v.status != "done") and age >= UNVERIFIED_DAYS:
            out.append(_sig("gbp_unverified", "google_business", g, age))

    google = [i for i in insts if BY_KEY[i.template_key].platform == "google_business"]
    if google:
        since = now - timedelta(days=NO_POST_DAYS)
        posted = (
            db.query(MarketingPublishAttempt)
            .filter(
                MarketingPublishAttempt.tenant_id == tenant.id,
                MarketingPublishAttempt.channel == "google",
                MarketingPublishAttempt.status == "published",
                MarketingPublishAttempt.published_at >= since,
            )
            .count()
        )
        up = by_key.get("gbp_upkeep")
        ticked = up is not None and any(
            p.step_key == "post" and p.status == "done" and p.done_at and _aware(p.done_at) >= since
            for (iid, _), steps in prog.items()
            if iid == up.id
            for p in steps.values()
        )
        if not posted and not ticked:
            out.append(_sig("gbp_no_post", "google_business", up or google[0], NO_POST_DAYS))

    overdue: dict[str, list] = defaultdict(list)
    for i in insts:
        if i.status != "active":
            continue
        for p in prog[(i.id, i.cycle_no)].values():
            due = _aware(p.due_at)
            if p.status == "todo" and due and due <= now - timedelta(days=OVERDUE_DAYS):
                overdue[BY_KEY[i.template_key].platform].append((i, (now - due).days))
    for platform, rows in overdue.items():
        worst = max(rows, key=lambda r: r[1])
        out.append(_sig("sop_overdue", platform, worst[0], worst[1], steps=len(rows)))

    promos = [i for i in insts if i.template_key.endswith("_promos") and i.status == "active"]
    if promos:
        from app.core.tenant_tz import get_tz
        from app.services import marketing_demand

        today = now.astimezone(get_tz(tenant)).date()
        lws = marketing_demand.long_weekends(
            marketing_demand.home_state(db, tenant), today, today + timedelta(days=PROMO_WINDOW_DAYS)
        )
        if lws:
            days = (datetime.fromisoformat(lws[0]["start"]).date() - today).days
            for i in promos:
                left = sum(p.status == "todo" for p in prog[(i.id, i.cycle_no)].values())
                if left:
                    out.append(_sig("promo_window_missed", BY_KEY[i.template_key].platform, i, days, steps_left=left))

    if tenant.created_at and (now - _aware(tenant.created_at)).days >= NOT_STARTED_DAYS:
        for key in ("gbp_setup", "instagram_profile"):
            if key not in by_key:
                out.append(_sig("sop_not_started", BY_KEY[key].platform, None, None, template=key))
    return out
