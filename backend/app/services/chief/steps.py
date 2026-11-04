"""The AI Executive's typed steps (E2). Each step calls ONE existing service and returns
(status, result, reason): status = done | waiting | failed. The executor (executor.py) runs them in order after an owner
approved the plan; a step is never run twice once done, and every step is safe to repeat.

  templates.create_drafts     wa_lead_pack.create_drafts (the Workflows "lead pack" button: drafts only)
  templates.submit            messaging.submit_to_meta (the template editor's Submit), for the named templates
  wait.templates_approved     reads the templates' status (kept in sync by the existing Meta sync); rejected = failed
  playbooks.set               lead_playbook_settings.update (audited workflows.settings_changed)
  notify.staff_opt_in         push to team members who have not turned on WhatsApp alerts (they opt in themselves)
  settings.lead_autopilot     lead_autopilot_service.update_settings (audited)
  kb.create_pending           a PENDING knowledge entry (unused until the owner approves it in the KB)
  payments.balance_reminders  balance_reminder_service.send_for_stays (idempotent per instalment)
  automation.comment_rule     marketing_comment_dm.reply_all_rule: every comment on that post gets the DM (+ public reply)
  marketing.agency_run        Marketing Studio's weekly run (marketing_agency.run_week): drafts only, posting keeps its approval
  reviews.draft_replies       the Studio's AI review-reply drafts (marketing_studio.draft_review_reply); a person posts
  website.change_draft        the Website page's "Change something" (website_change.request + website.builder_step): edits
                              the DRAFT only; going live stays the site's own sha-bound approval
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

WAIT_RECHECK = timedelta(minutes=10)
TEMPLATE_WAIT = timedelta(hours=72)
LANGUAGE = "en"

Result = tuple[str, dict | None, str | None, datetime | None]  # status, result, reason, retry_at


def _done(result: dict | None = None) -> Result:
    return "done", result or {}, None, None


def _failed(reason: str) -> Result:
    return "failed", None, reason[:500], None


def _template(db: Session, tenant_id: str, name: str):
    from app.services import wa_lead_pack

    WATemplate, _, _ = wa_lead_pack._model()
    return (
        db.query(WATemplate)
        .filter(WATemplate.tenant_id == tenant_id, WATemplate.name == name, WATemplate.language == LANGUAGE)
        .order_by(WATemplate.created_at.desc())
        .first()
    )


def _status(row) -> str | None:
    return getattr(row.status, "value", row.status) if row is not None else None


def create_drafts(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    from app.services import wa_lead_pack

    out = wa_lead_pack.create_drafts(db, tenant.id, actor_id)
    return _done({"created": out["created"]})


def submit(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    from fastapi import HTTPException

    from app.api.v1.endpoints.messaging import submit_to_meta

    out = {}
    for name in step["args"]["names"]:
        row = _template(db, tenant.id, name)
        if row is None:
            return _failed(f"The {name} template does not exist yet.")
        if _status(row) in ("approved", "pending"):
            out[name] = _status(row)
            continue
        try:
            res = submit_to_meta(db, row, row.id)
        except HTTPException as exc:
            return _failed(f"{name}: {exc.detail}")
        out[name] = res["status"]
        if res["status"] not in ("pending", "approved"):
            return _failed(f"Meta did not take {name}: {res.get('rejection_reason') or res['status']}")
    return _done({"statuses": out})


def wait_approved(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    started = datetime.fromisoformat(step.get("started_at") or now.isoformat())
    statuses = {}
    for name in step["args"]["names"]:
        row = _template(db, tenant.id, name)
        st = _status(row)
        if st == "rejected":
            return _failed(f"Meta rejected {name}: {row.rejection_reason or 'no reason given'}")
        statuses[name] = st
    if all(s == "approved" for s in statuses.values()):
        return _done({"statuses": statuses})
    if now - started > TEMPLATE_WAIT:
        return _failed("Meta has not decided on the template in 72 hours. Check it in the template editor.")
    return "waiting", {"statuses": statuses}, "Waiting for Meta to approve the template.", now + WAIT_RECHECK


def playbooks_set(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    from app.services import lead_playbook_settings

    try:
        changes = lead_playbook_settings.update(db, tenant, actor_id, step["args"]["patch"])
    except ValueError as exc:
        return _failed(str(exc))
    return _done({"changed": sorted(changes)})


def notify_staff_opt_in(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    from app.services import lead_alert_service
    from app.services.push_service import send_to_tenant

    asked = 0
    for r in lead_alert_service.recipients_view(db, tenant.id):
        if r["whatsapp_opt_in"]:
            continue
        send_to_tenant(
            db,
            tenant.id,
            "Turn on WhatsApp alerts",
            "Get new-lead alerts on WhatsApp with Acknowledge / I'll take it. Turn it on in your profile.",
            url="/dashboard/profile",
            tag="chief-opt-in",
            user_id=r["id"],
        )
        asked += 1
    return _done({"asked": asked})


def lead_autopilot(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    from app.services import lead_autopilot_service

    try:
        after = lead_autopilot_service.update_settings(db, tenant.id, actor_id, {"mode": step["args"]["mode"]})
    except ValueError as exc:
        return _failed(str(exc))
    return _done({"mode": after.get("mode")})


def kb_pending(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    from app.models.knowledge import KnowledgeEntry
    from app.services import knowledge_service

    ref = f"chief:{proposal.id}"
    existing = db.query(KnowledgeEntry.id).filter_by(tenant_id=tenant.id, source_ref=ref).first()
    if existing:
        return _done({"entry_id": existing[0]})
    a = step["args"]
    entry = KnowledgeEntry(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        category="faq",
        question=a["question"][:500],
        content=a["content"],
        source="conversation",
        source_ref=ref,
        priority=0,
        is_active=True,
        review_status="pending",
        embedding_status="pending",
        created_by=actor_id,
    )
    db.add(entry)
    db.flush()
    knowledge_service.audit_change(
        db,
        tenant.id,
        actor_id,
        "created",
        entry.id,
        after=knowledge_service.snapshot(entry),
        source="chief",
        proposal_id=proposal.id,
        consult_ids=a.get("consult_ids", []),
    )
    return _done({"entry_id": entry.id})


def balance_reminders(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    from app.models.property import Stay
    from app.services import balance_reminder_service, booking_agenda_service, lead_alert_service

    blocked = balance_reminder_service.blocker(db, tenant)
    if blocked:
        return _failed(
            "The balance-due WhatsApp template is not approved yet."
            if blocked == "template_not_approved"
            else "Razorpay is not connected, so no payment link can be made."
        )
    if lead_alert_service.in_quiet_hours(tenant, now):
        return "waiting", None, "Quiet hours: guests are not messaged now.", now + timedelta(minutes=30)
    stays = db.query(Stay).filter(Stay.tenant_id == tenant.id, Stay.id.in_(step["args"]["stay_ids"])).all()
    if not stays:
        return _done({"sent": 0, "skipped": 0})
    today = booking_agenda_service.tenant_today(db, tenant.id)
    out = balance_reminder_service.send_for_stays(db, tenant, stays, today, date.min, max(s.check_in for s in stays))
    return _done({"sent": out["sent"], "skipped": out["skipped"]})


def comment_rule(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    from app.services import marketing_comment_dm

    a = step["args"]
    rule = marketing_comment_dm.reply_all_rule(
        db, tenant.id, a["media_id"], a["message"], a.get("public_reply"), actor_id=actor_id
    )
    return _done({"rule_id": rule.id})


def agency_run(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    from app.services import marketing_agency_service
    from app.workers.tasks.marketing_studio import agency_run_week

    if marketing_agency_service.get_agency(tenant)["paused"]:
        return _failed("Marketing Studio's agency is paused.")
    agency_run_week.delay(tenant.id, "chief", actor_id)
    return _done({"queued": True})


def review_drafts(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    from app.models.marketing import MarketingGuestReview
    from app.workers.tasks.marketing_studio import draft_review_reply

    rows = (
        db.query(MarketingGuestReview)
        .filter(
            MarketingGuestReview.tenant_id == tenant.id,
            MarketingGuestReview.id.in_(step["args"]["review_ids"]),
            MarketingGuestReview.reply_status.in_(("none", "failed")),
        )
        .all()
    )
    for r in rows:
        draft_review_reply.delay(tenant.id, r.id)
    return _done({"queued": len(rows)})


def website_change(db: Session, tenant, proposal, step: dict, actor_id: str, now: datetime) -> Result:
    from app.models.user import User
    from app.services import website_change as wc
    from app.services.website_service import WebsiteError, get_site
    from app.workers.tasks.website import builder_step

    site, user = get_site(db, tenant.id), db.get(User, actor_id)
    if site is None or user is None:
        return _failed("There is no website to change.")
    try:
        job = wc.request(db, site, user, step["args"]["text"])
    except WebsiteError as exc:
        return _failed(getattr(exc, "message", None) or str(exc))
    db.commit()
    builder_step.delay(tenant.id, job.id)
    return _done({"job_id": job.id})


RUNNERS = {
    "templates.create_drafts": create_drafts,
    "templates.submit": submit,
    "wait.templates_approved": wait_approved,
    "playbooks.set": playbooks_set,
    "notify.staff_opt_in": notify_staff_opt_in,
    "settings.lead_autopilot": lead_autopilot,
    "kb.create_pending": kb_pending,
    "payments.balance_reminders": balance_reminders,
    "automation.comment_rule": comment_rule,
    "marketing.agency_run": agency_run,
    "reviews.draft_replies": review_drafts,
    "website.change_draft": website_change,
}
# Waiting is not an action: it never counts against the daily cap.
NOT_ACTIONS = {"wait.templates_approved"}


def step(kind: str, label: str, tier: str, **args) -> dict:
    """A plan's step, ready to store (executor fills status / result / reason / at)."""
    assert kind in RUNNERS, kind
    return {
        "type": kind,
        "label": label,
        "tier": tier,
        "args": args,
        "status": "pending",
        "result": None,
        "reason": None,
        "at": None,
    }
