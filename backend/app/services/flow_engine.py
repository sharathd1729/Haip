"""
Flow Builder graph interpreter — WhatsApp module Phase 2 (T2.2).

Walks a WAFlow's nodes/edges starting from the trigger node. Action nodes
call into automation_engine.dispatch_action() -- the same functions the
rule-based automations engine uses (Architecture Decision #2) -- rather
than a second, parallel set of send/tag/notify implementations. Delay
nodes park into flow_pending_executions, resumed by a Celery Beat task
(workers/tasks/flow_engine.py).

Frontend node vocabulary note: the current Flow Builder UI's "action"
node type offers tag_vip / create_inquiry / notify_agent / opt_out --
these don't map 1:1 onto automation_engine's action names, so this module
translates: tag_vip -> tag_guest, notify_agent -> notify_team, and
create_inquiry / opt_out are new (no automation_rules equivalent existed;
opt_out reuses the existing opt_out_responder.process_opt_out_event()
rather than reimplementing consent handling).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
import structlog

log = structlog.get_logger()

_TERMINAL_NODE_TYPES = {"end"}


def _log_run(db: Session, tenant_id: str, flow_id: str, guest_id: str, node: dict, status: str, detail: str = "", error: str = "") -> None:
    from app.models.flow_execution import WAFlowRun
    from app.models.base import gen_uuid
    try:
        db.add(WAFlowRun(
            id=gen_uuid(), tenant_id=tenant_id, flow_id=flow_id, guest_id=guest_id,
            node_id=node.get("id", ""), node_type=node.get("type", ""),
            status=status, detail=(detail or "")[:500], error=(error or "")[:2000] or None,
            ran_at=datetime.now(timezone.utc),
        ))
    except Exception as exc:
        log.warning("flow_run_log_failed", flow_id=flow_id, error=str(exc))


def _render_template(text: str, guest, context: dict) -> str:
    """Minimal {{name}}/{{property}} substitution -- flows have no richer
    templating today (matches what the Flow Builder UI actually offers)."""
    if not text:
        return text
    name = (guest.name if guest else "") or "there"
    property_name = context.get("property_name", "")
    return text.replace("{{name}}", name).replace("{{property}}", property_name)


def _execute_action_node(db: Session, tenant_id: str, guest_id: str, node: dict) -> str:
    from app.workers.tasks.automation_engine import dispatch_action

    action_key = node.get("content", "")
    context = {"guest_id": guest_id}

    if action_key == "tag_vip":
        return dispatch_action(db, "tag_guest", {"tags": ["VIP"]}, context, tenant_id)
    if action_key == "notify_agent":
        return dispatch_action(db, "notify_team", {}, context, tenant_id)
    if action_key == "create_inquiry":
        from app.services.inquiry_service import get_or_create
        inq = get_or_create(db, tenant_id, guest_id, source="whatsapp")
        db.commit()
        return f"Inquiry {inq.id} ensured"
    if action_key == "opt_out":
        from app.services.opt_out_responder import process_opt_out_event
        from app.models.guest import Guest
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
        if not guest or not guest.phone:
            return "skipped — guest has no phone"
        process_opt_out_event(
            db, tenant_id=tenant_id, guest_id=guest_id, guest_phone=guest.phone,
            direction="opt_out", matched_keyword="(flow action)",
        )
        db.commit()
        return "Guest opted out"
    return f"skipped — unknown action '{action_key}'"


def _evaluate_condition(db: Session, tenant_id: str, guest_id: str, conversation_id: Optional[str], node: dict) -> bool:
    condition = node.get("condition", "")
    from app.models.conversation import Message, MessageDirection, MessageDeliveryState

    if condition == "message_read":
        if not conversation_id:
            return False
        last_out = (
            db.query(Message)
            .filter_by(tenant_id=tenant_id, conversation_id=conversation_id, direction=MessageDirection.OUTBOUND)
            .order_by(Message.created_at.desc())
            .first()
        )
        return bool(last_out and last_out.delivery_state == MessageDeliveryState.READ)

    if condition == "replied":
        if not conversation_id:
            return False
        last_out = (
            db.query(Message)
            .filter_by(tenant_id=tenant_id, conversation_id=conversation_id, direction=MessageDirection.OUTBOUND)
            .order_by(Message.created_at.desc())
            .first()
        )
        if not last_out:
            return False
        newer_inbound = (
            db.query(Message)
            .filter(
                Message.tenant_id == tenant_id, Message.conversation_id == conversation_id,
                Message.direction == MessageDirection.INBOUND, Message.created_at > last_out.created_at,
            )
            .first()
        )
        return bool(newer_inbound)

    if condition == "is_vip":
        from app.models.guest import Guest
        from app.api.v1.endpoints.messaging import WASubscriber
        # guest_id (migration 091) is the reliable match -- exact phone
        # equality silently missed whenever the subscriber's number wasn't
        # typed in the same E.164 form Guest.phone is normalized to. Kept
        # as a fallback for subscriber rows created before the backfill.
        sub = db.query(WASubscriber).filter_by(tenant_id=tenant_id, guest_id=guest_id).first()
        if not sub:
            guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
            if not guest or not guest.phone:
                return False
            sub = db.query(WASubscriber).filter_by(tenant_id=tenant_id, phone=guest.phone).first()
        return bool(sub and "VIP" in (sub.tags or []))

    if condition == "has_booking":
        from app.models.property import Stay
        from app.models.guest import Guest
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
        if not guest:
            return False
        return db.query(Stay.id).filter_by(tenant_id=tenant_id, guest_id=guest_id).first() is not None

    log.warning("flow_unknown_condition", condition=condition)
    return False


def _next_node_id(edges_by_from: dict, node_id: str, branch: Optional[bool] = None) -> Optional[str]:
    edges = edges_by_from.get(node_id, [])
    if not edges:
        return None
    if branch is not None:
        wanted = "true" if branch else "false"
        matched = next((e for e in edges if (e.get("label") or "").lower() == wanted), None)
        if matched:
            return matched["to"]
        # Current Flow Builder UI only ever creates a single outgoing edge
        # per node (no branching UI yet) -- treat that lone edge as the
        # "true" path; a False result simply ends the flow here.
        return edges[0]["to"] if branch else None
    return edges[0]["to"]


def run_flow(
    db: Session, tenant_id: str, flow, guest_id: str,
    conversation_id: Optional[str] = None, start_node_id: Optional[str] = None,
) -> None:
    """
    Walk the flow graph starting at start_node_id (or the trigger node if
    not given -- i.e. a fresh run vs. a delay-node resume). Stops at an
    "end" node, a "delay" node (parks into flow_pending_executions and
    returns), or a dead end (node with no outgoing edge).
    """
    nodes_by_id = {n["id"]: n for n in (flow.nodes or [])}
    edges_by_from: dict[str, list] = {}
    for e in (flow.edges or []):
        edges_by_from.setdefault(e["from"], []).append(e)

    if start_node_id:
        current_id = start_node_id
    else:
        trigger = next((n for n in (flow.nodes or []) if n.get("type") == "trigger"), None)
        if not trigger:
            log.warning("flow_has_no_trigger_node", flow_id=flow.id)
            return
        current_id = trigger["id"]

    from app.models.guest import Guest
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()

    while current_id:
        node = nodes_by_id.get(current_id)
        if not node:
            break
        node_type = node.get("type")

        if node_type == "trigger":
            current_id = _next_node_id(edges_by_from, current_id)
            continue

        if node_type in _TERMINAL_NODE_TYPES:
            _log_run(db, tenant_id, flow.id, guest_id, node, "success", "Flow ended")
            break

        if node_type == "message":
            try:
                text = _render_template(node.get("content", ""), guest, {})
                _send_flow_message(db, tenant_id, guest_id, conversation_id, text)
                _log_run(db, tenant_id, flow.id, guest_id, node, "success", "Message sent")
            except FlowMessageNotSent as exc:
                _log_run(db, tenant_id, flow.id, guest_id, node, "skipped", f"Message not sent: {exc}")
            except Exception as exc:
                _log_run(db, tenant_id, flow.id, guest_id, node, "failed", error=str(exc))
            current_id = _next_node_id(edges_by_from, current_id)
            continue

        if node_type == "action":
            try:
                detail = _execute_action_node(db, tenant_id, guest_id, node)
                _log_run(db, tenant_id, flow.id, guest_id, node, "success", detail)
            except Exception as exc:
                _log_run(db, tenant_id, flow.id, guest_id, node, "failed", error=str(exc))
            current_id = _next_node_id(edges_by_from, current_id)
            continue

        if node_type == "condition":
            result = _evaluate_condition(db, tenant_id, guest_id, conversation_id, node)
            _log_run(db, tenant_id, flow.id, guest_id, node, "success", f"{node.get('condition')} -> {result}")
            current_id = _next_node_id(edges_by_from, current_id, branch=result)
            continue

        if node_type == "delay":
            next_id = _next_node_id(edges_by_from, current_id)
            if not next_id:
                _log_run(db, tenant_id, flow.id, guest_id, node, "success", "Delay with no next node -- flow ended")
                break
            delay_minutes = int(node.get("delay_minutes") or 60)
            from app.models.flow_execution import FlowPendingExecution
            from app.models.base import gen_uuid
            db.add(FlowPendingExecution(
                id=gen_uuid(), tenant_id=tenant_id, flow_id=flow.id, node_id=next_id,
                guest_id=guest_id, conversation_id=conversation_id,
                context={"guest_id": guest_id, "conversation_id": conversation_id},
                resume_at=datetime.now(timezone.utc) + timedelta(minutes=delay_minutes),
                status="pending",
            ))
            _log_run(db, tenant_id, flow.id, guest_id, node, "waiting", f"Waiting {delay_minutes}m")
            db.commit()
            return

        log.warning("flow_unknown_node_type", node_type=node_type, flow_id=flow.id)
        break

    db.commit()


class FlowMessageNotSent(Exception):
    """A flow message that must not go out; the reason is logged on the flow run."""


def _send_flow_message(db: Session, tenant_id: str, guest_id: str, conversation_id: Optional[str], text: str) -> None:
    """Send a flow "message" node's text to the guest on their official WhatsApp thread (Message row + send_whatsapp, the
    pipeline agent replies use; pre-authored, not AI-generated).

    Plain text only reaches a guest inside WhatsApp's 24-hour window (Meta drops it otherwise), so outside the window the
    step is refused with a reason instead of queueing a message that never arrives. Never written into a thread mirrored
    from an agent's personal WhatsApp (whatsapp_state only returns official threads). Stamped sender_kind="system": an
    automatic flow message is not a person contacting the guest (work_queue_signals.touch_rows)."""
    import uuid
    from app.models.conversation import ChannelType, Message, MessageDirection, MessageDeliveryState
    from app.services.booking_agenda_service import whatsapp_state

    del conversation_id   # the flow's own thread may be Instagram or a personal-WhatsApp mirror: always the official one
    state = whatsapp_state(db, tenant_id, guest_id)
    if not state["conversation_id"]:
        raise FlowMessageNotSent("the guest has no WhatsApp chat with the business number yet")
    if not state["window_open"]:
        raise FlowMessageNotSent("the guest's 24-hour WhatsApp window is closed; a plain message would not be delivered")

    message = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=state["conversation_id"],
        direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
        body=text, delivery_state=MessageDeliveryState.QUEUED, channel_status="queued",
        sender_name="Flow", sender_kind="system",
    )
    db.add(message)
    db.flush()
    db.commit()

    from app.workers.tasks.send_whatsapp import send_whatsapp
    send_whatsapp.delay(message_id=message.id, tenant_id=tenant_id)
