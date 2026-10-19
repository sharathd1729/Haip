"""Issue tax invoices and payment receipts for bookings.

Rules (the accountant must confirm the ones marked ASSUMPTION; see CLAUDE.md "Invoices"):
* Booking amounts (stay charge, add-ons) INCLUDE GST (ASSUMPTION: quotes say "incl. GST"). Each line's taxable value is
  its amount / (1 + rate); the tax is the rest, so the invoice total always equals the booking total.
* GST is charged only when the seller profile has a GSTIN (ASSUMPTION: without one the business is not registered).
* CGST + SGST (half each) when the place of supply is the seller's state, else IGST. Place of supply defaults to the
  seller's state (ASSUMPTION: the guest's state is not recorded; staff can set it when reissuing).
* The tax invoice is issued once, for the whole booking, on the first payment. Later payments get a receipt against it
  (no tax lines). A change to the booking is a "Reissue": a new number, the old invoice marked superseded.
* Numbers: "{prefix}/{financial year}/{0001}", one series per tenant, financial year (April to March, IST) and prefix.
  Issued rows are immutable: only status (issued -> superseded/void) and pdf_media_key may change, enforced below.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import event, inspect, update
from sqlalchemy.orm import Session

from app.models.invoice import Invoice, InvoiceSequence
from app.models.property import Stay
from app.models.stay_finance import StayAddOn, StayPayment
from app.models.tenant import Tenant
from app.schemas.invoice import GST_STATES, InvoiceProfile
from app.services import booking_service as bsvc

log = structlog.get_logger()

IST = ZoneInfo("Asia/Kolkata")
_CENT = Decimal("0.01")
_MUTABLE = {"status", "pdf_media_key", "updated_at"}


class InvoiceError(ValueError):
    """A reason an invoice cannot be issued, safe to show to staff."""


# ── Immutability ─────────────────────────────────────────────────────────────

@event.listens_for(Invoice, "before_update")
def _issued_documents_do_not_change(mapper, connection, target):  # noqa: ARG001
    state = inspect(target)
    changed = {a.key for a in state.attrs if a.history.has_changes()}
    illegal = changed - _MUTABLE
    if illegal:
        raise InvoiceError(f"An issued {target.kind} cannot be edited ({', '.join(sorted(illegal))}). Reissue it instead.")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)


def financial_year(d: date) -> str:
    """Indian financial year: April to March. 18 Oct 2026 -> "2026-27"; 10 Feb 2027 -> "2026-27"."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def today_ist() -> date:
    return datetime.now(IST).date()


def booking_ref(stay: Stay) -> str:
    return "#" + stay.id.replace("-", "")[:8].upper()


def get_profile(tenant: Tenant) -> InvoiceProfile:
    raw = (tenant.brand_config or {}).get("invoice_profile") or {}
    try:
        return InvoiceProfile(**raw)
    except ValueError:                      # stored before a rule tightened: read leniently, the settings page fixes it
        log.warning("invoice_profile_invalid", tenant_id=tenant.id)
        return InvoiceProfile.model_construct(**{**InvoiceProfile().model_dump(), **raw})


