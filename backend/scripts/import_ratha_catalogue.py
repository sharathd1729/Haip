"""Load the Rathaa commercial master (21 Oct 2026) as DRAFT business records and knowledge entries waiting for approval.

Source: scripts/data/ratha_catalogue_2026_10.json (packages, routes, day-by-day itineraries, the discount policy, reseller tiers,
guest-safe knowledge). Nothing is published and nothing reaches a guest until the owner reviews it in Settings > Knowledge >
Structured Business Data and publishes (destinations first, then packages, then itineraries; the policies at any time).

  * A DRY RUN unless --apply: prints what would be drafted, what is already the same as the published version, and what is
    skipped because an unpublished draft already exists for that record (edit or reject that one first, then run again).
  * Each record goes through business_data_service.create_draft (validated, versioned, audited as the tenant's owner); a published
    version is never edited in place.
  * Knowledge entries are idempotent on source_ref "commercial_master:2026-10:<key>" and created with review status pending.
  * Prints the review checklist from the data file at the end: estimates to confirm before publishing.

Usage (inside the API container):
    python3 scripts/import_ratha_catalogue.py --tenant rathaa
    python3 scripts/import_ratha_catalogue.py --tenant rathaa --apply
"""
import argparse
import json
import os
import sys
import uuid
from copy import deepcopy
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.business_record import BusinessRecord  # noqa: E402
from app.models.knowledge import KnowledgeEntry  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.schemas.business_data import SINGLETON_KEY, validate_data  # noqa: E402
from app.services import business_data_service as bds  # noqa: E402
from app.services import knowledge_service  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ratha_catalogue_2026_10.json")
KB_SOURCE, KB_BATCH, ACTOR = "owner_notes", "commercial_master:2026-10", "import_ratha_catalogue"
NOTE = "Rathaa commercial master, 21 Oct 2026"


def _rates(spec: dict, valid: dict, nights: int) -> list[dict]:
    """Two windows around the peak (29 Dec - 1 Jan has no rate: a person quotes it). A package-priced trip is chosen by its check-in
    date, so its first window ends early enough that the whole trip is over before the peak starts."""
    price, floor = spec["band"]
    unit = spec["unit"]
    start, peak, peak_end, end = (date.fromisoformat(valid[k]) for k in ("from", "peak_starts", "peak_ends", "to"))
    last_a = peak - timedelta(days=1 + (nights if unit == "package" else 0))
    common = {"amount": price, "unit": unit, "floor_amount": floor}
    return [{"label": "Oct - Dec 2026", "valid_from": start.isoformat(), "valid_to": last_a.isoformat(), **common},
            {"label": "Jan - Mar 2027", "valid_from": (peak_end + timedelta(days=1)).isoformat(), "valid_to": end.isoformat(), **common}]


def build(catalogue: dict) -> list[tuple[str, str, dict]]:
    """(kind, key, data) in publish order."""
    c, valid = catalogue["common"], catalogue["valid"]
    out = [("destination", d["key"], d["data"]) for d in catalogue["destinations"]]
    for p in catalogue["packages"]:
        data = deepcopy(p["data"])
        nights = int(data.get("min_nights") or 0)
        data.update(gst_percent=c["gst_percent"], extra_km_charge=deepcopy(c["extra_km_charge"]),
                    extra_hour_charge=deepcopy(c["extra_hour_charge"]), charges=deepcopy(c["kits"]),
                    inclusions=list(c["inclusions"]) + list(data.get("inclusions") or []),
                    exclusions=list(c["exclusions"]) + list(data.get("exclusions") or []),
                    at_actuals=([ "JLR safari, meals and activities (paid to JLR)"] if p.get("jlr") else []) + [c["third_party"]],
                    rates=_rates(p, valid, nights))
        if p.get("b2b"):
            data["audience"] = "b2b"
        out.append(("package", p["key"], data))
    out += [("itinerary", i["key"], i["data"]) for i in catalogue["itineraries"]]
    out.append(("discount_policy", SINGLETON_KEY, catalogue["discount_policy"]))
    out.append(("reseller_terms", SINGLETON_KEY, catalogue["reseller_terms"]))
    return out


