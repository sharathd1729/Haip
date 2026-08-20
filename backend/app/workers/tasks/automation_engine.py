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

def dispatch_action(db, action: str, cfg: dict, context: dict, tenant_id: str, actor=None) -> str:
    """
    Shared action layer -- both automation_rules (rule-based) and the Flow
    Builder (visual, workers/tasks/flow_engine.py) execute through this
    same function, per the WhatsApp module build plan's Architecture
    Decision #2. The two automation surfaces differ only in trigger/graph-
    walking logic, not in what an action actually does.

    `actor` (a real User row) is only passed by the human one-click endpoint
    (automations.py::execute_recommended_action) -- rule/flow triggers have
    no human clicking, so it's None there. move_stage/assign_to require a
    real actor for their audit trail and are gated to ONE_CLICK_ACTIONS only
    (not VALID_ACTIONS), so a rule can never reach them with actor=None.
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
    elif action == "send_whatsapp_draft":
        return _action_send_whatsapp_draft(db, cfg, context, tenant_id)
    elif action == "move_stage":
        return _action_move_stage(db, cfg, context, tenant_id, actor)
    elif action == "assign_to":
        return _action_assign_to(db, cfg, context, tenant_id, actor)
    elif action == "hold_dates":
        return _action_hold_dates(db, cfg, context, tenant_id)
    elif action == "send_quote":
        return _action_send_quote(db, cfg, context, tenant_id)
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

    from app.workers.tasks.whatsapp import _get_wa_access_token
    phone_number_id = (intg.config or {}).get("phone_number_id")
    access_token = _get_wa_access_token(db, tenant_id)
    if not phone_number_id or not access_token:
        return "skipped — missing phone_number_id or access_token for WhatsApp integration"
    adapter = get_wa_adapter(phone_number_id, access_token)

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


def _action_send_whatsapp_draft(db, cfg: dict, context: dict, tenant_id: str) -> str:
    """
    Approve + queue-send a pending AI draft. Same effect as the inbox's
    approve-draft endpoint (conversations.py::approve_ai_draft), but
    self-contained here rather than imported from it: that endpoint is
    FastAPI-request-scoped (reads current_user, raises HTTPException) and
    also handles inbox-specific edit-before-send text, neither of which
    applies to a one-click "send it as drafted" action fired from
    next_action_service's recommendation.
    """
    from app.models.conversation import Message, MessageDeliveryState
    from app.services import ai_draft_outcomes_service

    message_id = cfg.get("message_id")
    if not message_id:
        return "skipped — action_config.message_id is required for send_whatsapp_draft"

    msg = db.query(Message).filter_by(id=message_id, tenant_id=tenant_id).first()
    if not msg:
        return f"skipped — message {message_id} not found"
    if msg.was_approved is not None:
        return "skipped — draft already actioned"

    msg.was_approved = True
    msg.delivery_state = MessageDeliveryState.QUEUED

    ai_draft_outcomes_service.record_outcome(
        db, tenant_id=tenant_id, draft=msg, outcome="sent_verbatim",
        intent=msg.ai_intent,
    )
    db.commit()

    from app.workers.tasks.send_whatsapp import send_whatsapp
    send_whatsapp.delay(message_id=message_id, tenant_id=tenant_id)
    return "Draft approved and queued for send"


def _action_move_stage(db, cfg: dict, context: dict, tenant_id: str, actor) -> str:
    """
    Move an inquiry to a new pipeline stage (Leads360's tenant-owned
    pipeline_stages catalog, stage_id-driven -- the modern path, same one
    app/mcp/tools.py::_move_lead_stage already uses). ONE_CLICK_ACTIONS-only
    (not in VALID_ACTIONS): a stage move needs a real accountable actor for
    update_stage_by_id's backward-move guardrails, which an anonymous
    automation-rule trigger doesn't have.
    """
    from app.services.inquiry_service import update_stage_by_id, InvalidStageTransition

    if actor is None:
        return "skipped — move_stage requires a human actor"

    inquiry_id = context.get("inquiry_id")
    new_stage_id = cfg.get("new_stage_id")
    if not inquiry_id or not new_stage_id:
        return "skipped — inquiry_id (entity_refs) and action_config.new_stage_id are both required"

    actor_role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
    try:
        inquiry = update_stage_by_id(
            db, tenant_id=tenant_id, inquiry_id=inquiry_id, new_stage_id=new_stage_id,
            actor_user_id=actor.id, actor_role=actor_role, reason=cfg.get("reason"),
        )
    except InvalidStageTransition as exc:
        return f"skipped — {exc.detail}"
    except ValueError as exc:
        return f"skipped — {exc}"
    db.commit()
    return f"Inquiry moved to stage {inquiry.stage_id}"


def _action_assign_to(db, cfg: dict, context: dict, tenant_id: str, actor) -> str:
    """
    Assign an inquiry to a user. Reuses update_inquiry() the same way
    app/mcp/tools.py::_assign_lead does, rather than re-implementing the
    assignment write path a third time. ONE_CLICK_ACTIONS-only: update_inquiry
    needs a real authenticated User for its own authz/role checks.
    """
    from app.api.v1.endpoints.inquiries import update_inquiry
    from app.schemas.inquiry import InquiryUpdateRequest
    from fastapi import HTTPException

    if actor is None:
        return "skipped — assign_to requires a human actor"

    inquiry_id = context.get("inquiry_id")
    assignee_id = cfg.get("user_id")
    if not inquiry_id or not assignee_id:
        return "skipped — inquiry_id (entity_refs) and action_config.user_id are both required"

    try:
        update_inquiry(
            inquiry_id=inquiry_id, body=InquiryUpdateRequest(assigned_to=assignee_id),
            current_user=actor, db=db,
        )
    except HTTPException as exc:
        return f"skipped — {exc.detail}"
    return f"Inquiry assigned to user {assignee_id}"


def _action_hold_dates(db, cfg: dict, context: dict, tenant_id: str) -> str:
    """
    Manual date block for a property, reusing the same BlockedDate row
    calendar.py's create_block endpoint writes. NOTE: the plan's table calls
    this a "TTL" hold, but no expiry column or scheduled-cleanup job exists
    anywhere in this codebase -- this is a manual-release-only hold for V1,
    not a real TTL. Flagging rather than silently shipping the TTL claim.
    """
    from app.models.base import gen_uuid
    from app.models.property import Property, BlockedDate

    property_id = cfg.get("property_id") or context.get("property_id")
    date_from = cfg.get("from")
    date_to = cfg.get("to")
    if not property_id or not date_from or not date_to:
        return "skipped — action_config.property_id/from/to are all required"

    prop = db.query(Property).filter_by(id=property_id, tenant_id=tenant_id).first()
    if not prop:
        return f"skipped — property {property_id} not found"

    block = BlockedDate(
        id=gen_uuid(), tenant_id=tenant_id, property_id=property_id,
        blocked_from=date_from, blocked_to=date_to,
        reason="hold", notes=cfg.get("notes"), is_active=True,
    )
    db.add(block)
    db.commit()
    return f"{prop.name} held {date_from} to {date_to} (manual release only -- no auto-expiry)"


def _action_send_quote(db, cfg: dict, context: dict, tenant_id: str) -> str:
    """
    Text-message quote send -- either a per-night property quote or (HAIP
    Inbox prototype-wiring plan, ticket 4) a distance/route quote for
    caravan properties, whichever cfg asks for. The plan's table says
    "PDF/WA" -- no PDF library exists anywhere in this codebase's
    requirements, and adding one for a single action handler isn't a call
    to make unprompted (CLAUDE.md: no new dependencies without
    justification). Sends the same figures a human would read off
    calculator_service's breakdown as chat text via the tested
    send_whatsapp/send_instagram_dm pipelines (24h-session-window handling
    included) rather than a raw adapter call, by writing a Message row and
    queueing it exactly the way send_whatsapp_draft already does.

    Channel-aware: sends on whichever channel (WhatsApp or Instagram) the
    guest's most recently active open conversation is on, the same way
    concierge_draft already branches WhatsApp vs. Instagram -- not
    hardcoded to WhatsApp.
    """
    from app.models.base import gen_uuid
    from app.models.conversation import Conversation, Message, MessageDeliveryState
    from app.models.guest import Guest
    from app.services.calculator_service import calculator_service

    property_id = cfg.get("property_id") or context.get("property_id")
    guest_id = context.get("guest_id")
    if not (property_id and guest_id):
        return "skipped — action_config.property_id and entity_refs.guest_id are both required"

    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
    if not guest or not guest.phone:
        return "skipped — guest has no phone number"

    from_city = cfg.get("from_city")
    to_city = cfg.get("to_city")

    if from_city and to_city:
        # Route/km quote (caravan properties).
        route_quote = calculator_service.build_route_quote(
            db, tenant_id=tenant_id, property_id=property_id, from_city=from_city, to_city=to_city,
        )
        if not route_quote:
            return f"skipped — no route quote available for {property_id} ({from_city} to {to_city})"
        text = (
            f"Here's your quote for {from_city} to {to_city} (~{route_quote['km']} km):\n"
            f"Subtotal: ₹{route_quote['subtotal']}\n"
            f"GST: ₹{route_quote['gst']}\n"
            f"Total: ₹{route_quote['total']}\n"
            f"Advance due: ₹{route_quote['advance_amount']}"
        )
        total = route_quote["total"]
    else:
        checkin = cfg.get("checkin")
        checkout = cfg.get("checkout")
        adults = cfg.get("adults") or 1
        children = cfg.get("children") or 0
        if not (checkin and checkout):
            return "skipped — action_config.checkin/checkout are required (or from_city/to_city for a route quote)"

        try:
            quote = calculator_service.build_quote(
                db, tenant_id=tenant_id, property_id=property_id,
                checkin=checkin, checkout=checkout, adults=adults, children=children,
            )
        except Exception as exc:
            return f"skipped — could not build quote: {exc}"
        if not quote:
            return "skipped — property not available for those dates"

        text = (
            f"Here's your quote for {checkin} to {checkout}:\n"
            f"Subtotal: ₹{quote.subtotal}\n"
            f"GST: ₹{quote.gst}\n"
            f"Total: ₹{quote.total}\n"
            f"Advance due: ₹{quote.advance_amount}"
        )
        total = quote.total

    conv = (
        db.query(Conversation)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id, is_open=True)
        .order_by(Conversation.updated_at.desc())
        .first()
    )
    if not conv:
        return "skipped — no open conversation for this guest"

    channel_val = str(conv.channel.value if hasattr(conv.channel, "value") else conv.channel)

    msg = Message(
        id=gen_uuid(), tenant_id=tenant_id, conversation_id=conv.id,
        direction="outbound", channel=conv.channel, body=text,
        is_ai_generated=False, was_approved=True, delivery_state=MessageDeliveryState.QUEUED,
    )
    db.add(msg)
    db.commit()

    if channel_val == "instagram":
        from app.workers.tasks.send_instagram_dm import send_instagram_dm
        send_instagram_dm.delay(message_id=msg.id, tenant_id=tenant_id)
    else:
        from app.workers.tasks.send_whatsapp import send_whatsapp
        send_whatsapp.delay(message_id=msg.id, tenant_id=tenant_id)
    return f"Quote sent to guest via {channel_val}: total ₹{total}"
