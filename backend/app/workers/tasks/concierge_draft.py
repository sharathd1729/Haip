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
from datetime import date, datetime, timedelta, timezone
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from celery.exceptions import MaxRetriesExceededError
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
from app.services import agent_consult_flow, concierge_facts, sales_gateway, sales_playbook
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
    "description": (
        "Classify the guest's message and extract ONLY what the guest has actually stated (in the newest message or earlier in "
        "the conversation). Never infer or guess a value; leave it null."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["availability_check", "price_quote", "faq_answer", "booking_status", "complaint", "general"],
                "description": (
                    "availability_check: asking if specific dates are free. "
                    "price_quote: asking cost/pricing for a stay. "
                    "faq_answer: policy, amenity, or location question. "
                    "booking_status: asking about their OWN existing booking (is it confirmed, payment, arrival details). "
                    "complaint: expressing dissatisfaction. "
                    "general: greeting, unclear, or anything else."
                ),
            },
            "check_in": {"type": ["string", "null"], "description": "YYYY-MM-DD if a check-in date is stated or clearly inferable, else null"},
            "check_out": {"type": ["string", "null"], "description": "YYYY-MM-DD if a check-out date is stated or clearly inferable, else null"},
            "adults": {"type": ["integer", "null"]},
            "children": {"type": ["integer", "null"]},
            "destination": {"type": ["string", "null"], "description": "Place or route the guest wants to travel to/stay at, as stated"},
            "property_hint": {"type": ["string", "null"], "description": "A specific property/vehicle the guest named, as stated"},
            "occasion": {"type": ["string", "null"], "description": "Occasion or special request the guest stated (birthday, honeymoon ...)"},
            "budget": {"type": ["number", "null"], "description": "Budget in rupees ONLY if the guest stated one"},
            "questions": {
                "type": "array", "items": {"type": "string"},
                "description": "Each distinct thing the guest is asking in the newest message(s), as a short phrase",
            },
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "frustrated"]},
            "urgency": {"type": "string", "enum": ["low", "normal", "high"]},
            "wants_human": {"type": "boolean", "description": "True if the guest asks to speak to a person"},
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
#
# That reasoning is NVIDIA-specific (a documented infinite-hang bug, not
# ordinary slowness) and doesn't transfer to concierge_draft's current
# provider, Gemini -- confirmed live 2026-08-30 healthy at 3.8s on the real
# CONCIERGE_TOOL shape, and the account is on paid billing (no free-tier
# 15rpm queuing risk either). A real guest (Instagram DM) still hit "timed
# out after 2 attempts" the same day, most likely an ordinary transient
# latency spike getting killed by a timeout tuned for a different
# provider's known failure mode rather than Gemini's actual behavior. Giving
# Gemini more headroom before falling back to the generic reply costs
# nothing (Gemini has no known hang bug to guard against) and gives a real
# transient spike room to clear.
MAX_REPLY_SECONDS_BY_PROVIDER = {
    # EMERGENCY, TEMPORARY (2026-09-27): concierge_draft was rerouted to
    # NVIDIA openai/gpt-oss-20b (adapters/llm/__init__.py) while Gemini
    # billing was blocked. The 20s bound above was tuned against a
    # *different* model, nvidia/llama-3.3-nemotron-super-49b-v1.5, whose
    # failure mode was a true infinite hang (confirmed live: still no
    # response at a 90s uncapped ceiling). What's actually being hit on
    # gpt-oss-20b is different -- real production logs show every attempt
    # landing at almost exactly 20.02-20.03s wall clock, across many
    # different conversations, back to back (13:47, 13:59, 14:00...): a
    # bounded, consistent latency on this heavier prompt (full
    # conversation context + grounding + a 5-field tool schema, unlike the
    # short quick_classify-style prompts gpt-oss-20b was verified fast on),
    # not the same open-ended hang. Giving it real headroom, the same way
    # Gemini's bound was raised after its own tight-timeout-tuned-for-a-
    # different-provider false positive (comment above). MAX_REPLY_ATTEMPTS
    # below still caps the worst case at 2x this. If gpt-oss-20b instead
    # starts landing consistently AT this new ceiling too, that is the same
    # hang signature and this task should move to a different NVIDIA model
    # or back to Gemini (once billing clears), not get a further bump.
    "nvidia": 45,
    "gemini": 40,   # no known hang bug; paid tier; give real latency room
}
MAX_REPLY_SECONDS_DEFAULT = 20
MAX_REPLY_ATTEMPTS = 2  # worst case ~2x the per-provider bound before falling back

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
#
# Raised 400 -> 2048 after the Gemini migration: confirmed live via worker
# logs (repeated finish_reason=MAX_TOKENS with only 50-70 *visible* output
# tokens, and separately finish_reason=MALFORMED_FUNCTION_CALL) that
# gemini-3.6-flash's hidden "thinking" tokens count against this same
# budget -- gemini.py's own comment already names this failure mode for
# "thinking model[s]" on complex FC schemas. At 400, the model was running
# out of budget mid-thought before ever emitting the actual tool call,
# every retry in the fallback chain (gemini-flash-latest, then a text-JSON
# parse) inherited too little headroom to succeed either, and every guest
# got the generic empty-completion holding reply instead of a real answer
# -- happening repeatedly across many different conversations, not a rare
# edge case. 2048 matches the identical fix already proven necessary for
# the same root cause in generate_ai_summary.py. This doesn't loosen the
# "under 45 words" guest-facing reply itself (still enforced by the
# prompt) -- it only stops truncating the model's own reasoning before it
# gets to write that reply.
REPLY_MAX_TOKENS = 2048

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

# Confirmed live: a guest asked for photos, the draft said "Here are some
# photos of our luxury caravan," and no image was ever attached -- this
# pipeline only ever sends plain text (see the Message() built for the
# draft below, which never sets media_url/media_type). Catches "here are/
# here's [the] photos", "sharing/sent/attaching the pictures", "please find
# attached", "take a look at/check out the photos" etc. -- any claim that
# an image, video or brochure was included.
_MEDIA_CLAIM_RE = re.compile(
    r"\b(?:here(?:'s| is| are)|sharing|shared|attach(?:ing|ed)?|send(?:ing)?|sent|re-?sent|"
    r"re-?send(?:ing)?|e-?mail(?:ed|ing)?|mail(?:ed|ing)?|"
    r"forward(?:ing|ed)?|please find|find attached|take a look at|check out|see (?:the|some))\b"
    r"[^.!?\n]{0,40}\b(?:photos?|pics?|pictures?|images?|videos?|brochures?)\b",
    re.IGNORECASE,
)

