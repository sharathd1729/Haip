"""Per-arm metrics of a running experiment and the decision rule (pure, documented).

Metrics, over the experiment's assignments (conversations opened after it started):
  dm_to_lead    of conversations whose guest had no phone at assignment, the share whose guest is a lead now
  guest_reply   of all conversations, the share where the guest wrote at least twice after assignment
  lead_to_quote of conversations whose guest is a lead now, the share with a quote on the guest's enquiries after assignment
  quote_to_won  of those quoted, the share whose guest has a live booking made after assignment

decide(control, treatment) -- two-proportion z-test (analyst.stats), in this order:
  1. stop-loss: both arms >= max(10, min_sample/2) and treatment's rate < control's x (1 - stop_loss_relative) with one-sided
     p (treatment lower) < stop_loss_p                                                  -> roll back
  2. both arms >= min_sample and two-sided p < keep_p: treatment higher -> keep; lower -> roll back
  3. max_days reached                                                                   -> stop, "no clear difference" (base kept)
  4. otherwise                                                                          -> continue
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.analyst import AgentExperiment, AgentExperimentAssignment
from app.models.conversation import Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.property import Stay
from app.services.analyst import stats
from app.services.kpi_metrics import OCCUPYING_STATUSES, as_datetime


def arm_counts(db: Session, exp: AgentExperiment) -> dict:
    rows = db.query(AgentExperimentAssignment).filter_by(tenant_id=exp.tenant_id, experiment_id=exp.id).all()
    tid = exp.tenant_id
    out = {}
    for arm in ("control", "treatment"):
        n = {"dm_to_lead": 0, "guest_reply": 0, "lead_to_quote": 0, "quote_to_won": 0}
        x = dict(n)
        for a in (r for r in rows if r.arm == arm):
            at = as_datetime(a.assigned_at)
            g = db.query(Guest.lead_identified_at).filter_by(id=a.guest_id, tenant_id=tid).first() if a.guest_id else None
            is_lead = bool(g and g[0])
            n["guest_reply"] += 1
            inbound = db.query(func.count(Message.id)).filter(Message.tenant_id == tid, Message.conversation_id == a.conversation_id,
                                                               Message.direction == MessageDirection.INBOUND,
                                                               Message.created_at >= at).scalar() or 0
            x["guest_reply"] += 1 if inbound >= 2 else 0
            if not a.guest_was_lead:
                n["dm_to_lead"] += 1
                x["dm_to_lead"] += 1 if is_lead else 0
            if not is_lead:
                continue
            n["lead_to_quote"] += 1
            quoted = db.query(InquiryQuote.id).join(Inquiry, Inquiry.id == InquiryQuote.inquiry_id).filter(
                InquiryQuote.tenant_id == tid, Inquiry.guest_id == a.guest_id, InquiryQuote.created_at >= at).first() is not None
            if not quoted:
                continue
            x["lead_to_quote"] += 1
            n["quote_to_won"] += 1
            won = db.query(Stay.id).filter(Stay.tenant_id == tid, Stay.guest_id == a.guest_id, Stay.created_at >= at,
                                           Stay.status.in_(list(OCCUPYING_STATUSES))).first() is not None
            x["quote_to_won"] += 1 if won else 0
        out[arm] = {k: {"n": n[k], "x": x[k], "rate": stats.rate(x[k], n[k])} for k in n}
        out[arm]["assigned"] = sum(1 for r in rows if r.arm == arm)
    return out


def decide(c: tuple[int, int], t: tuple[int, int], *, elapsed_days: float, min_sample: int, max_days: int,
           stop_loss_relative: float, stop_loss_p: float, keep_p: float) -> dict:
    """c and t are (x, n). Returns {result: continue|keep|rollback|stop, reason, test}."""
    (cx, cn), (tx, tn) = c, t
    test = stats.two_proportion(cx, cn, tx, tn)
    early = max(10, min_sample // 2)
    if test and cn >= early and tn >= early:
        rc, rt = cx / cn, tx / tn
        if rc > 0 and rt < rc * (1 - stop_loss_relative) and test["p_lower"] < stop_loss_p:
            return {"result": "rollback", "reason": f"stop-loss: treatment {rt:.0%} vs control {rc:.0%}", "test": test}
    if test and cn >= min_sample and tn >= min_sample and test["p_two_sided"] < keep_p:
        if test["diff"] > 0:
            return {"result": "keep", "reason": "treatment better", "test": test}
        return {"result": "rollback", "reason": "treatment significantly worse", "test": test}
    if elapsed_days >= max_days:
        few = cn < min_sample or tn < min_sample
        return {"result": "stop", "reason": "too few conversations to judge" if few else "no clear difference", "test": test}
    return {"result": "continue", "reason": "collecting", "test": test}


def evaluate(db: Session, exp: AgentExperiment, now: datetime, defaults) -> dict:
    counts = arm_counts(db, exp)
    m = exp.target_metric
    c, t = counts["control"][m], counts["treatment"][m]
    elapsed = (as_datetime(now) - as_datetime(exp.started_at)).total_seconds() / 86400 if exp.started_at else 0
    sl = exp.stop_loss or {}
    verdict = decide((c["x"], c["n"]), (t["x"], t["n"]), elapsed_days=elapsed, min_sample=exp.min_sample_per_arm,
                     max_days=exp.max_days, stop_loss_relative=float(sl.get("relative", defaults.stop_loss_relative)),
                     stop_loss_p=float(sl.get("p", defaults.stop_loss_p)), keep_p=float(sl.get("keep_p", defaults.keep_p)))
    return {"counts": counts, "verdict": verdict, "elapsed_days": round(elapsed, 2)}


def days_left(exp: AgentExperiment, now: datetime) -> Optional[float]:
    if not exp.started_at:
        return None
    return round(max(0.0, exp.max_days - (as_datetime(now) - as_datetime(exp.started_at)).total_seconds() / 86400), 1)
