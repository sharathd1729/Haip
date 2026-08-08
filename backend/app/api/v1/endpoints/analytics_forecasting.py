"""
Phase 4: Predictive Intelligence Analytics Endpoints

GET /analytics/forecasting/occupancy   — 30-day occupancy forecast per property
GET /analytics/forecasting/revenue     — MTD + 12-month revenue forecast
GET /analytics/forecasting/pricing     — Dynamic pricing suggestions
GET /analytics/forecasting/churn       — Guest churn risk scoring
GET /analytics/forecasting/cohorts     — Guest acquisition cohort retention

All endpoints:
  - Require authentication (any role)
  - Accept ?range_days=30/90 and ?property_ids=uuid,uuid
  - Are Redis-cached for 5 minutes
  - Query EXISTING model fields — no new tables required
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta, date as date_cls
from typing import Optional, List
import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_module, require_flag
from app.models.user import User
from app.models.inquiry import Inquiry, InquiryStage
from app.models.guest import Guest
from app.models.property import Stay, Property, BlockedDate, RatePlan, SeasonalRate
from app.core.cache import cache_key, get_cached, set_cached

from app.schemas.analytics import (
    OccupancyForecastStats, PropertyOccupancyForecast, OccupancyForecastPoint,
    RevenueForecastStats, RevenueForecastPoint,
    PricingForecastStats, PricingSuggestionRow,
    ChurnStats, ChurnBucket, ChurnRiskGuest,
    CohortStats, CohortRow,
)

router = APIRouter(prefix="/analytics/forecasting", tags=["analytics"])


# ─── Shared helpers ────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_pct(n: float, d: float) -> float:
    return round(n / d * 100, 1) if d else 0.0


def _prop_ids_list(property_ids: Optional[str]) -> Optional[List[str]]:
    if not property_ids:
        return None
    return [p.strip() for p in property_ids.split(",") if p.strip()]


def _occupied_nights_for_date(stays: list, target_date: date_cls) -> int:
    """Count how many stays cover target_date. `stays` tuples come from
    Stay.check_in/check_out -- real DATE columns since migration 071, no
    fromisoformat() needed (or possible: these are already date objects)."""
    count = 0
    for ci, co in stays:
        try:
            if ci <= target_date < co:
                count += 1
        except Exception:
            pass
    return count


def _is_blocked(blocked: list, target_date: date_cls) -> bool:
    for bf_str, bt_str in blocked:
        try:
            bf = date_cls.fromisoformat(bf_str)
            bt = date_cls.fromisoformat(bt_str)
            if bf <= target_date < bt:
                return True
        except Exception:
            pass
    return False


def _linear_trend(values: list[float]) -> float:
    """Return slope per step using simple linear regression."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    num = sum((xs[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n))
    return num / den if den else 0.0


# ─── GET /analytics/forecasting/occupancy ────────────────────────────────────