# Second real case, same conversation, escalated: pressed on "still no
# photos," the model didn't just repeat the claim -- it invented an
# entirely new fictitious channel ("I've also resent the photos to your
# email"), to a guest who has no email on file at all. The verb list above
# already catches "resent ... photos" via re-?sent, but this catches the
# same lie in any phrasing built around a delivery channel this pipeline
# doesn't have (email, inbox, WhatsApp) rather than a specific verb.
_MEDIA_VIA_CHANNEL_RE = re.compile(
    r"\b(?:to|via|through|check|in)\s+your\s+(?:e-?mail|inbox)\b",
    re.IGNORECASE,
)


def _check_no_media_claim(reply_text: str) -> tuple[bool, "str | None"]:
    """The concierge can never actually attach a photo/video/brochure, or
    send one anywhere else (email, WhatsApp, an inbox) -- unlike the price/
    capacity checks above, there is no grounded fact that could make any
    version of "I've sent you the photos" true, so any match blocks the
    draft outright."""
    m = _MEDIA_CLAIM_RE.search(reply_text)
    if m:
        return False, f"claims to share media it never attaches: {m.group(0)!r}"
    if _MEDIA_VIA_CHANNEL_RE.search(reply_text) and re.search(
        r"\b(?:photos?|pics?|pictures?|images?|videos?|brochures?)\b", reply_text, re.IGNORECASE
    ):
        return False, "claims to have sent media through a channel this pipeline can't use"
    return True, None


def _history_block(history, limit: int = 8) -> str:
    """The last few real messages (never unsent AI drafts: build_concierge_context already excludes those), oldest first."""
    from app.services.message_author import author_of
    lines = []
    for m in (history or [])[-limit:]:
        who = m.get("who") or author_of(m.get("direction"))
        body = (m.get("body") or "").strip()
        if body:
            lines.append(f"[{who}] {body[:400]}")
    return "\n".join(lines)


async def _classify_and_extract(latest_message: str, history=None, known: dict | None = None) -> dict:
    """One cheap call that reads the guest's newest message IN the context of the conversation.

    It used to see only the newest burst, so "and for 3 nights?" lost the dates and party size the guest gave a message earlier,
    and the draft asked for them again. `history` is the recent conversation; `known` is what the enquiry already records.
    """
    adapter = get_llm("quick_classify")
    today = date.today().isoformat()
    context = ""
    block = _history_block(history)
    if block:
        context += "CONVERSATION SO FAR (oldest first; the guest's newest unanswered lines are last):\n" + block + "\n\n"
    if known:
        context += "ALREADY RECORDED ABOUT THIS ENQUIRY: " + json.dumps(known, default=str) + "\n\n"
    result = await adapter.complete(
        system_prompt=(
            f"Today's date is {today}. Classify the newest WhatsApp/Instagram message from a hospitality guest and extract "
            "the stay details the guest has STATED. A date or headcount given earlier in the conversation still counts; if the "
            "guest later changed it, use the latest value. Only [GUEST] lines are the guest's own words: never take a date, "
            "headcount, place or request from a line WE sent ([US: ...]), above all a [US: CAMPAIGN BROADCAST], which went to "
            "many guests at once. Never guess: leave anything not stated as null. Resolve relative "
            "dates (e.g. 'next weekend', 'the 14th') against today's date; if no year is given, assume the next future "
            "occurrence of that date. List every distinct thing the guest is asking in `questions`."
        ),
        user_message=context + "NEWEST UNANSWERED GUEST MESSAGE(S):\n" + latest_message,
        tools=[INTENT_TOOL],
    )
    return result.get("tool_use") or {"intent": "general"}


