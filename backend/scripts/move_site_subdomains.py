"""Move every site's HAIP subdomain from one base domain to another (dry run unless --apply).

Why: sites were given "<slug>.genhaip.site", a domain that was never registered, so no site address resolved
(Oct 2026). SITES_BASE_DOMAIN is now "sites.genhaip.com"; this rewrites the stored subdomain rows to match.
Custom domains are not touched.

  python scripts/move_site_subdomains.py                       # show what would change
  python scripts/move_site_subdomains.py --apply               # change it
  python scripts/move_site_subdomains.py --from genhaip.site --to sites.genhaip.com --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.website import SiteDomain  # noqa: E402


def plan(db, old: str, new: str) -> list[tuple[SiteDomain, str]]:
    """(row, new hostname) for each subdomain row under `old` whose new name is free."""
    taken = {h for (h,) in db.query(SiteDomain.hostname)}
    out = []
    for d in db.query(SiteDomain).filter(SiteDomain.kind == "subdomain").all():
        if not d.hostname.endswith("." + old):
            continue
        target = d.hostname[: -len(old)] + new
        if target in taken:
            print(f"SKIP {d.hostname}: {target} already exists")
            continue
        out.append((d, target))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="old", default="genhaip.site")
    ap.add_argument("--to", dest="new", default=settings.SITES_BASE_DOMAIN)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    db = SessionLocal()
    try:
        moves = plan(db, a.old.lower(), a.new.lower())
        for d, target in moves:
            print(f"{'MOVE' if a.apply else 'would move'} {d.hostname} -> {target}")
            if a.apply:
                d.hostname = target
        if a.apply:
            db.commit()
        print(f"{len(moves)} subdomain(s) {'moved' if a.apply else 'to move (dry run; add --apply)'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
