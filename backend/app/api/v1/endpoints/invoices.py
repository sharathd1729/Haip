"""Invoice details settings, a booking's invoices and booking messages, and the WhatsApp booking-template pack.

  GET    /settings/invoice-profile               seller profile + payment automation + logo preview  (owner, manager)
  PUT    /settings/invoice-profile               save them (audited)                                   (owner, manager)
  POST   /settings/invoice-profile/logo          upload the invoice logo (re-encoded PNG, audited)     (owner, manager)
  DELETE /settings/invoice-profile/logo          back to the Branding logo / none (audited)            (owner, manager)
  GET    /bookings/{id}/invoices                 invoices and receipts of a booking                    (bookings.read)
  POST   /bookings/{id}/invoices/reissue         new invoice number, old one superseded (audited)      (owner, manager)
  GET    /invoices/{id}/pdf                      short-lived link to the PDF                           (bookings.read)
  GET    /bookings/{id}/booking-messages         WhatsApp messages HAIP sent for this booking          (bookings.read)
  GET    /messaging/templates/booking-pack       the 4 booking templates and their status              (owner, manager)
  POST   /messaging/templates/booking-pack       create the missing ones as DRAFTS (never submitted)   (owner, manager)
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.api.v1.endpoints.booking_detail import _get_stay
from app.core.audit import append_audit
from app.core.database import get_db
from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.invoice import InvoiceSettingsIn, ReissueRequest
from app.services import invoice_profile_service as ips
from app.services import invoice_service, media_storage, wa_booking_messages, wa_booking_pack
from app.services.authz_service import require_capability

log = structlog.get_logger()
router = APIRouter(tags=["invoices"])

_MANAGE = (UserRole.OWNER, UserRole.MANAGER)


def _tenant(db: Session, user: User) -> Tenant:
    tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return tenant


# ── Settings ─────────────────────────────────────────────────────────────────

@router.get("/settings/invoice-profile")
def get_invoice_profile(current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    return ips.settings_out(_tenant(db, current_user))


@router.put("/settings/invoice-profile")
def put_invoice_profile(body: InvoiceSettingsIn, current_user: User = Depends(require_roles(*_MANAGE)),
                        db: Session = Depends(get_db)):
    return ips.save_settings(db, _tenant(db, current_user), body, current_user.id)


@router.post("/settings/invoice-profile/logo")
def upload_invoice_logo(file: UploadFile = File(...), current_user: User = Depends(require_roles(*_MANAGE)),
                        db: Session = Depends(get_db)):
    content = file.file.read(ips.MAX_LOGO_BYTES + 1)
    try:
        return ips.save_logo(db, _tenant(db, current_user), content, file.content_type or "", current_user.id)
    except ips.LogoError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/settings/invoice-profile/logo")
def delete_invoice_logo(current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    return ips.remove_logo(db, _tenant(db, current_user), current_user.id)


# ── A booking's invoices ─────────────────────────────────────────────────────

def _invoices_out(db: Session, user: User, stay_id: str) -> dict:
    rows = invoice_service.list_for_stay(db, user.tenant_id, stay_id)
    return {"invoices": [invoice_service.invoice_out(i) for i in rows],
            "can_reissue": user.role.value in ("owner", "manager")}


@router.get("/bookings/{booking_id}/invoices")
def list_booking_invoices(booking_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                          _cap=Depends(require_capability("bookings.read"))):
    stay = _get_stay(db, current_user, booking_id)
    return _invoices_out(db, current_user, stay.id)


@router.post("/bookings/{booking_id}/invoices/reissue", status_code=201)
def reissue_invoice(booking_id: str, body: ReissueRequest, current_user: User = Depends(require_roles(*_MANAGE)),
                    db: Session = Depends(get_db)):
    """Issue an invoice for the booking as it stands now. With no invoice yet this is the first one (e.g. a booking
    paid in cash); otherwise the current invoice is marked superseded and keeps its number."""
    stay = _get_stay(db, current_user, booking_id)
    tenant = _tenant(db, current_user)
    try:
        new, old = invoice_service.reissue(db, tenant, stay, actor_id=current_user.id, place_of_supply=body.place_of_supply,
                                           buyer_gstin=body.buyer_gstin, reason=body.reason)
    except invoice_service.InvoiceError as exc:
        raise HTTPException(status_code=409 if "just reissued" in str(exc) else 422, detail=str(exc))
    append_audit(db, tenant_id=tenant.id, actor_user_id=current_user.id,
                 action="booking.invoice_reissued" if old else "booking.invoice_issued", target_type="booking",
                 target_id=stay.id, payload={"number": new.number, "replaces": old.number if old else None,
                                             "total": float(new.total), "reason": body.reason})
    db.commit()
    from app.workers.tasks.invoice_tasks import render_pdf
    try:
        render_pdf.delay(tenant_id=tenant.id, invoice_id=new.id)
    except Exception as exc:  # noqa: BLE001 -- the invoice exists; opening its PDF queues the render again
        log.error("invoice_render_enqueue_failed", tenant_id=tenant.id, invoice_id=new.id, error=str(exc))
    return _invoices_out(db, current_user, stay.id)


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf_link(invoice_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                     _cap=Depends(require_capability("bookings.read"))):
    inv = db.query(Invoice).filter_by(id=invoice_id, tenant_id=current_user.tenant_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if not inv.pdf_media_key:
        from app.workers.tasks.invoice_tasks import render_pdf
        try:
            render_pdf.delay(tenant_id=inv.tenant_id, invoice_id=inv.id)
        except Exception as exc:  # noqa: BLE001
            log.error("invoice_render_enqueue_failed", tenant_id=inv.tenant_id, invoice_id=inv.id, error=str(exc))
        raise HTTPException(status_code=409, detail="The PDF is still being prepared. Try again in a minute.")
    label = "Receipt" if inv.kind == "receipt" else "Invoice"
    filename = f"{label} {inv.number.replace('/', '-')}.pdf"
    url = media_storage.get_presigned_download_url(inv.pdf_media_key, filename)
    if not url:
        raise HTTPException(status_code=503, detail="Could not open the file storage. Try again in a moment.")
    return {"url": url, "filename": filename}


@router.get("/bookings/{booking_id}/booking-messages")
def booking_messages(booking_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                     _cap=Depends(require_capability("bookings.read"))):
    stay = _get_stay(db, current_user, booking_id)
    return {"messages": wa_booking_messages.messages_for_stay(db, current_user.tenant_id, stay.id),
            "templates": wa_booking_pack.statuses(db, current_user.tenant_id)}


# ── WhatsApp booking-template pack ───────────────────────────────────────────

@router.get("/messaging/templates/booking-pack")
def get_booking_pack(current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    return {"templates": wa_booking_pack.pack_out(db, current_user.tenant_id)}


@router.post("/messaging/templates/booking-pack")
def create_booking_pack(current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    return wa_booking_pack.create_drafts(db, current_user.tenant_id, current_user.id)
