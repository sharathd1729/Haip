"""From an open finding to a proposal (E2). Code decides the plan from the CURRENT state (never the model); a plan is a list
of typed steps (steps.py) plus plain preview lines that say exactly what will happen, including any text that will go out.

  SA1  leads waiting, team alerts not set up   -> alert templates (draft -> submit to Meta -> wait APPROVED) -> P3 + P4 on
                                                  -> ask the team to opt in                                     R2
  A4   missed calls not called back            -> missed-call template (draft -> submit -> wait) -> P1 on       R3 (guests)
  C2   quotes with no follow-up                -> P5 follow-ups in "drafts" mode (a person approves each)       R2
  SA9  lead-stage suggestions nobody applies   -> lead autopilot "autopilot" (rules + confident AI moves)       R2
  OP1  arrivals tomorrow owing money           -> balance-due WhatsApp + Razorpay link to those guests          R3 (money)
  CO1  the same question handed over 3+ times  -> a PENDING KB entry from the staff's own answer               R2

Switching the lead playbooks' workspace switch on also starts any playbook already switched on underneath it: the plan
names those and becomes R3 when one of them messages guests. A template Meta rejected before is not resubmitted as is.
No plan = no proposal (the finding still shows). One open proposal per finding; a plan the owner rejected for the same
finding is not proposed again for 7 days.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.chief import OPEN_STATUSES, ChiefProposal
from app.models.insight import Insight
from app.services.chief.steps import step

log = structlog.get_logger()

TIER_RANK = {"R1": 1, "R2": 2, "R3": 3}
REJECT_COOL_OFF = timedelta(days=7)
GUEST_KINDS = ("guest_message", "followup")


def plan_sha(steps: list[dict], preview: list[str]) -> str:
    core = [{"type": s["type"], "args": s["args"], "tier": s["tier"]} for s in steps]
    return hashlib.sha256(
        json.dumps({"steps": core, "preview": preview}, sort_keys=True, default=str).encode()
    ).hexdigest()


def _templates(db: Session, tenant_id: str, names: list[str]) -> tuple[list[dict], list[str]] | None:
    """Steps that get these templates APPROVED (None when one was rejected: a person fixes the wording first)."""
    from app.services import wa_lead_pack

    st = {n: wa_lead_pack.status_of(db, tenant_id, n) for n in names}
    if any(s == "rejected" for s in st.values()):
        return None
    steps, lines = [], []
    if any(s is None for s in st.values()):
        steps.append(step("templates.create_drafts", "Add the WhatsApp templates as drafts", "R1"))
    todo = [n for n, s in st.items() if s in (None, "draft", "submission_failed")]
    if todo:
        steps.append(step("templates.submit", "Send the templates to Meta for approval", "R2", names=todo))
        lines.append(f"Sends {', '.join(todo)} to Meta for approval (Meta usually decides within a day).")
    if any(s != "approved" for s in st.values()):
        steps.append(step("wait.templates_approved", "Wait for Meta to approve them", "R1", names=names))
    return steps, lines


def _playbooks(tenant, keys: list[str], extra: dict | None = None) -> tuple[dict | None, list[str], bool]:
    """(the playbooks.set step or None when already on, preview lines, whether guests get messages because of it)."""
    from app.services import lead_playbook_catalog as cat
    from app.services import lead_playbook_settings as pbs

    s = pbs.get(tenant)
    active = [k for k in keys if pbs.playbook(tenant, k)["active"]]
    if len(active) == len(keys) and not extra:
        return None, [], False
    patch: dict = {"enabled": True, "playbooks": {k: {"enabled": True, **((extra or {}).get(k, {}))} for k in keys}}
    names = [cat.BY_KEY[k]["name"] for k in keys]
    lines = [f"Switches on: {', '.join(names)}."]
    guests = any(
        cat.BY_KEY[k]["kind"] in GUEST_KINDS and (extra or {}).get(k, {}).get("mode") != "drafts" for k in keys
    )
    if not s["enabled"]:
        others = [
            p for p in cat.CATALOG if p["key"] not in keys and s["playbooks"][p["key"]].get("enabled") and p["built"]
        ]
        if others:
            lines.append(
                "Also starts, because they were already switched on: " + ", ".join(p["name"] for p in others) + "."
            )
            guests = guests or any(p["kind"] in GUEST_KINDS for p in others)
    return step("playbooks.set", "Switch on the playbooks", "R2", patch=patch), lines, guests


def _sa1(db: Session, tenant, row: Insight) -> dict | None:
    from app.services import lead_alert_service, wa_lead_pack
    from app.services.lead_playbook_catalog import NEW_LEAD_ALERT, SLA_ESCALATION

    tpl = _templates(db, tenant.id, [wa_lead_pack.STAFF_ALERT, wa_lead_pack.STAFF_ESCALATION])
    if tpl is None:
        return None
    steps, lines = tpl
    pb, pb_lines, guests = _playbooks(tenant, [NEW_LEAD_ALERT, SLA_ESCALATION])
    if pb is not None:
        pb["args"]["patch"]["staff_whatsapp"] = True
        steps.append(pb)
        lines += pb_lines + [
            "Late leads then reach the lead's owner on WhatsApp (Acknowledge / I'll take it), then a manager."
        ]
    if not any(r["whatsapp_opt_in"] for r in lead_alert_service.recipients_view(db, tenant.id)):
        steps.append(step("notify.staff_opt_in", "Ask the team to turn on WhatsApp alerts", "R1"))
        lines.append("Asks each team member (app notification) to turn on WhatsApp alerts in their profile.")
    if not any(s["type"] != "wait.templates_approved" for s in steps):
        return None
    return {
        "title": "Set up team WhatsApp alerts for waiting leads",
        "steps": steps,
        "preview": lines,
        "guest_facing": guests,
    }


def _missed_calls(db: Session, tenant, row: Insight) -> dict | None:
    from app.services import wa_lead_pack
    from app.services.lead_playbook_catalog import MISSED_INBOUND_CALL

    pb, pb_lines, _ = _playbooks(tenant, [MISSED_INBOUND_CALL])
    if pb is None:
        return None
    tpl = _templates(db, tenant.id, [wa_lead_pack.MISSED_CALL])
    if tpl is None:
        return None
    steps, lines = tpl
    text = next(c["text"] for c in wa_lead_pack.BY_NAME[wa_lead_pack.MISSED_CALL]["components"] if c["type"] == "BODY")
    return {
        "title": "WhatsApp guests whose call we missed",
        "steps": steps + [pb],
        "preview": lines
        + pb_lines
        + [f'Each missed caller then gets: "{text}"', "A call-back task is made for the team."],
        "guest_facing": True,
    }


def _quote_followups(db: Session, tenant, row: Insight) -> dict | None:
    from app.services.lead_playbook_catalog import PROPOSAL_FOLLOWUP

    pb, lines, guests = _playbooks(tenant, [PROPOSAL_FOLLOWUP], {PROPOSAL_FOLLOWUP: {"mode": "drafts"}})
    if pb is None:
        return None
    return {
        "title": "Follow up quotes automatically, as drafts",
        "steps": [pb],
        "preview": lines
        + [
            "Each quote gets follow-ups at 6 hours, day 3 and day 7. The AI writes them as drafts and a "
            "person approves each one before it is sent."
        ],
        "guest_facing": guests,
    }


def _autopilot(db: Session, tenant, row: Insight) -> dict | None:
    from app.services import lead_autopilot_service

    if lead_autopilot_service.get_settings(db, tenant.id).get("mode") != "suggest":
        return None
    return {
        "title": "Let the lead autopilot move stages itself",
        "steps": [step("settings.lead_autopilot", "Lead autopilot: autopilot", "R2", mode="autopilot")],
        "preview": [
            "Lead stages move on their own when a rule applies (a booking, dates passed, a clear no) or the AI is "
            "at least 85% sure with evidence. Never into Sold by AI, never backwards, and every move can be undone."
        ],
        "guest_facing": False,
    }


def _arrivals(db: Session, tenant, row: Insight) -> dict | None:
    from app.services import balance_reminder_service

    stay_ids = [e["id"] for e in (row.evidence or []) if e.get("type") == "stay"]
    if not stay_ids or balance_reminder_service.blocker(db, tenant):
        return None
    return {
        "title": "Send balance reminders to tomorrow's arrivals",
        "steps": [
            step(
                "payments.balance_reminders",
                "Send the balance-due WhatsApp with a payment link",
                "R3",
                stay_ids=stay_ids,
            )
        ],
        "preview": [
            f"Sends the approved balance-due WhatsApp template with a Razorpay payment link to {len(stay_ids)} "
            "guest(s) arriving tomorrow, once per unpaid instalment. Never during quiet hours."
        ],
        "guest_facing": True,
    }


def consult_answer(db: Session, c) -> str:
    """What the team answered: the consult's own text, else the message a person sent from the Inbox."""
    if c.answer_text:
        return c.answer_text
    if c.answer_message_id:
        from app.models.conversation import Message

        msg = db.query(Message.body).filter_by(id=c.answer_message_id, tenant_id=c.tenant_id).first()
        return (msg[0] if msg else "") or ""
    return ""


