"""CRM reports on the Reports page (22 Oct 2026). Owner / manager with analytics.read, like the other reports; IST days.

GET /reports/daily-validation?date=YYYY-MM-DD     per agent + total: received, handled, in a valid stage, conversions
                                                  (automatic) apart from reviewed / valid / not valid / not yet reviewed
                                                  (a person's review). Default today (IST). lead_daily_report.
GET /reports/checkin-coverage?from=&to=           valid guest enquiries per upcoming check-in date and per weekend
                                                  (Fri-Sun) against a target of 5, with the booked vehicles. Default: today
                                                  to the 6th weekend; at most 120 days. checkin_coverage.
GET /reports/outcome-reasons?from=&to=&basis=     "Why we win / lose": won and lost leads by reason (confirmed apart from the
                                                  AI's unconfirmed proposals), by closed date (default) or check-in date.
                                                  Default: the last 30 days. lead_outcome_report.
GET /reports/checkin-months?months=6&start=YYYY-MM per check-in month: enquiries, valid, won, lost (+ top reasons), open,
                                                  booked revenue (revenue.read, else restricted) + a "Date not given yet"
                                                  row. Default start: two months before this one (IST). checkin_month_report.
GET/PUT /reports/daily-lead-email/settings        the 11:00 IST daily lead report email + 10:30 reminder (lead_report_email;
                                                  owner/manager; audited reports.daily_lead_email_changed)
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import checkin_coverage, lead_daily_report, lead_outcome_report
from app.services.authz_service import require_capability
from app.services.date_presets import IST

router = APIRouter(prefix="/reports", tags=["reports"])
_OWNERS = require_roles(UserRole.OWNER, UserRole.MANAGER)


def _today() -> date:
    return datetime.now(IST).date()


def _day(value: Optional[str], name: str) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid {name}: use YYYY-MM-DD")


@router.get("/daily-validation")
def daily_validation(day: Optional[str] = Query(None, alias="date"), current_user: User = Depends(_OWNERS),
                     _c=Depends(require_capability("analytics.read")), db: Session = Depends(get_db)) -> dict:
    return lead_daily_report.build(db, current_user.tenant_id, _day(day, "date") or _today())


@router.get("/checkin-coverage")
def checkin_coverage_report(d_from: Optional[str] = Query(None, alias="from"), d_to: Optional[str] = Query(None, alias="to"),
                            current_user: User = Depends(_OWNERS), _c=Depends(require_capability("analytics.read")),
                            db: Session = Depends(get_db)) -> dict:
    start, end = checkin_coverage.default_range(_today())
    start, end = _day(d_from, "from") or start, _day(d_to, "to") or end
    try:
        return checkin_coverage.build(db, current_user.tenant_id, start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/outcome-reasons")
def outcome_reasons(d_from: Optional[str] = Query(None, alias="from"), d_to: Optional[str] = Query(None, alias="to"),
                    basis: str = Query("closed", pattern="^(closed|checkin)$"), current_user: User = Depends(_OWNERS),
                    _c=Depends(require_capability("analytics.read")), db: Session = Depends(get_db)) -> dict:
    from datetime import timedelta
    end = _day(d_to, "to") or _today()
    start = _day(d_from, "from") or end - timedelta(days=29)
    try:
        return lead_outcome_report.build(db, current_user.tenant_id, start, end, basis)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/checkin-months")
def checkin_months(months: int = Query(6, ge=1, le=12), start: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
                   current_user: User = Depends(_OWNERS), _c=Depends(require_capability("analytics.read")),
                   db: Session = Depends(get_db)) -> dict:
    from app.models.tenant import Tenant
    from app.services import checkin_month_report
    from app.services.authz_service import has_capability
    try:
        first = checkin_month_report.parse_month(start) or checkin_month_report.default_start(_today())
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid start: use YYYY-MM")
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    return checkin_month_report.build(db, tenant, first, months, money=has_capability(db, current_user, "revenue.read"))


class DailyLeadEmailIn(BaseModel):
    enabled: Optional[bool] = None
    hour: Optional[int] = Field(default=None, ge=0, le=23)
    minute: Optional[int] = Field(default=None, ge=0, le=59)
    reminder: Optional[bool] = None


@router.get("/daily-lead-email/settings")
def get_daily_lead_email(current_user: User = Depends(_OWNERS), db: Session = Depends(get_db)) -> dict:
    from app.models.tenant import Tenant
    from app.services import lead_report_email
    return lead_report_email.settings_of(db.query(Tenant).filter_by(id=current_user.tenant_id).first())


@router.put("/daily-lead-email/settings")
def put_daily_lead_email(body: DailyLeadEmailIn, current_user: User = Depends(_OWNERS), db: Session = Depends(get_db)) -> dict:
    """Owner / manager. Audited reports.daily_lead_email_changed. The email goes to owners + managers at hour:minute IST,
    the reminder to reservations / concierge 30 minutes before (lead_report_email)."""
    from app.models.tenant import Tenant
    from app.services import lead_report_email
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    out = lead_report_email.put_settings(db, tenant, current_user, body.model_dump(exclude_none=True))
    db.commit()
    return out
