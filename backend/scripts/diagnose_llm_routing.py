"""Read-only: which model answers this tenant's guests, and what would make it not Gemini?  Writes NOTHING, calls no provider.

Prints, for one tenant: the route (provider + model) of every concierge task, the Gemini retry of the NVIDIA tasks, the reply
timeout and attempts, the tenant's stored llm_provider_override (and that it is not applied), and whether GEMINI_API_KEY /
NVIDIA_API_KEY are set -- present / absent only, never the value.

Usage (inside the API container):
    docker compose -f docker-compose.prod.yml exec api python3 scripts/diagnose_llm_routing.py --tenant-slug rathaa
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.llm_routing_report import report  # noqa: E402


def render(slug: str, data: dict) -> str:
    lines = [f"LLM routing for tenant '{slug}'", ""]
    g = data["guest_reply"]
    lines.append(f"Guest replies (WhatsApp + Instagram): {g['provider']} {g['model']}, {g['attempts']} attempt(s) x {g['timeout_seconds']}s")
    lines.append(f"  on failure: {g['on_failure']}")
    if g["will_fail"]:
        lines.append("  WARNING: the reply route needs GEMINI_API_KEY and it is absent -- every guest gets the holding reply.")
    lines.append("")
    for t in data["tasks"]:
        fb = f", Gemini retry after {t['gemini_fallback_after_seconds']}s ({'active' if t['gemini_fallback_active'] else 'inactive: no GEMINI_API_KEY'})" \
            if t["gemini_fallback_after_seconds"] else ""
        lines.append(f"  {t['task']:<18} {t['provider']:<7} {t['model']}{fb}")
        lines.append(f"  {'':<18} {t['purpose']}")
    lines.append("")
    lines.append(f"Tenant llm_provider_override: {data['tenant_override'] or '(none)'} -- applied: {data['override_applied']}")
    if data["override_note"]:
        lines.append(f"  {data['override_note']}")
    lines.append("Keys: " + ", ".join(f"{k}={v}" for k, v in data["keys"].items()))
    for ch, how in data["channels"].items():
        lines.append(f"  {ch}: {how}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant-slug", required=True)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            print(f"No tenant with slug {args.tenant_slug!r}")
            return 1
        print(render(args.tenant_slug, report(tenant)))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
