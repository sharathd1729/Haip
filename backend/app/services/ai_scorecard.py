"""The honest AI scorecard (GET /ai/scorecard?period=7d|30d): how much the AI did alone, how often it asked a person and why,
how fast people answered, and whether leads it asked about still converted.

Every block says the period it covers. A share whose denominator is zero is ``None`` (shown as "No data"), never 0% or 100%.
Plain ORM, so SQLite and PostgreSQL agree.

  ai_replies           AI drafts in the period by outcome (ai_draft_outcomes): sent alone, approved as written, edited, rejected;
                       ``no_edit_share`` = (sent alone + approved as written) / every decided draft
  consults             opened in the period, by reason code (agent_escalation_rules.REASONS), by status, expired
  answer_minutes       answered consults: median and 90th percentile minutes from opening to answer, and the share answered
                       inside the first SLA (agent_consult_settings.sla_due at opening time)
  held_back            undecided or rejected AI drafts in the period, by the first reason they were held (the text before ":")
  conversion           enquiries created in the period with a consult vs without, and how many of each are won (moved to a
                       closed-won stage)
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.agent_consult import AgentConsult
from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.conversation import Message, MessageDirection
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.services import agent_consult_settings as settings_svc
from app.services import agent_escalation_rules as rules

PERIODS = {"7d": 7, "30d": 30}


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _share(part: int, whole: int) -> Optional[float]:
    return round(part / whole, 3) if whole else None


def _percentile(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round(pct * (len(s) - 1)))))
    return round(s[idx], 1)


def build(db: Session, tenant, period: str = "7d", now: Optional[datetime] = None) -> dict:
    days = PERIODS.get(period, 7)
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    tid = tenant.id
    span = {"period": period, "from": start.isoformat(), "to": now.isoformat(), "days": days}

    outcomes = Counter(o for (o,) in db.query(AIDraftOutcome.outcome).filter(
        AIDraftOutcome.tenant_id == tid, AIDraftOutcome.created_at >= start, AIDraftOutcome.created_at <= now))
    decided = sum(outcomes[k] for k in ("sent_autonomous", "sent_verbatim", "sent_edited", "rejected"))
    alone = outcomes["sent_autonomous"] + outcomes["sent_verbatim"]
    ai_replies = {**span, "sent_alone": outcomes["sent_autonomous"], "approved_as_written": outcomes["sent_verbatim"],
                  "edited": outcomes["sent_edited"], "rejected": outcomes["rejected"], "decided": decided,
                  "no_edit_share": _share(alone, decided)}

    consults = db.query(AgentConsult).filter(AgentConsult.tenant_id == tid, AgentConsult.created_at >= start,
                                             AgentConsult.created_at <= now).all()
    by_reason = Counter(code for c in consults for code in (c.reason_codes or []))
    by_status = Counter(c.status for c in consults)
    minutes, inside = [], 0
    for c in consults:
        if c.status == "answered" and c.answered_at and c.answer_mode not in ("expired",):
            m = (_aware(c.answered_at) - _aware(c.created_at)).total_seconds() / 60
            minutes.append(m)
            if _aware(c.answered_at) <= settings_svc.sla_due(tenant, _aware(c.created_at)):
                inside += 1
    consult_block = {**span, "opened": len(consults), "by_status": dict(by_status), "expired": by_status.get("expired", 0),
                     "by_reason": [{"code": k, "label": rules.REASONS.get(k, k), "count": n} for k, n in by_reason.most_common()]}
    answer_block = {**span, "answered": len(minutes), "median": _percentile(minutes, 0.5), "p90": _percentile(minutes, 0.9),
                    "sla_minutes": int(settings_svc.get(tenant)["sla_minutes"]), "inside_sla_share": _share(inside, len(minutes))}

    held = Counter()
    for (reason,) in db.query(Message.ai_needs_human_reason).filter(
            Message.tenant_id == tid, Message.direction == MessageDirection.OUTBOUND, Message.is_ai_generated.is_(True),
            Message.created_at >= start, Message.created_at <= now, Message.sent_autonomously.isnot(True),
            Message.ai_needs_human_reason.isnot(None)):
        first = (reason or "").split(";")[0].split(":")[0].strip()
        if first:
            held[first[:60]] += 1
    held_block = {**span, "total": sum(held.values()), "reasons": [{"reason": k, "count": n} for k, n in held.most_common(8)]}

    won_stage_ids = {sid for (sid,) in db.query(PipelineStage.id).filter(PipelineStage.tenant_id == tid,
                                                                       PipelineStage.is_closed_won.is_(True))}
    inquiries = db.query(Inquiry.id, Inquiry.guest_id, Inquiry.stage_id).filter(
        Inquiry.tenant_id == tid, Inquiry.created_at >= start, Inquiry.created_at <= now).all()
    consulted_inq = {c.inquiry_id for c in consults if c.inquiry_id}
    consulted_guest = {c.guest_id for c in consults if c.guest_id}
    groups = {"with_consult": [0, 0], "without_consult": [0, 0]}
    for iid, gid, sid in inquiries:
        key = "with_consult" if iid in consulted_inq or gid in consulted_guest else "without_consult"
        groups[key][0] += 1
        groups[key][1] += 1 if sid in won_stage_ids else 0
    conversion = {**span, **{k: {"leads": v[0], "won": v[1], "rate": _share(v[1], v[0])} for k, v in groups.items()},
                  "note": "Enquiries created in the period; won = moved to a closed-won stage. Small numbers are not a trend."}
    return {"period": period, "ai_replies": ai_replies, "consults": consult_block, "answer_minutes": answer_block,
            "held_back": held_block, "conversion": conversion}
