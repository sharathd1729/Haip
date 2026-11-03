"""Asking the owner (E2): one approvals inbox, app notifications, and optional WhatsApp Approve / Reject.

pending()        ONE list for the founder: AI Executive proposals + Marketing Studio items (content in review, AI images)
                 + learning-loop changes waiting for a yes. Derived from each module's own table, nothing copied; each
                 item links to where it is decided.
notify_new()     push to every owner (+ an SSE nudge). With ``brand_config.chief.whatsapp_approvals`` on, the template
                 ``haip_chief_approval_v1`` APPROVED, outside quiet hours and for R1/R2 plans only (R3 = guests / public /
                 money: app only), each opted-in owner also gets it on WhatsApp via lead_alert_sender (a PlaybookAction,
                 playbook_key "chief"). Buttons carry ``ex:{action_id}:{approve|reject}:{nonce}``.
handle_tap()     the WhatsApp webhook's ``ex:`` taps (workers/tasks/whatsapp._staff_reply): the tap must come from the
                 number the request went to, with the right nonce (compare_digest); then executor.approve / reject.
"""

from __future__ import annotations

import json
import secrets

import structlog
from sqlalchemy.orm import Session

from app.models.chief import ChiefProposal
from app.models.lead_workflow import PlaybookAction
from app.models.user import User, UserRole
from app.services.chief import executor
from app.services.chief import settings as chief_settings

log = structlog.get_logger()

PREFIX = "ex:"
VERBS = ("approve", "reject")


def view(p: ChiefProposal) -> dict:
    return {
        "id": p.id,
        "finding_id": p.finding_id,
        "code": p.code,
        "title": p.title,
        "why": p.why,
        "risk_tier": p.risk_tier,
        "app_only": p.risk_tier == "R3",
        "preview": p.preview or [],
        "plan_sha": p.plan_sha,
        "status": p.status,
        "steps": [
            {
                "type": s["type"],
                "label": s["label"],
                "tier": s["tier"],
                "status": s.get("status"),
                "reason": s.get("reason"),
                "at": s.get("at"),
            }
            for s in (p.steps or [])
        ],
        "step_index": p.step_index,
        "created_at": p.created_at,
        "decided_at": p.decided_at,
        "decided_via": p.decided_via,
        "decision_reason": p.decision_reason,
        "finished_at": p.finished_at,
        "failure": p.failure,
        "next_check_at": p.next_check_at,
    }


def pending(db: Session, tenant) -> list[dict]:
    out = [
        {
            "source": "executive",
            "id": p.id,
            "title": p.title,
            "detail": p.why,
            "risk_tier": p.risk_tier,
            "waiting_since": p.created_at,
            "href": None,
        }
        for p in db.query(ChiefProposal)
        .filter_by(tenant_id=tenant.id, status="awaiting_approval")
        .order_by(ChiefProposal.created_at.asc())
        .limit(100)
    ]
    from app.services import marketing_agency_service

    for m in marketing_agency_service.pending_approvals(db, tenant.id):
        out.append(
            {
                "source": "marketing",
                "id": m["id"],
                "title": m["title"],
                "detail": f"Marketing {m['kind']} to approve",
                "risk_tier": "R3",
                "waiting_since": m["waiting_since"],
                "href": "/dashboard/marketing/studio",
            }
        )
    from app.models.analyst import AgentExperiment

    for e in (
        db.query(AgentExperiment)
        .filter(AgentExperiment.tenant_id == tenant.id, AgentExperiment.status.in_(("awaiting_approval", "proposed")))
        .order_by(AgentExperiment.created_at.asc())
        .limit(50)
    ):
        out.append(
            {
                "source": "learning",
                "id": e.id,
                "title": e.title,
                "detail": "A change to how the AI sales agent works, tested on half of new chats",
                "risk_tier": "R2",
                "waiting_since": e.created_at,
                "href": "/dashboard/analyst",
            }
        )
    return sorted(out, key=lambda x: str(x["waiting_since"]))


def _owners(db: Session, tenant_id: str) -> list[User]:
    return (
        db.query(User).filter(User.tenant_id == tenant_id, User.role == UserRole.OWNER, User.is_active.is_(True)).all()
    )