async def _ground_reply(
    db, tenant_id: str, latest_message: str, inquiry,
    history=None, known: dict | None = None, details_out: dict | None = None, property_id: str | None = None,
) -> tuple[str, list, list]:
    """Returns (intent, grounded_facts, suggested_actions). grounded_facts is
    [] whenever grounding wasn't attempted or found nothing -- never
    fabricated. suggested_actions is the RecommendedAction[] shape
    (HAIP Inbox prototype-wiring plan, ticket 4), populated only when a real
    quote was fetched -- never a guess at what the guest wants.

    `details_out`, when given, receives what the guest stated (dates, party, destination, questions ... validated by
    concierge_facts.clean_details) so the caller can remember it and stop asking for it again."""
    classification = await _classify_and_extract(latest_message, history=history, known=known)
    intent = classification.get("intent", "general")
    details = concierge_facts.clean_details(classification)
    # A party size only WE wrote (a campaign's "8 guests each") is not the guest's, whatever the classifier returned.
    from app.services.message_author import GUEST, author_of, keep_guest_headcount
    _guest_lines = [latest_message] + [m.get("body") or "" for m in (history or [])
                                       if (m.get("who") or author_of(m.get("direction"))) == GUEST]
    _our_lines = [m.get("body") or "" for m in (history or []) if (m.get("who") or author_of(m.get("direction"))) != GUEST]
    details, _dropped = keep_guest_headcount(details, _guest_lines, _our_lines, keys=("adults", "children"))
    if _dropped:
        log.info("concierge_headcount_not_from_guest", dropped=_dropped)
    if details_out is not None:
        details_out.update(details)
        details_out["intent"] = intent
    if intent not in GROUNDED_INTENTS:
        return intent, [], []

    # Stated dates win; otherwise what the enquiry already records. Both go through the same checks (real, in order, not past).
    check_in, check_out = details.get("check_in"), details.get("check_out")
    if not (check_in and check_out):
        check_in, check_out, _ = concierge_facts.valid_stay_dates(
            str(inquiry.check_in) if inquiry and inquiry.check_in else None,
            str(inquiry.check_out) if inquiry and inquiry.check_out else None,
        )
    adults = details.get("adults") or (inquiry.adults if inquiry else None) or 1
    children = details.get("children") or (inquiry.children if inquiry else 0) or 0

    if not check_in or not check_out:
        # Can't ground without dates -- the prompt already instructs the
        # model to ask a clarifying question when context is insufficient.
        return intent, [], []

    from app.services.calculator_service import calculator_service

    grounded_facts: list = []
    suggested_actions: list = []
    property_id = property_id or (inquiry.property_id if inquiry else None)

    # check_availability -- same underlying service the MCP tool of the same
    # name wraps (app/mcp/tools.py), called directly here rather than
    # through the MCP dispatch path: that path is scoped to external
    # assistants with a real authenticated user identity and its own audit
    # trail (action="mcp.tool.*"); this internal loop has neither, and
    # routing it through MCP's audit log would misrepresent an internal
    # HAIP task as an external client's tool call.
    args = {"checkin": check_in, "checkout": check_out, "adults": adults, "children": children, "property_id": property_id}
    try:
        results = calculator_service.search(
            db, tenant_id=tenant_id, checkin=check_in, checkout=check_out,
            adults=adults, children=children, property_id=property_id,
        )
    except Exception as exc:
        log.warning("concierge_grounding_availability_failed", tenant_id=tenant_id, error=str(exc))
        # Say so. Returning no fact at all made the prompt tell the model "no availability was fetched, ask for the dates" --
        # wrong when the dates are known and the lookup is what failed -- and left nothing for the guard to check a claim against.
        return intent, [{"tool": "check_availability", "args": args, "result": [], "lookup_failed": True}], []

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
    priced = [
        {
            "property_id": r.property_id, "property_name": r.property_name,
            "available": r.available, "price_per_night": str(r.price_per_night),
            "nights": r.nights, "currency": r.currency, "max_adults": r.max_adults,
        }
        for r in results
    ]
    # search() drops every property that cannot be booked; the report says why each one was dropped (booked or blocked, party too
    # large, no rate for these dates) so "nothing matched" is never a guess. Best effort: the priced results above stand alone.
    try:
        report = calculator_service.availability_report(
            db, tenant_id=tenant_id, checkin=check_in, checkout=check_out,
            adults=adults, children=children, property_id=property_id,
        )
        fact_results = concierge_facts.availability_with_reasons(report, priced)
    except Exception as exc:
        log.warning("concierge_availability_report_failed", tenant_id=tenant_id, error=str(exc))
        fact_results = priced
    availability_fact: dict = {"tool": "check_availability", "args": args, "result": fact_results}
    if not results:
        # Adults only -- max_adults caps adults, and children have their own
        # max_children. Counting a toddler against the adult limit is what
        # made an 8-adult party "too big" for an 8-adult caravan.
        capacity = _max_known_capacity(db, tenant_id, property_id)
        if capacity is not None and adults > capacity:
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
                        "property_name": target.property_name, "nights": target.nights,
                        "adults": adults, "children": children,
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


def _known_home_bases(db, tenant_id: str) -> list:
    """Cities the tenant's active vehicles actually depart from
    (Property.home_base). Distinct, so a two-caravan fleet based in one city
    renders as one place rather than a repeated list."""
    from app.models.property import Property
    rows = (
        db.query(Property.home_base)
        .filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
        .all()
    )
    seen, out = set(), []
    for (base,) in rows:
        base = (base or "").strip()
        if base and base.lower() not in seen:
            seen.add(base.lower())
            out.append(base)
    return out


_NEGATED_AVAILABILITY_RE = re.compile(
    r"\b(not available|unavailable|isn'?t available|aren'?t available|no availability|booked|blocked|taken|not free|not open)\b",
    re.IGNORECASE,
)


def _positive_availability_claim(reply_text: str) -> "str | None":
    """A sentence that says dates are open ("is available for those dates") without saying they are not."""
    for sentence in re.split(r"(?<=[.!?])\s+", reply_text):
        if (
            _AVAILABILITY_WORDS_RE.search(sentence)
            and _STAY_CONTEXT_RE.search(sentence)
            and not _NEGATED_AVAILABILITY_RE.search(sentence)
        ):
            return sentence.strip()
    return None


def _known_capacity_values(grounded_facts: list) -> set[str]:
    """Capacities the reply may cite: the availability lookup's, and each property record's own figures."""
    known: set[str] = set()
    for fact in grounded_facts:
        if fact.get("tool") == "check_availability":
            for p in fact.get("result", []):
                if p.get("max_adults"):
                    known.add(str(p["max_adults"]))
            if fact.get("max_capacity_note"):
                known.add(str(fact["max_capacity_note"]))
        elif fact.get("tool") == "property_facts":
            for p in fact.get("result", []):
                for key in ("max_adults", "max_children"):
                    if p.get(key):
                        known.add(str(p[key]))
        elif fact.get("tool") == "business_data":
            for p in (fact.get("result") or {}).get("packages", []):
                if p.get("max_guests"):
                    known.add(str(p["max_guests"]))
    return known


def _check_grounding(reply_text: str, grounded_facts: list) -> tuple[bool, "str | None"]:
    """Deterministic post-check (plan §1.3): every price figure the draft
    cites must be a money value in grounded_facts (exact match), and an
    availability claim must be backed by what the availability lookup said.
    Not full NLP understanding -- a conservative, literal check on the
    highest-risk claim types (a wrong price or a false "yes, it's free" is the
    worst-case outcome).

    Capacity check added after a confirmed live hallucination: a guest
    asking about a 20-person group was told "designed for up to 4 guests"
    -- the real max_adults is 8. Same shape as the money check: any
    "up to/max/fits/sleeps N guests"-style claim must match a real number
    from grounded_facts (per-property max_adults, or the empty-results
    max_capacity_note), not just sound plausible.

    Availability: if the lookup failed, or it found no property open for the dates and party, a reply that says the dates ARE
    available is a false promise -- a calendar block or a booking exists -- and is blocked."""
    from app.services import price_policy

    money_mentions = price_policy.money_figures(reply_text)
    availability_mentions = [
        m
        for sentence in re.split(r"(?<=[.!?])\s+", reply_text)
        if _AVAILABILITY_WORDS_RE.search(sentence) and _STAY_CONTEXT_RE.search(sentence)
        for m in _AVAILABILITY_WORDS_RE.findall(sentence)
    ]
    capacity_mentions = _CAPACITY_RE.findall(reply_text)

    known_capacities = _known_capacity_values(grounded_facts)

    if capacity_mentions:
        bad_capacity = [n for n in capacity_mentions if n not in known_capacities]
        if bad_capacity:
            return False, f"cites capacity {bad_capacity!r}, not present in grounded_facts (known: {known_capacities or 'none'})"

    # What the availability lookup actually said, when it was run for specific dates.
    checked = [f for f in grounded_facts if f.get("tool") == "check_availability" and (f.get("args") or {}).get("checkin")]
    if checked:
        positive = _positive_availability_claim(reply_text)
        if positive:
            if any(f.get("lookup_failed") for f in checked):
                return False, f"says dates are available but the availability lookup failed: {positive!r}"
            if not any(r.get("available") for f in checked for r in f.get("result", [])):
                return False, f"says dates are available but the lookup found no open property: {positive!r}"

    if not grounded_facts:
        if money_mentions or availability_mentions:
            return False, f"cites price/availability with zero grounded_facts: {money_mentions or availability_mentions}"
        return True, None

    unsupported = price_policy.unsupported_figures(reply_text, grounded_facts)
    if unsupported:
        return False, f"cites {unsupported!r}, not present in grounded_facts"
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
    # A call needs a number. A guest we hold no usable phone for (an Instagram DM) is not a lead yet: the reply itself asks
    # for the number (concierge_reply.jinja, guest_missing_phone), and the chat stays in the Inbox. Once they share it,
    # lead_identified_at is set and their next price question raises this task.
    if getattr(guest, "lead_identified_at", None) is None:
        log.info("price_handoff_skipped_no_phone", tenant_id=tenant_id, conversation_id=conversation.id)
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
        # Real bug, confirmed live (Ratha, Sep 2026, "autopilot" pass): both
        # worklist_service.overdue_followups() and work_queue_service's
        # "Due now" bucket hard-require a non-null due_date -- with none
        # set, this Task (already shipped) never once appeared on My Day.
        # Actionable the moment it's created, so due now.
        due_date=datetime.now(timezone.utc),
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


