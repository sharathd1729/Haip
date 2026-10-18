"""The AI sales agent: one step per guest message, run inside the concierge task (never in a request handler).

With ``brand_config.sales_agent.mode == "off"`` (the default) nothing here runs and the concierge behaves exactly as before.
Otherwise, for every message:

  1. the requirement is assembled from what the conversation and the lead already record (sales_requirement; no new extractor);
  2. availability comes from the booking calendar (caravan_availability: confirmed stays, iCal and maintenance blocks, the
     shared-vehicle pool), with the nearest free dates when the asked ones are taken;
  3. when the requirement is complete, the dates are free and price_disclosure is "grounded", the quote is priced from
     published records (sales_gateway / package_pricing_service), issued on the lead (quote_service.issue_options: snapshot,
     record versions, audit) and turned into a SalesAction: pending for staff (suggest), or sent by the agent itself
     (autopilot) when every guard passes and the reply itself went out;
  4. anything the agent must not decide (B2B/reseller, a discount request, a custom route, a refused quote) is handed to a
     person with a task;
  5. the reply is checked: no booking promised before payment, no discount offered, no link or "sent" claim the system did not
     make, no "available" without a calendar check (concierge_draft enforces the last one with its own availability matcher).

The model never decides a price, a vehicle, a date or a send: it is told what the code did (the ``sales_agent`` fact) and words it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.inquiry_360 import InquiryQuote
from app.models.sales_action import SalesAction
from app.services import business_data_service as bds
from app.services import caravan_availability, sales_action_service, sales_requirement
from app.services import quote_send_service as qss
from app.services import quote_service as qs
from app.services.price_policy import price_mode
from app.services.sales_agent_settings import mode as agent_mode

log = structlog.get_logger()

HANDOFF_WORDS = {
    "b2b": "a travel agent / reseller enquiry", "discount_request": "the guest asked for a discount",
    "custom_route": "a route that is not one of the published routes", "draft_records": "the plan or route is still a draft",
    "guest_wants_person": "the guest asked for a person",
}


# Statuses where a quote already exists for the lead (the agent's or staff's): no generic "call about pricing" task on top.
OWN_WORK_STATUSES = ("quote_pending", "quote_already_sent", "quote_declined", "staff_quote", "quote_ready", "quote_sending")


@dataclass
class SalesTurn:
    mode: str = "off"
    status: Optional[str] = None
    facts: list = field(default_factory=list)
    action_id: Optional[str] = None
    created_now: bool = False
    autopilot_candidate: bool = False
    hold_reasons: list = field(default_factory=list)
    handoff: Optional[str] = None
    inquiry_id: Optional[str] = None

    @property
    def active(self) -> bool:
        return self.mode != "off"


def _staff_quote(db: Session, tenant_id: str, inquiry_id: str) -> Optional[InquiryQuote]:
    """A live quote a PERSON issued on this lead: the agent never replaces it."""
    now = datetime.now(timezone.utc)
    for q in db.query(InquiryQuote).filter(InquiryQuote.tenant_id == tenant_id, InquiryQuote.inquiry_id == inquiry_id,
                                           InquiryQuote.is_active.is_(True), InquiryQuote.created_by.isnot(None)).all():
        vu = q.valid_until if q.valid_until is None or q.valid_until.tzinfo else q.valid_until.replace(tzinfo=timezone.utc)
        if q.status == "issued" and (vu is None or vu >= now):
            return q
    return None


def _stay_check(db: Session, tenant_id: str, q) -> tuple[str, bool]:
    """(stay_check, overnight). An overnight trip counts as checked only when the owner marked its plan or route auto-bookable."""
    overnight = bool(q.nights) or any(s.get("overnight") for s in ((q.km or {}).get("stops") or []))
    if not overnight:
        return "not_checked", False
    auto = bool(bds.parse(bds.get_effective(db, tenant_id, "package", q.package_key)).auto_bookable)
    dest = (q.destination or {}).get("key")
    if not auto and dest:
        rec = bds.get_effective(db, tenant_id, "destination", dest)
        auto = bool(rec is not None and bds.parse(rec).auto_bookable)
    return ("confirmed" if auto else "not_checked"), True


def _holds(db: Session, tenant_id: str, rows: list, guest, overnight: bool, stay_check: str, details: dict) -> list[str]:
    """Why the agent would not send this quote itself. Empty = autopilot may send (if the reply itself goes out)."""
    holds: list[str] = []
    if overnight and stay_check != "confirmed":
        holds.append("The overnight stay needs a check with the partner first (the plan or route is not marked auto-bookable).")
    ready = qss.readiness(db, tenant_id, rows[0], rows, guest)
    holds += [b["message"] for b in ready["blockers"] if b["code"] != "stay_not_confirmed"]
    holds += [w["message"] for w in ready["warnings"]]
    if details.get("wants_human"):
        holds.append("The guest asked to speak to a person.")
    if details.get("sentiment") == "frustrated":
        holds.append("The guest sounds frustrated.")
    return holds


def prepare_turn(db: Session, tenant, conversation, inquiry, guest, details: Optional[dict], text: str) -> SalesTurn:
    """Run the agent's step for this message. Commits what it issues (so no audit lock is held during the model call)."""
    mode = agent_mode(tenant)
    if mode == "off":
        return SalesTurn()
    details = details or {}
    turn = SalesTurn(mode=mode, inquiry_id=getattr(inquiry, "id", None))
    req = sales_requirement.assemble(db, tenant.id, inquiry, guest, details, text)
    if details.get("wants_human") and not req.handoff:
        req.handoff = "guest_wants_person"
    info: dict = {"requirement": req.as_fact()}

    avail = None
    if req.check_in and req.check_out:
        vehicle_ids = None
        if req.package_key:
            vehicle_ids = list(bds.parse(bds.get_effective(db, tenant.id, "package", req.package_key)).vehicle_property_ids) or None
        try:
            avail = caravan_availability.check(db, tenant.id, req.check_in, req.check_out, int(req.adults or 1), req.children,
                                               vehicle_ids, today=bds.tenant_today(db, tenant.id))
            turn.facts.append(caravan_availability.as_check_fact(avail, int(req.adults or 1), req.children))
        except Exception as exc:  # noqa: BLE001 -- a failed lookup is said, never guessed
            log.warning("sales_agent_availability_failed", tenant_id=tenant.id, error=str(exc))
            turn.facts.append({"tool": "check_availability", "source": "calendar", "lookup_failed": True, "result": [],
                               "args": {"checkin": req.check_in.isoformat(), "checkout": req.check_out.isoformat(),
                                        "adults": req.adults or 1, "children": req.children}})
            avail = {"available": False, "reason": "lookup_failed"}

    if req.handoff:
        status, turn.handoff = "handoff", req.handoff
    elif avail is not None and avail.get("reason") in ("lookup_failed", "no_vehicles"):
        status = "availability_unknown"
    elif avail is not None and not avail["available"]:
        status = "unavailable" if avail.get("reason") != "too_small" else "too_small"
    elif req.missing or inquiry is None:
        status = "collecting"
    elif price_mode(tenant) != "grounded":
        status = "price_by_team"
    else:
        status = _quote_step(db, tenant, conversation, inquiry, guest, details, req, turn, info)
    turn.status = status
    info.update({"mode": mode, "status": status, "handoff": HANDOFF_WORDS.get(turn.handoff or "", turn.handoff)})
    turn.facts.append({"tool": "sales_agent", "result": info})
    return turn


