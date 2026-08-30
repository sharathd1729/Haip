"""Agent worklist — the "who needs contacting right now" feed.

GET /worklist

Deliberately not behind require_module("analytics"): this is an inbox-style
operational view, not reporting. Gating it on the analytics module would
hide an agent's own follow-ups from them whenever that module is off (it is
currently off for some tenants), which is the opposite of the intent.
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import worklist_service
from app.services.date_presets import ist_range_to_utc

log = structlog.get_logger()

router = APIRouter(prefix="/worklist", tags=["worklist"])

SECTION_FUNCS = {
    "awaiting_reply": worklist_service.awaiting_reply,
    "missed_calls": worklist_service.missed_calls,
    "shared_details": worklist_service.shared_contact_details,
    "new_dms": worklist_service.new_dms,
    "overdue_followups": worklist_service.overdue_followups,
}


def _resolve_window_and_scope(
    current_user: User,
    hours: Optional[int], date_from: Optional[str], date_to: Optional[str], mine_only: Optional[bool],
):
    """Shared by GET /worklist and GET /worklist/section/{key} so a "load
    more" page request resolves the exact same window/scope as the initial
    load -- a drifted resolution here would silently paginate a different
    slice than the one currently on screen.

    Returns (hours, since, until, scope_user_id). Exactly one of
    (hours, since) is meaningful at a time: a custom date range resolves
    concrete since/until and hours=None; a rolling window returns the raw
    hours value (or None for "all time") with since/until left for the
    caller to resolve from it.
    """
    is_owner_view = current_user.role in (UserRole.OWNER, UserRole.MANAGER)

    # A custom range wins over the rolling window. Resolved through the same
    # IST helper the dashboard uses, so "1 Aug" means the Indian calendar day
    # rather than a UTC one shifted by 5.5 hours.
    since = until = None
    if date_from or date_to:
        try:
            d_from = date_from or date_to
            d_to = date_to or date_from
            _, _, since, until = ist_range_to_utc(d_from, d_to)
        except ValueError:
            raise HTTPException(status_code=422, detail="Dates must be YYYY-MM-DD")
        if since > until:
            raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
        hours = None
    elif not hours:
        # hours=0 is the explicit "all time" signal from the UI.
        hours = None

    # An agent always sees only their own assignments, whatever they pass --
    # same rule the dashboard applies. Owners and managers see everything by
    # default and can narrow to themselves.
    if is_owner_view:
        scope_user_id = current_user.id if mine_only else None
    else:
        scope_user_id = current_user.id

    return hours, since, until, scope_user_id


@router.get("")
def get_worklist(
    hours: Optional[int] = Query(
        # ge=0, not ge=1: 0 is the "all time" signal and would otherwise 422.
        default=24, ge=0, le=8760,
        description="Rolling window in hours. Pass 0 for all time, or use date_from/date_to.",
    ),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD (IST), inclusive"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD (IST), inclusive"),
    mine_only: Optional[bool] = Query(
        default=None,
        description="Agents are always scoped to themselves; owners/managers default to tenant-wide.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hours, since, until, scope_user_id = _resolve_window_and_scope(current_user, hours, date_from, date_to, mine_only)

    data = worklist_service.build_worklist(
        db, current_user.tenant_id, scope_user_id=scope_user_id,
        hours=hours, since=since, until=until,
    )
    data["scope"] = "mine" if scope_user_id else "team"
    return data


@router.get("/section/{section}")
def get_worklist_section(
    section: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=worklist_service.SECTION_LIMIT, ge=1, le=200),
    hours: Optional[int] = Query(default=24, ge=0, le=8760),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD (IST), inclusive"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD (IST), inclusive"),
    mine_only: Optional[bool] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One section's rows at an arbitrary offset -- the "Load more" page
    request. GET /worklist itself always returns just the first
    SECTION_LIMIT rows per section (it has to build all five sections in
    one call), so seeing rows 51+ needs a dedicated per-section fetch
    rather than a bigger `limit` on the combined endpoint."""
    func = SECTION_FUNCS.get(section)
    if func is None:
        raise HTTPException(status_code=404, detail=f"Unknown section {section!r}")

    hours, since, until, scope_user_id = _resolve_window_and_scope(current_user, hours, date_from, date_to, mine_only)
    if since is None and hours is not None:
        from datetime import datetime, timedelta, timezone
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

    if section == "awaiting_reply":
        rows = func(db, current_user.tenant_id, scope_user_id=scope_user_id, since=since, until=until, limit=limit, offset=offset)
    elif section == "overdue_followups":
        rows = func(db, current_user.tenant_id, scope_user_id=scope_user_id, limit=limit, offset=offset)
    else:
        rows = func(db, current_user.tenant_id, since, until=until, limit=limit, offset=offset)

    return {"rows": rows}


@router.get("/briefing")
def get_daily_briefing(
    current_user: User = Depends(get_current_user),
):
    """The AI Daily Briefing card -- cache-only read, never an inline LLM
    call (CLAUDE.md: never call LLM inline in a request handler). On a
    cache miss this kicks off async generation (beat also regenerates
    every 30 min) and returns unavailable immediately; the next poll
    picks up the result once it lands."""
    from app.core.cache import idem_check_and_set
    from app.services.daily_briefing_service import get_cached_briefing
    from app.workers.tasks.daily_briefing import generate_daily_briefing

    cached = get_cached_briefing(current_user.tenant_id)
    if cached:
        return {"available": True, **cached}

    # Guard against re-enqueuing on every poll while generation is in
    # flight -- a client polling this while "unavailable" would otherwise
    # queue one Celery task per request.
    if idem_check_and_set(f"haip:daily_briefing:pending:{current_user.tenant_id}", ttl=90):
        generate_daily_briefing.delay(tenant_id=current_user.tenant_id)
    return {"available": False}


@router.get("/daily-report")
def preview_daily_report(
    day: Optional[str] = Query(default=None, description="YYYY-MM-DD (IST). Defaults to yesterday."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The daily owner report as JSON -- what the email will contain."""
    from app.services import daily_report_service
    return daily_report_service.build_daily_report(db, current_user.tenant_id, day=day)


@router.post("/daily-report/send")
def send_daily_report_now(
    day: Optional[str] = Query(default=None),
    to_email: Optional[str] = Query(default=None, description="Override recipient; defaults to you."),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Send the daily report immediately, for checking it before 8am.

    Runs inline rather than through Celery so the caller gets the real
    result -- a queued task would return "accepted" whether or not the mail
    provider accepted it, which is exactly the false-success this report is
    meant to replace.
    """
    from app.workers.tasks.daily_owner_report import send_daily_owner_report
    result = send_daily_owner_report.run(
        tenant_id=current_user.tenant_id,
        day=day,
        to_email=to_email or current_user.email,
    )
    return result
