"""
Create a workspace's properties from a JSON file (e.g. scripts/data/jade_properties.json).

    python scripts/import_properties.py --tenant-slug jade-hospitainment --file scripts/data/jade_properties.json   # dry run
    ... --apply

Only creates properties the workspace does not have yet (matched by name or slug, case-insensitive). Existing ones are
listed and left untouched, so it is safe to re-run. One audit row (`property.imported`) per created property.
File: {"properties": [{name, slug, type, bedrooms, bathrooms|null, max_adults, address, city, state, description,
amenities: [..]}]}.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.models  # noqa: E402,F401
from app.core.audit import append_audit  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.property import Property  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402

FIELDS = ("type", "bedrooms", "bathrooms", "max_adults", "address", "city", "state", "description", "amenities")


def import_properties(db, tenant_id: str, rows: list[dict], apply: bool) -> dict:
    existing = db.query(Property.name, Property.slug).filter(Property.tenant_id == tenant_id).all()
    known = {v.strip().lower() for pair in existing for v in pair if v}
    created, skipped = [], []
    for row in rows:
        name, slug = row["name"].strip(), row["slug"].strip()
        if name.lower() in known or slug.lower() in known:
            skipped.append(name)
            continue
        created.append(name)
        known.update({name.lower(), slug.lower()})
        if apply:
            prop = Property(tenant_id=tenant_id, name=name, slug=slug, is_active=True,
                            **{k: row[k] for k in FIELDS if k in row})
            db.add(prop)
            db.flush()
            append_audit(db, tenant_id=tenant_id, action="property.imported", target_type="property",
                         target_id=prop.id, payload={"name": name, "source": "import_properties.py"})
    return {"created": created, "skipped": skipped}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    rows = json.loads(Path(a.file).read_text(encoding="utf-8"))["properties"]
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=a.tenant_slug).one_or_none()
        if not tenant:
            print("ERROR: unknown tenant slug")
            return 2
        report = import_properties(db, tenant.id, rows, a.apply)
        print(("APPLYING" if a.apply else "DRY RUN (nothing written; add --apply)")
              + f": create {len(report['created'])}, already there {len(report['skipped'])}")
        for n in report["created"]:
            print(f"  + {n}")
        for n in report["skipped"]:
            print(f"  = {n} (exists, left as is)")
        if a.apply:
            db.commit()
            print("done")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