def _quote_step(db, tenant, conversation, inquiry, guest, details, req, turn: SalesTurn, info: dict) -> str:
    if _staff_quote(db, tenant.id, inquiry.id) is not None:
        return "staff_quote"
    key = req.key()
    prior = (db.query(SalesAction).filter(SalesAction.tenant_id == tenant.id, SalesAction.inquiry_id == inquiry.id,
                                          SalesAction.requirement_key == key,
                                          SalesAction.created_at >= datetime.now(timezone.utc) - sales_action_service.WINDOW)
             .order_by(SalesAction.created_at.desc()).first())
    if prior is not None:                       # one quote per lead per 24 h for the same requirement, whatever happened to it
        info["quote"] = prior.summary
        return {"pending": "quote_pending", "sending": "quote_already_sent", "sent": "quote_already_sent"}.get(prior.status, "quote_declined")

    res, q = sales_requirement.price(db, tenant.id, req)
    turn.facts.append({"tool": "package_quote", "source": "sales_agent",
                       "args": {"package_key": req.package_key, "checkin": req.check_in.isoformat(), "checkout": req.check_out.isoformat()},
                       "result": res.data if res.ok else {"refused": res.data.get("reason"), "message": res.data.get("message")},
                       "sources": res.sources, "flags": res.flags})
    if not q.ok:
        turn.handoff = f"refused:{q.reason}"
        return "handoff"
    if q.uses_drafts:
        turn.handoff = "draft_records"
        return "handoff"
    fallback = sales_requirement.fallback_plan(db, tenant.id, req, q.package_key)
    stay_check, overnight = _stay_check(db, tenant.id, q)
    rows = qs.issue_options(db, tenant.id, inquiry.id, q, fallback, None,
                            meta={"stay_check": stay_check, "channel": "direct", "source": "sales_agent"})
    holds = _holds(db, tenant.id, rows, guest, overnight, stay_check, details)
    action = sales_action_service.create(db, tenant.id, inquiry_id=inquiry.id, conversation_id=conversation.id, primary=rows[0],
                                         fallback=rows[1] if len(rows) > 1 else None, mode=turn.mode, requirement_key=key,
                                         hold_reasons=holds)
    db.commit()
    turn.action_id, turn.created_now, turn.hold_reasons = action.id, True, holds
    turn.autopilot_candidate = turn.mode == "autopilot" and not holds
    info["quote"] = action.summary
    return "quote_sending" if turn.autopilot_candidate else "quote_ready"


