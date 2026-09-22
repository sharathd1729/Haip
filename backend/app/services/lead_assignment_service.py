"""Lead assignment -- gives every lead an owner, by the rules the owner or
manager chose in Settings > Lead assignment (schemas/lead_assignment.py).

Before this, only manually added leads were round-robined; every lead
auto-created from WhatsApp, Instagram or a call sat unassigned, so no agent
saw it as theirs and nobody could be held to it.

Entry points:
  assign_new_lead()      -- a lead was just created (chat/call/manual paths)
  on_call_logged()       -- a call row exists; the answering agent may own it
  claim_on_first_touch() -- an agent replied/called an unowned lead
  run_tick()             -- every few minutes: assign leads that waited for
                            working hours or for an available agent, and
                            pass on leads the owner never contacted

Owner changes always go through _set_owner(), which also moves the guest's
open conversations so Inbox "Mine" and the lead agree.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Iterable, Optional

import structlog
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.tenant_tz import get_tz
from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.inquiry import Inquiry, InquiryStage
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.lead_assignment import LeadAssignmentConfig

log = structlog.get_logger()

# Roles that can own leads. Anyone else (FOH, marketing, compliance, read-only)
# never receives one, whatever their availability flag says.
ASSIGNABLE_ROLES = (UserRole.OWNER, UserRole.MANAGER, UserRole.RESERVATIONS, UserRole.CONCIERGE)

# Methods that were chosen by a rule rather than by a person acting on the
# lead -- only these may be reassigned automatically.
AUTO_METHODS = ("round_robin", "balanced", "returning_guest", "reassigned")

# An uncontacted lead is passed on at most this many times, then left with
# its owner (the manager is alerted each time) -- avoids ping-ponging forever.
MAX_REASSIGNMENTS = 2

# Leads older than this are never picked up by the waiting-lead sweep, so
# turning auto-assignment on doesn't suddenly hand out months of history.
PENDING_LOOKBACK = timedelta(days=3)

_CLOSED_LEGACY = (InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED)


# ── Config ──────────────────────────────────────────────────────────────────

def get_config(tenant: Tenant) -> LeadAssignmentConfig:
    raw = getattr(tenant, "lead_assignment_config", None) or {}
    try:
        return LeadAssignmentConfig(**raw)
    except Exception as exc:  # a bad saved blob must not stop leads being created
        log.error("lead_assignment_config_invalid", tenant_id=tenant.id, error=str(exc))
        return LeadAssignmentConfig()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def within_working_hours(tenant: Tenant, cfg: LeadAssignmentConfig, at: Optional[datetime] = None) -> bool:
    if not cfg.working_hours_only:
        return True
    local = (at or _now()).astimezone(get_tz(tenant)).time()
    start = time.fromisoformat(cfg.hours_start)
    end = time.fromisoformat(cfg.hours_end)
    if start <= end:
        return start <= local < end
    return local >= start or local < end  # overnight window, e.g. 20:00-02:00


# ── Agents ──────────────────────────────────────────────────────────────────

def eligible_agents(db: Session, tenant_id: str) -> list[User]:
    """Active agents who take new leads, in a stable order."""
    return (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            User.is_deleted.is_(False),
            User.is_available_for_assignment.is_(True),
            User.role.in_(ASSIGNABLE_ROLES),
        )
        .order_by(User.email.asc())
        .all()
    )


def assignable_team(db: Session, tenant_id: str) -> list[User]:
    """Everyone who *could* take leads, available or not -- for Settings."""
    return (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            User.is_deleted.is_(False),
            User.role.in_(ASSIGNABLE_ROLES),
        )
        .order_by(User.name.asc())
        .all()
    )


def _closed_stage_ids(db: Session, tenant_id: str) -> list[str]:
    return [
        r.id for r in db.query(PipelineStage.id).filter(
            PipelineStage.tenant_id == tenant_id,
            or_(PipelineStage.is_closed_won.is_(True), PipelineStage.is_closed_lost.is_(True)),
        )
    ]


def _open_leads_query(db: Session, tenant_id: str):
    q = db.query(Inquiry).filter(
        Inquiry.tenant_id == tenant_id,
        Inquiry.stage.notin_(_CLOSED_LEGACY),
        Inquiry.qualification_status != "unqualified",
    )
    closed = _closed_stage_ids(db, tenant_id)
    if closed:
        q = q.filter(or_(Inquiry.stage_id.is_(None), Inquiry.stage_id.notin_(closed)))
    return q


def open_uncontacted_counts(db: Session, tenant_id: str, user_ids: Iterable[str]) -> dict[str, int]:
    """Open leads per agent that the agent hasn't contacted since getting them."""
    ids = list(user_ids)
    if not ids:
        return {}
    leads = _open_leads_query(db, tenant_id).filter(Inquiry.assigned_to.in_(ids)).all()
    contacted = contacted_since(db, tenant_id, leads)
    counts = {uid: 0 for uid in ids}
    for inq in leads:
        if inq.id not in contacted:
            counts[inq.assigned_to] = counts.get(inq.assigned_to, 0) + 1
    return counts


