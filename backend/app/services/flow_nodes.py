"""WhatsApp flow canvas steps (docs/whatsapp/FLOW_CANVAS_SPEC.md), called from flow_engine.run_flow.

Sending steps: media (a file this workspace uploaded, key ``<tenant>/wa_flows/...``, signed at send time by
send_whatsapp), location (a map pin), buttons / list / cta_url (wa_interactive specs), question (plain text) and http
(an https call to the owner's own system, SSRF-guarded). Every send goes through flow_engine._send_flow_message, so the
24-hour window rule and the outbound Message row are the same as a "message" step.

Waiting: buttons, list and question park the run in flow_pending_executions with status ``awaiting_reply`` (24 h expiry
in resume_at; the delay beat ignores these rows). The guest's next inbound WhatsApp message resumes it
(``on_inbound``): interactive reply ids are ``wfl:<pending_id>:<option_id>``, a typed option title also counts, else
the ``other`` edge, else the row keeps waiting and normal handling runs. A question's answer is saved per ``save_as``.

Keyword trigger: an active flow with trigger ``keyword`` whose trigger node keywords match the message starts, once per
inbound message (a trigger-node run row carries the message id).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

log = structlog.get_logger()

NODE_TYPES = {"media", "location", "buttons", "list", "cta_url", "question", "http"}
WAITING_TYPES = {"buttons", "list", "question"}
MEDIA_KINDS = {"image", "video", "audio", "document"}
AWAITING = "awaiting_reply"
WAIT_HOURS = 24
REPLY_PREFIX = "wfl:"
FILE_FOLDER = "wa_flows"
HTTP_TIMEOUT_S = 10
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def option_reply_id(pending_id: str, option_id: str) -> str:
    return f"{REPLY_PREFIX}{pending_id}:{option_id}"


# ── running a step ───────────────────────────────────────────────────────────────────────────────────────────────────

def run_node(db: Session, tenant_id: str, flow, guest_id: str, guest, conversation_id, node: dict,
             edges_by_from: dict) -> tuple[str | None, bool]:
    """Run one canvas step. Returns (next node id, parked). A waiting step that could not be sent ends the run."""
    from app.models.base import gen_uuid
    from app.services import flow_engine as fe

    ntype = node.get("type")
    waiting = ntype in WAITING_TYPES
    pending = _new_pending(db, tenant_id, flow, guest_id, conversation_id, node, gen_uuid()) if waiting else None
    try:
        detail = _call_http(node, guest) if ntype == "http" else _send(db, tenant_id, guest_id, guest, node, pending)
    except fe.FlowMessageNotSent as exc:
        _drop(db, pending)
        fe._log_run(db, tenant_id, flow.id, guest_id, node, "skipped", f"Not sent: {exc}")
        return (None if waiting else fe._next_node_id(edges_by_from, node["id"])), False
    except Exception as exc:  # noqa: BLE001 -- one broken step is logged on the run; a plain step carries on
        _drop(db, pending)
        fe._log_run(db, tenant_id, flow.id, guest_id, node, "failed", error=str(exc)[:500])
        return (None if waiting else fe._next_node_id(edges_by_from, node["id"])), False
    if pending is not None:
        from app.models.flow_execution import FlowPendingExecution as P
        # One waiting step per guest: a newer one replaces any older one (newest wins).
        db.query(P).filter(P.tenant_id == tenant_id, P.guest_id == guest_id, P.status == AWAITING,
                           P.id != pending.id).update({"status": "done"}, synchronize_session=False)
        fe._log_run(db, tenant_id, flow.id, guest_id, node, "waiting", f"{detail}; waiting for the guest's reply")
        db.commit()
        return None, True
    fe._log_run(db, tenant_id, flow.id, guest_id, node, "success", detail)
    return fe._next_node_id(edges_by_from, node["id"]), False


def _new_pending(db, tenant_id, flow, guest_id, conversation_id, node, pending_id):
    """Added before the send so it commits with the outbound message: a fast tap always finds it."""
    from app.models.flow_execution import FlowPendingExecution
    row = FlowPendingExecution(
        id=pending_id, tenant_id=tenant_id, flow_id=flow.id, node_id=node["id"], guest_id=guest_id,
        conversation_id=conversation_id, context={"guest_id": guest_id, "node_type": node.get("type")},
        resume_at=datetime.now(timezone.utc) + timedelta(hours=WAIT_HOURS), status=AWAITING,
    )
    db.add(row)
    return row


def _drop(db, pending) -> None:
    if pending is not None:
        pending.status = "failed"
        db.commit()


def _send(db: Session, tenant_id: str, guest_id: str, guest, node: dict, pending) -> str:
    from app.services.flow_engine import FlowMessageNotSent, _render_template, _send_flow_message

    ntype = node["type"]
    text = _render_template(str(node.get("content") or ""), guest, {})[:1024]
    if ntype == "media":
        kind, key = node.get("media_kind"), str(node.get("file_key") or "")
        if kind not in MEDIA_KINDS or not key.startswith(f"{tenant_id}/{FILE_FOLDER}/"):
            raise FlowMessageNotSent("the file is missing or belongs to another workspace")
        caption = "" if kind == "audio" else _render_template(str(node.get("caption") or ""), guest, {})[:1024]
        filename = str(node.get("filename") or "").strip()[:120]
        meta = {"filename": filename} if filename and kind == "document" else None
        _send_flow_message(db, tenant_id, guest_id, None, caption, media_type=kind, media_url=key, meta=meta)
        return f"{kind.capitalize()} sent"
    if ntype == "location":
        lat, lng = float(node["latitude"]), float(node["longitude"])
        name, address = str(node.get("name") or "").strip(), str(node.get("address") or "").strip()
        label = " · ".join(x for x in (name, address) if x) or f"{lat}, {lng}"
        _send_flow_message(db, tenant_id, guest_id, None, f"Location: {label}", media_type="location",
                           meta={"location": {"latitude": lat, "longitude": lng, "name": name, "address": address}})
        return "Location sent"
    if ntype == "question":
        _send_flow_message(db, tenant_id, guest_id, None, text)
        return "Question sent"
    from app.services import wa_interactive
    spec = wa_interactive.validate(_interactive_spec(node, pending.id if pending is not None else ""))
    _send_flow_message(db, tenant_id, guest_id, None, text, meta={"interactive": spec})
    return {"buttons": "Buttons sent", "list": "List sent"}.get(ntype, "Link button sent")


def _interactive_spec(node: dict, pending_id: str) -> dict:
    ntype = node["type"]
    if ntype == "buttons":
        buttons = node.get("buttons") or []
        return {"kind": "buttons", "buttons": [str(b.get("title") or "") for b in buttons],
                "button_ids": [option_reply_id(pending_id, str(b.get("id"))) for b in buttons]}
    if ntype == "list":
        rows = [{"id": option_reply_id(pending_id, str(r.get("id"))), "title": str(r.get("title") or ""),
                 **({"description": str(r["description"])} if r.get("description") else {})}
                for r in node.get("rows") or []]
        return {"kind": "list", "button": str(node.get("button_label") or ""), "sections": [{"rows": rows}]}
    return {"kind": "cta_url", "title": str(node.get("button_label") or ""), "url": str(node.get("url") or "")}


def _call_http(node: dict, guest) -> str:
    """POST/GET the owner's own endpoint. https only, public addresses only, no redirects followed. The body may carry
    the guest's first name and phone (the owner asked for that); it is never logged."""
    import httpx

    from app.core.url_safety import assert_public_url
    from app.services.flow_engine import _render_template

    method = str(node.get("method") or "POST").upper()
    if method not in ("GET", "POST"):
        raise ValueError(f"method {method} is not allowed")
    url = str(node.get("url") or "").strip()
    # shortcut: the host is resolved again by httpx after this check (DNS rebinding window); pin the IP if this matters.
    assert_public_url(url, allow_http=False)
    body = _render_template(str(node.get("body") or ""), guest, {})
    is_json = body.lstrip().startswith(("{", "["))
    with httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=False) as client:
        resp = client.request(method, url, content=body.encode() if method == "POST" else None,
                              headers={"Content-Type": "application/json" if is_json else "text/plain"})
    if resp.status_code >= 400:
        raise RuntimeError(f"{method} answered HTTP {resp.status_code}")
    return f"{method} answered HTTP {resp.status_code}"


