"""
Dynamic Pricing Service — smart rate engine for HAIP.

Applies configurable multipliers on top of the base seasonal rate:

  final_price = base_rate
    × lead_time_factor
    × weekend_factor (or weekday_factor)
    × occupancy_factor
    × duration_factor
    × demand_factor          (placeholder — set to 1.0 until ML is wired)

All factors are clamped to a [min, max] range so no single signal
can produce a pathological price.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import structlog

log = structlog.get_logger()


# ── Config defaults (can be overridden per tenant/property in future) ─────────

@dataclass
class PricingConfig:
    # Lead-time bands: (days_before_checkin, multiplier)
    lead_time_bands: list[tuple[int, float]] = field(default_factory=lambda: [
        (0,   1.35),   # same-day → +35%
        (3,   1.20),   # ≤ 3 days → +20%
        (7,   1.10),   # ≤ 7 days → +10%
        (14,  1.00),   # ≤ 14 days → base
        (30,  0.95),   # ≤ 30 days → -5% (early bird)
        (60,  0.90),   # ≤ 60 days → -10%
        (9999, 0.88),  # > 60 days → -12%
    ])

    # Weekend uplift (Fri/Sat/Sun check-in)
    weekend_multiplier: float = 1.12

    # Occupancy bands: (portfolio_occupancy_pct, multiplier)
    occupancy_bands: list[tuple[float, float]] = field(default_factory=lambda: [
        (95.0, 1.25),   # portfolio almost full → surge
        (85.0, 1.15),
        (70.0, 1.05),
        (50.0, 1.00),
        (30.0, 0.95),
        (0.0,  0.90),   # very low occupancy → discount
    ])

    # Duration discounts: (min_nights, multiplier)
    duration_bands: list[tuple[int, float]] = field(default_factory=lambda: [
        (14, 0.85),
        (7,  0.92),
        (5,  0.96),
        (3,  0.98),
        (1,  1.00),
    ])

    # Hard clamp on the aggregate multiplier
    min_total_multiplier: float = 0.70
    max_total_multiplier: float = 2.00


DEFAULT_CONFIG = PricingConfig()


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class DynamicPriceResult:
    base_rate: float
    final_rate: float            # per night
    total_price: float           # final_rate × nights
    nights: int

    lead_time_factor: float
    weekend_factor: float
    occupancy_factor: float
    duration_factor: float
    aggregate_multiplier: float

    insights: list[str]          # human-readable explanations
    suggested_floor: float       # don't go below this (base × 0.75)
    suggested_ceiling: float     # don't exceed this (base × 2.0)


# ── Core calculation ──────────────────────────────────────────────────────────

def _band_value(bands: list[tuple[Any, float]], key: float) -> float:
    """Return the multiplier for the first band whose threshold ≥ key."""
    for threshold, mult in sorted(bands, key=lambda x: x[0]):
        if key <= threshold:
            return mult
    return bands[-1][1]


def calculate_dynamic_price(
    base_rate_per_night: float,
    checkin: date,
    checkout: date,
    portfolio_occupancy_pct: float = 60.0,
    today: date | None = None,
    config: PricingConfig = DEFAULT_CONFIG,
) -> DynamicPriceResult:
    """
    Compute the dynamically priced rate for a given stay.

    Args:
        base_rate_per_night: The seasonal/base rate from the rate plan.
        checkin:             Guest check-in date.
        checkout:            Guest check-out date.
        portfolio_occupancy_pct: Current occupancy across tenant's portfolio
                             (default 60 if unknown).
        today:               Override 'today' for testability.
        config:              PricingConfig instance.

    Returns:
        DynamicPriceResult with final rate, factors, and insights.
    """
    today = today or date.today()
    nights = (checkout - checkin).days
    if nights <= 0:
        nights = 1

    base = float(base_rate_per_night)
    lead_days = (checkin - today).days

    # 1. Lead-time factor
    ltf = _band_value(config.lead_time_bands, max(0, lead_days))

    # 2. Weekend factor (Fri=4, Sat=5, Sun=6 in Python weekday)
    dow = checkin.weekday()
    wf = config.weekend_multiplier if dow in (4, 5, 6) else 1.0

    # 3. Occupancy factor
    of = _band_value(config.occupancy_bands, portfolio_occupancy_pct)

    # 4. Duration factor
    df = _band_value(config.duration_bands, nights)

    # Aggregate (clamp to configured range)
    agg = ltf * wf * of * df
    agg = max(config.min_total_multiplier, min(config.max_total_multiplier, agg))

    final_per_night = round(base * agg, -2)   # round to nearest 100
    total = final_per_night * nights

    # ── Insights ──────────────────────────────────────────────────────────────
    insights: list[str] = []

    if lead_days <= 0:
        insights.append("Same-day booking — last-minute premium applied (+35%)")
    elif lead_days <= 3:
        insights.append(f"Only {lead_days} days out — short lead-time premium (+20%)")
    elif lead_days <= 7:
        insights.append(f"{lead_days} days to check-in — modest urgency uplift (+10%)")
    elif lead_days >= 30:
        insights.append(f"Early booking ({lead_days} days out) — early-bird discount applied")

    if dow in (4, 5, 6):
        day_name = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][dow]
        insights.append(f"{day_name} check-in — weekend rate applies (+{round((wf-1)*100)}%)")

    if portfolio_occupancy_pct >= 85:
        insights.append(f"Portfolio {portfolio_occupancy_pct:.0f}% occupied — demand surge pricing")
    elif portfolio_occupancy_pct <= 30:
        insights.append(f"Low portfolio occupancy ({portfolio_occupancy_pct:.0f}%) — fill-rate discount")

    if nights >= 7:
        insights.append(f"{nights}-night stay — long-stay discount applied ({round((1-df)*100):.0f}% off)")
    elif nights >= 5:
        insights.append(f"{nights}-night stay — extended-stay discount applied")

    if not insights:
        insights.append("Base rate — no significant modifiers apply")

    floor   = round(base * 0.75, -2)
    ceiling = round(base * 2.0,  -2)

    log.info(
        "dynamic_price_calculated",
        base=base,
        final=final_per_night,
        agg=round(agg, 3),
        lead_days=lead_days,
        nights=nights,
        occupancy=portfolio_occupancy_pct,
    )

    return DynamicPriceResult(
        base_rate=base,
        final_rate=final_per_night,
        total_price=total,
        nights=nights,
        lead_time_factor=round(ltf, 3),
        weekend_factor=round(wf, 3),
        occupancy_factor=round(of, 3),
        duration_factor=round(df, 3),
        aggregate_multiplier=round(agg, 3),
        insights=insights,
        suggested_floor=floor,
        suggested_ceiling=ceiling,
    )
