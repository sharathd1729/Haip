"""Lead autopilot: Leads360 stages that follow what actually happened (Ratha, Oct 2026).

Owner ask: "a DM came in with a phone number, our agent called, the booking did not close -- it must be marked Lost.
That is not happening." Before this, lead_recommendation_service only suggested Mark Lost / Move stage and a person
clicked Apply.

How a decision is made (evaluate()):
  1. deterministic rules (lead_autopilot_rules.py) -- bookings, dates, explicit declines, unanswered calls, silence;
  2. only if no rule fired, and only from the Celery task: the AI classifier (lead_autopilot_ai.py) with confidence and
     evidence quotes.
What happens with it depends on the tenant's mode (brand_config["lead_autopilot"]["mode"]):
  off        nothing at all
  suggest    (default, today's behaviour) the decision is stored as a suggestion; the lead page shows it with Apply,
             which runs the existing audited move_stage action
  autopilot  rule decisions, and AI decisions at or above ai_threshold (default 0.85) with valid evidence, are applied
             through inquiry_service.update_stage_by_id (stage log, ledger, audit) plus a "lead_autopilot.stage_moved"
             audit row carrying the evidence. Everything else stays a suggestion.
Guards (always, whatever the mode): a pinned lead is left alone; nothing moves out of Sold or Lost; nothing moves
backwards; a lead is never auto-Lost while it has a live payment link, or a future check-in with a live quote; a move a
person undid is never re-applied to the same stage (it may still be suggested).
Every applied move can be undone with one click (undo()); a person moving the lead by hand supersedes open decisions
(on_stage_changed(), hooked into BOTH inquiry_service transition paths).

Runs: after a call is wrapped up (wrap_up), after the lead summary refresh (which is already debounced for message
bursts), and a daily sweep (beat, rules only).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.lead_autopilot import LeadAutopilotEvent
from app.schemas.lead_autopilot import AutopilotSettings
from app.services import lead_autopilot_rules as rules
from app.services.lead_autopilot_rules import Decision, StageMap

log = structlog.get_logger()

CONFIG_KEY = "lead_autopilot"
APPLYING_FLAG = "lead_autopilot_applying"     # db.info marker: the stage move in progress is the autopilot's own
OPEN_STATUSES = ("suggested", "applied")

# Autopilot taxonomy -> the inquiries.lost_reason column (LostReason enum, unchanged so reports keep working).
LOST_REASON_COLUMN = {
    "price": "budget_mismatch", "dates": "wrong_dates", "no_response": "no_response",
    "booked_elsewhere": "chose_competitor", "not_suitable": "other", "other": "other",
}
LOST_REASON_LABEL = {
    "price": "Price", "dates": "Dates", "no_response": "No response", "booked_elsewhere": "Booked elsewhere",
    "not_suitable": "Not suitable", "other": "Other",
}


# ── Settings ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def settings_from_config(brand_config) -> dict:
    raw = (brand_config or {}).get(CONFIG_KEY) if isinstance(brand_config, dict) else None
    try:
        return AutopilotSettings(**(raw if isinstance(raw, dict) else {})).model_dump()
    except Exception:                                   # a hand-edited bad value must not stop leads from loading
        log.warning("lead_autopilot_settings_invalid")
        return AutopilotSettings().model_dump()


# The proposal follow-up playbook (P5) runs to day 8 ("decide won or lost"). While it is on, the autopilot does not call a
# quote "Lost: no reply" before the follow-up has had its say.
FOLLOWUP_QUOTE_SILENCE_DAYS = 9


def _with_followups(db: Session, tenant_id: str, settings: dict) -> dict:
    from app.models.tenant import Tenant
    from app.services import lead_playbook_catalog as cat
    from app.services import lead_playbook_settings as pb_settings
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    if tenant is None or not pb_settings.playbook(tenant, cat.PROPOSAL_FOLLOWUP)["active"]:
        return settings
    return {**settings, "quote_silence_days": max(int(settings["quote_silence_days"]), FOLLOWUP_QUOTE_SILENCE_DAYS)}


def get_settings(db: Session, tenant_id: str) -> dict:
    from app.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    return settings_from_config(tenant.brand_config if tenant else None)


def update_settings(db: Session, tenant_id: str, actor_user_id: str, patch: dict) -> dict:
    """Owner-only (checked by the endpoint). Audited with before/after. Caller commits."""
    from app.core.audit import append_audit
    from app.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    before = settings_from_config(tenant.brand_config)
    after = AutopilotSettings(**{**before, **{k: v for k, v in patch.items() if v is not None}}).model_dump()
    cfg = dict(tenant.brand_config or {})
    cfg[CONFIG_KEY] = after
    tenant.brand_config = cfg
    changed = {k: {"from": before[k], "to": after[k]} for k in after if before.get(k) != after[k]}
    append_audit(db, tenant_id=tenant_id, action="lead_autopilot.settings_changed", actor_user_id=actor_user_id,
                 target_type="tenant", target_id=tenant_id, payload={"changed": changed})
    return after


def settings_stats(db: Session, tenant_id: str) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    q = db.query(LeadAutopilotEvent).filter(LeadAutopilotEvent.tenant_id == tenant_id)
    return {
        "applied_30d": q.filter(LeadAutopilotEvent.created_at >= since,
                                LeadAutopilotEvent.status.in_(("applied", "undone", "superseded")),
                                LeadAutopilotEvent.mode == "autopilot").count(),
        "undone_30d": q.filter(LeadAutopilotEvent.status == "undone", LeadAutopilotEvent.resolved_at >= since).count(),
        "suggested_open": q.filter(LeadAutopilotEvent.status == "suggested").count(),
    }


# ── Guards ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _live_commitment(db: Session, tenant_id: str, inquiry, now: datetime) -> Optional[str]:
    """Why this lead must not be auto-Lost, or None."""
    from app.services import collab_requests
    if collab_requests.pending_for_inquiry(db, tenant_id, inquiry) is not None:
        return "a collaboration request is waiting for a person's yes or no"
    from app.models.inquiry_360 import InquiryQuote
    from app.models.stay_finance import StayPaymentLink

    quotes = db.query(InquiryQuote).filter_by(tenant_id=tenant_id, inquiry_id=inquiry.id, is_active=True).all()
    live_quotes = [q for q in quotes if (q.status or "issued") == "issued"
                   and (q.valid_until is None or rules._aware(q.valid_until) > now)]
    if quotes:
        links = db.query(StayPaymentLink).filter(
            StayPaymentLink.tenant_id == tenant_id, StayPaymentLink.status == "created",
            StayPaymentLink.inquiry_quote_id.in_([q.id for q in quotes])).all()
        if any(link.expires_at is None or rules._aware(link.expires_at) > now for link in links):
            return "a payment link for this lead is still open"
    check_in = rules._parse_date(inquiry.check_in)
    if live_quotes and check_in is not None and check_in >= now.astimezone(rules.IST).date():
        return "the check-in is still ahead and the quote is still valid"
    return None


def _undone_before(db: Session, tenant_id: str, inquiry_id: str, to_stage_id: str) -> bool:
    return db.query(LeadAutopilotEvent.id).filter_by(
        tenant_id=tenant_id, inquiry_id=inquiry_id, to_stage_id=to_stage_id, status="undone").first() is not None


# ── Recording / applying a decision ────────────────────────────────────────────────────────────────────────────────────
def record_decision(db: Session, tenant_id: str, inquiry, decision: Decision, settings: dict, stages: StageMap,
                    now: Optional[datetime] = None) -> Optional[LeadAutopilotEvent]:
    """Store (and in autopilot mode apply) one decision. Returns the event, or None when nothing was recorded.
    Idempotent: the same open decision is refreshed, not duplicated. Caller commits."""
    now = now or datetime.now(timezone.utc)
    mode = settings["mode"]
    current = stages.by_id(inquiry.stage_id)
    target = decision.to_stage
    if mode == "off" or current is None or target is None or inquiry.autopilot_paused_at is not None:
        return None
    if current.id == target.id or current.is_closed_won or current.is_closed_lost:
        return None                                       # never out of Sold or Lost
    if target.order < current.order and not (target.is_closed_won or target.is_closed_lost):
        return None                                       # never backwards

    open_events = (db.query(LeadAutopilotEvent)
                   .filter(LeadAutopilotEvent.tenant_id == tenant_id, LeadAutopilotEvent.inquiry_id == inquiry.id,
                           LeadAutopilotEvent.status.in_(("suggested", "blocked"))).all())
    same = next((e for e in open_events if e.to_stage_id == target.id and e.rule == decision.rule), None)
    for e in open_events:
        if e is not same:
            e.status, e.resolved_at, e.resolved_by = "superseded", now, "autopilot"

    blocked = _live_commitment(db, tenant_id, inquiry, now) if target.is_closed_lost else None
    can_apply = (
        mode == "autopilot" and decision.apply_allowed and blocked is None
        and not _undone_before(db, tenant_id, inquiry.id, target.id)
        and (decision.source == "rule" or (decision.confidence or 0) >= float(settings["ai_threshold"]))
    )
    status = "applied" if can_apply else ("blocked" if blocked else "suggested")

    event = same or LeadAutopilotEvent(tenant_id=tenant_id, inquiry_id=inquiry.id, to_stage_id=target.id,
                                       rule=decision.rule, created_at=now)
    event.from_stage_id = current.id
    event.source = decision.source
    event.lost_reason = decision.lost_reason
    event.reason = decision.reason
    event.confidence = Decimal(str(decision.confidence)) if decision.confidence is not None else None
    event.evidence = decision.evidence or []
    event.mode = mode
    event.status = status
    event.blocked_reason = blocked
    event.prompt_version = decision.prompt_version
    event.model = decision.model
    if same is None:
        db.add(event)
    db.flush()
    if status == "applied":
        _apply(db, tenant_id, inquiry, event, current, target)
    return event


def _apply(db: Session, tenant_id: str, inquiry, event: LeadAutopilotEvent, current, target) -> None:
    from app.core.audit import append_audit
    from app.models.inquiry import LostReason
    from app.services import inquiry_service

    event.prev_lost_reason = getattr(inquiry.lost_reason, "value", inquiry.lost_reason)
    event.prev_lost_note = inquiry.lost_note
    db.info[APPLYING_FLAG] = inquiry.id
    try:
        # A RULE move records its own won/lost reason (source "rule", e.g. dates passed -> dates_unavailable); an AI move
        # records none, so the nightly lead_outcome sweep proposes one for a person to confirm.
        outcome = None
        if event.source == "rule" and target.is_closed_lost:
            from app.services.lead_outcome import AUTOPILOT_LOST
            outcome = {"reason": AUTOPILOT_LOST.get(event.lost_reason or "", "other"), "source": "rule"}
        inquiry_service.update_stage_by_id(
            db, tenant_id=tenant_id, inquiry_id=inquiry.id, new_stage_id=target.id,
            actor_user_id=None, actor_role="system", reason=f"Autopilot: {event.reason}", outcome=outcome,
        )
    finally:
        db.info.pop(APPLYING_FLAG, None)
    if target.is_closed_lost and event.lost_reason:
        inquiry.lost_reason = LostReason(LOST_REASON_COLUMN.get(event.lost_reason, "other"))
        inquiry.lost_note = f"Autopilot ({LOST_REASON_LABEL.get(event.lost_reason, 'Other')}): {event.reason}"[:1000]
    append_audit(db, tenant_id=tenant_id, action="lead_autopilot.stage_moved", actor_user_id=None,
                 target_type="inquiry", target_id=inquiry.id, payload={
                     "actor": "autopilot", "event_id": event.id, "rule": event.rule, "source": event.source,
                     "from_stage": current.key, "to_stage": target.key, "lost_reason": event.lost_reason,
                     "confidence": float(event.confidence) if event.confidence is not None else None,
                     "evidence": [{"kind": e.get("kind"), "id": e.get("id")} for e in (event.evidence or [])],
                     "prompt_version": event.prompt_version,
                 })
    log.info("lead_autopilot_applied", tenant_id=tenant_id, inquiry_id=inquiry.id, rule=event.rule,
             to_stage=target.key, source=event.source)


# ── Evaluation ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _ai_seen_key(tenant_id: str, inquiry_id: str, fingerprint: str) -> str:
    from app.core.cache import cache_key
    return cache_key("lead_autopilot_ai", tenant_id, iid=inquiry_id, fp=fingerprint)


def evaluate(db: Session, tenant_id: str, inquiry_id: str, *, allow_ai: bool = False,
             settings: Optional[dict] = None, stages: Optional[StageMap] = None,
             now: Optional[datetime] = None) -> Optional[LeadAutopilotEvent]:
    """Rules, then (allow_ai, Celery only) the AI classifier. Caller commits."""
    from app.models.inquiry import Inquiry
    settings = settings or get_settings(db, tenant_id)
    if settings["mode"] == "off":
        return None
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if inquiry is None or not inquiry.stage_id or inquiry.autopilot_paused_at is not None:
        return None
    stages = stages or StageMap.load(db, tenant_id)
    settings = _with_followups(db, tenant_id, settings)
    decision = rules.evaluate(db, tenant_id, inquiry, stages, settings, now=now)
    if decision is None and allow_ai and settings["ai_enabled"]:
        decision = _ai_decision(db, tenant_id, inquiry, stages)
    if decision is None:
        return None
    return record_decision(db, tenant_id, inquiry, decision, settings, stages, now=now)


def _ai_decision(db: Session, tenant_id: str, inquiry, stages: StageMap) -> Optional[Decision]:
    from app.core.cache import get_cached, set_cached
    from app.services import lead_autopilot_ai as ai

    current = stages.by_id(inquiry.stage_id)
    if current is None or current.is_closed_won or current.is_closed_lost or current.is_collab_entry:
        return None
    _, _, fingerprint = ai.build_context(db, tenant_id, inquiry, stages)
    key = _ai_seen_key(tenant_id, inquiry.id, fingerprint)
    if get_cached(key) is not None:
        return None                                       # nothing new since the last read: no second LLM call
    decision = ai.classify(db, tenant_id, inquiry, stages)
    set_cached(key, "1", ttl=7 * 24 * 3600)
    return decision


def sweep_tenant(db: Session, tenant_id: str, limit: int = 2000) -> int:
    """Daily, rules only: every open lead with a stage. Commits per lead (one bad lead is rolled back alone; the tenant
    context is set again for each transaction). Returns how many decisions were recorded."""
    from app.core.database import set_tenant_context
    from app.models.inquiry import Inquiry
    from app.models.pipeline_stage import PipelineStage
    set_tenant_context(db, tenant_id)
    settings = get_settings(db, tenant_id)
    if settings["mode"] == "off":
        return 0
    stages = StageMap.load(db, tenant_id)
    closed = [s.id for s in stages.stages if s.is_closed_won or s.is_closed_lost]
    ids = [r[0] for r in db.query(Inquiry.id).join(PipelineStage, PipelineStage.id == Inquiry.stage_id)
           .filter(Inquiry.tenant_id == tenant_id, Inquiry.autopilot_paused_at.is_(None), ~Inquiry.stage_id.in_(closed))
           .order_by(Inquiry.updated_at.desc()).limit(limit).all()]
    n = 0
    for inquiry_id in ids:
        try:
            set_tenant_context(db, tenant_id)
            n += 1 if evaluate(db, tenant_id, inquiry_id, settings=settings, stages=stages) else 0
            db.commit()
        except Exception as exc:                          # one bad lead must not stop the sweep
            db.rollback()
            log.warning("lead_autopilot_sweep_lead_failed", tenant_id=tenant_id, inquiry_id=inquiry_id, error=str(exc)[:300])
    return n


def open_inquiry_for_guest(db: Session, tenant_id: str, guest_id: Optional[str]) -> Optional[str]:
    """The guest's newest lead that is not Sold/Lost (a call is not always linked to one)."""
    from app.models.inquiry import Inquiry
    from app.models.pipeline_stage import PipelineStage
    if not guest_id:
        return None
    row = (db.query(Inquiry.id).join(PipelineStage, PipelineStage.id == Inquiry.stage_id)
           .filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == guest_id,
                   PipelineStage.is_closed_won.is_(False), PipelineStage.is_closed_lost.is_(False))
           .order_by(Inquiry.created_at.desc()).first())
    return row[0] if row else None