# ── the guest's next message ─────────────────────────────────────────────────────────────────────────────────────────

def on_inbound(db: Session, tenant_id: str, guest, conversation, msg: dict, text: str, message_id: str) -> str | None:
    """A reply to a waiting step, else a keyword flow. Returns the inbound message's automation_outcome when a flow
    took the message (the AI and keyword replies then stay out), else None."""
    from app.services.wa_catalog import reply_id

    if resume_on_reply(db, tenant_id, guest, conversation, text, reply_id(msg)):
        return "flow_reply"
    if start_keyword_flow(db, tenant_id, guest, conversation, text, message_id):
        return "flow_started"
    return None


def resume_on_reply(db: Session, tenant_id: str, guest, conversation, text: str, reply_id: str | None) -> bool:
    from app.api.v1.endpoints.messaging import WAFlow
    from app.models.flow_execution import FlowPendingExecution as P
    from app.services import flow_engine as fe

    row = (db.query(P).filter(P.tenant_id == tenant_id, P.guest_id == guest.id, P.status == AWAITING,
                              P.resume_at > datetime.now(timezone.utc))
           .order_by(P.created_at.desc()).first())
    if row is None:
        return False
    flow = db.query(WAFlow).filter_by(id=row.flow_id, tenant_id=tenant_id).first()
    node = next((n for n in (flow.nodes or []) if n.get("id") == row.node_id), None) if flow and flow.is_active else None
    if node is None or node.get("type") not in WAITING_TYPES:
        row.status = "done"   # the flow was switched off or edited: nothing to resume
        db.commit()
        return False
    edges = [e for e in (flow.edges or []) if e.get("from") == node["id"]]

    picked = None
    if node["type"] == "question":
        edge = edges[0] if edges else None
        detail = f"Answer saved as {node.get('save_as') or 'nothing'}"
    else:
        prefix, options = ("btn", node.get("buttons")) if node["type"] == "buttons" else ("row", node.get("rows"))
        options = options or []
        mine = f"{REPLY_PREFIX}{row.id}:"
        if reply_id and reply_id.startswith(mine):
            picked = next((o for o in options if str(o.get("id")) == reply_id[len(mine):]), None)
        if picked is None:
            wanted = (text or "").strip().lower()
            picked = next((o for o in options if str(o.get("title") or "").strip().lower() == wanted), None)
        label = f"{prefix}:{picked.get('id')}" if picked else "other"
        edge = next((e for e in edges if (e.get("label") or "") == label), None)
        if picked is None and edge is None:
            return False   # not an answer and no "other" path: keep waiting, normal handling runs
        detail = f"Guest picked {picked.get('title')}" if picked else "Guest wrote something else"

    # Claim it: two inbound messages at once must not both resume the same step.
    claimed = db.query(P).filter(P.id == row.id, P.status == AWAITING).update({"status": "done"}, synchronize_session=False)
    db.commit()
    if not claimed:
        return False
    if node["type"] == "question":
        _save_answer(db, tenant_id, guest, conversation, str(node.get("save_as") or ""), text)
    fe._log_run(db, tenant_id, flow.id, guest.id, node, "success", detail)
    db.commit()
    if edge is not None:
        fe.run_flow(db, tenant_id, flow, guest.id, conversation_id=conversation.id, start_node_id=edge["to"])
    return True


