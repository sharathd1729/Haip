"""The signed, recipient-bound, view-only report link (no login; analyst.delivery tokens, valid 7 days).

GET  /public/analyst/{token}                   the brief read-only (money only if the recipient may read revenue)
GET  /public/analyst/{token}/report.pdf        the same as a PDF (the WhatsApp template's document header)
POST /public/analyst/{token}/assign/start      {inquiry_id, user_id} e-mails a one-time code to the recipient
POST /public/analyst/{token}/assign/confirm    {nonce, code} assigns the lead (audited ``analyst.lead_assigned``)

Rate limited by the middleware's ``/api/v1/public/`` tier. A bad or expired token is a 404 with no detail.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tenant import Tenant
from app.services.analyst import delivery, pdf

router = APIRouter(prefix="/public/analyst", tags=["analyst-public"])


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inquiry_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nonce: str = Field(min_length=4, max_length=40)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


def _err(exc: delivery.DeliveryError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def _resolve(db: Session, token: str):
    try:
        return delivery.resolve(db, token)
    except delivery.DeliveryError as exc:
        raise _err(exc)


@router.get("/{token}")
def view(token: str, db: Session = Depends(get_db)):
    report, user = _resolve(db, token)
    return delivery.public_view(db, report, user)


@router.get("/{token}/report.pdf")
def report_pdf(token: str, db: Session = Depends(get_db)):
    report, user = _resolve(db, token)
    tenant = db.query(Tenant).filter_by(id=report.tenant_id).first()
    from app.services.analyst.reports import view as report_view
    data = pdf.render(report_view(report), brand_name=(tenant.brand_name or tenant.name) if tenant else "HAIP",
                      money=delivery._money(db, user))
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="report.pdf"', "Cache-Control": "private, no-store"})


@router.post("/{token}/assign/start")
def assign_start(token: str, body: StartIn, db: Session = Depends(get_db)):
    report, user = _resolve(db, token)
    try:
        return delivery.assign_start(db, report, user, body.inquiry_id, body.user_id)
    except delivery.DeliveryError as exc:
        raise _err(exc)


@router.post("/{token}/assign/confirm")
def assign_confirm(token: str, body: ConfirmIn, db: Session = Depends(get_db)):
    report, user = _resolve(db, token)
    try:
        return delivery.assign_confirm(db, report, user, body.nonce, body.code)
    except delivery.DeliveryError as exc:
        raise _err(exc)
