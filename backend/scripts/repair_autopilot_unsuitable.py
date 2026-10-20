"""Undo the lead autopilot's wrong moves into "Unsuitable", and untie pipeline stages that share an order.

The bug (20 Oct 2026): a lead that shared a phone number and a requirement (dates, route or headcount) is moved to "the first
open valid stage after the valid-lead entry", meant to be Active. Ratha's pipeline had Unsuitable and Active at the same
order and Unsuitable sorted first, so the autopilot moved every qualified lead to Unsuitable. The work queue treats
Unsuitable as done, so those leads vanished from My day, the team alerts and the follow-ups. The code no longer targets
Unsuitable (lead_autopilot_rules.NEVER_QUALIFIED_KEYS); this script repairs the data.

For each workspace (or one, with --tenant-slug):
  1. Stages sharing an order are renumbered 0..n, keeping the current order and breaking ties in the default pipeline's
     order (General Enquiry before RNR, Active before Unsuitable). Tied orders also make a person's move between the
     two stages fail ("same pipeline order").
  2. Every APPLIED autopilot move into Unsuitable whose lead is still there is reverted to the qualified stage (Active),
     through inquiry_service.revert_automatic_move: the same stage log, ledger event and audit row as any move, and it
     refuses a lead a person has moved since. The autopilot event is marked "undone" and a lead_autopilot.repaired audit
     row is written.

A DRY RUN unless you pass --apply: it prints what would change (short ids only, no guest names or numbers).

Usage (inside the API container, against production):
    docker exec -i haip_api python3 scripts/repair_autopilot_unsuitable.py
    docker exec -i haip_api python3 scripts/repair_autopilot_unsuitable.py --tenant-slug rathaa --apply
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.lead_autopilot import LeadAutopilotEvent  # noqa: E402
from app.models.pipeline_stage import PipelineStage  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402

TIE_ORDER = ["unqualified", "general_enquiry", "rnr", "active", "unsuitable", "lost", "sold", "collaboration_engagement"]


def untied_order(stages: list) -> list:
    """The stages in their current order, ties broken by the default pipeline's order, then by label."""
    rank = {k: i for i, k in enumerate(TIE_ORDER)}
    return sorted(stages, key=lambda s: (s.order, rank.get(s.key, len(TIE_ORDER)), s.label or "", s.id))


def fix_order(db, tenant_id: str, apply: bool) -> list[str]:
    """Renumber the tenant's stages when two share an order. Returns the new order (keys) when a change is needed."""
    from app.services import pipeline_stage_service
    stages = db.query(PipelineStage).filter_by(tenant_id=tenant_id).all()
    if len({s.order for s in stages}) == len(stages):
        return []
    ordered = untied_order(stages)
    if apply:
        pipeline_stage_service.reorder_stages(db, tenant_id, [s.id for s in ordered])
    return [f"{i} {s.key}" for i, s in enumerate(ordered)]


def wrong_moves(db, tenant_id: str) -> list[tuple]:
    """[(event, inquiry)] for applied autopilot moves into "unsuitable" whose lead is still in that stage."""
    bad = [s.id for s in db.query(PipelineStage).filter_by(tenant_id=tenant_id).all() if s.key == "unsuitable"]
    if not bad:
        return []
    events = (db.query(LeadAutopilotEvent)
              .filter(LeadAutopilotEvent.tenant_id == tenant_id, LeadAutopilotEvent.status == "applied",
                      LeadAutopilotEvent.to_stage_id.in_(bad))
              .order_by(LeadAutopilotEvent.created_at).all())
    out = []
    for e in events:
        inq = db.query(Inquiry).filter_by(id=e.inquiry_id, tenant_id=tenant_id).first()
        if inq is not None and inq.stage_id == e.to_stage_id:
            out.append((e, inq))
    return out


def repair(db, tenant_id: str, apply: bool) -> dict:
    from app.core.audit import append_audit
    from app.services import inquiry_service
    from app.services.lead_autopilot_rules import StageMap

    order = fix_order(db, tenant_id, apply)
    target = StageMap.load(db, tenant_id).qualified
    moves = wrong_moves(db, tenant_id)
    done, failed = [], []
    if apply and target is not None:
        now = datetime.now(timezone.utc)
        for event, inq in moves:
            try:
                with db.begin_nested():
                    inquiry_service.revert_automatic_move(
                        db, tenant_id=tenant_id, inquiry_id=inq.id, expected_stage_id=event.to_stage_id,
                        restore_stage_id=target.id, actor_user_id=None,
                        reason="Repair: the autopilot moved this qualified lead to Unsuitable by mistake")
                    event.status, event.resolved_at, event.resolved_by = "undone", now, "repair"
                    append_audit(db, tenant_id=tenant_id, action="lead_autopilot.repaired", actor_user_id=None,
                                 target_type="inquiry", target_id=inq.id,
                                 payload={"actor": "system", "event_id": event.id, "rule": event.rule,
                                          "from_stage": "unsuitable", "to_stage": target.key})
                done.append(inq.id)
            except Exception as exc:  # noqa: BLE001 -- report and carry on with the others
                failed.append((inq.id, str(exc)[:120]))
    return {"order": order, "target": target.key if target else None, "moves": moves, "done": done, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tenant-slug", help="one workspace (default: all)")
    parser.add_argument("--apply", action="store_true", help="make the changes (default: report only)")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        q = db.query(Tenant)
        if args.tenant_slug:
            q = q.filter_by(slug=args.tenant_slug)
        tenants = q.all()
        if not tenants:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}" if args.tenant_slug else "No tenants")
        print("APPLY" if args.apply else "DRY RUN (nothing written; add --apply to repair)")
        for t in tenants:
            set_tenant_context(db, t.id)
            r = repair(db, t.id, args.apply)
            if not r["order"] and not r["moves"]:
                continue
            print(f"\n{t.slug}:")
            if r["order"]:
                print("  stage order " + ("set to" if args.apply else "would be") + ": " + ", ".join(r["order"]))
            print(f"  autopilot moves into Unsuitable still in place: {len(r['moves'])} -> back to {r['target']}")
            for e, inq in r["moves"]:
                print(f"    lead {inq.id[:8]}  moved {e.created_at:%d %b %H:%M} UTC  rule {e.rule}")
            if args.apply:
                print(f"  repaired {len(r['done'])}, failed {len(r['failed'])}")
                for iid, err in r["failed"]:
                    print(f"    FAILED {iid[:8]}: {err}")
                db.commit()
            else:
                db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