# ── "Has anyone contacted this lead?" ───────────────────────────────────────

def contacted_since(db: Session, tenant_id: str, leads: list[Inquiry]) -> set[str]:
    """Lead ids whose guest got a human contact after the lead was assigned
    (or created, if never assigned): a message a person sent or approved, an
    outbound call, or an answered inbound call. AI messages sent on their own
    don't count -- the point is whether a person has reached out."""
    from app.services.call_status_service import is_missed_call

    by_guest: dict[str, list[Inquiry]] = {}
    for inq in leads:
        if inq.guest_id:
            by_guest.setdefault(inq.guest_id, []).append(inq)
    if not by_guest:
        return set()

    def since(inq: Inquiry) -> datetime:
        return _aware(inq.assigned_at) or _aware(inq.created_at) or datetime.min.replace(tzinfo=timezone.utc)

    earliest = min(since(i) for i in leads)
    touches: list[tuple[str, datetime]] = []

    msgs = (
        db.query(Conversation.guest_id, Message.created_at)
        .join(Message, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.guest_id.in_(list(by_guest)),
            Message.direction == MessageDirection.OUTBOUND,
            Message.is_internal.is_(False),
            or_(Message.is_ai_generated.isnot(True), Message.was_approved.is_(True)),
            Message.created_at >= earliest,
        )
        .all()
    )
    touches += [(g, _aware(t)) for g, t in msgs if t]

    for call in db.query(Call).filter(
        Call.tenant_id == tenant_id, Call.guest_id.in_(list(by_guest)), Call.created_at >= earliest,
    ):
        if call.direction != CallDirection.OUTBOUND and is_missed_call(call):
            continue
        touches.append((call.guest_id, _aware(call.created_at)))

    out: set[str] = set()
    for guest_id, at in touches:
        for inq in by_guest.get(guest_id, []):
            if at >= since(inq):
                out.add(inq.id)
    return out


# ── Picking an agent ────────────────────────────────────────────────────────

def _round_robin(db: Session, tenant: Tenant, agents: list[User], exclude: set[str]) -> Optional[User]:
    pool = [a for a in agents if a.id not in exclude]
    if not pool:
        return None
    ids = [a.id for a in agents]
    last = tenant.last_assigned_user_id
    start = (ids.index(last) + 1) if last in ids else 0
    for i in range(len(agents)):
        cand = agents[(start + i) % len(agents)]
        if cand.id not in exclude:
            tenant.last_assigned_user_id = cand.id
            return cand
    return None


