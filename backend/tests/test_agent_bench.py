"""Agent test bench, deterministic layer (CI): every scenario in tests/fixtures/agent_bench/rathaa.json through the REAL reply
pipeline with SCRIPTED model outputs (app/services/agent_bench.py). What is pinned here are the code-side guarantees, whatever a
model says: the triggers fire, no unpublished / invented / below-floor price is sent, one holding reply, a consult opens, no
payment link or booking without approval. The live layer (real router, pass^k) is scripts/agent_bench.py --live, never in CI.
"""
import pytest

from app.services import agent_bench

SCENARIOS = agent_bench.load_scenarios()


def test_the_bench_has_the_agreed_coverage():
    ids = {s["id"] for s in SCENARIOS}
    assert len(SCENARIOS) >= 50 and len(ids) == len(SCENARIOS)                  # ids are unique
    tags = {t for s in SCENARIOS for t in s.get("tags", [])}
    for needed in ("quote", "grounded", "peak", "capacity", "b2b", "discount", "complaint", "human", "language",
                   "custom-route", "cancellation", "hours", "loop", "injection", "policy"):
        assert needed in tags, needed
    for s in SCENARIOS:
        assert s.get("expect"), s["id"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scenario(db, scenario):
    world = agent_bench.build_world(db)
    out = agent_bench.run_scenario(db, world, scenario)
    checks = agent_bench.grade(scenario, out)
    failed = [c for c in checks if not c["ok"]]
    assert not failed, f"{scenario['id']}: {failed}\ndraft={out['draft']!r}\nreasons={out['reasons']}\nneeds_human={out['needs_human']}"
