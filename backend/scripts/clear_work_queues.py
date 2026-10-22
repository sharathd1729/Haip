"""
Clear a workspace's "Needs you now" queues so the dashboard shows zero. Nothing is deleted:

  Guests waiting for a reply      -> the conversation is closed (it reopens if the guest writes again)
  Missed calls not called back    -> the call is marked "dismissed" (not "called back": recovery
                                     analytics are unaffected, the call and recording stay)
  Follow-ups overdue / due today  -> the task is marked done
                                     (a service request linked to the task is marked done too)

Not touched here: "New leads to contact" comes from the lead pipeline. It clears when a person contacts the lead or
the lead leaves the open pipeline, so run scripts/bulk_move_leads_to_lost.py first. The final report says what is still counted.

Historical data (calls, messages, leads, bookings, analytics) is left exactly as it is.

DRY RUN BY DEFAULT. Nothing changes unless --apply is passed.

  cd backend
  python scripts/clear_work_queues.py --tenant-slug rathaa            # report only
  python scripts/clear_work_queues.py --tenant-slug rathaa --apply    # do it
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.audit import append_audit  # noqa: E402
from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.call import Call, CallDirection  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.models.stay_finance import StayServiceRequest  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import call_status_service, inbox_service, work_queue_service  # noqa: E402

CHUNK = 500
LABEL = {"consult": "Questions the AI asked the team (not cleared here)", "reply": "Leads waiting for a reply", "callback": "Missed calls not called back",
         "followup": "Follow-ups overdue / due soon", "new_lead": "New leads to contact",
         "no_reply": "Leads not replying to us (not cleared here)",
         "clash": "Calendar clashes (due ones are marked done with the follow-ups)"}


def _chunks(items, n=CHUNK):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _print_counts(title: str, counts: dict) -> None:
    print(title)
    for kind in work_queue_service.KINDS:
        print(f"  {counts.get(kind, 0):>6}  {LABEL[kind]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-slug", required=True, help="Workspace slug, e.g. rathaa")
    parser.add_argument("--apply", action="store_true", help="Actually clear the queues (default: report only)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if not tenant:
            print(f"No workspace with slug '{args.tenant_slug}'.")
            return 1
        set_tenant_context(db, tenant.id)
        now = datetime.now(timezone.utc)

        before = work_queue_service.counts(db, tenant, None)["counts"]
        print(f"Workspace: {tenant.name} ({tenant.slug})")
        _print_counts("Now:", before)

        # The very same selections the dashboard uses, minus its display cap.
        base = inbox_service.inbox_base_query(db, tenant.id)
        conv_ids = [c.id for c in inbox_service.apply_view(db, base, tenant.id, "needs_reply", "").all()]

        call_q = db.query(Call.id).filter(
            Call.tenant_id == tenant.id, Call.direction == CallDirection.INBOUND,
            call_status_service.missed_call_sql_filter(),
            Call.recovered_by_call_id.is_(None), Call.callback_dismissed_at.is_(None),
            Call.created_at >= now - work_queue_service.CALLBACK_WINDOW,
        )
        if tenant.ivr_provider:
            call_q = call_q.filter(Call.ivr_provider == tenant.ivr_provider)
        call_ids = [r[0] for r in call_q.all()]

        task_ids = [r[0] for r in db.query(Task.id).filter(
            Task.tenant_id == tenant.id, Task.is_done.is_(False), Task.due_date.isnot(None),
            Task.due_date <= now + timedelta(hours=1)).all()]

        print(f"\nWould close {len(conv_ids)} conversations, dismiss {len(call_ids)} missed calls, "
              f"mark {len(task_ids)} follow-ups done." if not args.apply else
              f"\nClosing {len(conv_ids)} conversations, dismissing {len(call_ids)} missed calls, "
              f"marking {len(task_ids)} follow-ups done ...")
        if not args.apply:
            print("Dry run only, nothing changed. Add --apply to clear the queues.")
            return 0

        for ids in _chunks(conv_ids):
            db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.id.in_(ids)) \
                .update({Conversation.is_open: False}, synchronize_session=False)
        for ids in _chunks(call_ids):
            db.query(Call).filter(Call.tenant_id == tenant.id, Call.id.in_(ids)) \
                .update({Call.callback_dismissed_at: now}, synchronize_session=False)
        for ids in _chunks(task_ids):
            db.query(Task).filter(Task.tenant_id == tenant.id, Task.id.in_(ids)) \
                .update({Task.is_done: True, Task.completed_at: now}, synchronize_session=False)
            # A service request on a booking mirrors its task: keep the two in step.
            db.query(StayServiceRequest).filter(StayServiceRequest.tenant_id == tenant.id,
                                                StayServiceRequest.task_id.in_(ids), StayServiceRequest.status != "done") \
                .update({StayServiceRequest.status: "done", StayServiceRequest.completed_at: now}, synchronize_session=False)

        append_audit(db, tenant_id=tenant.id, actor_user_id=None, action="work_queue.cleared", target_type="tenant",
                     target_id=tenant.id, payload={"conversations_closed": len(conv_ids), "missed_calls_dismissed": len(call_ids),
                                                   "followups_done": len(task_ids)})
        db.commit()
        set_tenant_context(db, tenant.id)

        after = work_queue_service.counts(db, tenant, None)["counts"]
        print()
        _print_counts("After:", after)
        rest = {k: v for k, v in after.items() if v}
        if rest:
            print("\nStill counted (they come from the lead pipeline, not from this script): "
                  + ", ".join(f"{LABEL[k]} ({v})" for k, v in rest.items())
                  + ".\nRun scripts/bulk_move_leads_to_lost.py to move those leads out of the open pipeline.")
        else:
            print("\nAll queues are at zero.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
