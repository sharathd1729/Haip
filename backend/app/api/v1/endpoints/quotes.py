"""Staff quote builder (services/quote_builder_service.py). No module gate: quoting is core sales work, not an AI feature.

GET  /quotes/catalog          packages, routes (+ pending drafts), reseller terms, kits, vehicles, what the caller may do
GET  /quotes/leads?q=         lead picker (same visibility as /leads)
POST /quotes/preview          price a primary option and an optional fallback; NO database writes; may use drafts
POST /quotes                  save both options to a lead (published records only); audited `quote.issued`; next step -> task
GET  /quotes?inquiry_id=      a lead's quotes, newest first
GET  /quotes/{id}             one quote + whether it is still valid, its payment link, where the send stands, what blocks it
POST /quotes/{id}/send        a Razorpay link per option (primary + fallback) + the WhatsApp quote with its PDF (queued);
                              typed refusals; idempotent (live links reused, never sent twice). quote_send_service.py

Writes and previews need `quotes.write` (owner, manager, reservations, concierge by default); reads need `leads.read` or
`bookings.read`. The catalogue needs any of quotes.write / business_data.draft / business_data.publish / settings.manage.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.quotes import QuoteIssueIn, QuotePreviewIn
from app.services import quote_builder_service as svc
from app.services import quote_send_service as qss
from app.services import quote_service as qs
from app.services.authz_service import require_capability

router = APIRouter(prefix="/quotes", tags=["quotes"])

_write = Depends(require_capability("quotes.write"))
_read = Depends(require_capability("leads.read", "bookings.read"))
_catalog = Depends(require_capability("quotes.write", "business_data.draft", "business_data.publish", "settings.manage"))


@router.get("/catalog")
def catalog(current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_catalog):
    return svc.catalog(db, current_user)


@router.get("/leads")
def lead_picker(q: str = Query("", max_length=80), current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    return svc.search_leads(db, current_user, q)


@router.post("/preview")
def preview(body: QuotePreviewIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    return svc.preview(db, current_user.tenant_id, body)          # reads only; nothing is committed


@router.post("", status_code=201)
def issue(body: QuoteIssueIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    try:
        result = svc.issue(db, current_user, body)
    except qs.QuoteError as exc:                   # raised before anything is written; the session is not committed
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})
    db.commit()
    return result


@router.get("")
def list_quotes(inquiry_id: str = Query(..., max_length=64), current_user: User = Depends(get_current_user),
                db: Session = Depends(get_db), _cap=_read):
    rows: Optional[list] = svc.list_quotes(db, current_user, inquiry_id)
    if rows is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Lead not found."})
    return rows


@router.get("/{quote_id}")
def get_quote(quote_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_read):
    row = svc.get_quote(db, current_user, quote_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Quote not found."})
    return row


@router.post("/{quote_id}/send")
def send_quote(quote_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    try:
        return qss.send(db, current_user, quote_id)
    except qs.QuoteError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})