def _maybe_alert_phone_decline(
    db, *, tenant_id: str, conversation, guest, inquiry, phone_decline_phrase: str,
) -> None:
    """Queue a human follow-up when a guest explicitly declines to share a
    phone number and asks to be helped in the DM itself.

    Does NOT touch confidence/hard_block/should_auto_send -- the AI's own
    reply still goes out same as always (confirmed live, it answers these
    fine). This is an additional signal for a human to personally pick up
    the thread on Instagram, same shape as _maybe_create_price_handoff
    above (which this is often paired with -- a guest declining a number is
    very often also asking about price). Deduplicated per conversation on
    the open task, same reasoning: a guest who repeats the refusal produces
    one task, not one per message.
    """
    from app.models.task import Task

    existing = (
        db.query(Task)
        .filter_by(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            is_done=False,
        )
        .filter(Task.title.ilike("Guest declined phone number%"))
        .first()
    )
    if existing:
        return

    guest_label = (getattr(guest, "name", None) or "").strip() or "this lead"
    task = Task(
        tenant_id=tenant_id,
        title=f"Guest declined phone number — {guest_label}",
        priority="high",
        guest_id=getattr(guest, "id", None),
        inquiry_id=getattr(inquiry, "id", None),
        conversation_id=conversation.id,
        # Same due_date fix as the price-handoff Task above -- gives the
        # guest a little room before it's "overdue".
        due_date=datetime.now(timezone.utc) + timedelta(hours=4),
    )
    db.add(task)
    db.commit()
    log.info(
        "phone_decline_task_created",
        tenant_id=tenant_id, conversation_id=conversation.id,
        task_id=task.id, matched=phone_decline_phrase,
    )

    try:
        from app.services.push_service import send_to_tenant
        send_to_tenant(
            db, tenant_id,
            title="Needs you now",
            body=f"{guest_label} declined to share a phone number and is waiting for a reply on Instagram.",
            url=f"/dashboard/inbox?conversation={conversation.id}",
        )
    except Exception as exc:
        log.warning("phone_decline_push_failed", tenant_id=tenant_id, error=str(exc))

    # Live-updates the Inbox list badge and thread callout without a full
    # refetch -- same SSE channel _emit_sse() already publishes on below,
    # just its own event name so DashboardSSEBridge.tsx can flip the flag
    # instead of re-running the "AI draft ready" flow.
    _emit_sse(tenant_id=tenant_id, event="phone_decline_alert", conversation_id=conversation.id)


# ── Task ─────────────────────────────────────────────────────────────────────

_VALID_TONES = {"warm", "formal", "brief", "persuasive"}


def _already_drafted_for_latest_inbound(db, conversation_id: str) -> bool:
    """True when an AI draft already exists that is newer than the guest's newest message.

    A Celery retry (or a duplicate delivery) of a run that had already stored its draft would otherwise draft AGAIN -- and in
    autonomous mode send a second reply to the same message. unanswered_guest_text() is empty by then (the stored draft counts as
    an outbound message), so the second run would not even know what the guest asked.
    """
    from app.models.conversation import MessageDirection
    newest_inbound = (
        db.query(Message.created_at)
        .filter(Message.conversation_id == conversation_id, Message.direction == MessageDirection.INBOUND)
        .order_by(Message.created_at.desc())
        .first()
    )
    if not newest_inbound:
        return False
    return db.query(Message.id).filter(
        Message.conversation_id == conversation_id,
        Message.direction == MessageDirection.OUTBOUND,
        Message.is_ai_generated.is_(True),
        Message.created_at >= newest_inbound[0],
    ).first() is not None


def _closing_acknowledgement(db, tenant_id: str, conversation_id: str) -> bool:
    """The guest's unanswered burst only acknowledges or closes ("Okay", "thanks", "👍", "okay waiting to hear from you") and the
    last message the guest got from us asked nothing. Live (Rathaa, Oct 2026): a bare "Okay" after our holding line opened an
    "Ask a manager" consult. After a question of ours ("Shall I check the long weekend?") the same "Okay" is an answer and is
    drafted as usual; with nothing from us yet, too."""
    from app.models.conversation import MessageDirection
    from app.services.agent_escalation_rules import is_acknowledgement
    if not is_acknowledgement(unanswered_guest_text(db, tenant_id, conversation_id)):
        return False
    last = (
        db.query(Message.body)
        .filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id,
                Message.direction == MessageDirection.OUTBOUND, Message.is_internal.isnot(True),
                # a held (unsent) AI draft is not something the guest saw
                ~((Message.is_ai_generated.is_(True)) & (Message.was_approved.isnot(True))))
        .order_by(Message.created_at.desc())
        .first()
    )
    return last is not None and "?" not in (last[0] or "")