def next_number(db: Session, tenant_id: str, fy: str, prefix: str) -> str:
    """Take the next number in a series. The UPDATE holds the row lock until the caller's transaction ends, so
    concurrent issuers queue behind each other on PostgreSQL; a rollback hands the number back."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    db.execute(
        insert(InvoiceSequence)
        .values(id=_uuid(), tenant_id=tenant_id, financial_year=fy, prefix=prefix, next_number=1,
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        .on_conflict_do_nothing(index_elements=["tenant_id", "financial_year", "prefix"])
    )
    taken = db.execute(
        update(InvoiceSequence)
        .where(InvoiceSequence.tenant_id == tenant_id, InvoiceSequence.financial_year == fy, InvoiceSequence.prefix == prefix)
        .values(next_number=InvoiceSequence.next_number + 1, updated_at=datetime.now(timezone.utc))
        .returning(InvoiceSequence.next_number)
        .execution_options(synchronize_session=False)
    ).scalar_one() - 1
    return f"{prefix}/{fy}/{taken:04d}"


def _uuid() -> str:
    from app.models.base import gen_uuid
    return gen_uuid()


def split_tax(total_tax: Decimal, intra_state: bool) -> dict:
    if not intra_state:
        return {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": total_tax}
    cgst = (total_tax / 2).quantize(_CENT, rounding=ROUND_HALF_UP)
    return {"cgst": cgst, "sgst": total_tax - cgst, "igst": Decimal("0.00")}


def compute(lines: list[dict], rate: float, seller_state: Optional[str], place_of_supply: Optional[str]) -> dict:
    """Lines are GST-inclusive amounts. Returns the lines with their taxable value plus the invoice totals."""
    r = Decimal(str(rate or 0))
    out_lines, taxable_total, gross_total = [], Decimal("0.00"), Decimal("0.00")
    for ln in lines:
        gross = _d(ln["amount"])
        taxable = (gross / (1 + r / 100)).quantize(_CENT, rounding=ROUND_HALF_UP) if r else gross
        out_lines.append({**ln, "amount": float(gross), "taxable": float(taxable)})
        taxable_total += taxable
        gross_total += gross
    tax = gross_total - taxable_total
    pos = place_of_supply or seller_state
    split = split_tax(tax, intra_state=(not seller_state or pos == seller_state))
    return {"lines": out_lines, "taxable_value": taxable_total, "total": gross_total, "place_of_supply": pos, **split}


def stay_lines(db: Session, tenant_id: str, stay: Stay) -> list[dict]:
    prop = stay.property
    nights = max(0, (stay.check_out - stay.check_in).days)
    span = f"{stay.check_in:%d %b %Y} to {stay.check_out:%d %b %Y}"
    lines = [{"description": prop.name if prop else "Stay", "quantity": 1, "amount": float(stay.total_amount or 0),
              "detail": f"{span}, {nights} night{'s' if nights != 1 else ''}" if nights else span}]
    for a in db.query(StayAddOn).filter_by(tenant_id=tenant_id, stay_id=stay.id).order_by(StayAddOn.created_at).all():
        amount = _d(a.quantity * Decimal(str(a.unit_price)))
        lines.append({"description": a.name, "quantity": a.quantity, "amount": float(amount),
                      "detail": f"{a.quantity} x Rs. {Decimal(str(a.unit_price)):,.2f}" if a.quantity != 1 else ""})
    return [ln for ln in lines if ln["amount"] > 0 or ln is lines[0]]


def quote_gst_rate(db: Session, tenant_id: str, stay_id: str) -> Optional[float]:
    """The GST rate of the rate-calculator quote this booking was made from (its paid advance link), or None. The quote's total
    already includes that GST (inclusive or added on top), and the booking total is that total, so splitting it at this rate
    gives back the quote's own tax."""
    from app.models.inquiry_360 import InquiryQuote
    from app.models.stay_finance import StayPaymentLink
    row = (db.query(InquiryQuote.snapshot).join(StayPaymentLink, StayPaymentLink.inquiry_quote_id == InquiryQuote.id)
           .filter(StayPaymentLink.tenant_id == tenant_id, StayPaymentLink.stay_id == stay_id, InquiryQuote.tenant_id == tenant_id)
           .first())
    snap = (row[0] if row else None) or {}
    if snap.get("kind") != "calculator" or snap.get("gst_percent") is None:
        return None
    return float(Decimal(str(snap["gst_percent"])))


def _seller(profile: InvoiceProfile, tenant: Tenant) -> dict:
    return {"legal_name": profile.legal_name or tenant.brand_name or tenant.name, "gstin": profile.gstin,
            "address": profile.address, "state_code": profile.state_code,
            "state": GST_STATES.get(profile.state_code or "", None), "sac_code": profile.sac_code,
            "brand_name": tenant.brand_name or tenant.name}


