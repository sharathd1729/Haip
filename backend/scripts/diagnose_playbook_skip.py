"""Why did a lead playbook (missed call / no answer WhatsApp) not reach this guest? READ-ONLY.

Prints, for each of the guest's calls in the last N days: how HAIP classifies it now (answered / unanswered), how old it was
when the AI decided, the playbook run + its actions (sent / skipped + reason), and any ``playbook.message_not_sent`` audit.
A call with NO run at all was never started: answered at ingest and only found unanswered later (before 26 Oct 2026 that
was dropped after 30 min with no trace), or the playbook was off. Phone numbers are never printed.

    cd backend && python scripts/diagnose_playbook_skip.py --tenant-slug rathaa --guest-id <uuid> [--days 14]
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--guest-id", required=True)
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()

    from app.core.database import SessionLocal, set_tenant_context
    from app.models.audit_event import AuditEvent
    from app.models.call import Call
    from app.models.lead_workflow import PlaybookAction, PlaybookRun
    from app.models.tenant import Tenant
    from app.services import lead_playbook_settings as settings
    from app.services.lead_playbook_engine import playbook_for_call

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=a.tenant_slug).first()
        if tenant is None:
            raise SystemExit("no such workspace")
        set_tenant_context(db, tenant.id)
        print("playbooks on now:", {k: settings.playbook(tenant, k)["active"] for k in settings.get(tenant)["playbooks"]})
        since = datetime.now(timezone.utc) - timedelta(days=a.days)
        calls = (db.query(Call).filter(Call.tenant_id == tenant.id, Call.guest_id == a.guest_id, Call.created_at >= since)
                 .order_by(Call.created_at).all())
        run_ids = set()
        for c in calls:
            key = playbook_for_call(c)
            print(f"\ncall {c.id} {c.direction} at {c.created_at} dur={c.duration_seconds}s dial={c.ivr_dial_status} "
                  f"ai={c.ai_disposition} human={c.human_disposition} -> playbook now: {key or 'answered (none)'}")
            for run in db.query(PlaybookRun).filter_by(tenant_id=tenant.id, trigger_ref=f"call:{c.id}").all():
                run_ids.add(run.id)
                print(f"  run {run.playbook_key} status={run.status} reason={run.stop_reason or ''}")
                for act in db.query(PlaybookAction).filter_by(tenant_id=tenant.id, run_id=run.id).all():
                    print(f"    {act.action} {act.status}: {act.reason or ''} template={act.template_name or ''}")
            if key and not db.query(PlaybookRun.id).filter_by(tenant_id=tenant.id, trigger_ref=f"call:{c.id}").first():
                print("  NO RUN: the playbook never started for this call (answered at ingest, unanswered only later; or off then)")
        for ev in (db.query(AuditEvent).filter(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "playbook.message_not_sent",
                                               AuditEvent.target_id.in_(run_ids or {"-"})).all()):
            print("audit", ev.created_at, ev.target_id, ev.payload)
    finally:
        db.close()


if __name__ == "__main__":
    main()
