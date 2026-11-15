"""tasks `personal.file_call` (after a personal call is summarised: calendar suggestions + folders) and `personal.sort_folder` (a folder was made or its
keywords / rule changed: look through recent calls). services/personal_folders.py; queue ai_scoring."""

import structlog

from app.adapters.llm.scope import scoped_task
from app.core.database import SessionLocal, set_tenant_context
from app.models.call import Call
from app.models.user import User, UserRole
from app.services import personal_folders as pf
from app.services.personal_ask import contact_namer
from app.workers.celery_app import celery_app

log = structlog.get_logger()


def _owner_name(db, tenant_id: str) -> str:
    u = db.query(User).filter_by(tenant_id=tenant_id, role=UserRole.OWNER).first()
    return u.name if u and u.name else "the user"


@celery_app.task(name="personal.file_call")
@scoped_task("yaad", ref_type="call", ref_arg="call_id", prompt_key="personal_folder")
def file_call(tenant_id: str, call_id: str) -> int:
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        from app.services import personal_calendar
        from app.services.booking_agenda_service import tenant_today

        folders = pf.all_folders(db, tenant_id)
        call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
        if call is None:
            return 0
        # Plans said on the call become calendar suggestions (no AI); then the folders.
        personal_calendar.suggest_from_calls(db, tenant_id, [call], tenant_today(db, tenant_id))
        n = pf.sort_calls(
            db,
            tenant_id,
            [call],
            folders,
            owner_name=_owner_name(db, tenant_id),
            contact=contact_namer(db, tenant_id, [call]),
        ) if folders else 0
        db.commit()
        return n
    finally:
        db.close()


@celery_app.task(name="personal.sort_folder")
@scoped_task("yaad", prompt_key="personal_folder")
def sort_folder(tenant_id: str, folder_id: str) -> int:
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        folder = pf.get(db, tenant_id, folder_id)
        if folder is None:
            return 0
        calls = pf.recent_calls(db, tenant_id, folder)
        n = pf.sort_calls(
            db,
            tenant_id,
            calls,
            [folder],
            owner_name=_owner_name(db, tenant_id),
            contact=contact_namer(db, tenant_id, calls),
        )
        db.commit()
        log.info("personal_folder_sorted", tenant_id=tenant_id, folder_id=folder_id, filed=n, looked_at=len(calls))
        return n
    finally:
        db.close()


@celery_app.task(name="personal.google_sync", bind=True, max_retries=3, default_retry_delay=60)
@scoped_task("yaad")
def google_sync(self, tenant_id: str, event_id: str | None = None, google_event_id: str | None = None) -> str:
    """Yaad calendar -> Google Calendar for one event (services/personal_google_calendar.py). `google_event_id` alone =
    the Yaad event was deleted: delete its Google copy. A refusal is stored on the event; a transient one is retried."""
    from app.adapters.instagram.publishing import PublishError
    from app.models.yaad_folder import YaadEvent
    from app.services import personal_google_calendar as gsync

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        try:
            out = (gsync.sync_event(db, tenant_id, event_id) if event_id
                   else gsync.delete_copy(db, tenant_id, google_event_id))
        except PublishError as exc:  # the event is changed only after Google said yes, so nothing to undo
            if event_id:
                e = db.query(YaadEvent).filter_by(id=event_id, tenant_id=tenant_id).first()
                if e is not None:
                    e.google_error = "Google is not answering, trying again." if exc.transient else "Google refused this event."
                    db.commit()
            log.warning("yaad_google_sync_failed", tenant_id=tenant_id, status=exc.status, transient=exc.transient)
            if exc.transient:
                raise self.retry(exc=exc) from exc
            return "failed"
        db.commit()
        return out
    finally:
        db.close()
