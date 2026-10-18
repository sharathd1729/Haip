"""HAIP's own website leads.

Public (no login, rate-limited per IP by RateLimitMiddleware + a per-visitor hourly count in the database):
  POST /public/leads                 book-demo | contact form -> platform_leads (+ a Leads360 lead in HAIP's sales workspace)

Owner of HAIP's sales workspace (PLATFORM_LEADS_TENANT_SLUG) only:
  GET  /platform-leads               the stored submissions, newest first
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db
from app.models.platform_lead import PlatformLead
from app.models.user import User, UserRole
from app.schemas.platform_leads import PlatformLeadAccepted, PlatformLeadRow, PlatformLeadSubmit
from app.services import platform_lead_service

log = structlog.get_logger()
router = APIRouter(tags=["platform-leads"])

MAX_BODY_BYTES = 16 * 1024


def client_ip(request: Request) -> Optional[str]:
    """Same rule as RateLimitMiddleware, so both limits count the same visitor."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None


def body_size_cap(request: Request) -> None:
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request too large.")


def store_submission(db: Session, body, request: Request, assessment_snapshot: Optional[dict] = None):
    """Shared by the lead form and the assessment report form. Maps service errors to HTTP."""
    try:
        return platform_lead_service.submit(
            db, body, ip=client_ip(request), user_agent=request.headers.get("user-agent"),
            assessment_snapshot=assessment_snapshot)
    except platform_lead_service.RateLimited:
        raise HTTPException(status_code=429, detail="Too many submissions from this connection. Please try again in an hour.",
                            headers={"Retry-After": "3600"})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/public/leads", response_model=PlatformLeadAccepted, status_code=201,
             dependencies=[Depends(body_size_cap)])
def submit_lead(body: PlatformLeadSubmit, request: Request, response: Response, db: Session = Depends(get_db)):
    lead, duplicate = store_submission(db, body, request)
    if duplicate:
        response.status_code = 200
    return PlatformLeadAccepted(id=lead.id, kind=lead.kind, duplicate=duplicate)


def require_sales_workspace_owner(current_user: User = Depends(require_roles(UserRole.OWNER)),
                                  db: Session = Depends(get_db)) -> User:
    """Owner of HAIP's own sales workspace. Any other workspace's owner gets 403 (these are HAIP's prospects)."""
    workspace = platform_lead_service.sales_workspace(db)
    if workspace is None or workspace.id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Only HAIP's sales workspace can see website leads.")
    return current_user


def _row(lead: PlatformLead) -> dict:
    return PlatformLeadRow(
        id=lead.id, kind=lead.kind, name=lead.name, email=lead.email, phone=lead.phone, company=lead.company,
        message=lead.message, details=lead.details or {}, is_spam=lead.is_spam, routing_status=lead.routing_status,
        workspace_inquiry_id=lead.workspace_inquiry_id, marketing_opt_in=lead.marketing_opt_in,
        created_at=lead.created_at.isoformat() if lead.created_at else "",
    ).model_dump()


@router.get("/platform-leads")
def list_platform_leads(
    kind: Optional[str] = Query(None, pattern="^(demo|contact|assessment)$"),
    include_spam: bool = False,
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_sales_workspace_owner),
    db: Session = Depends(get_db),
):
    rows = platform_lead_service.list_leads(db, kind=kind, include_spam=include_spam, limit=limit)
    return {"items": [_row(r) for r in rows], "count": len(rows)}
