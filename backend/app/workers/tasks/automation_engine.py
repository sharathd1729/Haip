"""
Automation trigger evaluator and action executors.

Usage (call from any event point):
    from app.workers.tasks.automation_engine import fire_trigger
    fire_trigger.delay(
        event="new_inquiry",
        tenant_id=str(tenant.id),
        context={"inquiry_id": inquiry.id, "guest_id": inquiry.guest_id},
    )

Supported triggers:
    new_inquiry         fired when an Inquiry is created
    call_completed      fired after wrap_up saves a call
    no_response_2h      fired by check_automation_timers beat task
    no_response_24h     fired by check_automation_timers beat task
    inquiry_lost        fired when inquiry stage → LOST / GHOSTED
    stay_check_in_1d    fired by check_automation_timers beat task
    stay_check_out_1d   fired by check_automation_timers beat task

Supported actions:
    send_whatsapp_template   sends an approved WA template to the guest
    create_draft_reply       queues concierge_draft task for the conversation
    notify_team              sends an internal Slack/WhatsApp message (config-driven)
    move_to_followup         advances inquiry stage to RESPONDING
    tag_guest                adds tags to the WASubscriber record
"""
import uuid
import traceback
from datetime import datetime, timezone
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
import structlog

log = structlog.get_logger()


@celery_app.task(name="tasks.automation_engine.fire_trigger")
def fire_trigger(event: str, tenant_id: str, context: dict):
    """
    Find all active rules for this tenant matching `event`,
    then execute each rule's action in sequence.

    Also fires any active Flow Builder flows (WAFlow) whose trigger field
    matches this event -- per the WhatsApp module build plan's Architecture
    Decision #2/#5, both automation surfaces react to the same event points
    rather than the flow engine needing its own separate set of fire calls
    scattered across the codebase. Rules run first, then flows, in this
    same task -- deterministic, single point of truth for ordering, no
    risk of double-firing from two different call sites for one event.

    Only "new_inquiry" is wired end-to-end today: it's the one flow
    trigger value (see flows/page.tsx's TRIGGER_OPTIONS) with a fire point
    that already exists and fires with the right context shape (guest_id).
    "keyword" / "opt_in" / "campaign_reply" have no equivalent fire_trigger
    call anywhere in the codebase yet -- wiring those needs new hook points
    (inbound-message keyword matching, WASubscriber opt-in, campaign reply
    detection) and is deliberately left unbuilt rather than guessed.
    """
    from app.core.database import set_tenant_context
    from app.models.automation import AutomationRule

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        rules = (
            db.query(AutomationRule)
            .filter_by(tenant_id=tenant_id, trigger=event, is_active=True)
            .all()
        )
        for rule in rules:
            _execute_rule(db, rule, event, context, tenant_id)

        _fire_matching_flows(db, event, tenant_id, context)
    finally:
        db.close()


def _execute_rule(db, rule, event: str, context: dict, tenant_id: str):
    """Execute a single rule and record the run in automation_runs."""
    from app.models.automation import AutomationRun

    run_id = str(uuid.uuid4())
    status = "success"
    detail = ""
    error = None

    try:
        detail = dispatch_action(db, rule.action, rule.action_config or {}, context, tenant_id)
    except Exception as exc:
        status = "failed"
        error = traceback.format_exc()[:2000]
        detail = str(exc)[:500]
        log.error(
            "automation_action_failed",
            rule_id=rule.id,
            rule_name=rule.name,
            action=rule.action,
            error=str(exc),
        )

    # Record the run
    run = AutomationRun(
        id=run_id,
        tenant_id=tenant_id,
        automation_id=rule.id,
        automation_name=rule.name,
        status=status,
        trigger_event=event,
        context=context,
        detail=detail or None,
        error=error,
        ran_at=datetime.now(timezone.utc),
    )
    db.add(run)

    # Update rule stats
    rule.run_count = (rule.run_count or 0) + 1
    rule.last_run_at = datetime.now(timezone.utc)
    db.commit()

    log.info(
        "automation_rule_executed",
        rule_id=rule.id,
        rule_name=rule.name,
        status=status,
    )