# ─── facts and guards ────────────────────────────────────────────────────────────────────────────────────

_LEGACY_PRICE_KEYS = ("price_per_night", "currency")


def merge_facts(tenant, grounded_facts: list, turn: SalesTurn) -> list:
    """The facts the prompt and guards see. The agent's calendar check and package quote replace the older lookups for the same
    thing; in grounded price mode with published packages, the only figures left are the package price engine's."""
    out = list(grounded_facts)
    mine = {f.get("tool") for f in turn.facts}
    if "check_availability" in mine:
        out = [f for f in out if not (f.get("tool") == "check_availability" and (f.get("args") or {}).get("checkin"))]
    if "package_quote" in mine:
        out = [f for f in out if f.get("tool") != "package_quote"]
    packages = any(f.get("tool") == "business_data" and (f.get("result") or {}).get("packages") for f in out)
    if price_mode(tenant) == "grounded" and packages:
        cleaned = []
        for f in out:
            if f.get("tool") == "get_quote":
                continue
            if f.get("tool") == "check_availability":
                f = {**f, "result": [{k: v for k, v in r.items() if k not in _LEGACY_PRICE_KEYS} for r in f.get("result") or []]}
            cleaned.append(f)
        out = cleaned
    return out + list(turn.facts)


_URL_RE = re.compile(r"https?://|\brzp\.io\b|\bwww\.", re.IGNORECASE)
_OFFER_RE = re.compile(r"\b\d+\s*%\s*(?:off|discount)\b|\bdiscount of\b|\b(?:give|offer|apply|extend)\w*\s+(?:you\s+)?(?:a\s+|an\s+)?"
                       r"(?:\w+\s+)?discount\b|\bspecial (?:price|rate|deal|offer) for you\b", re.IGNORECASE)
_BOOKED_RE = re.compile(r"\b(?:(?:you(?:'re| are)|it(?:'s| is)|trip is|booking is|reservation is|caravan is|dates are|everything is)\s+"
                        r"(?:now\s+|all\s+)?(?:booked|confirmed|reserved|locked in|blocked for you)"
                        r"|(?:i|we)(?:'ve| have)\s+(?:booked|reserved|blocked|locked)\b"
                        r"|(?:booking|reservation)\s+(?:is\s+|has been\s+)?confirmed)\b", re.IGNORECASE)
_SENT_RE = re.compile(r"\b(?:(?:i|we)(?:'ve| have)\s+(?:just\s+)?sent\s+(?:you\s+)?(?:the|your|a)\s+(?:quote|payment link|link)"
                      r"|(?:quote|payment link|link)\s+(?:is|has been)\s+sent|here(?:'s| is)\s+(?:the|your)\s+(?:payment\s+)?link)\b",
                      re.IGNORECASE)


def _has_live_booking(grounded_facts: list) -> bool:
    for f in grounded_facts:
        if f.get("tool") == "guest_bookings":
            if any(b.get("status") in ("confirmed", "checked_in") for b in f.get("result") or []):
                return True
    return False


