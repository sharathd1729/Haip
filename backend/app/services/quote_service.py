"""Issued quotes: what a guest was actually quoted, kept as a snapshot (docs/ai/RATHA_KB_EVOLUTION.md §3.3).

A PackageQuote from package_pricing_service is a calculation. Issuing it stores a copy in `inquiry_quotes` -- amounts, lines, inputs,
inclusions/exclusions and the exact business-record versions used -- so that a later price change, a rollback or a deactivation
cannot alter or lose what was agreed. Reading an issued quote never recomputes anything from live records.

Issuing the same inputs against the same record versions twice returns the same quote (idempotent); different inputs supersede the
previous active quote for that enquiry. The caller commits.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.services import business_data_service as bds
from app.services.package_pricing_service import PackageQuote


class QuoteError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _end_of_day_utc(db: Session, tenant_id: str, d: date) -> datetime:
    from app.core.tenant_tz import get_tz
    from app.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    tz = get_tz(tenant) if tenant else timezone.utc
    return datetime.combine(d, time(23, 59, 59), tzinfo=tz).astimezone(timezone.utc)


def issue_quote(db: Session, tenant_id: str, inquiry_id: str, quote: PackageQuote, actor_id: Optional[str] = None) -> InquiryQuote:
    if not quote.ok:
        raise QuoteError("not_quotable", f"A refused quote cannot be issued ({quote.reason}).", 422)
    if db.query(Inquiry.id).filter_by(id=inquiry_id, tenant_id=tenant_id).first() is None:
        raise QuoteError("not_found", "Enquiry not found.", 404)

    h = quote.params_hash()
    now = datetime.now(timezone.utc)
    active = db.query(InquiryQuote).filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id, is_active=True).all()
    for q in active:
        if q.params_hash == h and q.status == "issued" and (q.valid_until is None or _aware(q.valid_until) >= now):
            return q                                                      # same inputs, same terms: the quote already issued
    for q in active:
        q.is_active, q.status = False, "superseded"

    ci = date.fromisoformat(quote.inputs["check_in"])
    co = date.fromisoformat(quote.inputs["check_out"])
    row = InquiryQuote(
        tenant_id=tenant_id, inquiry_id=inquiry_id, amount=quote.total, currency=quote.currency,
        valid_until=_end_of_day_utc(db, tenant_id, quote.valid_until), created_by=actor_id, is_active=True,
        package_key=quote.package_key, check_in=ci, check_out=co, guests=quote.inputs["adults"] + quote.inputs["children"],
        snapshot=quote.to_snapshot(), record_refs=quote.record_refs, params_hash=h, status="issued",
    )
    db.add(row)
    db.flush()
    append_audit(
        db, tenant_id=tenant_id, action="quote.issued", actor_user_id=actor_id, target_type="inquiry_quote", target_id=row.id,
        payload={"inquiry_id": inquiry_id, "package_key": quote.package_key, "total": str(quote.total), "valid_until": quote.valid_until.isoformat(),
                 "record_refs": [(r["kind"], r["key"], r["version"]) for r in quote.record_refs],
                 "custom_lines": [(l.label, str(l.amount)) for l in quote.lines if l.custom]},
    )
    return row


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_issued_quote(db: Session, tenant_id: str, quote_id: str) -> InquiryQuote:
    row = db.query(InquiryQuote).filter_by(id=quote_id, tenant_id=tenant_id).first()
    if row is None:
        raise QuoteError("not_found", "Quote not found.", 404)
    return row


def check_still_valid(db: Session, tenant_id: str, row: InquiryQuote, at: Optional[datetime] = None) -> dict:
    """Is this issued quote still safe to honour or build on? Used before acceptance becomes a booking.

    {"valid": bool, "reasons": [...], "terms_changed": [{"kind","key","issued_version","current_version"}]}. A changed term does not
    rewrite the quote; it tells the caller to re-quote or to ask a person, because the price the guest holds may differ from today's."""
    at = at or datetime.now(timezone.utc)
    reasons: list[str] = []
    if row.status != "issued" or not row.is_active:
        reasons.append(f"quote is {row.status or 'inactive'}")
    if row.valid_until is not None and _aware(row.valid_until) < at:
        reasons.append("quote has expired")
    changed = []
    today = bds.tenant_today(db, tenant_id)
    for ref in row.record_refs or []:
        cur = bds.get_effective(db, tenant_id, ref["kind"], ref["key"], today)
        if cur is None:
            changed.append({"kind": ref["kind"], "key": ref["key"], "issued_version": ref["version"], "current_version": None})
        elif cur.version != ref["version"]:
            changed.append({"kind": ref["kind"], "key": ref["key"], "issued_version": ref["version"], "current_version": cur.version})
    if changed:
        reasons.append("the terms it was built on have changed since it was issued")
    return {"valid": not reasons, "reasons": reasons, "terms_changed": changed}


def inr(amount) -> str:
    """₹1,25,000 (Indian grouping). Paise are shown only when present."""
    d = Decimal(str(amount))
    sign, d = ("-" if d < 0 else ""), abs(d)
    whole, frac = divmod(d, 1)
    digits = str(int(whole))
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    text = ",".join(groups + [tail]) if groups else tail
    paise = f"{frac:.2f}"[1:] if frac else ""
    return f"{sign}₹{text}{paise}"


def message_text(row: InquiryQuote, guest_name: str = "") -> str:
    """The WhatsApp-ready text of an issued quote, built only from its snapshot. A person reviews and sends it; nothing here sends."""
    snap = row.snapshot or {}
    inputs = snap.get("inputs") or {}
    guests = int(inputs.get("adults") or 0) + int(inputs.get("children") or 0)
    out = [f"*{snap.get('package_name') or 'Your trip'}*", "",
           f"Dates: {inputs.get('check_in')} to {inputs.get('check_out')}  |  Guests: {guests}", ""]
    for line in snap.get("lines") or []:
        out.append(f"- {line['label']}: {inr(line['amount'])}")
    out.append("")
    if snap.get("gst") is not None:
        out.append(f"GST ({Decimal(str(snap.get('gst_percent'))).normalize():f}%): {inr(snap['gst'])}")
    out.append(f"*Total: {inr(snap.get('total'))}*")
    if snap.get("advance") is not None:
        out.append(f"Advance to confirm ({Decimal(str(snap.get('advance_percent'))).normalize():f}%): {inr(snap['advance'])}")
    if snap.get("inclusions"):
        out += ["", "Included: " + ", ".join(snap["inclusions"])]
    if snap.get("exclusions"):
        out.append("Not included: " + ", ".join(snap["exclusions"]))
    if snap.get("valid_until"):
        out += ["", f"This quote is valid until {snap['valid_until']}."]
    first = (guest_name or "").split()[0] if guest_name else ""
    out.append(f"Reply YES to confirm{', ' + first if first else ''}.")
    return "\n".join(out)