def _buyer(stay: Stay, buyer_gstin: Optional[str], pos: Optional[str]) -> dict:
    g = stay.guest
    phone = g.phone if g and g.phone and not str(g.phone).startswith("DELETED_") else None
    return {"name": (g.name if g else None) or "Guest", "phone": phone, "email": g.email if g else None,
            "gstin": buyer_gstin, "state_code": pos, "state": GST_STATES.get(pos or "", None)}


def current_invoice(db: Session, tenant_id: str, stay_id: str) -> Optional[Invoice]:
    return (db.query(Invoice).filter_by(tenant_id=tenant_id, stay_id=stay_id, kind="invoice", status="issued")
            .order_by(Invoice.issued_at.desc()).first())


def list_for_stay(db: Session, tenant_id: str, stay_id: str) -> list[Invoice]:
    return db.query(Invoice).filter_by(tenant_id=tenant_id, stay_id=stay_id).order_by(Invoice.issued_at.desc(), Invoice.number.desc()).all()


# ── Issue ────────────────────────────────────────────────────────────────────

def issue_invoice(db: Session, tenant: Tenant, stay: Stay, *, actor_id: Optional[str] = None,
                  place_of_supply: Optional[str] = None, buyer_gstin: Optional[str] = None,
                  supersedes: Optional[Invoice] = None, notes: Optional[str] = None,
                  payment_id: Optional[str] = None) -> Invoice:
    """A tax invoice for the booking as it is now. ``payment_id`` = the payment that triggered it (so a retried
    follow-up task finds it instead of issuing twice). Flushes; the caller commits (and audits)."""
    profile = get_profile(tenant)
    missing = profile.missing_for_invoice()
    if missing:
        raise InvoiceError(f"Add the {', '.join(missing)} under Settings > Invoice details before invoices can be issued.")
    lines = stay_lines(db, tenant.id, stay)
    rate = profile.gst_rate if profile.gstin else 0.0
    quoted = quote_gst_rate(db, tenant.id, stay.id)
    if quoted is not None:                  # booked from a paid rate-calculator quote: its GST slab, not the profile's
        rate = quoted
    calc = compute(lines, rate, profile.state_code, place_of_supply)
    if calc["total"] <= 0:
        raise InvoiceError("This booking has no amount to invoice yet.")
    fin = bsvc.financials_for(db, tenant.id, [stay])[stay.id]
    issued = today_ist()
    fy = financial_year(issued)
    inv = Invoice(
        tenant_id=tenant.id, stay_id=stay.id, kind="invoice", number=next_number(db, tenant.id, fy, profile.invoice_prefix),
        financial_year=fy, status="issued", gst_rate=rate, taxable_value=calc["taxable_value"], cgst=calc["cgst"],
        sgst=calc["sgst"], igst=calc["igst"], total=calc["total"], amount_received=_d(fin["paid"]),
        balance_due=max(calc["total"] - _d(fin["paid"]), Decimal("0.00")), place_of_supply=calc["place_of_supply"],
        lines=calc["lines"], seller=_seller(profile, tenant), buyer=_buyer(stay, buyer_gstin, calc["place_of_supply"]),
        booking_ref=booking_ref(stay), supersedes_id=supersedes.id if supersedes else None, notes=notes,
        payment_id=payment_id, created_by=actor_id, issued_at=datetime.now(timezone.utc),
    )
    db.add(inv)
    db.flush()
    return inv