def _known_enquiry(inquiry) -> dict:
    """What the CRM enquiry already records, for the classifier (never persisted back by this task)."""
    if not inquiry:
        return {}
    known = {
        "check_in": str(inquiry.check_in) if inquiry.check_in else None,
        "check_out": str(inquiry.check_out) if inquiry.check_out else None,
        "adults": inquiry.adults, "children": inquiry.children,
        "occasion": getattr(inquiry, "occasion", None),
    }
    return {k: v for k, v in known.items() if v}


def _known_lines(inquiry, details: dict) -> list[str]:
    """Plain-language list of what is already known about the trip: the enquiry's fields, then what the guest said in chat."""
    lines: list[str] = []
    ci = (str(inquiry.check_in) if inquiry and inquiry.check_in else None) or details.get("check_in")
    co = (str(inquiry.check_out) if inquiry and inquiry.check_out else None) or details.get("check_out")
    if details.get("check_in") and details.get("check_out"):
        ci, co = details["check_in"], details["check_out"]          # the guest's newest statement wins over an older record
    if ci and co:
        lines.append(f"Travel dates: {ci} → {co}")
    adults = details.get("adults") or (inquiry.adults if inquiry else None)
    children = details.get("children") if details.get("children") is not None else (inquiry.children if inquiry else None)
    if adults:
        lines.append(f"Party: {adults} adults" + (f" + {children} children" if children else ""))
    place = details.get("destination") or details.get("property_hint")
    if place:
        lines.append(f"Destination / property mentioned: {place}")
    occasion = details.get("occasion") or (getattr(inquiry, "occasion", None) if inquiry else None)
    if occasion:
        lines.append(f"Occasion / special request: {occasion}")
    if details.get("budget") or (inquiry and getattr(inquiry, "budget", None)):
        lines.append("Budget: shared (the team handles it; never repeat the figure)")
    return lines


def _extract_draft(result: dict) -> dict:
    """The model's reply object. Some providers answer in plain text/JSON instead of calling the tool."""
    tool_use = result.get("tool_use")
    if isinstance(tool_use, dict) and tool_use:
        return tool_use
    content = result.get("content")
    if isinstance(content, str) and content.strip():
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
            except ValueError:
                obj = None
            if isinstance(obj, dict) and "reply" in obj:
                return obj
    return {}


MAX_REPLY_CHARS = 1200


