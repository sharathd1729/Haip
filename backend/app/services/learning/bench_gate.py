"""Bench gate: before an experiment may run, the agent bench must pass with the TREATMENT applied.

What runs: the deterministic layer of the agent bench (services/agent_bench.py, scripted model, the REAL reply pipeline) on
the scenarios of the change's area, plus one scripted case for the changed behaviour (the new wording / rule must reach the
prompt). The treatment is applied to the bench world exactly as the resolver would for a treatment conversation: the treated
sales playbook and the treated learning_base controls. Any failed guarantee = ``bench_failed``; the experiment never runs.

Isolation: a throwaway in-memory SQLite database (like scripts/agent_bench.py), every ``SessionLocal`` reference in loaded app
modules pointed at it for the duration, the LLM router replaced by the scripted model, every send / push captured by the bench
itself. Run it only in a prefork Celery worker (one task per process): the patches are process-wide while it runs.
"""
from __future__ import annotations

import sys
from contextlib import ExitStack
from typing import Callable, Optional
from unittest.mock import patch

import structlog

log = structlog.get_logger()

AREA_TAGS = {
    "replies": {"faq", "playbook", "human", "injection", "loop", "language", "complaint", "guard"},
    "prices": {"quote", "grounded", "discount", "peak", "b2b", "price-guard", "kit"},
    "routes": {"custom-route", "faq", "quote"},
}
MAX_SCENARIOS = 25


def scenarios_for(area: str, all_scenarios: list[dict]) -> list[dict]:
    tags = AREA_TAGS.get(area, set())
    picked = [s for s in all_scenarios if tags & set(s.get("tags", []))]
    return picked[:MAX_SCENARIOS]


def changed_behaviour_case(exp) -> Optional[dict]:
    """A scripted case proving the treatment reaches the prompt."""
    d = exp.diff or {}
    want = None
    if exp.change_type == "playbook_wording" and isinstance(d.get("value"), str) and d["value"].strip():
        want = d["value"].strip()[:60]
    elif exp.change_type == "early_package_share":
        from app.services.learning.catalogue import EARLY_RULE
        want = EARLY_RULE[:60]
    elif exp.change_type == "kit_before_discount":
        want = "Before any talk of a discount"
    if not want:
        return None
    return {"id": f"learning-{exp.change_type}", "tags": ["learning"], "guest": "Hi, tell me about your caravan trips",
            "classify": {"intent": "general"}, "reply": {"text": "Happy to help! Where would you like to go?"},
            "expect": {"prompt_contains": [want]}}


def _treated_config(db, tenant, exp) -> dict:
    from app.services.learning import catalogue
    from app.services.learning import settings as ls
    cfg: dict = {"learning_base": ls.base(tenant)}
    value = catalogue.after_value(db, tenant, exp.change_type, exp.diff or {})
    control = catalogue.TYPES[exp.change_type].control
    if control == "sales_playbook":
        cfg["sales_playbook"] = value
    else:
        key = {"price_disclosure": "price_disclosure_packages", "consult_threshold": "consult_price_above",
               "route_map": "route_map", "followup_timing": "followup_first_hours"}[control]
        cfg["learning_base"] = {**cfg["learning_base"], key: value}
    return cfg


def _isolated_runner(treated: dict, scenarios: list[dict]) -> list[dict]:
    """Run scenarios in a throwaway database. Returns [{id, passed, failed: [checks]}]."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.models  # noqa: F401 -- every table, so create_all builds the whole schema
    from app.core import database
    from app.core.database import Base
    from app.services import agent_bench
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(bind=engine, autoflush=False)
    real = database.SessionLocal
    results = []
    with ExitStack() as stack:
        for name, mod in list(sys.modules.items()):
            if name.startswith("app.") and getattr(mod, "SessionLocal", None) is real:
                stack.enter_context(patch.object(mod, "SessionLocal", maker))

        def _no_llm(*_a, **_k):
            raise RuntimeError("the bench gate never calls a real model")
        stack.enter_context(patch("app.adapters.llm.get_llm", _no_llm))
        bdb = maker()
        try:
            world = agent_bench.build_world(bdb, playbook=False)
            world.tenant.brand_config = {**(world.tenant.brand_config or {}), **treated}
            bdb.commit()
            results = run_with(bdb, world, scenarios)
        finally:
            bdb.close()
    engine.dispose()
    return results


def run_with(db, world, scenarios: list[dict]) -> list[dict]:
    """Run scenarios on an already-built world whose brand_config carries the treatment."""
    from app.services import agent_bench
    keep = {k: v for k, v in (world.tenant.brand_config or {}).items() if k in ("sales_playbook", "learning_base")}
    out = []
    for s in scenarios:
        world.tenant.brand_config = {**keep}
        db.commit()
        try:
            res = agent_bench.run_scenario(db, world, s)
            checks = agent_bench.grade(s, res)
            failed = [c for c in checks if not c["ok"]]
        except Exception as exc:  # noqa: BLE001 -- a crash is a failure, never a pass
            failed = [{"check": "crashed", "ok": False, "detail": f"{type(exc).__name__}: {exc}"[:200]}]
        out.append({"id": s["id"], "passed": not failed, "failed": failed[:3]})
    return out


def check(db, tenant, exp, *, runner: Optional[Callable[[dict, list[dict]], list[dict]]] = None) -> dict:
    from app.services import agent_bench
    from app.services.learning import catalogue
    scenarios = scenarios_for(catalogue.TYPES[exp.change_type].area, agent_bench.load_scenarios())
    extra = changed_behaviour_case(exp)
    if extra:
        scenarios.append(extra)
    treated = _treated_config(db, tenant, exp)
    try:
        results = (runner or _isolated_runner)(treated, scenarios)
    except Exception as exc:  # noqa: BLE001 -- the gate could not run: the experiment does not start
        log.warning("learning_bench_gate_error", experiment_id=exp.id, error=type(exc).__name__)
        return {"passed": False, "ran": 0, "failed": [{"id": "gate", "failed": [{"check": "gate_error", "detail": type(exc).__name__}]}]}
    failed = [r for r in results if not r["passed"]]
    return {"passed": bool(results) and not failed, "ran": len(results), "failed": failed[:10],
            "scenarios": [r["id"] for r in results]}
