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
        detail = _dispatch_action(db, rule, context, tenant_id)
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


# ─── Action dispatchers ────────────────────────────────────────────────────────

def _dispatch_action(db, rule, context: dict, tenant_id: str) -> str:
    action = rule.action
    cfg = rule.action_config or {}

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
    Send an internal team notification.
    Config: {"channel": "whatsapp", "to": "+91XXXXXXXXXX", "message": "..."}
    If 'to' is missing, logs the notification (no-op for now — Slack/email wiring is future work).
    """
    to_number = cfg.get("to")
    message = cfg.get("message", "Automation alert from HAIP")

    if not to_number:
        log.info("automation_notify_team_no_target", tenant_id=tenant_id, context=context)
        return "notification logged (no target number configured)"

    import asyncio
    from app.models.integration import Integration
    from app.adapters.whatsapp.meta_cloud import get_wa_adapter

    intg = db.query(Integration).filter_by(
        tenant_id=tenant_id, kind="whatsapp_meta", status="active"
    ).first() or db.query(Integration).filter_by(
        tenant_id=tenant_id, kind="whatsapp", status="active"
    ).first()
    if not intg:
        return "skipped — no active WhatsApp integration for notify_team"

    config = intg.config or {}
    adapter = get_wa_adapter(config["phone_number_id"], config["access_token"])

    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    _run(adapter.send_text(to=to_number, body=message))
    return f"Team notified at {to_number[:4]}****"


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