def queue_evaluation(inquiry_id: Optional[str], tenant_id: str, trigger: str) -> None:
    """Fire-and-forget from other workers (wrap_up, generate_ai_summary). Never raises."""
    if not inquiry_id:
        return
    try:
        from app.workers.tasks.lead_autopilot import evaluate_inquiry
        evaluate_inquiry.delay(inquiry_id=str(inquiry_id), tenant_id=tenant_id, trigger=trigger)
    except Exception as exc:
        log.warning("lead_autopilot_enqueue_failed", inquiry_id=inquiry_id, error=str(exc)[:200])


# ── Human actions ──────────────────────────────────────────────────────────────────────────────────────────────────────
class AutopilotActionError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def undo(db: Session, tenant_id: str, inquiry, event_id: str, actor_user_id: str) -> LeadAutopilotEvent:
    """Put the lead back where it was before one automatic move. Caller commits."""
    from app.core.audit import append_audit
    from app.models.inquiry import LostReason
    from app.services import inquiry_service

    event = db.query(LeadAutopilotEvent).filter_by(id=event_id, tenant_id=tenant_id, inquiry_id=inquiry.id).first()
    if event is None:
        raise AutopilotActionError(404, "Autopilot move not found")
    if event.status != "applied" or not event.from_stage_id:
        raise AutopilotActionError(409, "This move can no longer be undone")
    try:
        inquiry_service.revert_automatic_move(
            db, tenant_id=tenant_id, inquiry_id=inquiry.id, expected_stage_id=event.to_stage_id,
            restore_stage_id=event.from_stage_id, actor_user_id=actor_user_id,
            reason=f"Undo autopilot move: {event.reason}"[:500],
        )
    except inquiry_service.InvalidStageTransition as exc:
        raise AutopilotActionError(409, exc.detail)
    if event.prev_lost_reason:
        inquiry.lost_reason = LostReason(event.prev_lost_reason)
        inquiry.lost_note = event.prev_lost_note
    event.status, event.resolved_at, event.resolved_by = "undone", datetime.now(timezone.utc), actor_user_id
    append_audit(db, tenant_id=tenant_id, action="lead_autopilot.undone", actor_user_id=actor_user_id,
                 target_type="inquiry", target_id=inquiry.id,
                 payload={"event_id": event.id, "rule": event.rule, "restored_stage_id": event.from_stage_id})
    return event


