"""A sample PDF for a WhatsApp template's DOCUMENT header, so the owner can submit it without making one by hand.

Meta's review needs a sample file for a document header. The real sends attach this guest's quote or invoice; the sample
is only for the reviewer. It is drawn with the same renderers as the real documents (``quote_pdf`` / ``invoice_pdf``),
with this workspace's seller details and logo, and DUMMY guest and trip values (the booking pack's own examples:
"Sample Guest", Coorg, 30 Oct - 1 Nov). No guest, booking or quote row is read or written, and every page says SAMPLE.

Which document: a template whose name says quote -> a quotation; payment received / receipt -> a payment receipt;
anything else (booking confirmed, invoices) -> a tax invoice.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.services import invoice_pdf, quote_pdf, wa_booking_pack

SAMPLE_NOTE = "SAMPLE for WhatsApp template review. Not a real booking."
SAMPLE_BUYER = {"name": "Sample Guest"}

# The booking pack's example trip: Coorg, 6 guests, total 89,880 incl. 5% GST, half paid as the advance.
_TAXABLE = Decimal("85600.00")
_GST = Decimal("4280.00")
_TOTAL = _TAXABLE + _GST
_ADVANCE = Decimal("44940.00")


def document_kind(template_name: str) -> str:
    """quote | receipt | invoice, from the template's name."""
    name = (template_name or "").lower()
    if name == wa_booking_pack.QUOTE_PAYMENT or "quote" in name:
        return "quote"
    if name == wa_booking_pack.PAYMENT_RECEIVED or "receipt" in name or "payment_received" in name:
        return "receipt"
    return "invoice"


def _seller_and_logo(tenant: Tenant) -> tuple[dict, Optional[bytes]]:
    from app.services import invoice_profile_service, invoice_service
    seller = invoice_service._seller(invoice_service.get_profile(tenant), tenant)
    return seller, invoice_profile_service.logo_bytes(tenant)


def _trip_dates(today: date) -> tuple[date, date]:
    start = today + timedelta(days=10)
    return start, start + timedelta(days=2)


def _quote_pdf(seller: dict, logo: Optional[bytes], today: date) -> bytes:
    check_in, check_out = _trip_dates(today)
    snapshot = {
        "inputs": {"adults": 6, "children": 0, "check_in": check_in.isoformat(), "check_out": check_out.isoformat()},
        "destination": {"name": "Coorg"},
        "package_name": "48-hour Retreat (sample)",
        "lines": [{"label": "Caravan, 2 nights", "detail": "Sample line", "amount": "70000.00"},
                  {"label": "Driver and fuel", "detail": "Sample line", "amount": "15600.00"}],
        "gst_percent": 5, "taxable": str(_TAXABLE), "gst": str(_GST), "total": str(_TOTAL),
        "advance": str(_ADVANCE), "advance_percent": 50,
        "at_actuals": ["Tolls and parking"],
    }
    return quote_pdf.render(number="SAMPLE-0001", issued_on=today, valid_until=today + timedelta(days=3), seller=seller,
                            buyer=SAMPLE_BUYER, options=[{"title": "Sample option", "snapshot": snapshot, "guests": 6}],
                            logo=logo)


def _invoice_pdf(kind: str, seller: dict, logo: Optional[bytes], now: datetime) -> bytes:
    half = (_GST / 2).quantize(Decimal("0.01"))
    if kind == "receipt":
        inv = Invoice(kind="receipt", number="SAMPLE-RCPT-0001", issued_at=now, seller=seller, buyer=SAMPLE_BUYER,
                      lines=[{"description": "Balance payment (sample)", "detail": None, "quantity": 1,
                              "amount": str(_TOTAL - _ADVANCE), "taxable": None}],
                      gst_rate=0, total=_TOTAL - _ADVANCE, amount_received=_TOTAL, balance_due=Decimal("0"),
                      booking_ref="#SAMPLE01", notes=SAMPLE_NOTE)
    else:
        inv = Invoice(kind="invoice", number="SAMPLE-INV-0001", issued_at=now, seller=seller, buyer=SAMPLE_BUYER,
                      lines=[{"description": "Caravan stay, 2 nights (sample)", "detail": "Coorg", "quantity": 1,
                              "amount": "73500.00", "taxable": "70000.00"},
                             {"description": "Driver and fuel (sample)", "detail": None, "quantity": 1,
                              "amount": "16380.00", "taxable": "15600.00"}],
                      gst_rate=5, taxable_value=_TAXABLE, cgst=half, sgst=_GST - half, igst=Decimal("0"), total=_TOTAL,
                      amount_received=_ADVANCE, balance_due=_TOTAL - _ADVANCE, booking_ref="#SAMPLE01",
                      place_of_supply=seller.get("state_code"), notes=SAMPLE_NOTE)
    return invoice_pdf.render(inv, logo=logo)


def sample_pdf(tenant: Tenant, template_name: str, now: Optional[datetime] = None) -> tuple[bytes, str]:
    """(PDF bytes, file name) of a dummy quote / receipt / invoice for this template's header."""
    now = now or datetime.now(timezone.utc)
    kind = document_kind(template_name)
    seller, logo = _seller_and_logo(tenant)
    if kind == "quote":
        return _quote_pdf(seller, logo, now.date()), "sample-quote.pdf"
    return _invoice_pdf(kind, seller, logo, now), f"sample-{kind}.pdf"


def needs_sample(components: list) -> bool:
    """True when the template has a DOCUMENT header with no sample handle yet."""
    for comp in components or []:
        if (comp.get("type") or "").upper() == "HEADER" and (comp.get("format") or "").upper() == "DOCUMENT":
            handle = (comp.get("example") or {}).get("header_handle") or []
            return not handle or not str(handle[0]).strip()
    return False


def with_handle(components: list, handle: str) -> list:
    """A copy of the components with the DOCUMENT header's example set to this handle (a new list, so the JSON
    column sees the change)."""
    out = []
    for comp in components or []:
        comp = dict(comp)
        if (comp.get("type") or "").upper() == "HEADER" and (comp.get("format") or "").upper() == "DOCUMENT":
            comp["example"] = {**(comp.get("example") or {}), "header_handle": [handle]}
        out.append(comp)
    return out