def _balanced(db: Session, tenant: Tenant, agents: list[User], exclude: set[str]) -> Optional[User]:
    pool = [a for a in agents if a.id not in exclude]
    if not pool:
        return None
    counts = open_uncontacted_counts(db, tenant.id, [a.id for a in pool])
    low = min(counts.get(a.id, 0) for a in pool)
    tied = [a for a in pool if counts.get(a.id, 0) == low]
    # Ties rotate like round robin so the same person doesn't win every tie.
    return _round_robin(db, tenant, tied, set()) if len(tied) > 1 else tied[0]


def _pick(db: Session, tenant: Tenant, cfg: LeadAssignmentConfig, exclude: set[str] = frozenset()) -> Optional[User]:
    agents = eligible_agents(db, tenant.id)
    if cfg.mode == "balanced":
        return _balanced(db, tenant, agents, set(exclude))
    return _round_robin(db, tenant, agents, set(exclude))


def _returning_guest_owner(db: Session, inquiry: Inquiry) -> Optional[str]:
    prev = (
        db.query(Inquiry.assigned_to)
        .filter(
            Inquiry.tenant_id == inquiry.tenant_id,
            Inquiry.guest_id == inquiry.guest_id,
            Inquiry.id != inquiry.id,
            Inquiry.assigned_to.isnot(None),
        )
        .order_by(Inquiry.created_at.desc())
        .first()
    )
    if not prev:
        return None
    eligible = {a.id for a in eligible_agents(db, inquiry.tenant_id)}
    return prev[0] if prev[0] in eligible else None


# ── Setting the owner ───────────────────────────────────────────────────────

def _set_owner(db: Session, inquiry: Inquiry, user_id: str, method: str, *, notify: bool = True) -> None:
    previous = inquiry.assigned_to
    inquiry.assigned_to = user_id
    inquiry.assigned_at = _now()
    inquiry.assignment_method = method
    # Inbox "Mine" and worklists read Conversation.assigned_to -- keep the
    # guest's open threads with the lead's owner.
    db.query(Conversation).filter(
        Conversation.tenant_id == inquiry.tenant_id,
        or_(Conversation.inquiry_id == inquiry.id,
            and_(Conversation.guest_id == inquiry.guest_id, Conversation.is_open.is_(True))),
    ).update({Conversation.assigned_to: user_id}, synchronize_session=False)
    db.flush()
    log.info(
        "lead_assigned", tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id,
        user_id=user_id, previous=previous, method=method, attempts=inquiry.assignment_attempts,
    )
    if notify:
        _notify(db, inquiry, user_id, method)


def _notify(db: Session, inquiry: Inquiry, user_id: str, method: str) -> None:
    try:
        from app.services.push_service import send_to_tenant
        name = (inquiry.guest.name if getattr(inquiry, "guest", None) else None) or "A guest"
        why = {"reassigned": "passed to you -- not contacted yet"}.get(method, "assigned to you")
        send_to_tenant(
            db, inquiry.tenant_id, title="New lead for you", body=f"{name}: {why}",
            url=f"/dashboard/leads/{inquiry.id}", tag=f"lead-{inquiry.id}", user_id=user_id,
        )
    except Exception as exc:  # push is best-effort
        log.warning("lead_assign_push_failed", inquiry_id=inquiry.id, error=str(exc))


def _is_marketing(db: Session, inquiry: Inquiry) -> bool:
    if not inquiry.stage_id:
        return False
    cat = db.query(PipelineStage.category).filter(PipelineStage.id == inquiry.stage_id).scalar()
    return cat == "marketing"


# ── Entry points ────────────────────────────────────────────────────────────

