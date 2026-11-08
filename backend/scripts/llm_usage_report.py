"""Read-only: per AI task, how many model calls, how fast, how often they failed or fell back, tokens and cost. Writes NOTHING.

Reads usage_events kinds llm_call / embedding_call / vision_call (adapters/llm/metered.py) for one tenant over the last N
days; batch results show as "<task> (batch)", and a per-kind block follows the tasks. --all-tenants prints one TOTAL line
per active tenant instead. Cost per property per month = cost / active properties (the "Unassigned" placeholder left out)
x 30 / days. Rupees at services/llm_usage_report.DEFAULT_USD_INR (Rs 88/USD) unless --usd-inr is given.
Also (one tenant): guest message -> concierge draft stored, p50 / p95 (services/llm_usage_report.guest_to_draft_ms).

Usage (inside the API container):
    docker compose -f docker-compose.prod.yml exec api python3 scripts/llm_usage_report.py --tenant-slug rathaa --days 7
    ... --usd-inr 84.2 --json
    ... --all-tenants --days 30
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.llm_usage_report import (  # noqa: E402
    DEFAULT_USD_INR, guest_to_draft_ms, load, reply_latency, summarise, tenant_totals,
)


def _ms(v):
    return "-" if v is None else f"{v / 1000:.1f}s"


def _table(blocks: list[dict], first: str, inr: bool) -> list[str]:
    head = f"{first:<28}{'calls':>7}{'tries':>7}{'p50':>8}{'p95':>8}{'err%':>7}{'fb%':>6}{'tokens':>11}{'cost $':>11}"
    head += f"{'$/prop/mo':>11}" + (f"{'cost Rs':>11}{'Rs/prop/mo':>12}" if inr else "")
    lines = [head]
    for b in blocks:
        if b["task"] == "TOTAL":
            lines.append("-" * len(head))
        per = b["cost_usd_per_property_month"]
        line = (
            f"{b['task'][:27]:<28}{b['calls']:>7}{b.get('attempts', b['calls']):>7}{_ms(b['p50_ms']):>8}"
            f"{_ms(b['p95_ms']):>8}{b['error_pct']:>7}{b['fallback_pct']:>6}{b['tokens']:>11}{b['cost_usd']:>11.4f}"
            f"{'-' if per is None else f'{per:.4f}':>11}"
        )
        if inr:
            per_inr = b["cost_inr_per_property_month"]
            line += f"{b['cost_inr']:>11.2f}{'-' if per_inr is None else f'{per_inr:.2f}':>12}"
        if b["cost_unknown_calls"]:
            line += f"  ({b['cost_unknown_calls']} calls with unknown cost)"
        lines.append(line)
    return lines


def render(slug: str, data: dict) -> str:
    inr = data["usd_inr"] is not None
    lines = [f"Model usage for '{slug}', last {data['days']} days, {data['properties']} active properties"
             + (f", Rs {data['usd_inr']}/USD" if inr else ""), ""]
    lines += _table(data["tasks"] + ([data["total"]] if data["total"] else []), "task", inr)
    if not data["tasks"]:
        lines.append("(no usage rows in this window)")
    if data.get("kinds"):
        lines += ["", *_table(data["kinds"], "kind", inr)]
    g = data.get("guest_to_draft")
    if g is not None:
        lines += ["", f"Guest message to draft stored: {g['drafts']} drafts, p50 {_ms(g['p50_ms'])}, p95 {_ms(g['p95_ms'])}"]
    return "\n".join(lines)


def render_tenants(rows: list[dict], days: int, usd_inr: float | None) -> str:
    lines = [f"Model usage per tenant, last {days} days" + (f", Rs {usd_inr}/USD" if usd_inr else ""), ""]
    lines += _table(rows, "tenant", usd_inr is not None) if rows else ["(no usage rows in this window)"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--tenant-slug")
    who.add_argument("--all-tenants", action="store_true", help="one TOTAL line per active tenant")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--usd-inr", type=float, default=DEFAULT_USD_INR,
                    help=f"USD to INR rate for the rupee columns (default {DEFAULT_USD_INR})")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.days < 1:
        ap.error("--days must be at least 1")
    db = SessionLocal()
    try:
        if args.all_tenants:
            rows = tenant_totals(db, args.days, args.usd_inr)
            print(json.dumps(rows, indent=2) if args.json else render_tenants(rows, args.days, args.usd_inr))
            return 0
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            print(f"No tenant with slug {args.tenant_slug!r}")
            return 1
        rows, properties = load(db, tenant.id, args.days)
        data = summarise(rows, args.days, properties, args.usd_inr)
        data["guest_to_draft"] = reply_latency(guest_to_draft_ms(db, tenant.id, args.days))
        print(json.dumps(data, indent=2) if args.json else render(args.tenant_slug, data))
        return 0
    finally:
        db.rollback()  # read-only: nothing to keep
        db.close()


if __name__ == "__main__":
    sys.exit(main())
