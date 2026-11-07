"""scripts/llm_usage_report.py + services/llm_usage_report.py: read-only per-task LLM usage from usage_events kind=llm_call."""

import importlib.util
import os
import uuid
from datetime import UTC, datetime, timedelta

from app.models.property import Property
from app.models.tenant import Tenant
from app.models.usage_event import UsageEvent
from app.services.llm_usage_report import load, summarise

_SPEC = importlib.util.spec_from_file_location(
    "llm_usage_report_script", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "llm_usage_report.py")
)
script = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(script)


def _row(task, ms, ok=True, fallback=False, cost=0.001, units=100):
    return {
        "units": units,
        "meta": {"task": task, "latency_ms": ms, "ok": ok, "fallback_used": fallback, "cost_usd": cost},
    }


def test_summarise_per_task():
    rows = [_row("concierge_draft", ms) for ms in (1000, 2000, 3000, 4000)]
    rows += [_row("concierge_draft", 9000, ok=False, cost=None), _row("lead_summary", 500, fallback=True, cost=0.0)]
    data = summarise(rows, days=7, properties=2, usd_inr=84.0)
    c = data["tasks"][0]
    assert c["task"] == "concierge_draft" and c["calls"] == 5
    assert c["p50_ms"] == 3000 and c["p95_ms"] == 9000 and c["error_pct"] == 20.0 and c["fallback_pct"] == 0.0
    assert c["tokens"] == 500 and c["cost_usd"] == 0.004 and c["cost_unknown_calls"] == 1
    assert c["cost_usd_per_property_month"] == round(0.004 / 2 * 30 / 7, 6)
    assert c["cost_inr"] == round(0.004 * 84.0, 2)
    assert data["tasks"][1]["fallback_pct"] == 100.0 and data["total"]["calls"] == 6
    assert "cost_inr" not in summarise(rows, 7, 2)["tasks"][0]  # no rate given: no rupees, no built-in FX
    assert "concierge_draft" in script.render("rathaa", data)


def test_summarise_empty_and_no_properties():
    assert summarise([], 7, 0) == {"days": 7, "properties": 0, "usd_inr": None, "tasks": [], "total": None}
    assert summarise([_row("x", 1)], 7, 0)["tasks"][0]["cost_usd_per_property_month"] is None
    assert "no llm_call rows" in script.render("x", summarise([], 7, 0))


def test_load_reads_only_this_tenants_recent_llm_call_rows(db, tenant_and_user):
    tenant_id = tenant_and_user["tenant"].id
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.flush()
    now = datetime.now(UTC)
    db.add_all(
        [
            UsageEvent(
                tenant_id=tenant_id, module="concierge", kind="llm_call", units=10, meta={"task": "concierge_draft"}
            ),
            UsageEvent(
                tenant_id=tenant_id, module="marketing_studio", kind="llm_tokens", units=99
            ),  # older Studio rows: not read
            UsageEvent(
                tenant_id=tenant_id, module="concierge", kind="llm_call", units=7, created_at=now - timedelta(days=30)
            ),
            UsageEvent(
                tenant_id=other.id, module="concierge", kind="llm_call", units=5, meta={"task": "concierge_draft"}
            ),
            Property(tenant_id=tenant_id, name="Ratha 1", slug=f"r1-{uuid.uuid4().hex[:4]}", is_active=True),
            Property(
                tenant_id=tenant_id,
                name="Unassigned (vehicle not chosen yet)",
                slug=f"u-{uuid.uuid4().hex[:4]}",
                is_active=True,
            ),
            Property(tenant_id=other.id, name="Villa", slug=f"v-{uuid.uuid4().hex[:4]}", is_active=True),
        ]
    )
    db.flush()
    rows, properties = load(db, tenant_id, days=7, now=now + timedelta(seconds=1))
    assert [r["units"] for r in rows] == [10] and properties == 1
