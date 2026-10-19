"""The latest quote on a Leads360 card and the quote lines of a lead's timeline. Read-only, one query per page of cards."""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.inquiry_360 import InquiryQuote

_SHOWN = ("issued", "pending_approval", "accepted")
HOW = {"sent": "sent on WhatsApp", "copied": "copied", None: "saved, not sent"}


def _valid_text(q: InquiryQuote) -> Optional[str]:
    from app.services.wa_booking_messages import day
    snap = q.snapshot or {}
    v = snap.get("valid_until")
    try:
        d = date.fromisoformat(v) if v else (q.valid_until.date() if q.valid_until else None)
    except ValueError:
        d = None
    return day(d) if d else None


def card_out(q: InquiryQuote) -> dict:
    snap = q.snapshot or {}
    return {"quote_id": q.id, "amount": float(q.amount), "status": q.status, "shared_via": q.shared_via,
            "how": "waiting for the owner's OK" if q.status == "pending_approval" else HOW.get(q.shared_via, "saved, not sent"),
            "valid_until": q.valid_until.isoformat() if q.valid_until else None, "valid_until_text": _valid_text(q),
            "label": snap.get("package_name") or q.package_key}


def latest_for(db: Session, tenant_id: str, inquiry_ids: list[str]) -> dict[str, dict]:
    if not inquiry_ids:
        return {}
    rows = (db.query(InquiryQuote).filter(InquiryQuote.tenant_id == tenant_id, InquiryQuote.inquiry_id.in_(inquiry_ids),
                                          InquiryQuote.status.in_(_SHOWN), InquiryQuote.option_rank == 1)
            .order_by(InquiryQuote.created_at.desc()).all())
    out: dict[str, dict] = {}
    for q in rows:
        out.setdefault(q.inquiry_id, card_out(q))
    return out


def timeline_entries(db: Session, tenant_id: str, inquiry_id: str, limit: int = 10) -> list[dict]:
    from app.services.wa_booking_messages import inr
    rows = (db.query(InquiryQuote).filter(InquiryQuote.tenant_id == tenant_id, InquiryQuote.inquiry_id == inquiry_id,
                                          InquiryQuote.option_rank == 1)
            .order_by(InquiryQuote.created_at.desc()).limit(limit).all())
    out = []
    for q in rows:
        c = card_out(q)
        bits = [f"Quote {inr(q.amount)}", c["label"] or "", c["how"] if q.status in _SHOWN else (q.status or "")]
        if c["valid_until_text"] and q.status in ("issued", "pending_approval"):
            bits.append(f"valid till {c['valid_until_text']}")
        out.append({"id": f"quote-{q.id}", "channel": "quote", "direction": "outbound" if q.shared_via == "sent" else "system",
                    "occurred_at": q.shared_at or q.created_at, "content_preview": " · ".join(b for b in bits if b)[:120],
                    "is_ai_generated": False})
    return out