def _kb(db: Session, tenant, row: Insight) -> dict | None:
    from app.models.agent_consult import AgentConsult

    ids = [e["id"] for e in (row.evidence or []) if e.get("type") == "consult"]
    consults = (
        db.query(AgentConsult)
        .filter(AgentConsult.tenant_id == tenant.id, AgentConsult.id.in_(ids))
        .order_by(AgentConsult.answered_at.desc())
        .all()
    )
    answer = next((a for a in (consult_answer(db, c).strip() for c in consults) if a), "")
    if not consults or not answer:
        return None
    question = (consults[-1].question or "").strip()[:500]
    return {
        "title": "Teach the AI the answer it keeps asking for",
        "steps": [
            step(
                "kb.create_pending",
                "Add a knowledge-base entry for your review",
                "R2",
                question=question,
                content=answer[:4000],
                consult_ids=ids,
            )
        ],
        "preview": [
            "Adds this to the knowledge base as PENDING. The AI uses it only after you approve it there.",
            f"Question: {question}",
            f"Answer (your team's own words): {answer[:600]}",
        ],
        "guest_facing": False,
    }


PLANNERS = {"SA1": _sa1, "A4": _missed_calls, "C2": _quote_followups, "SA9": _autopilot, "OP1": _arrivals, "CO1": _kb}


