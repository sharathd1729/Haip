"""Import Ratha's October 2026 route and package notes into the knowledge base, as entries WAITING FOR APPROVAL.

The owner shared internal meeting notes ("update this also for bot to train"). This file holds the GUEST-SAFE version of them,
rewritten in plain guest-facing language. Left out on purpose (internal only): the specific client, vendor booking costs, an
unconfirmed Mysore city property tie-up, the date-blocking fee idea, action items and team member names. No prices: the current
rates are seasonal and change from November; prices come only from published business data (and Ratha's price setting hands
price questions to the team).

What it does (a DRY RUN unless you pass --apply; nothing is written in a dry run):
  * creates one knowledge entry per item below, source "owner_notes", review status "pending" -- the bot does NOT use any of them
    until the owner approves each one on the knowledge page (Settings -> Knowledge, filter "Imported notes");
  * idempotent on a stable key (source_ref "owner_notes:2026-10:<key>"): a second run creates nothing; if this file's wording
    changed, a still-pending entry is updated to the new wording; an entry the owner already approved or rejected is left alone;
  * every write is audited like any knowledge-base edit (kb.created / kb.updated, knowledge_service.audit_change).

Usage (inside the API container):
    python3 scripts/import_ratha_kb_2026_10.py --tenant rathaa
    ... same command with --apply to write.
"""
import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.knowledge import KnowledgeEntry  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import knowledge_service  # noqa: E402

SOURCE = "owner_notes"
BATCH = "owner_notes:2026-10"
ACTOR = "import_ratha_kb_2026_10"

# (key, category, question, answer). Guest-facing wording only.
ENTRIES = [
    ("coastal-overview", "routes", "Do you do caravan trips to coastal or North Karnataka?",
     "Yes. Coastal and North Karnataka trips are longer journeys. The drive from Bangalore to the Mulki / Mangalore coast takes "
     "about 8 to 10 hours, so we suggest staying 1 to 2 nights there before moving on. The team plans the route and stops with you."),
    ("maravante-beach", "routes", "Can we stay at Maravante Beach?",
     "Yes. Maravante is a beach with the river on one side and the sea on the other. We park the caravan at a partner property "
     "there, so you stay right by the beach."),
    ("sai-radha-beach", "routes", "Is there a beach stay near Sai Radha Beach?",
     "Yes, Sai Radha Beach is one of the beach stay options on the coastal route."),
    ("sharavati-jog-falls", "routes", "Can we go to Jog Falls? What is there to do?",
     "Yes. Near Jog Falls the caravan can stay on the Sharavati waterfront. Water activities there include speed boats, kayaking "
     "and swimming, and in season Jog Falls is in full flow."),
    ("karwar-devbag", "routes", "Can we visit Karwar or Devbag?",
     "Yes. From Karwar you can visit Devbag, an island that feels like a private-island getaway."),
    ("gokarna", "routes", "Do you go to Gokarna?",
     "Yes. In Gokarna we stay on a hilltop near Om Beach, at a spot with parking for the caravan."),
    ("dandeli", "routes", "Can we do river rafting in Dandeli?",
     "Dandeli is on the North Karnataka route, but river rafting there is currently closed. The team can suggest other activities "
     "on the way."),
    ("belgaum-goa", "routes", "Can the trip go on to Belgaum and Goa?",
     "It is possible, but it is a long trip: plan for about 5 to 6 days. The team will work out the route with you."),
    ("bhimeshwari", "routes", "Can we stay at Bhimeshwari?",
     "Yes. Bhimeshwari has a riverside partner stay with parking for the caravan."),
    ("mysore-belt-route", "routes", "Do you have a route to Mysore?",
     "Yes. A popular South Karnataka route goes Bhimeshwari, then Mysore, then Coorg. The KRS backwaters near Mysore can be "
     "included along the way."),
    ("coorg-virajpet", "routes", "How many nights should we plan for Coorg?",
     "For Coorg (the Virajpet side) we suggest 2 nights."),
    ("tailored-packages", "faq", "Can you make a custom package or arrange a group trip?",
     "Yes. Our packages are tailored: we can build a North / Coastal Karnataka package or a South Karnataka package on request. "
     "Group and institution trips (for example a college or university group) and longer block hires can also be arranged. "
     "The team will put together a custom quote for you."),
    ("seasonal-rates", "pricing", "Will the price change?",
     "Our current rates are a seasonal offer, and rates change from November. The team will confirm the latest price for your dates."),
]


def ref(key: str) -> str:
    return f"{BATCH}:{key}"


def run(db, tenant_id: str, *, apply: bool = False) -> dict:
    out = {"created": [], "updated": [], "unchanged": [], "left_alone": []}
    for key, category, question, answer in ENTRIES:
        existing = db.query(KnowledgeEntry).filter_by(tenant_id=tenant_id, source=SOURCE, source_ref=ref(key)).first()
        if existing is None:
            out["created"].append(question)
            if apply:
                entry = KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=tenant_id, category=category, question=question, content=answer,
                                       source=SOURCE, source_ref=ref(key), priority=0, is_active=True, review_status="pending",
                                       embedding_status="pending")
                db.add(entry)
                db.flush()
                knowledge_service.audit_change(db, tenant_id, None, "created", entry.id, after=knowledge_service.snapshot(entry),
                                               source=SOURCE, actor=ACTOR)
            continue
        if existing.question == question and existing.content == answer:
            out["unchanged"].append(question)
        elif existing.review_status != "pending":
            out["left_alone"].append(question)              # the owner already decided on it: never overwritten
        else:
            out["updated"].append(question)
            if apply:
                before = knowledge_service.snapshot(existing)
                existing.question, existing.content, existing.category = question, answer, category
                existing.embedding_status, existing.embedding_error, existing.embedding_attempts = "pending", None, 0
                knowledge_service.audit_change(db, tenant_id, None, "updated", existing.id, before=before,
                                               after=knowledge_service.snapshot(existing), actor=ACTOR)
    if apply:
        db.commit()
        _queue_indexing(db, tenant_id)
    return out


def _queue_indexing(db, tenant_id: str) -> None:
    """Index in advance (still pending review, so unused) so an approval takes effect immediately."""
    try:
        from app.workers.tasks.embed_knowledge import embed_entry
        for (entry_id,) in db.query(KnowledgeEntry.id).filter(KnowledgeEntry.tenant_id == tenant_id, KnowledgeEntry.source == SOURCE,
                                                              KnowledgeEntry.source_ref.like(f"{BATCH}:%"),
                                                              KnowledgeEntry.embedding_status == "pending").all():
            embed_entry.delay(tenant_id, entry_id)
    except Exception as exc:  # noqa: BLE001 -- the periodic index sweep picks pending entries up
        print(f"  (could not queue indexing now: {str(exc)[:120]}; the periodic sweep will index them)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", required=True, help="workspace slug, e.g. rathaa")
    ap.add_argument("--apply", action="store_true", help="write the entries (default: dry run)")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant!r}")
        from app.core.database import set_tenant_context
        set_tenant_context(db, tenant.id)
        out = run(db, tenant.id, apply=args.apply)
        print("APPLIED (entries wait for approval on the knowledge page)" if args.apply else "DRY RUN (nothing written; add --apply)")
        for label in ("created", "updated", "unchanged", "left_alone"):
            print(f"  {label}: {len(out[label])}")
            for q in out[label]:
                print(f"    - {q}")
        if not args.apply:
            db.rollback()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
