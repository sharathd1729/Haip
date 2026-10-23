"""Reports > "Why we win / lose" (GET /reports/outcome-reasons; lead_outcome). Guest enquiries only (lead_types).

Basis ``closed`` (default): leads that entered a closed-won / closed-lost stage in the period (IST days,
``inquiries.current_stage_entered_at``). Basis ``checkin``: leads closed (now) whose check-in falls in the period
(``inquiries.check_in`` is a string: unreadable ones are counted in ``skipped``).

Per side (won / lost) and reason: ``confirmed`` (a reason recorded by a person, a person confirming the AI, or a rule) apart
from ``proposed`` (only the AI's proposal, nobody confirmed it yet); leads with neither are ``not_recorded``. The two are
never added into one number.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.services import lead_outcome
from app.services.date_presets import ist_range_to_utc
from app.services.lead_types import is_guest_sql

BASES = ("closed", "checkin")


def _date(v) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def build(db: Session, tenant_id: str, d_from: date, d_to: date, basis: str = "closed") -> dict:
    if basis not in BASES:
        raise ValueError("basis must be closed or checkin")
    if d_to < d_from:
        raise ValueError("'to' is before 'from'")
    q = (db.query(Inquiry, PipelineStage).join(PipelineStage, PipelineStage.id == Inquiry.stage_id)
         .filter(Inquiry.tenant_id == tenant_id, PipelineStage.tenant_id == tenant_id, is_guest_sql(Inquiry.lead_type),
                 (PipelineStage.is_closed_won.is_(True)) | (PipelineStage.is_closed_lost.is_(True))))
    skipped = 0
    if basis == "closed":
        start, end = ist_range_to_utc(d_from.isoformat(), d_to.isoformat())[2:]
        rows = q.filter(Inquiry.current_stage_entered_at >= start, Inquiry.current_stage_entered_at <= end).all()
    else:
        rows = []
        for inq, st in q.filter(Inquiry.check_in.isnot(None), Inquiry.check_in >= d_from.isoformat(),
                                Inquiry.check_in <= d_to.isoformat() + "~").all():
            ci = _date(inq.check_in)
            if ci is None:
                skipped += 1
            elif d_from <= ci <= d_to:
                rows.append((inq, st))
    out = {}
    for kind in ("won", "lost"):
        confirmed, proposed, missing = Counter(), Counter(), 0
        for inq, st in rows:
            if (kind == "won") != bool(st.is_closed_won):
                continue
            p = inq.outcome_proposal if isinstance(inq.outcome_proposal, dict) else {}
            if inq.outcome_reason in lead_outcome.CATALOGUE[kind]:
                confirmed[inq.outcome_reason] += 1
            elif p.get("status") == "ready" and p.get("kind") == kind and p.get("reason") in lead_outcome.CATALOGUE[kind]:
                proposed[p["reason"]] += 1
            else:
                missing += 1
        reasons = [{"reason": r, "label": label, "confirmed": confirmed[r], "proposed": proposed[r]}
                   for r, label in lead_outcome.CATALOGUE[kind].items()]
        reasons.sort(key=lambda x: (-(x["confirmed"] + x["proposed"]), x["label"]))
        out[kind] = {"total": sum(confirmed.values()) + sum(proposed.values()) + missing, "confirmed": sum(confirmed.values()),
                     "proposed": sum(proposed.values()), "not_recorded": missing, "reasons": reasons}
    return {"from": d_from.isoformat(), "to": d_to.isoformat(), "basis": basis, "timezone": "Asia/Kolkata", "skipped": skipped,
            **out, "definitions": {
                "confirmed": "A reason recorded by a person (or a person confirming the AI's), or by a rule (dates passed).",
                "proposed": "Only the AI's proposal from the calls and chats; nobody has confirmed it yet.",
                "not_recorded": "Closed with no reason and no proposal yet (the AI reads these overnight)."}}