def _recently_rejected(db: Session, tenant_id: str, row: Insight, now: datetime) -> bool:
    q = db.query(ChiefProposal.id).filter(
        ChiefProposal.tenant_id == tenant_id,
        ChiefProposal.code == row.category_code,
        ChiefProposal.status == "rejected",
        ChiefProposal.decided_at >= now - REJECT_COOL_OFF,
    )
    q = q.filter(
        ChiefProposal.target_id.is_(None) if row.target_id is None else ChiefProposal.target_id == row.target_id
    )
    return q.first() is not None


def expire_stale(db: Session, tenant_id: str, now: datetime) -> int:
    """Proposals still awaiting a decision whose finding went away (resolved or dismissed)."""
    n = 0
    rows = (
        db.query(ChiefProposal, Insight)
        .join(Insight, Insight.id == ChiefProposal.finding_id)
        .filter(ChiefProposal.tenant_id == tenant_id, ChiefProposal.status == "awaiting_approval")
        .all()
    )
    for p, f in rows:
        if f.is_auto_resolved or f.is_dismissed:
            p.status, p.finished_at = "expired", now
            append_audit(
                db,
                tenant_id=tenant_id,
                actor_user_id=None,
                action="chief.proposal_expired",
                target_type="chief_proposal",
                target_id=p.id,
                payload={"actor": "chief", "code": p.code},
            )
            n += 1
    return n


def propose_for_tenant(db: Session, tenant, now: datetime | None = None) -> list[ChiefProposal]:
    """Create proposals for open findings that have a plan. Returns the new ones; the caller commits."""
    now = now or datetime.now(UTC)
    expire_stale(db, tenant.id, now)
    open_ids = {
        fid
        for (fid,) in db.query(ChiefProposal.finding_id).filter(
            ChiefProposal.tenant_id == tenant.id, ChiefProposal.status.in_(OPEN_STATUSES)
        )
    }
    rows = (
        db.query(Insight)
        .filter(
            Insight.tenant_id == tenant.id,
            Insight.category_code.in_(list(PLANNERS)),
            Insight.is_dismissed.is_(False),
            Insight.is_auto_resolved.is_(False),
        )
        .all()
    )
    created = []
    for row in rows:
        if row.id in open_ids or _recently_rejected(db, tenant.id, row, now):
            continue
        try:
            with db.begin_nested():
                plan = PLANNERS[row.category_code](db, tenant, row)
        except Exception as exc:  # noqa: BLE001 -- one planner failing never blocks the others
            log.warning(
                "chief_plan_failed", tenant_id=tenant.id, code=row.category_code, error=f"{type(exc).__name__}: {exc}"
            )
            continue
        if not plan:
            continue
        tier = max((s["tier"] for s in plan["steps"]), key=TIER_RANK.get)
        if plan.get("guest_facing"):
            tier = "R3"
        exp = row.explanation if isinstance(row.explanation, dict) else {}
        p = ChiefProposal(
            tenant_id=tenant.id,
            finding_id=row.id,
            code=row.category_code,
            target_id=row.target_id,
            title=plan["title"][:255],
            why=exp.get("why") or row.body or row.title,
            risk_tier=tier,
            preview=plan["preview"],
            steps=plan["steps"],
            plan_sha=plan_sha(plan["steps"], plan["preview"]),
            status="awaiting_approval",
            step_index=0,
        )
        db.add(p)
        db.flush()
        append_audit(
            db,
            tenant_id=tenant.id,
            actor_user_id=None,
            action="chief.proposal_created",
            target_type="chief_proposal",
            target_id=p.id,
            payload={"actor": "chief", "code": p.code, "tier": tier, "steps": [s["type"] for s in p.steps]},
        )
        created.append(p)
    return created