def _fire_matching_flows(db, event: str, tenant_id: str, context: dict) -> None:
    guest_id = context.get("guest_id")
    if not guest_id:
        return   # every flow trigger today (new_inquiry) requires a guest to run against

    from app.api.v1.endpoints.messaging import WAFlow
    from app.services.flow_engine import run_flow

    flows = db.query(WAFlow).filter_by(tenant_id=tenant_id, trigger=event, is_active=True).all()
    for flow in flows:
        try:
            run_flow(db, tenant_id, flow, guest_id, conversation_id=context.get("conversation_id"))
        except Exception as exc:
            log.error("flow_trigger_failed", flow_id=flow.id, event=event, error=str(exc))


# ─── Action dispatchers ────────────────────────────────────────────────────────

def dispatch_action(db, action: str, cfg: dict, context: dict, tenant_id: str) -> str:
    """
    Shared action layer -- both automation_rules (rule-based) and the Flow
    Builder (visual, workers/tasks/flow_engine.py) execute through this
    same function, per the WhatsApp module build plan's Architecture
    Decision #2. The two automation surfaces differ only in trigger/graph-
    walking logic, not in what an action actually does.
    """
    if action == "send_whatsapp_template":
        return _action_send_wa_template(db, cfg, context, tenant_id)
    elif action == "create_draft_reply":
        return _action_create_draft(db, cfg, context, tenant_id)
    elif action == "notify_team":
        return _action_notify_team(db, cfg, context, tenant_id)
    elif action == "move_to_followup":
        return _action_move_followup(db, cfg, context, tenant_id)
    elif action == "tag_guest":
        return _action_tag_guest(db, cfg, context, tenant_id)
    else:
        raise ValueError(f"Unknown action: {action}")


def _action_send_wa_template(db, cfg: dict, context: dict, tenant_id: str) -> str:
    """Send an approved WhatsApp template to the guest phone."""
    import asyncio
    from app.models.integration import Integration
    from app.models.guest import Guest
    from app.api.v1.endpoints.messaging import WATemplate
    from app.adapters.whatsapp.meta_cloud import get_wa_adapter

    template_id = cfg.get("template_id")
    if not template_id:
        raise ValueError("action_config.template_id is required for send_whatsapp_template")

    # Resolve guest phone
    guest_id = context.get("guest_id")
    if not guest_id:
        return "skipped — no guest_id in context"

    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
    if not guest or not guest.phone:
        return "skipped — guest has no phone number"

    template = db.query(WATemplate).filter_by(id=template_id, tenant_id=tenant_id).first()
    if not template:
        return f"skipped — template {template_id} not found"
    if not template.meta_template_id:
        return f"skipped — template '{template.name}' not submitted to Meta"

    intg = db.query(Integration).filter_by(
        tenant_id=tenant_id, kind="whatsapp_meta", status="active"
    ).first() or db.query(Integration).filter_by(
        tenant_id=tenant_id, kind="whatsapp", status="active"
    ).first()
    if not intg:
        return "skipped — no active WhatsApp integration"

    config = intg.config or {}
    adapter = get_wa_adapter(config["phone_number_id"], config["access_token"])

    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    _run(adapter.send_template(
        to=guest.phone,
        template_name=template.name,
        language_code=template.language or "en",
    ))
    return f"Template '{template.name}' sent to guest"