def assign_new_lead(db: Session, inquiry: Inquiry, tenant: Optional[Tenant] = None) -> Optional[str]:
    """Give a just-created lead an owner if the tenant's rules say so.
    Never raises: a failure here must not lose the inbound message or call."""
    try:
        if inquiry.assigned_to:
            return inquiry.assigned_to
        tenant = tenant or db.query(Tenant).filter_by(id=inquiry.tenant_id).first()
        if not tenant:
            return None
        cfg = get_config(tenant)
        if _is_marketing(db, inquiry):  # collab/influencer DMs are not sales leads
            return None

        if cfg.returning_guest_same_agent:
            prev = _returning_guest_owner(db, inquiry)
            if prev:
                _set_owner(db, inquiry, prev, "returning_guest")
                return prev

        if cfg.mode == "manual" or not within_working_hours(tenant, cfg):
            return None  # first agent to act claims it / assigned at opening
        agent = _pick(db, tenant, cfg)
        if not agent:
            log.warning("lead_assign_no_agent", tenant_id=tenant.id, inquiry_id=inquiry.id)
            return None
        _set_owner(db, inquiry, agent.id, cfg.mode)
        return agent.id
    except Exception as exc:
        log.error("lead_assign_failed", inquiry_id=getattr(inquiry, "id", None), error=str(exc))
        return None


def on_call_logged(db: Session, inquiry: Inquiry, call: Call) -> None:
    """After a call row is saved. An answered call by a known agent makes that
    agent the owner when the lead has none, or -- with "call answerer owns"
    on -- when a rule had assigned it and nobody had contacted the guest yet.
    Otherwise an unowned lead gets the normal new-lead treatment."""
    try:
        if not inquiry:
            return
        tenant = db.query(Tenant).filter_by(id=inquiry.tenant_id).first()
        if not tenant:
            return
        cfg = get_config(tenant)
        answered = (call.duration_seconds or 0) > 0
        agent_id = call.agent_id
        if agent_id and (answered or call.direction == CallDirection.OUTBOUND):
            if not inquiry.assigned_to:
                _set_owner(db, inquiry, agent_id, "call_answered" if cfg.call_answerer_owns else "first_touch",
                           notify=False)
                return
            # A rule-assigned owner who hasn't engaged yet yields to the agent
            # who actually picked up the guest's call. Outbound calls never
            # move a lead -- ringing someone else's guest doesn't take it over.
            if (
                cfg.call_answerer_owns and answered and call.direction != CallDirection.OUTBOUND
                and inquiry.assigned_to != agent_id
                and inquiry.assignment_method in AUTO_METHODS
                and _only_touch_is(db, inquiry, _aware(call.created_at) or _now())
            ):
                _set_owner(db, inquiry, agent_id, "call_answered", notify=False)
            return
        if not inquiry.assigned_to:
            assign_new_lead(db, inquiry, tenant)
    except Exception as exc:
        log.error("lead_assign_call_failed", inquiry_id=getattr(inquiry, "id", None), error=str(exc))


def _only_touch_is(db: Session, inquiry: Inquiry, call_at: datetime) -> bool:
    """True when no human touch happened between assignment and this call."""
    from app.services.call_status_service import is_missed_call

    since = _aware(inquiry.assigned_at) or _aware(inquiry.created_at)
    msg = (
        db.query(Message.id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Conversation.tenant_id == inquiry.tenant_id,
            Conversation.guest_id == inquiry.guest_id,
            Message.direction == MessageDirection.OUTBOUND,
            Message.is_internal.is_(False),
            or_(Message.is_ai_generated.isnot(True), Message.was_approved.is_(True)),
            Message.created_at >= since, Message.created_at < call_at,
        )
        .first()
    )
    if msg:
        return False
    for c in db.query(Call).filter(
        Call.tenant_id == inquiry.tenant_id, Call.guest_id == inquiry.guest_id,
        Call.created_at >= since, Call.created_at < call_at,
    ):
        if c.direction == CallDirection.OUTBOUND or not is_missed_call(c):
            return False
    return True


