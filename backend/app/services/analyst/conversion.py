"""The analyst's "conversion" facts: where enquiries of one period went, where they stopped and why (code only, never the model).
Feeds the brief's facts and, computed on demand, "Ask a follow-up" on any report (ask.py), so "why are we not converting?"
has numbers to stand on.

Cohort: guest enquiries created in the period (kpi_metrics.lead_filters, the analyst's enquiry definition). Every step reuses
an existing rule, never a parallel one:
  with_phone      the guest is a lead (guests.lead_identified_at, lead_metrics' lead definition)
  qualified       lead_metrics.qualified_inquiry_ids (not spam, valid pipeline stage)
  contacted       lead_journeys.first_human_contact_at (work_queue_signals.touch_rows' contact rule)
  quote_sent      lead_journeys.proposal_shared_at
  booked          the enquiry is in a closed-won stage
Each step is counted on its own (a lead can get a quote without a logged contact), so a step can exceed the one before.
  leaks           open enquiries (not won / lost) with no contact by a person, contacted but never quoted, quoted with no
                  follow-up after (workflow_report_service._followed_up), and the stage they sit in now
  speed           median minutes received -> first human contact / -> quote shared; share contacted within the new-lead
                  SLA (work_queue_service.SLA_MINUTES["new_lead"][0])
  reasons         lead_outcome_report (leads CLOSED in the period, confirmed apart from AI-proposed), top 3 each side
  open_quotes     open enquiries of the cohort with a live quote and the sum of their latest quote amounts (an estimate of
                  what is still in play)
  waiting_now     work_queue_service.counts: people waiting on us right now (NOT the period)
Requests for routes we do not offer are in facts.demand.unavailable_asks (metrics_ops.demand), not repeated here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from statistics import median
from typing import Optional

from sqlalchemy.orm import Session

from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.lead_workflow import LeadJourney
from app.models.pipeline_stage import PipelineStage
from app.services import kpi_metrics, lead_metrics, lead_outcome_report
from app.services.work_queue_service import SLA_MINUTES

STEPS = ("enquiries", "with_phone", "qualified", "contacted", "quote_sent", "booked")


def _mins(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a is None or b is None:
        return None
    m = (kpi_metrics.as_datetime(b) - kpi_metrics.as_datetime(a)).total_seconds() / 60
    return m if m >= 0 else None


def _med(values: list) -> Optional[int]:
    return int(round(median(values))) if values else None


def _rate(x: int, n: int) -> Optional[float]:
    return round(x / n, 4) if n else None


def build(db: Session, tenant, d_from: date, d_to: date, lo: datetime, hi: datetime) -> dict:
    from app.services import work_queue_service
    from app.services.workflow_report_service import _followed_up
    tid = tenant.id
    rows = (db.query(Inquiry, Guest.lead_identified_at, PipelineStage.label, PipelineStage.is_closed_won,
                     PipelineStage.is_closed_lost, LeadJourney)
            .outerjoin(Guest, Guest.id == Inquiry.guest_id)
            .outerjoin(PipelineStage, PipelineStage.id == Inquiry.stage_id)
            .outerjoin(LeadJourney, (LeadJourney.inquiry_id == Inquiry.id) & (LeadJourney.tenant_id == tid))
            .filter(*kpi_metrics.lead_filters(tid, lo, hi)).all())
    ids = [r[0].id for r in rows]
    qualified = lead_metrics.qualified_inquiry_ids(db, tid, ids)
    followed = _followed_up(db, tid, ids)
    latest_quote: dict[str, float] = {}
    for inq_id, amount in (db.query(InquiryQuote.inquiry_id, InquiryQuote.amount)
                           .filter(InquiryQuote.tenant_id == tid, InquiryQuote.inquiry_id.in_(ids), InquiryQuote.is_active.is_(True))
                           .order_by(InquiryQuote.created_at).all() if ids else []):
        latest_quote[inq_id] = float(amount or 0)        # ordered by time: the last one wins

    sla = SLA_MINUTES["new_lead"][0]
    counts = Counter()
    by_source: dict[str, Counter] = defaultdict(Counter)
    stuck: Counter = Counter()
    leaks = Counter()
    contact_m, quote_m = [], []
    within_sla = journeys = 0
    open_quoted, open_value = 0, 0.0
    for inq, identified, stage_label, won, lost, j in rows:
        reached = {"enquiries": True, "with_phone": identified is not None, "qualified": inq.id in qualified,
                   "contacted": bool(j and j.first_human_contact_at), "quote_sent": bool(j and j.proposal_shared_at),
                   "booked": bool(won)}
        src = getattr(inq.source, "value", inq.source) or "not_recorded"
        for k, hit in reached.items():
            if hit:
                counts[k] += 1
                by_source[src][k] += 1
        if j is not None:
            journeys += 1
            m = _mins(j.received_at or inq.created_at, j.first_human_contact_at)
            if m is not None:
                contact_m.append(m)
                within_sla += 1 if m <= sla else 0
            q = _mins(j.received_at or inq.created_at, j.proposal_shared_at)
            if q is not None:
                quote_m.append(q)
        if won or lost:
            continue
        stuck[stage_label or "No stage"] += 1
        if not reached["contacted"]:
            leaks["open_no_contact_from_us"] += 1
        elif not reached["quote_sent"]:
            leaks["open_contacted_never_quoted"] += 1
        elif inq.id not in followed:
            leaks["open_quoted_no_followup"] += 1
        if inq.id in latest_quote:
            open_quoted += 1
            open_value += latest_quote[inq.id]

    funnel, prev = [], None
    for k in STEPS:
        funnel.append({"step": k, "count": counts[k], "rate_from_previous": _rate(counts[k], prev) if prev is not None else None})
        prev = counts[k]
    sources = sorted(by_source.items(), key=lambda kv: -kv[1]["enquiries"])[:5]
    outcome = lead_outcome_report.build(db, tid, d_from, d_to)

    def top(side: str) -> dict:
        s = outcome[side]
        return {"closed": s["total"], "confirmed": s["confirmed"], "ai_proposed": s["proposed"], "not_recorded": s["not_recorded"],
                "top": [{"reason": r["label"], "confirmed": r["confirmed"], "ai_proposed": r["proposed"]}
                        for r in s["reasons"] if r["confirmed"] + r["proposed"]][:3]}

    wq = work_queue_service.counts(db, tenant, None)
    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "funnel": funnel,
        "by_source": [{"source": k, **{s: c[s] for s in ("enquiries", "with_phone", "quote_sent", "booked")},
                       "booked_rate": _rate(c["booked"], c["enquiries"])} for k, c in sources],
        "leaks": {"open_enquiries": sum(stuck.values()), **{k: leaks[k] for k in
                  ("open_no_contact_from_us", "open_contacted_never_quoted", "open_quoted_no_followup")},
                  "open_by_stage": [{"stage": k, "count": n} for k, n in stuck.most_common(6)]},
        "speed": {"median_first_contact_minutes": _med(contact_m), "median_first_quote_minutes": _med(quote_m),
                  "sla_minutes": sla, "contacted_within_sla": within_sla, "tracked_enquiries": journeys,
                  "within_sla_rate": _rate(within_sla, journeys)},
        "reasons": {"basis": "leads closed in the period", "lost": top("lost"), "won": top("won")},
        "open_quotes": {"enquiries": open_quoted, "latest_quote_total_estimate": round(open_value, 2)},
        "waiting_now": {"people_waiting": wq.get("people_waiting"), "by_kind": wq.get("counts")},
    }
