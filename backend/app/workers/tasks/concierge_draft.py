"""
AI Concierge draft task — generates WhatsApp reply using brand-voice + KB RAG.
In shadow mode: stores as ai_drafted=True, awaits agent approval.
In autonomous mode: queues send_whatsapp directly.

AI Autonomy Plan Phase 1, ticket 4: drafts for availability/price-quote
intents are now grounded in real inventory (check_availability/get_quote)
via a bounded loop, with a deterministic hallucination guard on the
output. See _ground_reply() and _check_grounding() below.
"""
import asyncio
import json
import re
import time
import uuid
from datetime import date
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.conversation import Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.inquiry import Inquiry
from app.adapters.llm import get_llm
from app.core.prompt_versions import stamp


def _run_async(coro):
    """Run an async coroutine from a sync Celery task safely (Python 3.10+)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
from app.services.concierge_service import build_concierge_context, is_latest_pending_draft, unanswered_guest_text
from app.core.database import set_tenant_context
import structlog

log = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))

# Already the canonical ToolSpec shape (adapters/llm/tools.py) -- passed to
# adapter.complete() raw, unconverted. Works unchanged for both Claude (its
# native dialect) and Gemini (adapters/llm/gemini.py's own
# _anthropic_tool_to_gemini() does the conversion internally).
CONCIERGE_TOOL = {
    "name": "concierge_reply",
    "description": "Draft a WhatsApp reply for the guest",
    "input_schema": {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "confidence": {"type": "number"},
            "citations": {"type": "array", "items": {"type": "string"}},
            "needs_human": {"type": "boolean"},
            "reason_needs_human": {"type": ["string", "null"]},
        },
        "required": ["reply", "confidence", "needs_human"],
    },
}

# T3.2: fallback only -- per-tenant threshold (tenant.ig_ai_confidence_threshold)
# is read below and takes precedence whenever the tenant row has a value.
CONFIDENCE_THRESHOLD = 0.78

# ── Ticket 4: intent gating + bounded grounding loop ────────────────────────
#
# The plan assumed an existing per-message intent classifier decides when to
# run the grounded tool loop. It doesn't exist (verified against the real
# codebase -- classify_intent.py is a nightly keyword job over
# Inquiry/Call.occasion, unrelated to chat messages). This is the real one,
# scoped to exactly this decision: is this message worth spending tool
# calls on, and if so what dates/pax does it imply.
INTENT_TOOL = {
    "name": "classify_and_extract",
    "description": "Classify the guest's message intent and extract any stay dates/party size mentioned",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["availability_check", "price_quote", "faq_answer", "complaint", "general"],
                "description": (
                    "availability_check: asking if specific dates are free. "
                    "price_quote: asking cost/pricing for a stay. "
                    "faq_answer: policy, amenity, or location question. "
                    "complaint: expressing dissatisfaction. "
                    "general: greeting, unclear, or anything else."
                ),
            },
            "check_in": {"type": ["string", "null"], "description": "YYYY-MM-DD if a check-in date is stated or clearly inferable, else null"},
            "check_out": {"type": ["string", "null"], "description": "YYYY-MM-DD if a check-out date is stated or clearly inferable, else null"},
            "adults": {"type": ["integer", "null"]},
            "children": {"type": ["integer", "null"]},
        },
        "required": ["intent"],
    },
}

# Per plan §1 "DECISIONS TO LOCK": these are the only two intents worth
# grounding in v1 -- deterministic, verifiable, high volume. faq_answer
# pattern-matches over KB text (no inventory needed); complaint needs a
# human, not a price lookup.
GROUNDED_INTENTS = {"availability_check", "price_quote"}

# Hard rule (plan §1.2): max 4 tool calls, 8s wall clock. On exhaustion,
# degrade to the ungrounded path and force needs_human=True -- never leave
# a guest unanswered because the loop hung.
MAX_GROUNDING_SECONDS = 8
MAX_TOOL_CALLS = 4

# Confirmed live: a single concierge_draft run took 56.7s end to end, almost
# entirely one adapters/llm/nvidia_nim.py chat/completions call (~55s for
# nvidia/llama-3.3-nemotron-super-49b-v1.5) -- that call had NO timeout at
# all (the openai SDK client is constructed with no `timeout=`, so it
# inherits the SDK's own 10-minute default). Grounding already has its own
# bounded MAX_GROUNDING_SECONDS; the final reply completion -- the part the
# guest is actually waiting on -- had nothing.
#
# Three real post-deploy timeouts (25.03s / 26.8s / 35.02s, each landing
# within ~1s of whatever the bound was set to at the time -- 25s, then 35s)
# all trace back to the SAME conversation, and its actual rendered prompt
# measured ~1500 tokens for a ~60-token reply -- nowhere near large enough
# to explain that latency on its own. Every failure clustering right at the
# ceiling rather than scattering above/below it is the signature of a
# request genuinely hanging, not one that's merely slow -- raising the bound
# further only makes the guest wait longer for the same outcome. A retry
# with a fresh request (new client, new connection) has a real chance of
# succeeding where a stuck one won't, so this is now bounded attempts at a
# shorter per-attempt timeout rather than one long wait.
MAX_REPLY_SECONDS = 20  # per attempt
MAX_REPLY_ATTEMPTS = 2  # worst case ~2x MAX_REPLY_SECONDS before falling back

# Confirmed live: one specific conversation's completion call never returned
# even with NO timeout at all (tested directly against NVIDIA with a 90s
# ceiling -- still nothing, no exception, no partial output). The adapter's
# shared default is max_tokens=4096 (sized for tasks like report_gen/
# deep_reason with genuinely long output), but this reply is capped at
# "UNDER 45 WORDS" by its own prompt -- a few hundred tokens covers the
# reply text plus the small JSON tool-call wrapper with real headroom. If
# the model gets into a degenerate repetition loop for a specific prompt (a
# real, known failure mode -- generation that never hits a natural stop
# token), a 4096-token ceiling gives it a huge amount of rope, and since
# this call isn't streamed, nothing comes back to the client until
# generation is completely finished, however long that takes. A tight cap
# bounds the worst case regardless of what's actually happening inside the
# model.
REPLY_MAX_TOKENS = 400

_MONEY_RE = re.compile(r"₹\s?[\d,]+(?:\.\d+)?")
_AVAILABILITY_WORDS_RE = re.compile(
    r"\b(available|unavailable|booked out|fully booked|not available|is free|are free)\b",
    re.IGNORECASE,
)
# _AVAILABILITY_WORDS_RE alone can't tell "the caravan is available for those
# dates" (a real claim needing grounding) from "add-ons like BBQ, bonfire, or
# private chef available" (a menu listing sourced from the KB, no dates
# involved). Confirmed live: the latter zeroed confidence on every draft that
# mentioned an add-on, silently overriding autonomous mode regardless of the
# model's own confidence or the threshold. Only treat it as an availability
# claim when the same sentence also references a date/stay, which is what
# actually needs grounding.
_STAY_CONTEXT_RE = re.compile(
    r"\b(date|dates|night|nights|check-?in|check-?out|book|booking|stay|"
    r"room|caravan|property|weekend)\b|\d",
    re.IGNORECASE,
)
# Catches "designed for up to 4 guests", "sleeps 8", "max 6 people", "fits
# 4 pax", "can host 4 guests" -- any specific headcount-capacity claim,
# which must trace back to a real max_adults value (see _check_grounding's
# capacity check below).
#
# "host(s)?" added after a confirmed live miss: a guest stated her own
# party size (4) and the model echoed it back as "can comfortably host 4
# guests" -- not factually wrong (real max_adults was 8, grounded and
# available), but exactly the phrasing this guard exists to catch, since
# it evaded every other verb in this alternation and auto-sent unchecked.
_CAPACITY_RE = re.compile(
    r"\b(?:up to|max(?:imum)?|fits?|sleeps?|holds?|seats?|hosts?|accommodat\w*|capacity of)\s+(\d+)\s*"
    r"(?:guests?|people|persons?|pax|adults?)\b",
    re.IGNORECASE,
)


async def _classify_and_extract(latest_message: str) -> dict:
    adapter = get_llm("quick_classify")
    today = date.today().isoformat()
    result = await adapter.complete(
        system_prompt=(
            f"Today's date is {today}. Classify this WhatsApp message from a "
            "hospitality guest and extract any stay details mentioned. "
            "Resolve relative dates (e.g. 'next weekend', 'the 14th') against "
            "today's date. If no year is given, assume the next future "
            "occurrence of that date."
        ),
        user_message=latest_message,
        tools=[INTENT_TOOL],
    )
    return result.get("tool_use") or {"intent": "general"}


async def _ground_reply(db, tenant_id: str, latest_message: str, inquiry) -> tuple[str, list, list]:
    """Returns (intent, grounded_facts, suggested_actions). grounded_facts is
    [] whenever grounding wasn't attempted or found nothing -- never
    fabricated. suggested_actions is the RecommendedAction[] shape
    (HAIP Inbox prototype-wiring plan, ticket 4), populated only when a real
    quote was fetched -- never a guess at what the guest wants."""
    classification = await _classify_and_extract(latest_message)
    intent = classification.get("intent", "general")
    if intent not in GROUNDED_INTENTS:
        return intent, [], []

    check_in = classification.get("check_in") or (inquiry.check_in if inquiry else None)
    check_out = classification.get("check_out") or (inquiry.check_out if inquiry else None)
    adults = classification.get("adults") or (inquiry.adults if inquiry else None) or 1
    children = classification.get("children") or (inquiry.children if inquiry else 0) or 0

    if not check_in or not check_out:
        # Can't ground without dates -- the prompt already instructs the
        # model to ask a clarifying question when context is insufficient.
        return intent, [], []

    from app.services.calculator_service import calculator_service

    grounded_facts: list = []
    suggested_actions: list = []
    property_id = inquiry.property_id if inquiry else None

    # check_availability -- same underlying service the MCP tool of the same
    # name wraps (app/mcp/tools.py), called directly here rather than
    # through the MCP dispatch path: that path is scoped to external
    # assistants with a real authenticated user identity and its own audit
    # trail (action="mcp.tool.*"); this internal loop has neither, and
    # routing it through MCP's audit log would misrepresent an internal
    # HAIP task as an external client's tool call.
    try:
        results = calculator_service.search(
            db, tenant_id=tenant_id, checkin=check_in, checkout=check_out,
            adults=adults, children=children, property_id=property_id,
        )
    except Exception as exc:
        log.warning("concierge_grounding_availability_failed", tenant_id=tenant_id, error=str(exc))
        return intent, [], []

    # Confirmed live bug: a guest asking about a 20-person group got told
    # "our caravans are designed for up to 4 guests" -- Property.max_adults
    # is actually 8 for both real caravans, so the model invented that
    # number outright (the prompt never renders a capacity figure at all).
    # PropertyRate already carries max_adults (calculator_service.py); it
    # just wasn't being copied into the fact dict, so the model had no real
    # number to cite when explaining why nothing matched. Copying it in
    # here, plus the empty-results capacity note below, plus the
    # _check_grounding() guard extension, closes that gap the same way the
    # price/availability guards already do for their claim types.
    availability_fact: dict = {
        "tool": "check_availability",
        "args": {"checkin": check_in, "checkout": check_out, "adults": adults, "children": children, "property_id": property_id},
        "result": [
            {
                "property_id": r.property_id, "property_name": r.property_name,
                "available": r.available, "price_per_night": str(r.price_per_night),
                "nights": r.nights, "currency": r.currency, "max_adults": r.max_adults,
            }
            for r in results
        ],
    }
    if not results:
        total_guests = adults + children
        capacity = _max_known_capacity(db, tenant_id, property_id)
        if capacity is not None and total_guests > capacity:
            availability_fact["max_capacity_note"] = capacity
    grounded_facts.append(availability_fact)

    # get_quote -- only for a price_quote intent, and only when there's an
    # unambiguous single property to quote (already scoped by the inquiry,
    # or exactly one match came back).
    if intent == "price_quote" and len(grounded_facts) < MAX_TOOL_CALLS and results:
        target = next((r for r in results if r.property_id == property_id), None) or (results[0] if len(results) == 1 else None)
        if target:
            try:
                quote = calculator_service.build_quote(
                    db, tenant_id=tenant_id, property_id=target.property_id,
                    checkin=check_in, checkout=check_out, adults=adults, children=children,
                )
            except Exception as exc:
                log.warning("concierge_grounding_quote_failed", tenant_id=tenant_id, error=str(exc))
                quote = None
            if quote:
                grounded_facts.append({
                    "tool": "get_quote",
                    "args": {"property_id": target.property_id, "checkin": check_in, "checkout": check_out},
                    "result": {
                        "subtotal": str(quote.subtotal), "gst": str(quote.gst),
                        "total": str(quote.total), "advance_amount": str(quote.advance_amount),
                        "currency": quote.currency,
                    },
                })
                # Ticket 4: a real quote exists -- offer it as a one-click
                # send_quote card in the thread, same dispatch path
                # automation_engine.py::_action_send_quote already uses.
                suggested_actions.append({
                    "action_type": "send_quote",
                    "label": "Send full quote",
                    "action_config": {
                        "property_id": target.property_id,
                        "checkin": check_in, "checkout": check_out,
                        "adults": adults, "children": children,
                    },
                    "confirm": True,
                })

    return intent, grounded_facts, suggested_actions


def _max_known_capacity(db, tenant_id: str, property_id: "str | None") -> "int | None":
    """Real max_adults across the tenant's active properties (or just the
    one in scope, if the inquiry is already tied to a property) -- used so
    an empty availability result can tell the model the true capacity
    instead of leaving it to guess one. None if there's nothing to report
    (no active properties at all)."""
    from app.models.property import Property
    q = db.query(Property).filter_by(tenant_id=tenant_id, is_active=True)
    if property_id:
        q = q.filter(Property.id == property_id)
    values = [p.max_adults for p in q.all() if p.max_adults]
    return max(values) if values else None


def _check_grounding(reply_text: str, grounded_facts: list) -> tuple[bool, "str | None"]:
    """Deterministic post-check (plan §1.3): every ₹ figure the draft cites
    must appear somewhere in grounded_facts' results, and an availability
    claim must not be made with zero grounding attempted at all. Not full
    NLP understanding -- a conservative, literal check on the highest-risk
    claim types (a wrong price is the worst-case outcome).

    Capacity check added after a confirmed live hallucination: a guest
    asking about a 20-person group was told "designed for up to 4 guests"
    -- the real max_adults is 8. Same shape as the money check: any
    "up to/max/fits/sleeps N guests"-style claim must match a real number
    from grounded_facts (per-property max_adults, or the empty-results
    max_capacity_note), not just sound plausible."""
    money_mentions = _MONEY_RE.findall(reply_text)
    availability_mentions = [
        m
        for sentence in re.split(r"(?<=[.!?])\s+", reply_text)
        if _AVAILABILITY_WORDS_RE.search(sentence) and _STAY_CONTEXT_RE.search(sentence)
        for m in _AVAILABILITY_WORDS_RE.findall(sentence)
    ]
    capacity_mentions = _CAPACITY_RE.findall(reply_text)

    known_capacities: set[str] = set()
    for fact in grounded_facts:
        if fact.get("tool") != "check_availability":
            continue
        for p in fact.get("result", []):
            if p.get("max_adults"):
                known_capacities.add(str(p["max_adults"]))
        if fact.get("max_capacity_note"):
            known_capacities.add(str(fact["max_capacity_note"]))

    if capacity_mentions:
        bad_capacity = [n for n in capacity_mentions if n not in known_capacities]
        if bad_capacity:
            return False, f"cites capacity {bad_capacity!r}, not present in grounded_facts (known: {known_capacities or 'none'})"

    if not grounded_facts:
        if money_mentions or availability_mentions:
            return False, f"cites price/availability with zero grounded_facts: {money_mentions or availability_mentions}"
        return True, None

    grounded_blob = json.dumps(grounded_facts, default=str)
    for money in money_mentions:
        digits = re.sub(r"[^\d]", "", money)
        if digits and digits not in grounded_blob:
            return False, f"cites {money!r}, not present in grounded_facts"
    return True, None


def _maybe_create_price_handoff(
    db, *, tenant_id: str, conversation, guest, inquiry, intent: str,
    qualified: bool, price_leak: bool,
) -> None:
    """Queue a human callback when pricing is in play.

    Fires when the guest asked about cost, or when we have enough detail to
    hold a real pricing conversation. Deduplicated per conversation on the
    open task, so a lead who asks about price four times produces one task,
    not four.
    """
    from app.models.task import Task

    wants_pricing = intent == "price_quote" or price_leak
    if not (wants_pricing or qualified):
        return
    # Nothing to talk about yet -- a callback with no dates and no party size
    # wastes the agent's call and the guest's time.
    if not qualified and not wants_pricing:
        return

    existing = (
        db.query(Task)
        .filter_by(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            is_done=False,
        )
        .filter(Task.title.ilike("Call lead about pricing%"))
        .first()
    )
    if existing:
        return

    guest_label = (getattr(guest, "name", None) or "").strip() or "this lead"
    task = Task(
        tenant_id=tenant_id,
        title=f"Call lead about pricing — {guest_label}",
        priority="high" if qualified else "medium",
        guest_id=getattr(guest, "id", None),
        inquiry_id=getattr(inquiry, "id", None),
        conversation_id=conversation.id,
    )
    db.add(task)
    db.commit()
    log.info(
        "price_handoff_task_created",
        tenant_id=tenant_id, conversation_id=conversation.id,
        task_id=task.id, qualified=qualified, intent=intent,
    )

    # Surface it immediately -- a task nobody sees until they open the list
    # is not a handoff.
    try:
        from app.services.push_service import send_to_tenant
        send_to_tenant(
            db, tenant_id,
            title="Lead waiting on pricing",
            body=f"{guest_label} asked about pricing. Call to discuss options.",
            url=f"/dashboard/inbox?conversation={conversation.id}",
        )
    except Exception as exc:
        log.warning("price_handoff_push_failed", tenant_id=tenant_id, error=str(exc))


# ── Task ─────────────────────────────────────────────────────────────────────

_VALID_TONES = {"warm", "formal", "brief", "persuasive"}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, name="tasks.concierge_draft")
def concierge_draft(self, message_id: str, conversation_id: str, tenant_id: str, tone: str | None = None):
    from app.workers.tasks.send_whatsapp import send_whatsapp
    from app.workers.tasks.send_instagram_dm import send_instagram_dm

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        conversation = db.query(Conversation).filter_by(id=conversation_id, tenant_id=tenant_id).first()
        if not conversation:
            log.error("concierge_draft_conversation_not_found", conversation_id=conversation_id)
            return

        # Message-burst debounce: a newer inbound message arrived and
        # queued its own (fresher-delayed) concierge_draft run after this
        # one was scheduled -- that run is the one that should actually
        # draft, covering this message too via unanswered_guest_text()
        # below. No-op here rather than writing a second, disjointed draft.
        if not is_latest_pending_draft(tenant_id, conversation_id, message_id):
            log.info("concierge_draft_superseded", conversation_id=conversation_id, message_id=message_id)
            return

        guest_id = conversation.guest_id
        ctx = build_concierge_context(db, tenant_id=tenant_id, conversation_id=conversation_id, guest_id=guest_id)

        guest = ctx["guest"]
        tenant = ctx["tenant"]
        inquiry = ctx["inquiry"]

        # "Off" must suppress drafting entirely, on every channel. The
        # Instagram path checked this before dispatching but the WhatsApp
        # path never did, so a tenant set to Off still accumulated drafts on
        # WhatsApp. Checking here covers both callers in one place.
        from app.services import ai_mode_service
        if ai_mode_service.resolve_mode(tenant, conversation) == "off":
            log.info(
                "concierge_draft_skipped_mode_off",
                conversation_id=conversation_id, tenant_id=tenant_id,
            )
            return

        # Let the guest see "typing…" while the draft is being generated --
        # grounding + LLM completion can take several seconds, and a silent
        # gap after their message reads as ignored. Best-effort only: never
        # let a Meta API hiccup here cost the guest their actual reply.
        channel_val = str(conversation.channel.value if hasattr(conversation.channel, "value") else conversation.channel)
        if channel_val == "whatsapp":
            try:
                _send_whatsapp_typing_indicator(db, tenant_id, message_id)
            except Exception as exc:
                log.warning("concierge_typing_indicator_failed", conversation_id=conversation_id, error=str(exc))

        # ── Ticket 4: bounded grounding, budget-limited to 8s total ────────
        # Uses the guest's whole unanswered burst (see DEBOUNCE_SECONDS /
        # unanswered_guest_text in concierge_service.py), not just this
        # task's single triggering message -- a burst like "Hi" + "I want
        # to book this weekend" should ground/escalate on both lines.
        burst_text = unanswered_guest_text(db, tenant_id, conversation_id)
        grounded_facts: list = []
        suggested_actions: list = []
        # Initialised up front: _intent is otherwise only bound inside the
        # try below, so a grounding timeout/failure -- or a message with no
        # body -- left it undefined for every later reader.
        _intent: str = "general"
        if burst_text:
            start = time.monotonic()
            try:
                _intent, grounded_facts, suggested_actions = _run_async(
                    asyncio.wait_for(
                        _ground_reply(db, tenant_id, burst_text, inquiry),
                        timeout=MAX_GROUNDING_SECONDS,
                    )
                )
            except asyncio.TimeoutError:
                log.warning("concierge_grounding_timed_out", conversation_id=conversation_id, elapsed_sec=round(time.monotonic() - start, 2))
                grounded_facts = []
            except Exception as exc:
                log.warning("concierge_grounding_failed", conversation_id=conversation_id, error=str(exc))
                grounded_facts = []

        # Capacity is cheap, static tenant data (Property.max_adults), not
        # date-gated like availability -- but _ground_reply() above only
        # ever grounds capacity via a check_availability fact, which itself
        # requires real dates AND an intent the classifier tagged as
        # availability_check/price_quote. Confirmed live: "Only 4 people?"
        # has no dates and isn't phrased as an availability check, so
        # grounding never ran at all, the model had zero real capacity
        # data, and it echoed the guest's own guessed number back
        # ("designed for up to 4 guests") -- the capacity guard below still
        # caught and blocked it (confidence forced to 0), but the guest was
        # never actually told the *right* number. Always attach the real
        # capacity here, independent of intent/dates, so a bare headcount
        # question always has something true to ground on.
        if not any(f.get("tool") == "check_availability" for f in grounded_facts):
            _capacity = _max_known_capacity(db, tenant_id, inquiry.property_id if inquiry else None)
            if _capacity is not None:
                grounded_facts.append({
                    "tool": "check_availability",
                    "args": {}, "result": [], "max_capacity_note": _capacity,
                })

        # HAIP Inbox UI-fidelity pass, ticket 3: widen the AI card trigger
        # beyond price_quote-only. One query, checked alongside the rest of
        # the context-building above.
        from app.models.guest_identity import GuestIdentity, IdentityType
        guest_missing_phone = db.query(GuestIdentity.id).filter_by(
            tenant_id=tenant_id, guest_id=guest_id, identity_type=IdentityType.PHONE.value,
        ).first() is None

        template = _jinja_env.get_template("concierge_reply.jinja")

        # Render with context
        class TenantProxy:
            def __init__(self, t):
                self.brand_name = t.brand_name or t.name
                self.brand_config = t.brand_config or {}
                self.name = t.name

        # Pricing is never disclosed in chat (price_policy). The concierge
        # qualifies the lead; a human agent negotiates. Facts are redacted
        # before rendering so the model is never shown a figure it could
        # repeat -- instructions alone leave the number one slip away from
        # the guest's screen.
        from app.services import price_policy
        missing_details = price_policy.missing_lead_details(guest, inquiry)
        qualified = price_policy.is_qualified(guest, inquiry)

        system_prompt = template.render(
            tenant=TenantProxy(tenant),
            guest=guest,
            inquiry=inquiry,
            recent_messages=ctx["recent_messages"],
            call_summaries=ctx["call_summaries"],
            kb_snippets=ctx["kb_snippets"],
            grounded_facts=price_policy.redact_price_facts(grounded_facts),
            tone=tone if tone in _VALID_TONES else None,
            guest_missing_phone=guest_missing_phone,
            missing_details=missing_details,
            qualified=qualified,
        )

        # No explicit model= here: NVIDIA-only routing (2026-08-05) means the
        # routed default_model set by get_llm("concierge_draft") is what
        # should fire -- an explicit override here previously hardcoded the
        # Claude model string, which would silently break once this task
        # moved to the NVIDIA adapter.
        adapter = get_llm("concierge_draft")
        result = None
        for attempt in range(1, MAX_REPLY_ATTEMPTS + 1):
            completion_start = time.monotonic()
            try:
                result = _run_async(
                    asyncio.wait_for(
                        adapter.complete(
                            system_prompt=system_prompt,
                            user_message="Draft a reply for this guest.",
                            tools=[CONCIERGE_TOOL],
                            max_tokens=REPLY_MAX_TOKENS,
                        ),
                        timeout=MAX_REPLY_SECONDS,
                    )
                )
                break
            except asyncio.TimeoutError:
                log.warning(
                    "concierge_completion_timed_out", conversation_id=conversation_id,
                    message_id=message_id, attempt=attempt,
                    elapsed_sec=round(time.monotonic() - completion_start, 2),
                )
        if result is None:
            result = {"tool_use": {
                "reply": "Thanks for your message! Let me check and get right back to you.",
                "confidence": 0.0, "citations": [], "needs_human": True,
                "reason_needs_human": f"AI reply generation timed out after {MAX_REPLY_ATTEMPTS} attempts",
            }}
        draft = result.get("tool_use") or {}
        confidence = draft.get("confidence", 0.0)
        reply_text = draft.get("reply", "")
        needs_human = draft.get("needs_human", True)
        # Persisted so "why didn't this auto-send despite high confidence"
        # is answerable from the database afterward, not just from a log
        # line the next container restart erases (migration 088).
        needs_human_reasons: list[str] = []
        # hard_block vs needs_human: needs_human alone conflated two very
        # different things -- the model's own soft "a human should ideally
        # own this" judgment (set above, e.g. a complex custom quote or a
        # frustrated-but-not-escalation-worthy guest) vs the draft being
        # actually wrong or risky (hallucinated claim, leaked price, a
        # refund/legal/safety escalation keyword, rate limiting). Every
        # guest message deserves a reply, but only hard_block should ever
        # block one -- confirmed as the explicit product decision. A
        # soft-only needs_human still auto-sends (subject to the normal
        # mode/confidence gate below); leads_service.py separately flags
        # the lead for a human to follow up on, using the same
        # ai_needs_human_reason this block already persists.
        hard_block = False
        if needs_human and draft.get("reason_needs_human"):
            needs_human_reasons.append(str(draft["reason_needs_human"]))

        # ── Ticket 4: deterministic hallucination guard ────────────────────
        is_grounded, violation = _check_grounding(reply_text, grounded_facts)
        if not is_grounded:
            log.warning(
                "draft_ungrounded_claim", conversation_id=conversation_id,
                message_id=message_id, reason=violation,
            )
            needs_human = True
            hard_block = True
            confidence = 0.0
            needs_human_reasons.append(f"ungrounded claim: {violation}")

        # ── Escalation guard ───────────────────────────────────────────────
        # Refunds, legal threats, cancellations, safety incidents and
        # "get me a manager" are never answered autonomously. Checked
        # against the guest's own words (not the draft) so the decision does
        # not depend on the model having judged the tone correctly.
        from app.services import escalation_policy
        escalation = escalation_policy.should_escalate(
            burst_text,
            _intent,
            tenant,
        )
        if escalation:
            log.warning(
                "draft_escalated_to_human",
                conversation_id=conversation_id, message_id=message_id,
                category=escalation["category"], keyword=escalation["keyword"],
            )
            needs_human = True
            hard_block = True
            confidence = 0.0
            needs_human_reasons.append(f"escalation: {escalation['category']} (matched {escalation['keyword']!r})")

        # ── Price-disclosure guard (hard policy, not a preference) ─────────
        # The prompt forbids quoting prices; this makes it true even when the
        # model ignores that. A leaked rate sent unreviewed is precisely the
        # outcome the no-pricing-in-chat rule exists to prevent, so any price
        # mention drops the draft to human review rather than being sent.
        price_leak = price_policy.detect_price(reply_text)
        if price_leak:
            log.warning(
                "draft_price_leak_blocked",
                conversation_id=conversation_id, message_id=message_id,
                matched=price_leak,
            )
            needs_human = True
            hard_block = True
            confidence = 0.0
            needs_human_reasons.append(f"price leak: {price_leak!r}")

        # Determine mode. Resolved per-channel from the tenant's current
        # policy (ai_mode_service), NOT from the snapshot copied into
        # conversations.ai_mode at creation time -- otherwise switching the
        # tenant to Autonomous leaves every existing thread in shadow with no
        # visible reason. A per-conversation "off" still wins.
        from app.services import ai_mode_service
        ai_mode, confidence_threshold = ai_mode_service.resolve(tenant, conversation)
        if confidence_threshold is None:
            confidence_threshold = CONFIDENCE_THRESHOLD
        should_auto_send = (ai_mode == "autonomous" and confidence >= confidence_threshold and not hard_block)

        # Rate limit -- the last gate before a message leaves unsupervised.
        # Blocking only withholds the automatic send: the draft is still
        # written and still visible to agents, so a rate-limited guest gets
        # a slower human reply rather than no reply.
        rate_limited_reason = None
        if should_auto_send:
            from app.services import ai_rate_limit_service
            allowed, rate_limited_reason = ai_rate_limit_service.check_send_allowed(
                db, tenant, conversation,
            )
            if not allowed:
                should_auto_send = False
                needs_human = True
                hard_block = True
                needs_human_reasons.append(f"rate limited: {rate_limited_reason}")
                log.warning(
                    "ai_send_rate_limited",
                    conversation_id=conversation_id, tenant_id=tenant_id,
                    reason=rate_limited_reason,
                )

        draft_message_id = str(uuid.uuid4())

        # HAIP Inbox UI-fidelity pass, ticket 3: offer the drafted reply
        # itself as a one-click card when it's carrying a phone-number ask --
        # reuses send_whatsapp_draft (same action next_action_service.py
        # already recommends for calls), not a new action type. Additive to
        # any send_quote suggestion _ground_reply() already produced.
        if guest_missing_phone and not needs_human and not should_auto_send:
            suggested_actions = suggested_actions + [{
                "action_type": "send_whatsapp_draft",
                "label": "Send (asks for phone number)",
                "action_config": {
                    "message_id": draft_message_id,
                    "conversation_id": conversation_id,
                },
                "confirm": True,
            }]

        # Store the drafted message
        draft_message = Message(
            id=draft_message_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            channel=conversation.channel,
            body=reply_text,
            is_ai_generated=True,
            ai_confidence=confidence,
            was_approved=True if should_auto_send else None,
            # was_approved alone cannot answer "what did the AI send with no
            # human involved?" -- the inbox approve handler and the one-click
            # action set it too. This is what the rate limiter counts.
            sent_autonomously=bool(should_auto_send),
            # Persisted so approve/reject can attribute their outcome rows to
            # the same intent (migration 082).
            ai_intent=_intent,
            sender_name="AI Concierge",
            grounded_facts=grounded_facts,
            suggested_actions=suggested_actions,
            ai_needs_human_reason="; ".join(needs_human_reasons) if needs_human_reasons else None,
        )
        db.add(draft_message)
        db.commit()

        log.info("concierge_draft_stored", message_id=draft_message.id, confidence=confidence,
                 auto_send=should_auto_send, grounded=bool(grounded_facts), **stamp("concierge_reply"))

        # ── Audit row for autonomous sends ─────────────────────────────────
        # Human-reviewed drafts get an ai_draft_outcomes row on approve or
        # reject; autonomous sends previously got nothing at all, so exactly
        # the messages with no human oversight were the ones missing from the
        # trust scorecard. `intent` is passed here too -- the column has
        # existed since migration 058 and no caller has ever populated it,
        # which made the per-intent accuracy the graduation gate is meant to
        # be judged on impossible to compute.
        if should_auto_send:
            try:
                from app.services.ai_draft_outcomes_service import record_outcome
                record_outcome(
                    db,
                    tenant_id=tenant_id,
                    draft=draft_message,
                    outcome="sent_autonomous",
                    actor_user_id=None,   # nobody reviewed it, by definition
                    intent=_intent,
                )
                db.commit()
            except Exception as exc:
                # Losing the audit row must not cost the guest their reply.
                log.warning(
                    "autonomous_outcome_record_failed",
                    message_id=draft_message.id, error=str(exc),
                )

        # ── Rate-limit alert ───────────────────────────────────────────────
        # A silent rate limit hides the loop it just caught. Someone needs to
        # look at why the AI wanted to send that many messages.
        if rate_limited_reason:
            try:
                from app.services.push_service import send_to_tenant
                _label = (getattr(guest, "name", None) or "A guest").strip()
                send_to_tenant(
                    db, tenant_id,
                    title="AI send paused",
                    body=f"{_label}: {rate_limited_reason}. Reply waiting for review.",
                    url=f"/dashboard/inbox?conversation={conversation_id}",
                )
            except Exception as exc:
                log.warning("rate_limit_push_failed", conversation_id=conversation_id, error=str(exc))

        # ── Escalation alert ───────────────────────────────────────────────
        # These are time-sensitive by definition -- a refund demand sitting
        # unread in the inbox is the failure mode this guard exists to stop.
        if escalation:
            try:
                from app.services.push_service import send_to_tenant
                _label = (getattr(guest, "name", None) or "A guest").strip()
                send_to_tenant(
                    db, tenant_id,
                    title="Needs a human now",
                    body=f"{_label}: {escalation['category'].replace('_', ' ')}. AI reply held for review.",
                    url=f"/dashboard/inbox?conversation={conversation_id}",
                )
            except Exception as exc:
                log.warning("escalation_push_failed", conversation_id=conversation_id, error=str(exc))

        # ── Human handoff for pricing ──────────────────────────────────────
        # The concierge never negotiates. Once the lead has asked about cost
        # or we hold enough detail to talk properly, a person has to pick it
        # up -- otherwise "someone will reach out personally" is a promise
        # nothing in the system is tracking.
        try:
            _maybe_create_price_handoff(
                db, tenant_id=tenant_id, conversation=conversation, guest=guest,
                inquiry=inquiry, intent=_intent, qualified=qualified,
                price_leak=bool(price_leak),
            )
        except Exception as exc:
            # A missed task must never cost the guest their reply.
            log.warning("price_handoff_failed", conversation_id=conversation_id, error=str(exc))

        if should_auto_send:
            channel_val = str(conversation.channel.value if hasattr(conversation.channel, "value") else conversation.channel)
            if channel_val == "instagram":
                send_instagram_dm.delay(message_id=draft_message.id, tenant_id=tenant_id)
            else:
                send_whatsapp.delay(message_id=draft_message.id, tenant_id=tenant_id)
        else:
            # Push SSE notification to inbox
            _emit_sse(tenant_id=tenant_id, event="ai_draft_ready", conversation_id=conversation_id)
            # Push notification (browser closed / mobile PWA)
            try:
                from app.services.push_service import send_to_tenant
                send_to_tenant(
                    db=db,
                    tenant_id=tenant_id,
                    title="AI draft ready for review",
                    body="A reply has been drafted and is waiting for your approval.",
                    url=f"/dashboard/inbox?id={conversation_id}",
                    tag="haip-draft",
                    user_id=conversation.assigned_to or None,
                )
            except Exception as _push_exc:
                log.warning("push_notify_failed", error=str(_push_exc))

        # Leads360: trigger debounced AI summary refresh for linked inquiry
        if inquiry and inquiry.id:
            try:
                from app.services.leads_service import trigger_summary_refresh
                trigger_summary_refresh(
                    db=db,
                    inquiry_id=str(inquiry.id),
                    tenant_id=tenant_id,
                    source="message",    # 30-min Redis debounce applies
                )
            except Exception as summary_exc:
                log.warning("concierge_summary_refresh_skipped",
                            conversation_id=conversation_id, error=str(summary_exc))

    except Exception as exc:
        log.error("concierge_draft_failed", message_id=message_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


def _send_whatsapp_typing_indicator(db, tenant_id: str, message_id: str) -> None:
    """Resolve the tenant's WhatsApp credentials and show the typing bubble
    for `message_id` (the guest's own latest inbound message -- Meta's API
    requires the read-receipt/typing call to reference the message being
    responded to). Same credential-resolution shape as send_whatsapp.py.

    Confirmed live: this was passing HAIP's own internal Message.id (a UUID
    we generated) straight through as Meta's message_id -- Meta rejected
    every call with 400 Bad Request since that's not a real WhatsApp
    message id. The real WAMID lives on Message.channel_message_id (set on
    every inbound message, see whatsapp.py's webhook handler), not on the
    row's own primary key."""
    from app.models.integration import Integration
    from app.workers.tasks.whatsapp import _get_wa_access_token
    from app.adapters.whatsapp.meta_cloud import get_wa_adapter

    message = db.query(Message).filter_by(id=message_id, tenant_id=tenant_id).first()
    if not message or not message.channel_message_id:
        return

    integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp_meta").first()
    if not integration:
        integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp").first()
    if not integration:
        return

    phone_number_id = (integration.config or {}).get("phone_number_id")
    access_token = _get_wa_access_token(db, tenant_id)
    if not phone_number_id or not access_token:
        return

    adapter = get_wa_adapter(phone_number_id, access_token)
    _run_async(adapter.send_typing_indicator(message.channel_message_id))


def _emit_sse(tenant_id: str, event: str, conversation_id: str):
    try:
        import redis, json
        from app.core.config import settings
        r = redis.from_url(settings.REDIS_URL)
        r.publish(f"sse:{tenant_id}", json.dumps({"event": event, "conversation_id": conversation_id}))
    except Exception as e:
        log.warning("sse_publish_failed", error=str(e))