def _action_create_draft(db, cfg: dict, context: dict, tenant_id: str) -> str:
    """Queue the concierge_draft Celery task for the relevant conversation."""
    from app.models.conversation import Conversation, Message, ChannelType

    conversation_id = context.get("conversation_id")
    inquiry_id = context.get("inquiry_id")

    if not conversation_id and inquiry_id:
        # Find the most recent open conversation for this inquiry's guest
        from app.models.inquiry import Inquiry
        inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
        if inq:
            conv = (
                db.query(Conversation)
                .filter_by(tenant_id=tenant_id, guest_id=inq.guest_id, is_open=True)
                .order_by(Conversation.updated_at.desc())
                .first()
            )
            if conv:
                conversation_id = str(conv.id)

    if not conversation_id:
        return "skipped — no open conversation found"

    # Get the latest inbound message to draft a reply for
    latest_msg = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id, direction="inbound")
        .order_by(Message.created_at.desc())
        .first()
    )
    if not latest_msg:
        return "skipped — no inbound message in conversation"

    from app.workers.tasks.concierge_draft import concierge_draft
    concierge_draft.apply_async(kwargs={
        "message_id": latest_msg.id,
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "channel": latest_msg.channel.value if hasattr(latest_msg.channel, "value") else "whatsapp",
    })
    return "AI draft queued for conversation"


def _action_notify_team(db, cfg: dict, context: dict, tenant_id: str) -> str:
    """
    In-app team notification (WhatsApp module Phase 3, T3.3 -- scoped to
    in-app only per explicit confirmation; Slack/email are real, separate
    scope decisions per CLAUDE.md's non-goals, not built speculatively).

    Previously required a "to" WhatsApp number in cfg and no-op'd
    otherwise ("Slack/email wiring is future work" -- an in-app option was
    never actually built either, despite HAIP already having the
    push_subscription/SSE infrastructure this reuses). Now delivers via:
      - Web push (push_service.send_to_tenant) to subscribed devices
      - SSE "team_alert" event, fed into the existing notification bell
        (useNotificationsStore) the same way message_received/ai_draft_ready
        already are -- no new frontend polling mechanism needed.

    Config: {"title": "...", "message": "..."}
    """
    title = cfg.get("title", "Automation alert")
    message = cfg.get("message", "Automation alert from HAIP")

    from app.services.push_service import send_to_tenant
    send_to_tenant(
        db, tenant_id, title=title, body=message,
        url=(f"/dashboard/inbox?id={context['conversation_id']}" if context.get("conversation_id") else "/dashboard/inbox"),
        tag="team_alert",
    )

    try:
        import redis as _redis
        import json as _json
        from app.core.config import settings as _settings
        _r = _redis.Redis.from_url(_settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        _r.publish(f"sse:{tenant_id}", _json.dumps({
            "event": "team_alert",
            "title": title,
            "message": message,
            "conversation_id": context.get("conversation_id"),
        }))
        _r.close()
    except Exception as exc:
        log.warning("notify_team_sse_publish_failed", tenant_id=tenant_id, error=str(exc))

    return f"Team notified in-app: {title}"


def _action_move_followup(db, cfg: dict, context: dict, tenant_id: str) -> str:
    """Move the related inquiry to RESPONDING stage (if currently NEW)."""
    from app.models.inquiry import Inquiry, InquiryStage

    inquiry_id = context.get("inquiry_id")
    if not inquiry_id:
        return "skipped — no inquiry_id in context"

    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if not inq:
        return "skipped — inquiry not found"
    if inq.stage != InquiryStage.NEW:
        return f"skipped — inquiry already in {inq.stage.value}"

    inq.stage = InquiryStage.RESPONDING
    db.commit()
    return f"Inquiry moved to RESPONDING"


def _action_tag_guest(db, cfg: dict, context: dict, tenant_id: str) -> str:
    """Add tags to the WASubscriber record for the guest's phone."""
    tags = cfg.get("tags", [])
    if not tags:
        return "skipped — no tags configured"

    guest_id = context.get("guest_id")
    if not guest_id:
        return "skipped — no guest_id in context"

    from app.models.guest import Guest
    from app.api.v1.endpoints.messaging import WASubscriber

    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
    if not guest or not guest.phone:
        return "skipped — guest has no phone"

    sub = db.query(WASubscriber).filter_by(tenant_id=tenant_id, phone=guest.phone).first()
    if not sub:
        return "skipped — no subscriber record for guest phone"

    current = set(sub.tags or [])
    sub.tags = list(current | set(tags))
    db.commit()
    return f"Tags added: {', '.join(tags)}"