def _save_answer(db: Session, tenant_id: str, guest, conversation, save_as: str, text: str) -> None:
    answer = (text or "").strip()[:500]
    if not answer:
        return
    if save_as == "name":
        guest.name = answer[:255]
    elif save_as == "email":
        if not _EMAIL.fullmatch(answer):
            log.info("wa_flow_answer_not_an_email", tenant_id=tenant_id)
            return
        from app.services.identity_service import add_signal
        add_signal(db, tenant_id, guest.id, "email", answer.lower(), source="whatsapp_flow")
        if not guest.email:
            guest.email = answer.lower()[:255]
    elif save_as == "notes" or save_as.startswith("custom:"):
        inquiry = _open_inquiry(db, tenant_id, guest.id, conversation)
        if inquiry is None:
            log.info("wa_flow_answer_no_inquiry", tenant_id=tenant_id, save_as=save_as)
            return
        if save_as == "notes":   # an inquiry has no notes column: special_requests is the free-text note on the lead
            inquiry.special_requests = "\n".join(x for x in (inquiry.special_requests, answer) if x)
        else:
            inquiry.custom_fields = {**(inquiry.custom_fields or {}), save_as.split(":", 1)[1][:60]: answer}
    db.commit()


def _open_inquiry(db: Session, tenant_id: str, guest_id: str, conversation):
    from app.models.inquiry import Inquiry
    if getattr(conversation, "inquiry_id", None):
        inq = db.query(Inquiry).filter_by(id=conversation.inquiry_id, tenant_id=tenant_id).first()
        if inq is not None:
            return inq
    return (db.query(Inquiry).filter_by(tenant_id=tenant_id, guest_id=guest_id)
            .order_by(Inquiry.created_at.desc()).first())


def start_keyword_flow(db: Session, tenant_id: str, guest, conversation, text: str, message_id: str) -> bool:
    from app.api.v1.endpoints.messaging import WAFlow
    from app.models.flow_execution import WAFlowRun
    from app.services import flow_engine as fe
    from app.services.wa_keyword_replies import _matches

    flows = (db.query(WAFlow).filter_by(tenant_id=tenant_id, trigger="keyword", is_active=True)
             .order_by(WAFlow.created_at).all())
    for flow in flows:
        trigger = next((n for n in (flow.nodes or []) if n.get("type") == "trigger"), None)
        keywords = (trigger or {}).get("keywords") or []
        tc = {"keywords": keywords, "match": "exact" if (trigger or {}).get("match") == "exact" else "word"}
        if not keywords or not _matches(text, tc):
            continue
        marker = f"Started by message {message_id}"
        if db.query(WAFlowRun.id).filter_by(tenant_id=tenant_id, flow_id=flow.id, detail=marker).first():
            return True   # this message already started it (a redelivered webhook)
        fe._log_run(db, tenant_id, flow.id, guest.id, trigger, "success", marker)
        db.commit()
        fe.run_flow(db, tenant_id, flow, guest.id, conversation_id=conversation.id)
        log.info("wa_keyword_flow_started", tenant_id=tenant_id, flow_id=flow.id)
        return True
    return False