def _sanitize_draft(draft: dict) -> tuple[dict, list[str]]:
    """Coerce the model's output to the contract, and name every way it broke it.

    A model can return a non-string reply, a confidence of "high" or 7, a reply wrapped in JSON/code fences, or a runaway wall of
    text. None of those may reach a guest or crash the task; each one drops confidence to 0 (human review) and is recorded.
    """
    problems: list[str] = []
    reply = draft.get("reply")
    if not isinstance(reply, str):
        reply = ""
        if "reply" in draft:
            problems.append("reply was not text")
    reply = reply.strip()
    if reply.startswith("```"):
        reply = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", reply).strip()
    if reply.startswith("{") and '"reply"' in reply:
        try:
            inner = json.loads(reply)
            if isinstance(inner, dict) and isinstance(inner.get("reply"), str):
                reply = inner["reply"].strip()
                problems.append("reply was wrapped in JSON")
        except ValueError:
            problems.append("reply looked like unparsed JSON")
            reply = ""
    if len(reply) > MAX_REPLY_CHARS:
        problems.append(f"reply unusually long ({len(reply)} characters)")

    try:
        confidence = float(draft.get("confidence", 0.0))
        if confidence != confidence or confidence < 0.0 or confidence > 1.0:      # NaN or out of range
            problems.append(f"confidence {draft.get('confidence')!r} out of range")
            confidence = 0.0
    except (TypeError, ValueError):
        problems.append(f"confidence {draft.get('confidence')!r} not a number")
        confidence = 0.0

    needs_human = draft.get("needs_human", True)
    if not isinstance(needs_human, bool):
        problems.append("needs_human was not true/false")
        needs_human = True
    reason = draft.get("reason_needs_human")
    return {
        "reply": reply, "confidence": confidence, "needs_human": needs_human,
        "reason_needs_human": reason if isinstance(reason, str) else None,
    }, problems


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, name="tasks.concierge_draft")
def concierge_draft(self, message_id: str, conversation_id: str, tenant_id: str, tone: str | None = None, force: bool = False):
    from app.workers.tasks.send_whatsapp import send_whatsapp
    from app.workers.tasks.send_instagram_dm import send_instagram_dm

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        conversation = db.query(Conversation).filter_by(id=conversation_id, tenant_id=tenant_id).first()
        if not conversation:
            log.error("concierge_draft_conversation_not_found", conversation_id=conversation_id)
            return

        # A chat mirrored from the read-only personal WhatsApp bridge: the agent is talking on their own phone and HAIP cannot
        # send there, so any reply (autonomous or a draft to approve) would go out from the official number. Refused for every
        # caller (webhook, reply recovery, automations, "write a draft").
        if conversation.is_personal_bridge:
            log.warning("concierge_draft_refused_personal_bridge", conversation_id=conversation_id, tenant_id=tenant_id,
                        message_id=message_id)
            return

        # Message-burst debounce: a newer inbound message arrived and
        # queued its own (fresher-delayed) concierge_draft run after this
        # one was scheduled -- that run is the one that should actually
        # draft, covering this message too via unanswered_guest_text()
        # below. No-op here rather than writing a second, disjointed draft.
        if not is_latest_pending_draft(tenant_id, conversation_id, message_id):
            log.info("concierge_draft_superseded", conversation_id=conversation_id, message_id=message_id)
            return

        # `force` is the agent clicking "write a draft" -- a second draft is exactly what they asked for. Every automatic caller
        # (webhooks, automations, retries) is stopped when this message already has its draft.
        if not force and _already_drafted_for_latest_inbound(db, conversation_id):
            log.info("concierge_draft_already_drafted", conversation_id=conversation_id, message_id=message_id)
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
            # No draft means nothing below refreshes the lead's summary, so an enquiry whose AI is off kept an analysis that
            # ignored every new message. The refresh does not need a draft.
            if inquiry and inquiry.id:
                try:
                    from app.services.leads_service import trigger_summary_refresh
                    trigger_summary_refresh(db=db, inquiry_id=str(inquiry.id), tenant_id=tenant_id, source="message")
                except Exception as summary_exc:
                    log.warning("concierge_summary_refresh_skipped", conversation_id=conversation_id, error=str(summary_exc))
            return

        # "Okay" / "thanks" / "👍" after a message of ours that asked nothing: nothing to answer, so no "typing…", no model call,
        # no draft, no consult. A forced "write a draft" click still drafts.
        if not force and _closing_acknowledgement(db, tenant_id, conversation_id):
            log.info("concierge_draft_skipped_acknowledgement", conversation_id=conversation_id, message_id=message_id)
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
        # What the guest has stated, filled by _ground_reply (dates, party, destination, the questions they asked ...). It is
        # filled as soon as the message is understood, so it survives a later availability-lookup timeout.
        details: dict = {}
        scope_property_id = (inquiry.property_id if inquiry else None) or conversation.property_id
        if burst_text:
            start = time.monotonic()
            try:
                _intent, grounded_facts, suggested_actions = _run_async(
                    asyncio.wait_for(
                        _ground_reply(
                            db, tenant_id, burst_text, inquiry,
                            history=ctx["recent_messages"], known=_known_enquiry(inquiry),
                            details_out=details, property_id=scope_property_id,
                        ),
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

        # Where trips actually start. Property.home_base is real, per-vehicle
        # data ("Bengaluru" on both Ratha caravans); without it in the prompt
        # the model simply accepted whatever starting point a guest proposed
        # -- confirmed live, a guest naming another origin was told that was
        # fine. Rendered as a constraint, not a suggestion. Read from the
        # tenant's own properties so it stays correct for any fleet.
        _home_bases = _known_home_bases(db, tenant_id)
        if _home_bases:
            grounded_facts.append({"tool": "home_base", "result": _home_bases})

        # Operational data the reply may rely on, from the same tables the rest of HAIP reads. Each is best effort: a failed
        # lookup leaves the fact out (the prompt then says the team will confirm) and never costs the guest their reply.
        for _label, _builder in (
            ("property_facts", lambda: concierge_facts.property_facts(db, tenant_id, scope_property_id)),
            ("guest_bookings", lambda: concierge_facts.guest_booking_facts(db, tenant_id, guest_id)),
        ):
            try:
                _fact = _builder()
                if _fact:
                    grounded_facts.append(_fact)
            except Exception as exc:
                log.warning("concierge_fact_lookup_failed", fact=_label, conversation_id=conversation_id, error=str(exc))
        # Ratha's structured business data (packages, routes, itineraries, policies, and a package quote when the guest has named
        # one): published records only, read through the gateway, best effort like the facts above.
        try:
            grounded_facts.extend(sales_gateway.concierge_business_facts(db, tenant_id, details))
        except Exception as exc:
            log.warning("concierge_fact_lookup_failed", fact="business_data", conversation_id=conversation_id, error=str(exc))
        if details:
            grounded_facts.append({"tool": "conversation_details", "result": details})

        # The AI sales agent (brand_config.sales_agent.mode; "off" by default = nothing runs and the reply path is unchanged):
        # calendar availability, a grounded package quote on the lead, a pending or autopilot quote send. sales_agent_service.
        from app.services import sales_agent_service, sales_agent_settings
        try:
            sales_turn = sales_agent_service.prepare_turn(db, tenant, conversation, inquiry, guest, details, burst_text)
        except Exception as exc:
            db.rollback()
            log.warning("sales_agent_turn_failed", conversation_id=conversation_id, error=str(exc))
            sales_turn = sales_agent_service.SalesTurn(mode=sales_agent_settings.mode(tenant), status="error")
        grounded_facts = sales_agent_service.merge_facts(tenant, grounded_facts, sales_turn)

        # HAIP Inbox UI-fidelity pass, ticket 3: widen the AI card trigger
        # beyond price_quote-only. One query, checked alongside the rest of
        # the context-building above.
        # A WhatsApp-number signal is a phone too: a guest merged with a WhatsApp lead (or whose number came in as one) used to be
        # asked for "a phone number" again because only the "phone" signal type was checked.
        from app.services.chat_phone_capture import guest_has_phone
        guest_missing_phone = not guest_has_phone(db, tenant_id, guest_id)

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
        price_mode = price_policy.price_mode(tenant)
        # Learning loop (services/learning/resolver.py, THE hook): this conversation's arm of every running experiment. The
        # control arm reads the base settings; a treatment may only show a PUBLISHED package's price or hand a big quote to a
        # person (the guards below apply to both arms). Any failure here = the base settings.
        from app.services.learning import lessons as learning_lessons
        from app.services.learning import resolver as learning_resolver
        try:
            _learning = learning_resolver.for_conversation(db, tenant, conversation, guest_id=guest_id,
                                                           guest_was_lead=getattr(guest, "lead_identified_at", None) is not None)
            _pq = next((f for f in grounded_facts if f.get("tool") == "package_quote"), None) or {}
            _pq_result = _pq.get("result") if isinstance(_pq.get("result"), dict) else {}
            price_mode = learning_resolver.price_mode_for_turn(
                price_mode, _learning, (_pq.get("args") or {}).get("package_key"),
                float(_pq_result["total"]) if _pq_result.get("total") is not None else None)
            _proven = learning_lessons.prompt_lines(db, tenant)
        except Exception as exc:  # noqa: BLE001
            log.warning("learning_effective_failed", conversation_id=conversation_id, error=type(exc).__name__)
            _learning, _proven = None, []
        missing_details = price_policy.missing_lead_details(guest, inquiry, details)
        qualified = price_policy.is_qualified(guest, inquiry, details)

        # "handoff" (default): the model is never shown a figure. "grounded": it sees the live rate/quote and may repeat exactly
        # those figures (the guard further down blocks any other number).
        prompt_facts = grounded_facts if price_mode == "grounded" else price_policy.redact_price_facts(grounded_facts)
        _by_tool = {f.get("tool"): f for f in prompt_facts}
        questions = details.get("questions") or []
        system_prompt = template.render(
            tenant=TenantProxy(tenant),
            guest=guest,
            inquiry=inquiry,
            recent_messages=ctx["recent_messages"],
            call_summaries=ctx["call_summaries"],
            # A document's old rate must never compete with the live one: figures are removed from knowledge text.
            kb_snippets=[dict(sn, text=price_policy.strip_prices(sn.get("text", ""))) for sn in ctx["kb_snippets"]],
            kb_unavailable=ctx.get("kb_status") in ("embedding_unavailable", "search_failed"),
            grounded_facts=prompt_facts,
            property_info=(_by_tool.get("property_facts") or {}).get("result") or [],
            guest_bookings=(_by_tool.get("guest_bookings") or {}).get("result") or [],
            known_lines=_known_lines(inquiry, details),
            date_problem=details.get("date_problem"),
            questions=questions,
            max_words=80 if len(questions) >= 2 else 45,
            price_mode=price_mode,
            tone=tone if tone in _VALID_TONES else None,
            guest_missing_phone=guest_missing_phone,
            missing_details=missing_details,
            qualified=qualified,
            playbook=_learning.prompt_playbook(db, tenant_id) if _learning is not None else sales_playbook.prompt_view(tenant),
            proven_lessons=_proven,
        )

        # No explicit model= here: whatever get_llm("concierge_draft") routes
        # to (Gemini as of 2026-08-25, see _TASK_ROUTES) is what should
        # fire -- an explicit override here previously hardcoded the Claude
        # model string, which would silently break once this task moved off
        # whatever provider it was on at the time.
        adapter = get_llm("concierge_draft")
        reply_timeout = MAX_REPLY_SECONDS_BY_PROVIDER.get(
            getattr(adapter, "provider", None), MAX_REPLY_SECONDS_DEFAULT
        )
        result = None
        last_error: str | None = None   # set only for a real exception, never for a plain timeout
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
                        timeout=reply_timeout,
                    )
                )
                # Provider, model, latency and (when the provider reports it) token usage -- never the prompt or the reply text.
                log.info(
                    "concierge_completion_ok", conversation_id=conversation_id, attempt=attempt,
                    provider=getattr(adapter, "provider", None),
                    elapsed_sec=round(time.monotonic() - completion_start, 2),
                    prompt_chars=len(system_prompt),
                    **{k: result.get(k) for k in ("model", "input_tokens", "output_tokens", "tokens_used") if result.get(k) is not None},
                )
                break
            except asyncio.TimeoutError:
                log.warning(
                    "concierge_completion_timed_out", conversation_id=conversation_id,
                    message_id=message_id, attempt=attempt, provider=getattr(adapter, "provider", None),
                    timeout_sec=reply_timeout, elapsed_sec=round(time.monotonic() - completion_start, 2),
                )
            except Exception as exc:
                # Real incident (Ratha, Sep 2026): a provider error here (auth,
                # quota, an outage) is not an asyncio.TimeoutError, so it fell
                # through this loop uncaught, past the "result is None" holding
                # reply below, straight to the task's outer except -- which
                # retries the identical failing call up to 3 times and then
                # raises MaxRetriesExceededError with nothing caught around it.
                # The task simply crashed: no draft, no holding reply, no
                # notification, guest and agent both got silence. Every
                # completion failure must produce the same safe fallback the
                # timeout path already gets, never an unhandled crash.
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "concierge_completion_failed", conversation_id=conversation_id,
                    message_id=message_id, attempt=attempt, provider=getattr(adapter, "provider", None),
                    error=last_error, elapsed_sec=round(time.monotonic() - completion_start, 2),
                )
        if result is None:
            reason = f"AI reply generation failed after {MAX_REPLY_ATTEMPTS} attempts ({last_error})" if last_error \
                else f"AI reply generation timed out after {MAX_REPLY_ATTEMPTS} attempts"
            result = {"tool_use": {
                "reply": "Thanks for your message! Let me check and get right back to you.",
                "confidence": 0.0, "citations": [], "needs_human": True,
                "reason_needs_human": reason,
            }}
        draft, _malformed = _sanitize_draft(_extract_draft(result))
        confidence = draft["confidence"]
        reply_text = draft["reply"]
        needs_human = draft["needs_human"]
        # Persisted so "why didn't this auto-send despite high confidence"
        # is answerable from the database afterward, not just from a log
        # line the next container restart erases (migration 088).
        needs_human_reasons: list[str] = []
        if _malformed:
            log.warning("concierge_malformed_output", conversation_id=conversation_id, problems=_malformed,
                        provider=getattr(adapter, "provider", None))
            needs_human_reasons.append("malformed model output: " + "; ".join(_malformed))
            confidence = 0.0
            needs_human = True

        # Real bug, reported live: a completion that finishes without
        # timing out but comes back with no usable tool_use (the model
        # declined the tool call, or returned a malformed/empty one) fell
        # through with reply_text="" and confidence=0.0 -- unlike the
        # timeout path just above, there was no fallback text here, so a
        # blank, unreviewable "0%" draft got stored and shown to an agent
        # with literally nothing to approve/edit/reject. Same treatment as
        # a timeout: a real holding reply, forced to human review. Confirmed
        # live and reproducible: Gemini returning MALFORMED_FUNCTION_CALL,
        # the retry also failing, and the text-JSON fallback also failing
        # to parse -- not a one-off fluke for this guest's message.
        if not reply_text or not reply_text.strip():
            log.warning(
                "concierge_completion_empty_reply", conversation_id=conversation_id,
                message_id=message_id, provider=getattr(adapter, "provider", None),
                had_tool_use=bool(result.get("tool_use")),
            )
            reply_text = "Thanks for your message! Let me check and get right back to you."
            confidence = 0.0
            needs_human = True
            needs_human_reasons.append("AI reply generation returned no usable content")
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
        hard_block = bool(_malformed)
        if needs_human and draft.get("reason_needs_human"):
            needs_human_reasons.append(str(draft["reason_needs_human"]))

        # The guest's tone and any request for a person are recorded for the agent (soft flag: it never blocks a send by itself,
        # the escalation guard below does that for the cases that must not be answered by the AI).
        if details.get("wants_human"):
            needs_human = True
            needs_human_reasons.append("guest asked to speak to a person")
        if details.get("sentiment") == "frustrated":
            needs_human = True
            needs_human_reasons.append("guest sounds frustrated")

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

        # ── Media-claim guard ───────────────────────────────────────────────
        no_media_claim, media_violation = _check_no_media_claim(reply_text)
        if not no_media_claim:
            log.warning(
                "draft_media_claim_blocked", conversation_id=conversation_id,
                message_id=message_id, reason=media_violation,
            )
            needs_human = True
            hard_block = True
            confidence = 0.0
            needs_human_reasons.append(media_violation)

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
        if price_mode == "grounded":
            # Any figure must be one the live lookup returned for this conversation; anything else is a leak all the same.
            _unsupported = price_policy.unsupported_figures(reply_text, grounded_facts)
            price_leak = f"figure(s) not from the live rate: {_unsupported}" if _unsupported else None
        else:
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

        # ── Sales-agent guard (sales mode only): no booking promised before payment, no discount, no link or "sent" claim the
        # system did not make, and no "available" without a calendar check.
        _sales_violation = sales_agent_service.check_reply(reply_text, grounded_facts, sales_turn)
        if sales_turn.active and not _sales_violation and _positive_availability_claim(reply_text) and not any(
                f.get("tool") == "check_availability" and (f.get("args") or {}).get("checkin") for f in grounded_facts):
            _sales_violation = "says dates are available without a calendar check"
        if _sales_violation:
            log.warning("draft_sales_guard_blocked", conversation_id=conversation_id, message_id=message_id, reason=_sales_violation)
            needs_human = True
            hard_block = True
            confidence = 0.0
            needs_human_reasons.append(f"sales guard: {_sales_violation}")

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

        # Final staleness re-check, immediately before deciding what gets
        # persisted/sent. Grounding + LLM completion above can take several
        # seconds (bounded by MAX_GROUNDING_SECONDS + reply_timeout *
        # MAX_REPLY_ATTEMPTS) -- long enough for a newer guest message to
        # have arrived, been marked the new "latest pending draft", and
        # scheduled its own task that already covers this message via
        # unanswered_guest_text(). Confirmed live: two guest messages 6s
        # apart (just past DEBOUNCE_SECONDS=5, concierge_service.py) each
        # independently passed the entry-time staleness check above
        # ("concierge_draft_superseded") because neither had arrived yet
        # when the other's check ran -- both then auto-sent, producing a
        # duplicate guest-facing reply and burning an extra rate-limit slot
        # that went on to block a later, real, distinct question from
        # auto-sending. Re-verifying right before the one truly irreversible
        # step (the guest-facing send) closes that gap regardless of how
        # DEBOUNCE_SECONDS is tuned -- a fresher task already has this
        # message's text via unanswered_guest_text(), so this draft would
        # only ever duplicate it, never add anything.
        if should_auto_send and not is_latest_pending_draft(tenant_id, conversation_id, message_id):
            log.info("concierge_draft_send_superseded", conversation_id=conversation_id, message_id=message_id)
            should_auto_send = False
            needs_human_reasons.append("superseded by a newer guest message before send")

        # Ask a manager (services/agent_consult_flow.py): a deterministic trigger holds the guessed answer; the consult opens below.
        consult_turn = agent_consult_flow.check_turn(db, tenant, conversation, guest, inquiry, message_id=message_id, ai_mode=ai_mode, force=force, burst_text=burst_text, intent=_intent, details=details, grounded_facts=grounded_facts, reply_text=reply_text, model_confidence=draft["confidence"], threshold=confidence_threshold, escalation=escalation, price_mode=price_mode, price_leak=price_leak, ungrounded=(violation if not is_grounded else media_violation), model_failed=bool(_malformed) or any("AI reply generation" in r for r in needs_human_reasons), sales_turn=sales_turn, rate_limited=bool(rate_limited_reason))
        if consult_turn.hold:
            should_auto_send, needs_human = False, True; needs_human_reasons.append(consult_turn.note)

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
        agent_consult_flow.after_draft(db, consult_turn, draft_message, tenant, conversation, guest, inquiry)

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
        if escalation and not consult_turn.consult_id:    # a consult already told the team, naming the question
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
            # The sales agent's own work item (a prepared quote, or a handoff task) replaces the generic pricing callback.
            if not (sales_turn.action_id or sales_turn.handoff or sales_turn.status in sales_agent_service.OWN_WORK_STATUSES or consult_turn.owns_price):
                _maybe_create_price_handoff(
                    db, tenant_id=tenant_id, conversation=conversation, guest=guest,
                    inquiry=inquiry, intent=_intent, qualified=qualified,
                    price_leak=bool(price_leak),
                )
        except Exception as exc:
            # A missed task must never cost the guest their reply.
            log.warning("price_handoff_failed", conversation_id=conversation_id, error=str(exc))

        # ── Phone-decline alert ─────────────────────────────────────────────
        # Instagram-only: a WhatsApp conversation's identity IS a phone
        # number (that's the channel), so "declined to share a phone
        # number" only makes sense for Instagram DMs.
        channel_val_for_decline = str(conversation.channel.value if hasattr(conversation.channel, "value") else conversation.channel)
        # Not when we already have their number: a guest who wrote "won't share my number here, call 98765 43210" (or shared it
        # earlier) has not declined anything, and the alert would put up a stale "No phone shared" chip.
        if channel_val_for_decline == "instagram" and burst_text and guest_missing_phone:
            from app.services.phone_decline_detector import detect_phone_decline
            phone_decline_phrase = detect_phone_decline(burst_text)
            if phone_decline_phrase:
                try:
                    _maybe_alert_phone_decline(
                        db, tenant_id=tenant_id, conversation=conversation, guest=guest,
                        inquiry=inquiry, phone_decline_phrase=phone_decline_phrase,
                    )
                except Exception as exc:
                    # A missed task must never cost the guest their reply.
                    log.warning("phone_decline_alert_failed", conversation_id=conversation_id, error=str(exc))

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
                if not consult_turn.consult_id: send_to_tenant(  # noqa: E701 -- a consult already pushed, naming the question
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

        if sales_turn.active:
            try:
                sales_agent_service.after_draft(db, tenant_id, sales_turn, draft_message.id, bool(should_auto_send), conversation, guest)
            except Exception as exc:
                db.rollback()
                log.warning("sales_agent_after_draft_failed", conversation_id=conversation_id, error=str(exc))

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
        # self.retry() itself raises MaxRetriesExceededError once max_retries
        # is exhausted -- uncaught, that crashed the task silently (no draft,
        # no notification, guest and agent both got nothing). Same class of
        # bug already fixed once in sync_wa_templates.py; it was never
        # propagated here. A sibling except on the same try can't catch an
        # exception raised from inside another except block, so it has to be
        # caught around this retry() call specifically.
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            log.error("concierge_draft_retries_exhausted", message_id=message_id, conversation_id=conversation_id, error=str(exc))
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