def _owner(db, tenant_id: str):
    return db.query(User).filter(User.tenant_id == tenant_id, User.role == UserRole.OWNER, User.is_active.is_(True)).first()


def run(db, tenant_id: str, catalogue: dict, *, apply: bool = False) -> dict:
    out = {"drafted": [], "same_as_published": [], "draft_exists": [], "invalid": [], "kb_created": [], "kb_updated": [], "kb_left_alone": []}
    owner = _owner(db, tenant_id)
    actor = owner.id if owner else None
    for kind, key, data in build(catalogue):
        model, problems = validate_data(kind, data)
        label = f"{kind} {key}"
        if model is None:
            out["invalid"].append(f"{label}: {'; '.join(problems)}")
            continue
        if bds.open_draft(db, tenant_id, kind, key) is not None:
            out["draft_exists"].append(label)
            continue
        live = bds.get_effective(db, tenant_id, kind, key)
        if live is not None and live.data == bds.canonical(model):
            out["same_as_published"].append(label)
            continue
        out["drafted"].append(label + (f" (new version of v{live.version})" if live is not None else " (new)"))
        if apply:
            bds.create_draft(db, tenant_id, kind, key, data, actor, note=NOTE)
    for item in catalogue["knowledge"]:
        ref = f"{KB_BATCH}:{item['key']}"
        existing = db.query(KnowledgeEntry).filter_by(tenant_id=tenant_id, source=KB_SOURCE, source_ref=ref).first()
        if existing is None:
            out["kb_created"].append(item["question"])
            if apply:
                entry = KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=tenant_id, category=item["category"], question=item["question"],
                                       content=item["answer"], source=KB_SOURCE, source_ref=ref, priority=0, is_active=True,
                                       review_status="pending", embedding_status="pending")
                db.add(entry)
                db.flush()
                knowledge_service.audit_change(db, tenant_id, None, "created", entry.id, after=knowledge_service.snapshot(entry),
                                               source=KB_SOURCE, actor=ACTOR)
        elif existing.review_status != "pending":
            out["kb_left_alone"].append(item["question"])          # the owner already decided on it: never overwritten
        elif (existing.question, existing.content) != (item["question"], item["answer"]):
            out["kb_updated"].append(item["question"])
            if apply:
                before = knowledge_service.snapshot(existing)
                existing.question, existing.content, existing.category = item["question"], item["answer"], item["category"]
                existing.embedding_status, existing.embedding_error, existing.embedding_attempts = "pending", None, 0
                knowledge_service.audit_change(db, tenant_id, None, "updated", existing.id, before=before,
                                               after=knowledge_service.snapshot(existing), actor=ACTOR)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", required=True, help="workspace slug, e.g. rathaa")
    ap.add_argument("--apply", action="store_true", help="write the drafts (default: dry run)")
    args = ap.parse_args()
    with open(DATA, encoding="utf-8") as fh:
        catalogue = json.load(fh)
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant!r}")
        from app.core.database import set_tenant_context
        set_tenant_context(db, tenant.id)
        out = run(db, tenant.id, catalogue, apply=args.apply)
        if out["invalid"]:
            db.rollback()
            print("NOT APPLIED: the data file has invalid records (nothing was written):")
            for line in out["invalid"]:
                print(f"  - {line}")
            return 1
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print("APPLIED: drafts wait for review in Settings > Knowledge > Structured Business Data" if args.apply
              else "DRY RUN (nothing written; add --apply)")
        for label, items in out.items():
            if label != "invalid":
                print(f"  {label}: {len(items)}")
                for line in items:
                    print(f"    - {line}")
        print("\nCheck before publishing:")
        for line in catalogue["review"]:
            print(f"  * {line}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