def set_pinned(db: Session, tenant_id: str, inquiry, actor_user_id: str, pinned: bool) -> None:
    """Pin = the autopilot leaves this lead alone (no moves, no suggestions). Audited. Caller commits."""
    from app.core.audit import append_audit
    now = datetime.now(timezone.utc)
    if pinned == (inquiry.autopilot_paused_at is not None):
        return
    inquiry.autopilot_paused_at = now if pinned else None
    inquiry.autopilot_paused_by = actor_user_id if pinned else None
    if pinned:
        db.query(LeadAutopilotEvent).filter(
            LeadAutopilotEvent.tenant_id == tenant_id, LeadAutopilotEvent.inquiry_id == inquiry.id,
            LeadAutopilotEvent.status.in_(("suggested", "blocked")),
        ).update({"status": "dismissed", "resolved_at": now, "resolved_by": actor_user_id}, synchronize_session=False)
    append_audit(db, tenant_id=tenant_id, action="lead_autopilot.pinned" if pinned else "lead_autopilot.unpinned",
                 actor_user_id=actor_user_id, target_type="inquiry", target_id=inquiry.id, payload={})


def on_stage_changed(db: Session, inquiry, new_stage_id: Optional[str], actor_user_id: Optional[str]) -> None:
    """Hook called by BOTH inquiry_service transition paths. A move that is not the autopilot's own closes open
    decisions: a suggestion the person followed becomes "accepted", the rest "superseded" (no Undo once the lead moved
    on). Never raises into the transition (the caller wraps it too)."""
    if db.info.get(APPLYING_FLAG) == inquiry.id:
        return
    now = datetime.now(timezone.utc)
    events = (db.query(LeadAutopilotEvent)
              .filter(LeadAutopilotEvent.tenant_id == inquiry.tenant_id, LeadAutopilotEvent.inquiry_id == inquiry.id,
                      LeadAutopilotEvent.status.in_(("suggested", "applied", "blocked"))).all())
    for e in events:
        accepted = e.status in ("suggested", "blocked") and e.to_stage_id == new_stage_id
        e.status = "accepted" if accepted else "superseded"
        e.resolved_at, e.resolved_by = now, actor_user_id or "system"