def check_reply(reply_text: str, grounded_facts: list, turn: SalesTurn) -> Optional[str]:
    """Why this reply must not leave unreviewed in sales mode, or None."""
    if not turn.active or not reply_text:
        return None
    if _URL_RE.search(reply_text):
        return "contains a link (payment links go only in the quote message)"
    if _OFFER_RE.search(reply_text):
        return "offers a discount (only staff apply the published discount policy)"
    if _BOOKED_RE.search(reply_text) and not _has_live_booking(grounded_facts):
        return "says the trip is booked or confirmed before any payment"
    if _SENT_RE.search(reply_text) and turn.status not in ("quote_sending", "quote_already_sent"):
        return "says a quote or link was sent when the system did not send one"
    return None


# ─── after the draft ─────────────────────────────────────────────────────────────────────────────────────

def after_draft(db: Session, tenant_id: str, turn: SalesTurn, draft_message_id: str, reply_auto_sent: bool, conversation, guest) -> None:
    """Tie the action to the draft; autopilot sends only when the reply itself went out unreviewed, else it waits for staff."""
    if turn.action_id:
        _settle_action(db, tenant_id, turn, draft_message_id, reply_auto_sent, conversation, guest)
    if turn.handoff:
        _handoff_task(db, tenant_id, turn, conversation, guest)


def _settle_action(db, tenant_id, turn, draft_message_id, reply_auto_sent, conversation, guest) -> None:
    row = db.query(SalesAction).filter_by(id=turn.action_id, tenant_id=tenant_id).first()
    if row is None:
        return
    row.message_id = row.message_id or draft_message_id
    if turn.autopilot_candidate and row.status == "pending":
        if reply_auto_sent and sales_action_service.start_autopilot(db, tenant_id, row.id):
            db.commit()
            from app.workers.tasks.sales_agent_tasks import send_quote
            try:
                send_quote.delay(tenant_id=tenant_id, action_id=row.id)
                return
            except Exception as exc:  # noqa: BLE001 -- broker down: a person sends it
                log.error("sales_agent_enqueue_failed", tenant_id=tenant_id, action_id=row.id, error=str(exc))
                db.query(SalesAction).filter_by(id=row.id, tenant_id=tenant_id).update(
                    {SalesAction.status: "pending", SalesAction.decided_at: None}, synchronize_session=False)
                row = db.query(SalesAction).filter_by(id=turn.action_id, tenant_id=tenant_id).first()
        row.hold_reasons = list(row.hold_reasons or []) + ["The AI reply itself was held for review, so the quote waits for a person too."]
    db.commit()
    if turn.created_now:
        _push(db, tenant_id, conversation, guest, "Quote ready to send", "the AI prepared a quote and payment link. Review and send.")


def _handoff_task(db, tenant_id, turn, conversation, guest) -> None:
    from app.models.task import Task
    from app.services import task_service
    label = (getattr(guest, "name", None) or "").strip() or "this lead"
    reason = HANDOFF_WORDS.get(turn.handoff, turn.handoff)
    if turn.handoff.startswith("refused:"):
        reason = "the quote could not be priced (" + turn.handoff.split(":", 1)[1].replace("_", " ") + ")"
    title = f"Sales agent handed over: {label} ({reason})"[:255]
    if db.query(Task.id).filter(Task.tenant_id == tenant_id, Task.conversation_id == conversation.id, Task.is_done.is_(False),
                                Task.title == title).first():
        return
    task_service.create_task(db, tenant_id, title, priority="high", guest_id=getattr(guest, "id", None),
                             inquiry_id=turn.inquiry_id, conversation_id=conversation.id, due_date=datetime.now(timezone.utc), commit=False)
    db.commit()
    _push(db, tenant_id, conversation, guest, "Lead needs a person", f"{reason}.")


def _push(db, tenant_id, conversation, guest, title: str, body: str) -> None:
    try:
        from app.services.push_service import send_to_tenant
        label = (getattr(guest, "name", None) or "").strip() or "A guest"
        send_to_tenant(db, tenant_id, title=title, body=f"{label}: {body}", url=f"/dashboard/inbox?conversation={conversation.id}")
    except Exception as exc:  # noqa: BLE001 -- a missed push never costs the guest their reply
        log.warning("sales_agent_push_failed", tenant_id=tenant_id, error=str(exc))
