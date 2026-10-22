"""Write Rathaa's sales playbook (sales meeting, 22 Oct 2026) into brand_config.sales_playbook.

The playbook shapes HOW the AI sells (opening, qualification, objections, follow-ups). It never states a figure on its own: the
"too expensive" answer here has no rupee numbers because, in handoff price mode, any figure in a reply is blocked by the price
guard. The owner can add the per-km comparison in Settings > AI if Rathaa moves to grounded prices.

  * A DRY RUN unless --apply: prints the playbook and what would change.
  * --apply writes it through sales_playbook.update (validated, audited as `ai.sales_playbook_changed`, actor
    seed_ratha_playbook). Re-running with the same text changes nothing.

Usage (inside the API container):
    python3 scripts/seed_ratha_playbook.py --tenant rathaa
    python3 scripts/seed_ratha_playbook.py --tenant rathaa --apply
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.schemas.sales_playbook import SalesPlaybook  # noqa: E402
from app.services import sales_playbook  # noqa: E402

RATHA_PLAYBOOK = SalesPlaybook(
    opening_line=("Rathaa is a private retreat that travels with you: a lounge, a bed, a washroom and a kitchenette, with a "
                  "driver, wherever you want to wake up. Rathaa can go where the room can't go."),
    qualification_questions=[
        "When are you planning to travel?",
        "How many of you will be travelling?",
        "Is it a day trip or an overnight trip?",
        "What kind of experience are you looking for: wildlife, nature, a celebration, spiritual, adventure, wellness or leisure?",
        "Do you have a destination in mind?",
        "How many days would you like to be away?",
        "Would you like to sleep in Rathaa, or stay at a resort and use Rathaa for the journey?",
        "Will there be children or senior citizens with you?",
        "Is there a special occasion we should plan around?",
        "Any food preferences or activities you would like on the way?",
    ],
    never_ask_budget_first=True,
    objection_answers={
        "too expensive": ("Compare it with what you would otherwise book: a Tempo Traveller or an Innova is transport only, "
                          "charged by the kilometre. Rathaa is the lounge, the bed, the washroom, the kitchenette and the driver "
                          "together: the room travels with you, so the stay and the journey are one."),
        "we can take our own car": ("You can, but then the drive is time lost. In Rathaa the journey becomes part of the "
                                    "holiday: you relax, eat and rest while you travel, and nobody in the family has to drive."),
        "can we drive it ourselves": "Rathaa always comes with our own trained driver; self-drive is not offered.",
    },
    follow_up_style=("Name what we held for them, never 'any update?'. For example: \"I've held the Wild Karnataka itinerary for "
                     "your dates. Would you like Kabini and Bandipur, or just Kabini?\" One clear question, one next step."),
    never_say_no=True,
    add_value_before_discount=True,
    rules=[
        "Recommend ONE itinerary that fits what they told you, plus at most one alternative. Never send a list of packages.",
        "Offer a kit (Culinary, Wellness or Adventure) before any talk of a discount; a discount is for the team to decide.",
        "Rathaa sleeps 4 and travels about 6: never promise beds for more than 4 on an overnight trip; larger groups go to the team.",
        "No self-drive: Rathaa always travels with our driver.",
        "Lead with the experience and the places, not the price.",
    ],
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", required=True, help="workspace slug, e.g. rathaa")
    ap.add_argument("--apply", action="store_true", help="write the playbook (default: dry run)")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant!r}")
        set_tenant_context(db, tenant.id)
        changes = sales_playbook.update(db, tenant, None, RATHA_PLAYBOOK, actor="seed_ratha_playbook")
        print(json.dumps(RATHA_PLAYBOOK.model_dump(), indent=2, ensure_ascii=False))
        print(f"\nFields that would change: {', '.join(sorted(changes)) or 'none (already the same)'}")
        if args.apply:
            db.commit()
            print("APPLIED: the playbook is live in the next AI reply (Settings > AI shows it).")
        else:
            db.rollback()
            print("DRY RUN: nothing written. Run again with --apply.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
