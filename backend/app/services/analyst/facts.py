"""Build the FACTS for one report: every number the brief may use, computed in code (metrics_funnel, metrics_ops), compared
(findings) and checked (health). The model only ever sees this JSON; the number-grounding check (grounding.py) reads it too.

Keys starting with "_" are working data (record ids for evidence, raw amounts) and are removed before the facts are stored.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.services.analyst import findings, health, metrics_funnel, metrics_ops
from app.services.analyst.periods import Window, windows

KIND_LABELS = {"daily_pulse": "Daily pulse", "weekly_brief": "Weekly brief", "monthly_review": "Monthly review"}


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _period(db: Session, tenant, w: Window, today: date, *, full: bool) -> dict:
    lo, hi = w.bounds()
    j = metrics_funnel.journey(db, tenant.id, w.d_from, w.d_to, lo, hi)
    team = metrics_ops.team(db, tenant.id, lo, hi, j["_workflow_agents"], j["segments"]["agent"])
    out = {"window": w.out(), "journey": j, "team": team}
    if full:
        out["ai"] = metrics_ops.ai(db, tenant, hi, w.days)
        out["demand"] = metrics_ops.demand(db, tenant.id, lo, hi, today, j["quotes"]["by_package"])
        out["pricing"] = metrics_ops.pricing(db, tenant.id, lo, hi, j["quotes"], j["_quote_amounts"])
    return out


def build(db: Session, tenant, kind: str, today: date, *, lessons: Optional[list[dict]] = None,
          last_followup: Optional[dict] = None) -> dict:
    cur_w, prev_w, base_w = windows(kind, today)
    cur = _period(db, tenant, cur_w, today, full=True)
    prev = _period(db, tenant, prev_w, today, full=False)
    base = _period(db, tenant, base_w, today, full=False)
    c_core = findings.core(cur["journey"], cur["team"])
    p_core = findings.core(prev["journey"], prev["team"])
    b_core = findings.core(base["journey"], base["team"])
    detected = findings.detect(c_core, p_core, b_core, cur_days=cur_w.days, prev_days=prev_w.days, base_days=base_w.days)
    lo, hi = cur_w.bounds()
    facts = {
        "kind": kind, "kind_label": KIND_LABELS[kind], "brand": tenant.brand_name or tenant.name,
        "period": cur_w.out(), "previous_period": prev_w.out(), "baseline_period": base_w.out(),
        "journey": cur["journey"], "team": cur["team"], "ai": cur["ai"], "demand": cur["demand"], "pricing": cur["pricing"],
        "core": {"current": _core_out(c_core), "previous": _core_out(p_core), "baseline": _core_out(b_core)},
        "findings": detected["findings"][:10], "watch": detected["watch"], "steady": [f["metric"] for f in detected["steady"]],
        "lessons": lessons or [],
        "last_week_followup": last_followup or {},
    }
    facts["health"] = health.build(db, tenant.id, lo, hi, facts)
    return _strip(facts)


def _core_out(c: dict) -> dict:
    out = {}
    for k, v in c.items():
        if isinstance(v, tuple):
            x, n = v
            out[k] = {"x": x, "n": n, "rate": round(x / n, 4) if n else None}
        else:
            out[k] = v
    return out