@router.get("/occupancy", response_model=OccupancyForecastStats)
def occupancy_forecast(
    range_days: int = Query(default=30, ge=7, le=90),
    property_ids: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("channel_manager", "analytics")),
):
    tid = current_user.tenant_id
    prop_ids = _prop_ids_list(property_ids)
    ck = cache_key("occ_forecast", tid, range_days=range_days, pids=property_ids or "all")
    if (cached := get_cached(ck)) is not None:
        return OccupancyForecastStats(**cached)

    now = _now()
    today = now.date()
    history_start = today - timedelta(days=90)  # 90d actuals for trend
    forecast_end = today + timedelta(days=range_days)

    props_q = db.query(Property).filter(Property.tenant_id == tid, Property.is_active == True)
    if prop_ids:
        props_q = props_q.filter(Property.id.in_(prop_ids))
    props = props_q.all()
    all_pids = [str(p.id) for p in props]

    # Batch-fetch stays and blocked dates for every property in one query each
    # instead of issuing 2 queries per property (was 2×N).
    stays_by_prop: dict[str, list[tuple]] = {pid: [] for pid in all_pids}
    if all_pids:
        stays_raw_all = db.query(Stay.property_id, Stay.check_in, Stay.check_out).filter(
            Stay.tenant_id == tid,
            Stay.property_id.in_(all_pids),
            Stay.status.in_(["confirmed", "checked_in", "checked_out"]),
            Stay.check_in < forecast_end.isoformat(),
            Stay.check_out > history_start.isoformat(),
        ).all()
        for r in stays_raw_all:
            stays_by_prop.setdefault(str(r.property_id), []).append((r.check_in, r.check_out))

    blocked_by_prop: dict[str, list[tuple]] = {pid: [] for pid in all_pids}
    if all_pids:
        blocked_raw_all = db.query(BlockedDate.property_id, BlockedDate.blocked_from, BlockedDate.blocked_to).filter(
            BlockedDate.tenant_id == tid,
            BlockedDate.property_id.in_(all_pids),
            BlockedDate.blocked_from < forecast_end.isoformat(),
            BlockedDate.blocked_to > history_start.isoformat(),
        ).all()
        for r in blocked_raw_all:
            blocked_by_prop.setdefault(str(r.property_id), []).append((r.blocked_from, r.blocked_to))

    prop_forecasts: list[PropertyOccupancyForecast] = []

    for prop in props:
        pid = str(prop.id)
        stays = stays_by_prop.get(pid, [])
        blocked = blocked_by_prop.get(pid, [])

        # Build 90d historical occupancy series (1 room = 1 property unit)
        hist_pcts: list[float] = []
        for i in range(90):
            d = history_start + timedelta(days=i)
            occ = _occupied_nights_for_date(stays, d)
            hist_pcts.append(min(100.0, occ * 100))  # binary: 0 or 100 for single-unit

        slope = _linear_trend(hist_pcts)
        last_30_avg = sum(hist_pcts[-30:]) / 30 if hist_pcts else 0.0

        # Build series: last 30d actual + next range_days forecast
        series: list[OccupancyForecastPoint] = []

        for i in range(30):
            d = today - timedelta(days=30 - i)
            occ = _occupied_nights_for_date(stays, d)
            pct = min(100.0, occ * 100.0)
            series.append(OccupancyForecastPoint(
                date=d.isoformat(),
                actual_pct=round(pct, 1),
                is_blocked=_is_blocked(blocked, d),
            ))

        # Future forecast: trend extrapolation clamped 0–100
        forecast_pcts: list[float] = []
        for i in range(range_days):
            d = today + timedelta(days=i)
            if _is_blocked(blocked, d):
                pct = 0.0
            else:
                # Already confirmed stays count as actual
                occ = _occupied_nights_for_date(stays, d)
                if occ > 0:
                    pct = min(100.0, occ * 100.0)
                else:
                    # Trend projection from last known
                    raw = last_30_avg + slope * (30 + i)
                    pct = max(0.0, min(100.0, round(raw, 1)))
            forecast_pcts.append(pct)
            series.append(OccupancyForecastPoint(
                date=d.isoformat(),
                forecast_pct=round(pct, 1),
                is_blocked=_is_blocked(blocked, d),
            ))

        current_occ = last_30_avg
        forecast_avg = sum(forecast_pcts) / len(forecast_pcts) if forecast_pcts else 0.0
        trend = "up" if forecast_avg > current_occ + 2 else ("down" if forecast_avg < current_occ - 2 else "flat")

        prop_forecasts.append(PropertyOccupancyForecast(
            property_id=pid,
            property_name=prop.name,
            current_occ_pct=round(current_occ, 1),
            forecast_30d_pct=round(forecast_avg, 1),
            trend=trend,
            series=series,
        ))

    # Portfolio-level aggregates
    portfolio_current = (
        sum(p.current_occ_pct for p in prop_forecasts) / len(prop_forecasts)
        if prop_forecasts else 0.0
    )
    portfolio_forecast = (
        sum(p.forecast_30d_pct for p in prop_forecasts) / len(prop_forecasts)
        if prop_forecasts else 0.0
    )

    # Highest/lowest demand date across portfolio
    if prop_forecasts:
        date_demand: dict[str, float] = defaultdict(float)
        for pf in prop_forecasts:
            for pt in pf.series:
                if pt.forecast_pct is not None:
                    date_demand[pt.date] += pt.forecast_pct
        if date_demand:
            highest_d = max(date_demand, key=date_demand.__getitem__)
            lowest_d = min(date_demand, key=date_demand.__getitem__)
        else:
            highest_d = lowest_d = None
    else:
        highest_d = lowest_d = None

    result = OccupancyForecastStats(
        portfolio_current_occ=round(portfolio_current, 1),
        portfolio_forecast_30d=round(portfolio_forecast, 1),
        highest_demand_date=highest_d,
        lowest_demand_date=lowest_d,
        properties=prop_forecasts,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/forecasting/revenue ──────────────────────────────────────

@router.get("/revenue", response_model=RevenueForecastStats)
def revenue_forecast(
    property_ids: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("channel_manager", "analytics")),
):
    tid = current_user.tenant_id
    prop_ids = _prop_ids_list(property_ids)
    ck = cache_key("rev_forecast", tid, pids=property_ids or "all")
    if (cached := get_cached(ck)) is not None:
        return RevenueForecastStats(**cached)

    now = _now()
    today = now.date()

    # Fetch all stays from last 12 months
    year_start = (today.replace(day=1) - timedelta(days=365)).replace(day=1)
    stays_q = db.query(
        Stay.check_in, Stay.check_out, Stay.total_amount, Stay.status, Stay.created_at,
    ).filter(
        Stay.tenant_id == tid,
        Stay.status.in_(["confirmed", "checked_in", "checked_out"]),
        Stay.check_in >= year_start.isoformat(),
    )
    if prop_ids:
        stays_q = stays_q.filter(Stay.property_id.in_(prop_ids))
    stays = stays_q.all()

    # Bucket revenue by month of check_in
    monthly: dict[str, float] = defaultdict(float)
    for s in stays:
        try:
            # migration 071: check_in is a real DATE column now, already a
            # datetime.date -- no fromisoformat() needed (or possible).
            month_key = s.check_in.strftime("%Y-%m")
            monthly[month_key] += float(s.total_amount or 0)
        except Exception:
            pass

    current_month = today.strftime("%Y-%m")
    mtd_actual = monthly.get(current_month, 0.0)

    # Days elapsed and remaining in month
    day_of_month = today.day
    import calendar as cal_mod
    days_in_month = cal_mod.monthrange(today.year, today.month)[1]
    days_remaining = days_in_month - day_of_month

    # Daily run rate from last 90 days (excluding current month)
    past_90_revenue = 0.0
    for s in stays:
        try:
            if s.check_in < today.replace(day=1):
                past_90_revenue += float(s.total_amount or 0)
        except Exception:
            pass
    daily_rate = past_90_revenue / 90 if past_90_revenue > 0 else 0.0

    full_month_forecast = round(mtd_actual + daily_rate * days_remaining, 2)

    # Build 12-month series (actuals for past, forecast for future/current)
    series: list[RevenueForecastPoint] = []
    for i in range(12):
        d = year_start + timedelta(days=i * 30)
        mk = d.strftime("%Y-%m")
        actual_v = monthly.get(mk)
        is_future = mk >= current_month
        if is_future:
            fc = full_month_forecast if mk == current_month else round(daily_rate * days_in_month, 2)
            variance = fc * 0.12  # ±12% confidence band
            series.append(RevenueForecastPoint(
                month=mk,
                forecast=fc,
                lower_bound=round(max(0, fc - variance), 2),
                upper_bound=round(fc + variance, 2),
            ))
        else:
            series.append(RevenueForecastPoint(month=mk, actual=round(actual_v or 0.0, 2)))

    ytd_start = today.replace(month=1, day=1)
    ytd_actual = sum(
        float(s.total_amount or 0) for s in stays
        if s.check_in and s.check_in >= ytd_start
    )
    ytd_forecast = ytd_actual + daily_rate * days_remaining

    best_month = max(monthly, key=monthly.__getitem__) if monthly else None
    best_rev = monthly[best_month] if best_month else 0.0

    result = RevenueForecastStats(
        mtd_actual=round(mtd_actual, 2),
        mtd_forecast=round(full_month_forecast, 2),
        full_month_forecast=round(full_month_forecast, 2),
        ytd_actual=round(ytd_actual, 2),
        ytd_forecast=round(ytd_forecast, 2),
        best_month=best_month,
        best_month_revenue=round(best_rev, 2),
        series=series,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/forecasting/pricing ──────────────────────────────────────

@router.get("/pricing", response_model=PricingForecastStats)
def pricing_suggestions(
    property_ids: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    _ctx=Depends(require_module("channel_manager", "analytics")),
    db: Session = Depends(get_db),
):
    tid = current_user.tenant_id
    prop_ids = _prop_ids_list(property_ids)
    ck = cache_key("pricing_forecast", tid, pids=property_ids or "all")
    if (cached := get_cached(ck)) is not None:
        return PricingForecastStats(**cached)

    now = _now()
    today = now.date()
    month_start = today.replace(day=1)
    month_end = today + timedelta(days=30)

    props_q = db.query(Property).filter(Property.tenant_id == tid, Property.is_active == True)
    if prop_ids:
        props_q = props_q.filter(Property.id.in_(prop_ids))
    props = props_q.all()
    all_pids = [str(p.id) for p in props]

    # Batch-fetch upcoming stays for every property in one query (was N queries).
    stays_by_prop: dict[str, list] = {pid: [] for pid in all_pids}
    if all_pids:
        upcoming_stays_all = db.query(Stay.property_id, Stay.check_in, Stay.check_out).filter(
            Stay.tenant_id == tid,
            Stay.property_id.in_(all_pids),
            Stay.status.in_(["confirmed", "checked_in"]),
            Stay.check_in < month_end.isoformat(),
            Stay.check_out > today.isoformat(),
        ).all()
        for s in upcoming_stays_all:
            stays_by_prop.setdefault(str(s.property_id), []).append(s)

    suggestions: list[PricingSuggestionRow] = []
    total_uplift = 0.0
    up_count = 0
    down_count = 0

    for prop in props:
        pid = str(prop.id)

        # Base price from active rate plan or property default
        rate = db.query(RatePlan).filter(
            RatePlan.tenant_id == tid,
            RatePlan.property_id == pid,
            RatePlan.is_active == True,
        ).first()
        base_price = float(rate.base_price_per_night if rate else (prop.price_per_day or 0))
        if base_price <= 0:
            continue

        # Check seasonal rate override for today
        seasonal = db.query(SeasonalRate).filter(
            SeasonalRate.tenant_id == tid,
            SeasonalRate.property_id == pid,
            SeasonalRate.is_active == True,
            SeasonalRate.date_from <= today.isoformat(),
            SeasonalRate.date_to >= today.isoformat(),
        ).order_by(SeasonalRate.priority.desc()).first()
        if seasonal:
            base_price = float(seasonal.price_per_night)

        # Occupancy in next 30 days
        upcoming_stays = stays_by_prop.get(pid, [])

        booked_nights = 0
        for s in upcoming_stays:
            try:
                ci = max(s.check_in, today)
                co = min(s.check_out, month_end)
                booked_nights += max(0, (co - ci).days)
            except Exception:
                pass

        occ_pct = min(100.0, booked_nights / 30 * 100)

        # Pricing logic
        if occ_pct >= 80:
            delta = 0.15
            reason = f"High demand — {occ_pct:.0f}% occupied next 30d"
            confidence = "high"
        elif occ_pct >= 60:
            delta = 0.08
            reason = f"Solid occupancy — {occ_pct:.0f}% next 30d"
            confidence = "medium"
        elif occ_pct >= 40:
            delta = 0.0
            reason = f"Moderate occupancy — hold rate ({occ_pct:.0f}%)"
            confidence = "medium"
        elif occ_pct >= 20:
            delta = -0.08
            reason = f"Low demand — {occ_pct:.0f}% next 30d, suggest discount"
            confidence = "medium"
        else:
            delta = -0.15
            reason = f"Very low occupancy ({occ_pct:.0f}%) — aggressive discount advised"
            confidence = "low"

        suggested = round(base_price * (1 + delta))
        delta_pct = round(delta * 100, 1)

        suggestions.append(PricingSuggestionRow(
            property_id=pid,
            property_name=prop.name,
            current_price=round(base_price, 2),
            suggested_price=suggested,
            delta_pct=delta_pct,
            reason=reason,
            occupancy_pct=round(occ_pct, 1),
            confidence=confidence,
        ))

        total_uplift += delta_pct
        if delta > 0:
            up_count += 1
        elif delta < 0:
            down_count += 1

    avg_uplift = round(total_uplift / len(suggestions), 1) if suggestions else 0.0
    result = PricingForecastStats(
        avg_suggested_uplift_pct=avg_uplift,
        properties_suggesting_increase=up_count,
        properties_suggesting_decrease=down_count,
        suggestions=sorted(suggestions, key=lambda x: -x.delta_pct),
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/forecasting/churn ────────────────────────────────────────

@router.get("/churn", response_model=ChurnStats)
def churn_risk(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("channel_manager", "analytics")),
):
    tid = current_user.tenant_id
    ck = cache_key("churn_risk", tid)
    if (cached := get_cached(ck)) is not None:
        return ChurnStats(**cached)

    now = _now()
    today = now.date()

    # Guests who have stayed at least once and have no open inquiry
    open_inquiry_guest_ids = {
        str(r.guest_id)
        for r in db.query(Inquiry.guest_id).filter(
            Inquiry.tenant_id == tid,
            Inquiry.stage.notin_(["lost", "booked"]),
        ).all()
        if r.guest_id
    }

    guests = db.query(Guest).filter(
        Guest.tenant_id == tid,
        Guest.total_stays >= 1,
        Guest.is_deleted == False if hasattr(Guest, "is_deleted") else True,
    ).all()

    at_risk: list[ChurnRiskGuest] = []
    for g in guests:
        if str(g.id) in open_inquiry_guest_ids:
            continue

        last_contact_str = g.last_contact_at
        if not last_contact_str:
            continue

        try:
            lc = date_cls.fromisoformat(last_contact_str[:10])
            days_since = (today - lc).days
        except Exception:
            continue

        if days_since < 45:
            continue  # Not at risk yet

        # Risk score: 0–100
        score = min(100, int(days_since / 2) + (20 if g.total_stays >= 3 else 0))
        risk_label = "high" if score >= 70 else ("medium" if score >= 50 else "low")

        at_risk.append(ChurnRiskGuest(
            guest_id=str(g.id),
            name=g.name or "Unknown",
            phone=g.phone,
            total_stays=g.total_stays or 0,
            lifetime_value=float(g.lifetime_value or 0),
            days_since_contact=days_since,
            risk_score=score,
            risk_label=risk_label,
        ))

    at_risk.sort(key=lambda x: -x.risk_score)

    # Bucket counts
    b30_60 = [g for g in at_risk if 45 <= g.days_since_contact < 60]
    b60_90 = [g for g in at_risk if 60 <= g.days_since_contact < 90]
    b90p   = [g for g in at_risk if g.days_since_contact >= 90]

    def _avg_ltv(lst):
        return round(sum(g.lifetime_value for g in lst) / len(lst), 2) if lst else 0.0

    buckets = [
        ChurnBucket(bucket="45-60d", count=len(b30_60), avg_ltv=_avg_ltv(b30_60)),
        ChurnBucket(bucket="60-90d", count=len(b60_90), avg_ltv=_avg_ltv(b60_90)),
        ChurnBucket(bucket="90d+",   count=len(b90p),   avg_ltv=_avg_ltv(b90p)),
    ]

    high_risk = [g for g in at_risk if g.risk_label == "high"]
    rev_at_risk = sum(g.lifetime_value * 0.3 for g in at_risk)  # 30% of LTV as expected revenue
    avg_days = round(sum(g.days_since_contact for g in at_risk) / len(at_risk), 1) if at_risk else 0.0

    result = ChurnStats(
        total_at_risk=len(at_risk),
        high_risk_count=len(high_risk),
        medium_risk_count=len([g for g in at_risk if g.risk_label == "medium"]),
        revenue_at_risk=round(rev_at_risk, 2),
        avg_days_since_contact=avg_days,
        buckets=buckets,
        at_risk_guests=at_risk[:50],  # cap at 50 for response size
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/forecasting/cohorts ──────────────────────────────────────

@router.get("/cohorts", response_model=CohortStats)
def guest_cohorts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("channel_manager", "analytics")),
):
    tid = current_user.tenant_id
    ck = cache_key("cohorts", tid)
    if (cached := get_cached(ck)) is not None:
        return CohortStats(**cached)

    guests = db.query(Guest).filter(
        Guest.tenant_id == tid,
        Guest.is_sample == False,
    ).all()

    VIP_TIERS = {"silver", "gold", "platinum"}

    # Bucket guests by acquisition quarter (created_at)
    cohort_data: dict[str, list] = defaultdict(list)
    for g in guests:
        try:
            created_str = str(g.created_at)[:10] if g.created_at else None
            if not created_str:
                continue
            d = date_cls.fromisoformat(created_str)
            q = (d.month - 1) // 3 + 1
            cohort_key = f"Q{q} {d.year}"
            cohort_data[cohort_key].append(g)
        except Exception:
            pass

    cohort_rows: list[CohortRow] = []
    for cohort_key in sorted(cohort_data.keys()):
        gs = cohort_data[cohort_key]
        n = len(gs)
        returned = [g for g in gs if (g.total_stays or 0) > 1]
        avg_stays = round(sum(g.total_stays or 0 for g in gs) / n, 1)
        avg_ltv = round(sum(float(g.lifetime_value or 0) for g in gs) / n, 2)
        vip_count = sum(1 for g in gs if g.vip_tier and g.vip_tier.lower() in VIP_TIERS)
        cohort_rows.append(CohortRow(
            cohort=cohort_key,
            guests=n,
            returned_pct=_safe_pct(len(returned), n),
            avg_stays=avg_stays,
            avg_ltv=avg_ltv,
            vip_pct=_safe_pct(vip_count, n),
        ))

    total = len(guests)
    total_returned = sum(1 for g in guests if (g.total_stays or 0) > 1)
    overall_ltv = sum(float(g.lifetime_value or 0) for g in guests) / total if total else 0.0
    vip_total = sum(1 for g in guests if g.vip_tier and g.vip_tier.lower() in VIP_TIERS)

    result = CohortStats(
        total_guests=total,
        repeat_rate=_safe_pct(total_returned, total),
        avg_ltv=round(overall_ltv, 2),
        vip_rate=_safe_pct(vip_total, total),
        cohorts=cohort_rows[-8:],  # last 8 quarters
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result