def claim_on_first_touch(db: Session, tenant_id: str, guest_id: Optional[str], user_id: str) -> None:
    """An agent replied to or called a guest: if the guest's open lead has no
    owner, it's theirs. Works in every mode, so nothing stays ownerless once
    someone has acted on it."""
    if not guest_id or not user_id:
        return
    try:
        user = db.query(User).filter_by(id=user_id, tenant_id=tenant_id).first()
        if not user or user.role not in ASSIGNABLE_ROLES:
            return
        inquiry = (
            _open_leads_query(db, tenant_id)
            .filter(Inquiry.guest_id == guest_id, Inquiry.assigned_to.is_(None))
            .order_by(Inquiry.created_at.desc())
            .first()
        )
        if inquiry:
            _set_owner(db, inquiry, user_id, "first_touch", notify=False)
    except Exception as exc:
        log.error("lead_claim_failed", tenant_id=tenant_id, error=str(exc))


def run_tick(db: Session, tenant: Tenant, now: Optional[datetime] = None) -> dict:
    """Periodic pass for one tenant: assign waiting leads, pass on stale ones."""
    now = now or _now()
    cfg = get_config(tenant)
    assigned = reassigned = 0
    if cfg.mode != "manual" and within_working_hours(tenant, cfg, now):
        waiting = (
            _open_leads_query(db, tenant.id)
            .filter(Inquiry.assigned_to.is_(None), Inquiry.created_at >= now - PENDING_LOOKBACK)
            .order_by(Inquiry.created_at.asc())
            .limit(200)
            .all()
        )
        for inq in waiting:
            if _is_marketing(db, inq):
                continue
            agent = _pick(db, tenant, cfg)
            if not agent:
                break
            _set_owner(db, inq, agent.id, cfg.mode)
            assigned += 1

    if cfg.reassign_if_not_contacted and within_working_hours(tenant, cfg, now):
        cutoff = now - timedelta(minutes=cfg.reassign_after_minutes)
        stale = (
            _open_leads_query(db, tenant.id)
            .filter(
                Inquiry.assigned_to.isnot(None),
                Inquiry.assignment_method.in_(AUTO_METHODS),
                Inquiry.assigned_at.isnot(None),
                Inquiry.assigned_at <= cutoff,
                Inquiry.assignment_attempts < MAX_REASSIGNMENTS,
            )
            .limit(200)
            .all()
        )
        touched = contacted_since(db, tenant.id, stale)
        for inq in stale:
            if inq.id in touched:
                continue
            previous = inq.assigned_to
            agent = _pick(db, tenant, cfg, exclude={previous})
            if not agent:
                continue
            inq.assignment_attempts = (inq.assignment_attempts or 0) + 1
            _set_owner(db, inq, agent.id, "reassigned")
            _alert_managers(db, tenant, inq, previous, agent)
            reassigned += 1
    db.commit()
    if assigned or reassigned:
        log.info("lead_assign_tick", tenant_id=tenant.id, assigned=assigned, reassigned=reassigned)
    return {"assigned": assigned, "reassigned": reassigned}


def _alert_managers(db: Session, tenant: Tenant, inquiry: Inquiry, previous: str, new_agent: User) -> None:
    try:
        from app.services.push_service import send_to_tenant
        prev_name = db.query(User.name).filter(User.id == previous).scalar() or "The owner"
        guest = (inquiry.guest.name if getattr(inquiry, "guest", None) else None) or "a guest"
        for mgr in db.query(User).filter(
            User.tenant_id == tenant.id, User.is_active.is_(True),
            User.role.in_((UserRole.OWNER, UserRole.MANAGER)),
        ):
            if mgr.id == new_agent.id:
                continue
            send_to_tenant(
                db, tenant.id, title="Lead passed on",
                body=f"{prev_name} didn't contact {guest} in time -- now with {new_agent.name}.",
                url=f"/dashboard/leads/{inquiry.id}", tag=f"lead-reassign-{inquiry.id}", user_id=mgr.id,
            )
    except Exception as exc:
        log.warning("lead_reassign_alert_failed", inquiry_id=inquiry.id, error=str(exc))


def unassigned_open_count(db: Session, tenant_id: str) -> int:
    return (
        _open_leads_query(db, tenant_id)
        .filter(Inquiry.assigned_to.is_(None))
        .with_entities(func.count(Inquiry.id))
        .scalar()
        or 0
    )
