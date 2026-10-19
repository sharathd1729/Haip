"""One-off: turn vehicle-based packages into route-based ones (both caravans cost the same; HAIP holds whichever is free).

Ratha's packages were drafted per vehicle ("Black Caravan — The Night Voyager - same day", "White Caravan — The Light Wanderer -
same day", ...). The rate calculator lists packages by route only. This script:
  1. finds every package whose newest version (the open draft, else the published one) is tied to vehicles or named after a
     caravan, and groups the ones that are the same trip (same name after the caravan part, same prices and terms);
  2. for each group, creates ONE route-based package (a new key, no vehicles, the same prices) through business_data_service
     (a new versioned draft; nothing published is ever edited in place);
  3. turns down the old vehicle drafts ("Merged into ...") -- and, with --publish, publishes the new package when it has a real
     price and retires (deactivates) old PUBLISHED vehicle versions it replaces. A package with a price of 0 stays a draft and is
     listed: set its price in Settings > Quotes, then publish it.
Two packages with the same trip name but different prices are NOT merged: they are listed as a conflict and left alone.

A DRY RUN unless you pass --apply: the dry run only reads and prints exactly what would be created, turned down and retired.
Every change is attributed to the tenant's owner and audited (business_record.*).

Usage (inside the API container):
    python3 scripts/route_packages.py --tenant-slug rathaa
    python3 scripts/route_packages.py --tenant-slug rathaa --apply
    python3 scripts/route_packages.py --tenant-slug rathaa --apply --publish
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.business_record import BusinessRecord  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services import business_data_service as bds  # noqa: E402

_CARAVAN = re.compile(r"caravan", re.I)
_SPLIT = re.compile(r"\s+[-—–]\s+")
FRIENDLY = {"same day": "Same-day ride", "sameday": "Same-day ride", "overnight": "Overnight escape", "multiday": "Multi-day trip",
            "multi day": "Multi-day trip", "multi-day": "Multi-day trip"}
_IGNORED = ("name", "summary", "vehicle_property_ids")


def route_name(name: str) -> str:
    """"Black Caravan — The Night Voyager - same day" -> "Same-day ride"; a name without a caravan part is kept as it is."""
    parts = [p for p in _SPLIT.split(name.strip()) if p]
    tail = parts[-1] if len(parts) > 1 and _CARAVAN.search(parts[0]) else name.strip()
    key = tail.strip().lower()
    return FRIENDLY.get(key, tail[:1].upper() + tail[1:])


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60].strip("-") or "package"


def _signature(data: dict) -> str:
    return json.dumps({k: v for k, v in data.items() if k not in _IGNORED}, sort_keys=True, default=str)


def _newest(db, tenant_id: str) -> list[BusinessRecord]:
    """Per package key: the open draft, else the published version in effect."""
    today = bds.tenant_today(db, tenant_id)
    live = {r.key: r for r in bds.list_effective(db, tenant_id, "package", today)}
    drafts = {r.key: r for r in db.query(BusinessRecord).filter_by(tenant_id=tenant_id, kind="package", status="draft").all()}
    return [drafts.get(k) or live[k] for k in sorted(set(live) | set(drafts))]


def _vehicle_based(rec: BusinessRecord) -> bool:
    data = rec.data or {}
    return bool(data.get("vehicle_property_ids")) or bool(_CARAVAN.search(str(data.get("name") or "")))


def plan(db, tenant_id: str) -> dict:
    """Read-only: what --apply would do."""
    groups: dict[str, list[BusinessRecord]] = {}
    for rec in _newest(db, tenant_id):
        if _vehicle_based(rec):
            groups.setdefault(route_name(str(rec.data.get("name") or rec.key)), []).append(rec)
    out = {"merge": [], "conflicts": [], "unchanged": []}
    for name, recs in sorted(groups.items()):
        sigs = {_signature(r.data) for r in recs}
        members = [{"key": r.key, "version": r.version, "status": r.status, "name": r.data.get("name")} for r in recs]
        if len(sigs) > 1:
            out["conflicts"].append({"name": name, "members": members, "why": "same trip name, different prices or terms"})
            continue
        new_key = slug(name)
        existing = bds.get_effective(db, tenant_id, "package", new_key) or bds.open_draft(db, tenant_id, "package", new_key)
        data = {**recs[0].data, "name": name, "vehicle_property_ids": []}
        if existing is not None and _signature(existing.data) == _signature(data) and not existing.data.get("vehicle_property_ids"):
            out["unchanged"].append({"name": name, "key": new_key, "members": members, "why": "already converted"})
            continue
        if existing is not None and existing.status == "draft":
            out["conflicts"].append({"name": name, "members": members, "why": f"a draft '{new_key}' already exists; publish or reject it first"})
            continue
        priced = any(float(r.get("amount") or 0) > 0 for r in data.get("rates") or [])
        out["merge"].append({"name": name, "new_key": new_key, "members": members, "priced": priced, "data": data})
    return out


def apply(db, tenant_id: str, the_plan: dict, publish: bool) -> dict:
    """Perform the plan in the session; the caller commits."""
    owner = db.query(User).filter(User.tenant_id == tenant_id, User.role == UserRole.OWNER, User.is_active.is_(True)).first()
    if owner is None:
        raise SystemExit("This tenant has no active owner to attribute the changes to.")
    done = {"created": [], "published": [], "rejected": [], "retired": [], "left": []}
    for g in the_plan["merge"]:
        note = "Route-based package (both caravans, same price) merged from: " + ", ".join(m["key"] for m in g["members"])
        draft = bds.create_draft(db, tenant_id, "package", g["new_key"], g["data"], owner.id, note=note[:500])
        done["created"].append(g["new_key"])
        live_new = False
        if publish and g["priced"]:
            bds.publish(db, tenant_id, draft.id, owner.id, actor_role="owner")
            done["published"].append(g["new_key"])
            live_new = True
        for m in g["members"]:
            rec = db.query(BusinessRecord).filter_by(tenant_id=tenant_id, kind="package", key=m["key"], version=m["version"]).first()
            if rec is None:
                continue
            if rec.status == "draft":
                bds.reject(db, tenant_id, rec.id, owner.id, reason=f"Merged into route package {g['new_key']}")
                done["rejected"].append(m["key"])
            elif rec.status == "published" and live_new:
                try:
                    bds.deactivate(db, tenant_id, "package", m["key"], owner.id, note=f"Replaced by route package {g['new_key']}")
                    done["retired"].append(m["key"])
                except bds.BusinessDataError as exc:
                    done["left"].append({"key": m["key"], "why": exc.message})
            else:
                done["left"].append({"key": m["key"], "why": "published; kept until the route package is published"})
    return done


def _print(the_plan: dict, done=None) -> None:
    for g in the_plan["merge"]:
        print(f"MERGE  -> new package '{g['new_key']}' ({g['name']}), {'priced' if g['priced'] else 'PRICE 0: stays a draft'}")
        for m in g["members"]:
            print(f"         from '{m['key']}' v{m['version']} [{m['status']}] {m['name']}")
    for c in the_plan["conflicts"]:
        print(f"SKIP   {c['name']}: {c['why']} -> {[m['key'] for m in c['members']]}")
    for u in the_plan["unchanged"]:
        print(f"OK     {u['name']}: {u['why']} ('{u['key']}')")
    if not any(the_plan.values()):
        print("Nothing to convert: no vehicle-based packages.")
    if done is not None:
        print("APPLIED:", json.dumps(done, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run, nothing is written)")
    ap.add_argument("--publish", action="store_true", help="with --apply: publish the priced route packages and retire old published ones")
    args = ap.parse_args()
    from app.core.database import SessionLocal, set_tenant_context
    from app.models.tenant import Tenant
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}.")
        set_tenant_context(db, tenant.id)
        the_plan = plan(db, tenant.id)
        if not args.apply:
            _print(the_plan)
            print("\nDRY RUN: nothing was written. Re-run with --apply (and --publish) to make these changes.")
            return
        done = apply(db, tenant.id, the_plan, args.publish)
        db.commit()
        _print(the_plan, done)
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