def notify_new(db: Session, tenant, proposals: list[ChiefProposal]) -> dict:
    """Tell the owners. Best effort: a failed send is logged on its PlaybookAction and never blocks the proposal."""
    if not proposals:
        return {"push": 0, "whatsapp": 0}
    from app.services import lead_alert_sender, lead_alert_service, wa_lead_pack
    from app.services.push_service import send_to_tenant

    owners = _owners(db, tenant.id)
    title = (
        "AI Executive needs your OK" if len(proposals) == 1 else f"AI Executive: {len(proposals)} things need your OK"
    )
    for u in owners:
        send_to_tenant(db, tenant.id, title, proposals[0].title, url="/dashboard/analyst", tag="chief", user_id=u.id)
    try:
        import redis

        from app.core.config import settings

        redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2).publish(
            f"sse:{tenant.id}", json.dumps({"event": "chief.approval_needed", "count": len(proposals)})
        )
    except Exception as exc:  # noqa: BLE001
        log.info("chief_sse_failed", tenant_id=tenant.id, error=str(exc))

    sent = 0
    cfg = chief_settings.get(tenant)
    if not cfg.whatsapp_approvals or lead_alert_service.in_quiet_hours(tenant):
        return {"push": len(owners), "whatsapp": 0}
    if lead_alert_sender.template_approved(db, tenant.id, wa_lead_pack.CHIEF_APPROVAL) is None:
        return {"push": len(owners), "whatsapp": 0}
    for p in proposals:
        if p.risk_tier == "R3":
            continue
        what = "; ".join(s["label"] for s in p.steps)[:200]
        for u in owners:
            phone = lead_alert_service.staff_phone(u)
            if not phone:
                continue
            nonce = secrets.token_urlsafe(12)
            action = PlaybookAction(
                tenant_id=tenant.id,
                playbook_key="chief",
                action="staff_wa",
                status="queued",
                recipient_user_id=u.id,
                template_name=wa_lead_pack.CHIEF_APPROVAL,
                payload={"proposal_id": p.id, "nonce": nonce},
            )
            db.add(action)
            db.flush()
            ok = lead_alert_sender.deliver(
                db, action, phone, [p.title, p.why, what], payloads=[f"{PREFIX}{action.id}:{v}:{nonce}" for v in VERBS]
            )
            sent += ok
    return {"push": len(owners), "whatsapp": sent}


def parse(payload: str | None) -> tuple[str, str, str] | None:
    if not payload or not payload.startswith(PREFIX):
        return None
    parts = payload[len(PREFIX) :].split(":")
    if len(parts) != 3 or parts[1] not in VERBS or not parts[0] or not parts[2]:
        return None
    return parts[0], parts[1], parts[2]


def handle_tap(db: Session, tenant_id: str, from_phone: str, payload: str | None) -> str:
    """approved | rejected | refused | wrong_person | unknown | ignored. Replies to the owner on WhatsApp."""
    from app.models.tenant import Tenant
    from app.services import lead_alert_sender, lead_alert_service

    parsed = parse(payload)
    if parsed is None:
        return "ignored"
    action_id, verb, nonce = parsed
    action = db.query(PlaybookAction).filter_by(id=action_id, tenant_id=tenant_id, playbook_key="chief").first()
    if action is None or not action.recipient_user_id:
        return "unknown"
    user = db.query(User).filter_by(id=action.recipient_user_id, tenant_id=tenant_id).first()
    expected = str((action.payload or {}).get("nonce") or "")
    if (
        user is None
        or user.role != UserRole.OWNER
        or lead_alert_service.staff_phone(user) != from_phone
        or not secrets.compare_digest(expected, nonce)
    ):
        log.warning("chief_tap_refused", tenant_id=tenant_id, action_id=action_id)
        return "wrong_person"
    p = db.query(ChiefProposal).filter_by(id=(action.payload or {}).get("proposal_id"), tenant_id=tenant_id).first()
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    if p is None or tenant is None:
        return "unknown"
    try:
        if verb == "approve":
            executor.approve(db, tenant, p, user.id, p.plan_sha, via="whatsapp")
            reply, outcome = f"Approved: {p.title}. I'll tell you when it's done.", "approved"
        else:
            executor.reject(db, tenant, p, user.id, None, "Rejected on WhatsApp", via="whatsapp")
            reply, outcome = f"Okay, I won't do it: {p.title}.", "rejected"
        action.acked_at = action.acked_at or p.decided_at
        db.commit()
    except executor.DecisionError as exc:
        db.commit()  # an expiry found while approving is kept
        reply, outcome = exc.message, "refused"
    if outcome == "approved":
        from app.workers.tasks.chief_tasks import execute_proposal

        execute_proposal.delay(tenant_id, p.id)
    lead_alert_sender.send_text(db, tenant_id, from_phone, reply)
    return outcome