def issue_receipt(db: Session, tenant: Tenant, stay: Stay, payment: StayPayment, invoice: Optional[Invoice],
                  *, actor_id: Optional[str] = None) -> Invoice:
    """A receipt for one later payment, against the booking's tax invoice. Shows received to date and the balance."""
    profile = get_profile(tenant)
    missing = profile.missing_for_invoice()
    if missing:
        raise InvoiceError(f"Add the {', '.join(missing)} under Settings > Invoice details before receipts can be issued.")
    fin = bsvc.financials_for(db, tenant.id, [stay])[stay.id]
    issued = today_ist()
    fy = financial_year(issued)
    method = "Razorpay" if payment.method == "razorpay" else payment.method.replace("_", " ").title()
    amount = _d(payment.amount)
    rec = Invoice(
        tenant_id=tenant.id, stay_id=stay.id, kind="receipt", number=next_number(db, tenant.id, fy, profile.receipt_prefix),
        financial_year=fy, status="issued", gst_rate=0, total=amount, taxable_value=0,
        amount_received=_d(fin["paid"]), balance_due=_d(fin["outstanding"]),
        place_of_supply=invoice.place_of_supply if invoice else profile.state_code,
        lines=[{"description": "Payment received", "quantity": 1, "amount": float(amount), "taxable": 0,
                "detail": f"{method}{', ' + payment.reference if payment.reference else ''} on {payment.paid_on:%d %b %Y}"}],
        seller=_seller(profile, tenant), buyer=_buyer(stay, (invoice.buyer or {}).get("gstin") if invoice else None,
                                                      invoice.place_of_supply if invoice else None),
        booking_ref=booking_ref(stay), invoice_id=invoice.id if invoice else None, payment_id=payment.id,
        notes=f"Against tax invoice {invoice.number}" if invoice else None,
        created_by=actor_id, issued_at=datetime.now(timezone.utc),
    )
    db.add(rec)
    db.flush()
    return rec


def reissue(db: Session, tenant: Tenant, stay: Stay, *, actor_id: Optional[str], place_of_supply: Optional[str] = None,
            buyer_gstin: Optional[str] = None, reason: Optional[str] = None) -> tuple[Invoice, Optional[Invoice]]:
    """Issue a fresh invoice; the current one (if any) is marked superseded by one guarded UPDATE, so two reissues at
    the same time cannot both supersede it. Returns (new, old)."""
    old = current_invoice(db, tenant.id, stay.id)
    if old is not None:
        done = db.execute(
            update(Invoice).where(Invoice.id == old.id, Invoice.tenant_id == tenant.id, Invoice.status == "issued")
            .values(status="superseded", updated_at=datetime.now(timezone.utc)).execution_options(synchronize_session=False)
        ).rowcount
        if done != 1:
            raise InvoiceError("This invoice was just reissued by someone else. Reload the booking.")
        db.expire(old, ["status"])
        if place_of_supply is None:
            place_of_supply = old.place_of_supply
        if buyer_gstin is None:
            buyer_gstin = (old.buyer or {}).get("gstin")
    new = issue_invoice(db, tenant, stay, actor_id=actor_id, place_of_supply=place_of_supply, buyer_gstin=buyer_gstin,
                        supersedes=old, notes=(f"Replaces {old.number}." if old else None) if not reason else
                        (f"Replaces {old.number}: {reason}" if old else reason))
    return new, old


def invoice_out(inv: Invoice) -> dict:
    return {
        "id": inv.id, "kind": inv.kind, "number": inv.number, "status": inv.status, "financial_year": inv.financial_year,
        "issued_at": inv.issued_at.isoformat() if inv.issued_at else None, "total": float(inv.total),
        "taxable_value": float(inv.taxable_value), "cgst": float(inv.cgst), "sgst": float(inv.sgst), "igst": float(inv.igst),
        "gst_rate": float(inv.gst_rate), "amount_received": float(inv.amount_received), "balance_due": float(inv.balance_due),
        "place_of_supply": inv.place_of_supply, "booking_ref": inv.booking_ref, "supersedes_id": inv.supersedes_id,
        "invoice_id": inv.invoice_id, "payment_id": inv.payment_id, "pdf_ready": bool(inv.pdf_media_key), "notes": inv.notes,
    }
