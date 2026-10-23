"""
Leads360 — Async AI Summary Generation Task

Generates a 3-sentence narrative for an inquiry and writes it to
inquiries.ai_summary. Called by:
  - leads_service.trigger_summary_refresh() on inquiry creation
  - classify task (after call.analyzed — immediate, no debounce)
  - concierge_draft / message handlers (debounced 30 min via Redis TTL)
  - POST /leads/{inquiry_id}/refresh-summary (manual — always immediate)

Constitution checks:
  ✓ Uses get_llm("lead_summary") — never direct provider import
  ✓ Phone never logged in plaintext
  ✓ LLM failure does not crash the task — graceful degradation
"""

import asyncio
import re
from datetime import datetime, timezone
import structlog

from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.adapters.llm import get_llm

log = structlog.get_logger()

from app.core.prompt_versions import get_version, stamp

# Kept as a module constant for backwards compatibility with existing readers,
# but the registry is now the single source of truth — bump it there.
PROMPT_VERSION = get_version("leads360_summary")

SYSTEM_PROMPT = """You are a hospitality sales intelligence assistant.
Given a lead's inquiry details, recent conversation, and call notes,
respond with ONLY a JSON object (no markdown fences, no other text):

{
  "summary": "<exactly 3 sentences: 1. what the guest wants (destination, dates, occasion, group); 2. budget signal or pricing concern if any; 3. recommended next action for the sales agent>",
  "analysis": {
    "intent": "<one short phrase: what the guest is trying to do, e.g. 'weekend villa stay for anniversary'>",
    "sentiment": "<one of: positive | neutral | hesitant | negative>",
    "objection": "<the guest's main objection/blocker in one short phrase, or null if none>",
    "reply_urgency": "<one of: high | medium | low — how urgently the team should reply>",
    "next_action": "<one specific action for the sales agent>",
    "unanswered_questions": ["<each question the GUEST asked that the team has NOT yet answered in this conversation, as a short phrase; [] if none>"],
    "requirements": ["<each amenity/need the guest stated (pets, kitchen, wheelchair access ...), as a short phrase; [] if none>"],
    "inferences": ["<anything you CONCLUDED but the guest did NOT say, e.g. 'likely price-sensitive'; [] if none. Never put an inference anywhere else>"],
    "follow_up": "<when/how to follow up if a follow-up is due (e.g. 'call back tomorrow morning'), else null>",__ACTIONABLE__
  },
  "extracted": {
    "check_in": "<ISO date YYYY-MM-DD ONLY if the guest explicitly stated a check-in/travel date, else null. If the guest gave a date with no year (e.g. 'sept 16-18', 'the 20th'), resolve the year using the 'Reference date' given in the lead context below -- pick the nearest occurrence of that month/day ON OR AFTER the reference date, never a year already in the past relative to it, and never guess a year with no anchor.>",
    "check_out": "<ISO date YYYY-MM-DD ONLY if the guest explicitly stated a check-out/return date, else null. Same year-resolution rule as check_in above.>",
    "adults": "<integer number of adults ONLY if explicitly stated, else null. If the guest gives a total group/party size without breaking it into adults and children (e.g. '5 guests', 'party of 6', 'we are 4'), use that total number here -- guests overwhelmingly phrase headcount this way, and it is still a literal readback of what they said, not a guess. Only leave this null if the guest genuinely gave no headcount at all, or if they explicitly split out children and gave NO adult figure.>",
    "children": "<integer number of children ONLY if explicitly stated, else null>",
    "party_size": "<integer TOTAL number of people travelling (adults + children) ONLY if the guest stated a headcount ('4 of us', 'we are 4', 'family of 5', '6 people'), else null. Count the whole group, never just the person writing or the people they named one by one (e.g. 'my 84-year-old father').>",
    "occasion": "<short phrase, e.g. 'anniversary', ONLY if explicitly stated, else null>",
    "budget": "<number, the guest's stated budget in INR, ONLY if explicitly stated, else null>",
    "special_requests": "<short phrase of a specific request the guest explicitly made (dietary, accessibility, celebration setup, etc.), else null>",
    "route_mentioned": "<the route or locations mentioned, e.g. 'Shirdi to Mumbai' or 'Bangalore to Coorg', ONLY if explicitly stated, else null. If the guest changes their mind mid-conversation, use their LATEST stated route>",
    "quoted_amount": "<number, the exact price figure that was actually quoted to the guest in this conversation (by a human agent or in a call), ONLY if a specific number was stated, else null. Never a guess or a range -- only a real quoted figure>",
    "upsell_offered": "<short phrase naming an add-on/upgrade that was offered to the guest, ONLY if one was actually offered, else null>",
    "upsell_accepted": "<true if the guest accepted the offered upsell, false if they explicitly declined it, else null if not offered or not yet answered>"
  },
  "lead_analysis": "<2-3 sentences, YOUR OWN synthesis (unlike 'extracted' above, this is not a literal readback): what's the real state of this lead, what's stalling it or drove the outcome, and one concrete next step. Ground it strictly in what's actually in this conversation/call data -- never invent facts not present.>"
}

Rules for using the lead context:
- If a PREVIOUS SUMMARY is given, UPDATE it: keep what is still true, change only what the newer messages changed, and never
  contradict the conversation. Details the guest gave earlier still count even if they are not in the newest messages.
- The lead's STAGE and BOOKING STATUS are facts. Make "next_action" consistent with them: for a Sold lead the next action is
  about the stay/after-sales, for a Lost lead there is no sales push, and if a quote was already sent do not recommend sending
  one -- recommend following it up. Never describe a booking differently from BOOKING STATUS.
- Each message line names who wrote it: [guest] is the guest; [us: team member], [us: AI assistant] and
  [us: automated message] are what we sent this guest; [us: campaign broadcast] is a marketing message we sent to many
  guests at once. Only a [us: team member] or [us: AI assistant] message can have answered a question.
- "extracted" trip facts (dates, adults, children, party_size, occasion, budget, special_requests, route_mentioned) and
  "unanswered_questions" / "requirements" come ONLY from [guest] lines and call notes, never from anything we sent: a
  campaign's dates, group sizes, places or offers are not the guest's request. quoted_amount and upsell_offered are the only
  fields read from our messages, and never from a campaign broadcast.
- The Adults / Children lines in the lead context are what HAIP currently shows, not something the guest said: never copy
  them into "extracted", and never put 1 in "adults" for the person writing when they gave a group total.

Be specific and concise. If data is missing, state what's unknown rather than
inventing it. "extracted" fields are a strict, literal readback of what the
guest actually said in this conversation -- never infer, guess, or estimate
a value the guest did not state. "lead_analysis" is the one exception: it is
your own reasoned assessment, not a literal readback, but it must still be
grounded strictly in this conversation's actual content. When in doubt, use
null. Output only the JSON object.

__ACTIONABLE_RULES__ The owner is the "Assigned agent" in the lead context when there is one; deadlines are relative to
"Today" in the lead context."""

from app.services import ai_actionable as _actionable  # noqa: E402

SYSTEM_PROMPT = (SYSTEM_PROMPT.replace("__ACTIONABLE__", _actionable.PROMPT_SPEC.rstrip())
                 .replace("__ACTIONABLE_RULES__", _actionable.PROMPT_RULES))


_ANALYSIS_KEYS = ("intent", "sentiment", "objection", "reply_urgency", "next_action",
                  "unanswered_questions", "requirements", "inferences", "follow_up")
_SENTIMENTS = ("positive", "neutral", "hesitant", "negative")
_URGENCIES = ("high", "medium", "low")
_LIST_KEYS = ("unanswered_questions", "requirements", "inferences")


def _clean_analysis(raw: dict) -> dict:
    """Keep only values the rest of the product understands.

    The model returns free text for fields other code branches on (sentiment drives call-back urgency, reply_urgency drives the
    work queue). "mostly positive" or "ASAP" used to be stored as-is and silently matched nothing; an unknown value is now
    dropped (None), and list fields are lists of short strings.
    """
    out: dict = {}
    for key in _ANALYSIS_KEYS:
        val = raw.get(key)
        if key in _LIST_KEYS:
            items = val if isinstance(val, list) else []
            out[key] = [str(x).strip()[:160] for x in items if isinstance(x, (str, int, float)) and str(x).strip()][:6]
        elif key == "sentiment":
            out[key] = val.strip().lower() if isinstance(val, str) and val.strip().lower() in _SENTIMENTS else None
        elif key == "reply_urgency":
            out[key] = val.strip().lower() if isinstance(val, str) and val.strip().lower() in _URGENCIES else None
        else:
            out[key] = val.strip()[:300] if isinstance(val, str) and val.strip() else None
    # v8 actionable block (added keys; nothing renamed). next_action stays the one-line text older readers use.
    out.update(_actionable.clean_actionable(raw))
    if not out.get("next_action"):
        out["next_action"] = _actionable.next_action_text(out.get("next_best_action"))
    return out
_EXTRACTED_KEYS = (
    "check_in", "check_out", "adults", "children", "occasion", "budget", "special_requests",
    "route_mentioned", "quoted_amount", "upsell_offered", "upsell_accepted", "party_size",
)


class SummaryRejected(Exception):
    """The model's reply is not a usable prose summary. Raised inside the task so the existing retry path runs; carries only a
    short reason, never the model's text (it quotes the guest)."""


# Every key the prompt asks for, as the model spells it. One of these in the summary text means it rendered fields, not prose.
_FIELD_NAMES = frozenset(
    ("summary", "analysis", "extracted", "lead_analysis", "intent", "sentiment", "objection", "reply_urgency", "next_action",
     "unanswered_questions", "requirements", "inferences", "follow_up", "next_best_action", "blocking_objection",
     "missed_revenue", "temperature", "haip_updates", "check_in", "check_out", "adults", "children", "occasion", "budget",
     "special_requests", "route_mentioned", "quoted_amount", "upsell_offered", "upsell_accepted", "party_size")
)
_SNAKE_TOKEN = re.compile(r"(?<![A-Za-z0-9])_?[a-z]+(?:_[a-z]+)+(?![A-Za-z0-9])")
_JSON_KEY = re.compile(r'"[A-Za-z_][A-Za-z0-9_ ]{0,40}"\s*:')
_LABEL_LINE = re.compile(r"^\s*(?:[#*>-]+\s*)?[A-Za-z][A-Za-z /&-]{0,40}:\s*(?:-\s*)?$", re.MULTILINE)
_LITERAL_VALUE = re.compile(r":\s*(?:null|true|false|\[|\{)", re.IGNORECASE)
_TERMINAL = re.compile(r"[.!?…।][\"'”’)\]]*$")


def summary_rejection_reason(text) -> str | None:
    """Why ``text`` is not a clean prose summary, or None when it is. Shared with scripts/repair_broken_summaries.py.

    Rejects what the model emits when it does not follow the JSON contract: backticked or snake_case field names
    (`requirements`, upsell_accepted), JSON keys or literal values (": null", ": ["), markdown field labels on their own line
    ("Next best action:"), and text cut off mid-sentence (no closing punctuation, the max_tokens case)."""
    if not isinstance(text, str) or not text.strip():
        return "empty"
    t = text.strip()
    if t[0] in "{[" or _JSON_KEY.search(t):
        return "json"
    if "`" in t:
        return "backticks"
    if any(m.group(0).lstrip("_") in _FIELD_NAMES or m.group(0).startswith("_") for m in _SNAKE_TOKEN.finditer(t)):
        return "field_names"
    if _LITERAL_VALUE.search(t):
        return "literal_values"
    if _LABEL_LINE.search(t):
        return "field_labels"
    if not _TERMINAL.search(t):
        return "truncated"
    return None


def _parse_summary_response(raw: str) -> tuple[str, dict | None, dict | None, str | None]:
    """Parse the v4 JSON response into (summary_text, analysis_dict, extracted_dict, lead_analysis).

    Degrades gracefully: markdown fences and reasoning-model <think> blocks
    are stripped; a truncated JSON payload (max_tokens hit mid-object) still
    yields its "summary" field via regex instead of leaking raw JSON into
    the UI (analysis/extracted/lead_analysis are simply absent in that
    case); plain prose is kept as-is with analysis=extracted=lead_analysis=None."""
    import json as _json
    import re as _re

    text = raw.strip()
    # Reasoning models (nemotron super/ultra) may prepend <think>...</think>
    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    parsed = None
    try:
        parsed = _json.loads(text)
    except (ValueError, TypeError):
        pass

    if isinstance(parsed, dict):
        summary = str(parsed.get("summary") or "").strip()
        analysis_raw = parsed.get("analysis")
        analysis = None
        if isinstance(analysis_raw, dict):
            analysis = _clean_analysis(analysis_raw)
        extracted_raw = parsed.get("extracted")
        extracted = None
        if isinstance(extracted_raw, dict):
            extracted = {k: extracted_raw.get(k) for k in _EXTRACTED_KEYS}
        lead_analysis_raw = parsed.get("lead_analysis")
        lead_analysis = lead_analysis_raw.strip() if isinstance(lead_analysis_raw, str) and lead_analysis_raw.strip() else None
        # Never fall back to the raw JSON: an empty or malformed "summary" makes the whole run unusable (caller keeps the old one).
        if summary_rejection_reason(summary):
            return "", None, None, None
        return summary, analysis, extracted, lead_analysis

    # Truncated/malformed JSON: salvage the summary value rather than storing
    # a raw JSON fragment as the "prose" summary.
    if text.startswith("{"):
        m = _re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if m:
            try:
                salvaged = _json.loads(f'"{m.group(1)}"')  # unescape
            except (ValueError, TypeError):
                salvaged = m.group(1)
            if salvaged.strip() and not summary_rejection_reason(salvaged.strip()):
                return salvaged.strip(), None, None, None
        return "", None, None, None   # unusable JSON fragment — caller logs + keeps old summary

    # Plain text is only kept when it reads as a prose summary. A markdown rendering of the JSON fields ("Requirements:"
    # then "`requirements`: [...]") or a cut-off fragment used to be stored verbatim as the lead's summary.
    if summary_rejection_reason(text):
        return "", None, None, None
    return text, None, None, None


def _rejection_reason_for(raw: str) -> str:
    """For the log line only: why _parse_summary_response returned no summary (the JSON's own "summary" value when there is
    one, else the whole reply)."""
    import json as _json

    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip().strip("`").strip()
    if text.startswith("json"):
        text = text[4:].strip()
    try:
        parsed = _json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        return "summary_field_" + (summary_rejection_reason(str(parsed.get("summary") or "")) or "unusable")
    return summary_rejection_reason(text) or "unusable"


def _valid_iso_date(value) -> str | None:
    """Accept only a real, strictly-formatted YYYY-MM-DD string -- a
    malformed model output must never reach the DB as a bogus date."""
    import datetime as _dt

    if not isinstance(value, str):
        return None
    try:
        _dt.datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value


def _coerce_number(value):
    """NVIDIA's nemotron models frequently emit a numeric extracted field as
    a JSON string ("4" instead of 4) despite the prompt specifying
    "<integer ... else null>" -- a plain `isinstance(x, (int, float))` check
    then silently rejects a value the model got right, with no error and no
    log line. Confirmed live: a guest who explicitly said "4 guests" got the
    correct free-text next_action but adults stayed null. Accept a numeric
    string too; reject anything else (None stays None, "unknown" stays
    rejected)."""
    if isinstance(value, bool):
        return None  # bool is a subclass of int -- never treat True/False as a count
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        try:
            return float(stripped) if "." in stripped else int(stripped)
        except ValueError:
            return None
    return None


def _adults_with_party_size(adults, children, party_size, stored_children=None):
    """The adult count to write, given the stated group total.

    Live bug (Oct 2026): a guest wrote that they were 4 people including her 84-year-old father; the summary said a group of
    4 but adults stayed 1 -- the model filled "adults" with the one person it could name (or the speaker) and nothing
    checked it against the headcount. When the guest gave a total and the adults plus known children fall short of it,
    the rest are adults: "4 of us" with no children = 4 adults, "4 of us, 1 child" = 3. Children come from this run, else
    from what is on file. A larger adult count than the total is left as the model gave it (it is the more specific one)."""
    if isinstance(party_size, bool) or party_size is None or not (0 < party_size <= 100):
        return adults
    kids = children if children is not None and 0 <= children <= 100 else (stored_children or 0)
    implied = int(party_size) - int(kids)
    if implied <= 0:
        return adults
    if adults is None or not (0 < adults <= 100) or int(adults) + int(kids) < int(party_size):
        return implied
    return adults


def _apply_extracted_fields(inquiry, extracted: dict) -> list[str]:
    """Fill in Inquiry trip fields the guest explicitly stated in chat.

    Most fields below now behave like check_in/check_out already did: a
    later message that clearly restates a value updates it, the same way a
    human editing the field again would. Real product decision (Ratha, Sep
    2026, "autopilot" request): a human correction does not need to be
    permanently protected from a later AI update -- if a new message gives
    different info, the field should move again, and staff can always edit
    it back. This trades a small risk (a misheard later value overwriting a
    deliberate correction) for the alternative that was actually reported as
    broken (a lead's real, later-stated details never landing at all).

    quoted_amount/quoted_at stay write-once -- a formal quote is a fact once
    made, categorically different from a re-statable trip detail: a
    misread number here must never silently change a price already implied
    to a guest.

    Returns the list of field names actually written, for logging."""
    written = []

    # Unlike a formal quote or the guest's stated occasion, travel dates are
    # exactly the field most likely to change mid-conversation -- a guest
    # proposing new dates because the first didn't work is routine, not
    # exceptional. Confirmed live: a lead's Trip Details stayed stuck on an
    # earlier (wrong) guess through several later messages that clearly
    # restated the dates, because this only ever wrote check_in/check_out
    # once. Now allowed to update again as long as the value on file is
    # itself chat-derived (dates_from_chat) -- a Dograh voice-call date
    # (dograh_call_processor.py, dates_from_chat left False/null) still
    # never gets overwritten by a chat-text guess.
    check_in = _valid_iso_date(extracted.get("check_in"))
    check_out = _valid_iso_date(extracted.get("check_out"))
    # A stay cannot end before it starts. Two dates that contradict each other (or contradict the one on file) are a misreading,
    # not a new fact: write neither rather than storing an impossible trip.
    effective_in = check_in or (str(inquiry.check_in) if inquiry.check_in else None)
    effective_out = check_out or (str(inquiry.check_out) if inquiry.check_out else None)
    if effective_in and effective_out and effective_out < effective_in:
        log.warning("generate_ai_summary_dates_inverted", inquiry_id=getattr(inquiry, "id", None))
        check_in = check_out = None
    if check_in and (not inquiry.check_in or inquiry.dates_from_chat) and check_in != inquiry.check_in:
        inquiry.check_in = check_in
        inquiry.dates_from_chat = True
        written.append("check_in")

    if check_out and (not inquiry.check_out or inquiry.dates_from_chat) and check_out != inquiry.check_out:
        inquiry.check_out = check_out
        inquiry.dates_from_chat = True
        written.append("check_out")

    adults = _adults_with_party_size(
        _coerce_number(extracted.get("adults")),
        _coerce_number(extracted.get("children")),
        _coerce_number(extracted.get("party_size")),
        inquiry.children,
    )
    if adults is not None and 0 < adults <= 100 and int(adults) != inquiry.adults:
        inquiry.adults = int(adults)
        written.append("adults")

    children = _coerce_number(extracted.get("children"))
    if children is not None and 0 <= children <= 100 and int(children) != inquiry.children:
        inquiry.children = int(children)
        written.append("children")

    occasion = extracted.get("occasion")
    if isinstance(occasion, str) and occasion.strip():
        occasion = occasion.strip()[:100]
        if occasion != inquiry.occasion:
            inquiry.occasion = occasion
            written.append("occasion")

    budget = _coerce_number(extracted.get("budget"))
    if budget is not None and 0 < budget < 100_000_000:
        from decimal import Decimal
        new_budget = Decimal(str(budget))
        if new_budget != inquiry.budget:
            inquiry.budget = new_budget
            written.append("budget")

    special_requests = extracted.get("special_requests")
    if isinstance(special_requests, str) and special_requests.strip():
        special_requests = special_requests.strip()
        if special_requests != inquiry.special_requests:
            inquiry.special_requests = special_requests
            written.append("special_requests")

    route_mentioned = extracted.get("route_mentioned")
    if isinstance(route_mentioned, str) and route_mentioned.strip():
        route_mentioned = route_mentioned.strip()[:255]
        if route_mentioned != inquiry.route_mentioned:
            inquiry.route_mentioned = route_mentioned
            written.append("route_mentioned")
        # The guest's starting city (lead_validity's location check): the origin of an "A to B" route, only while empty --
        # a person's edit on the lead page is never overwritten.
        if not getattr(inquiry, "guest_location", None):
            from app.services.lead_validity import origin_of_route
            origin = origin_of_route(route_mentioned)
            if origin:
                inquiry.guest_location = origin
                written.append("guest_location")

    # quoted_amount/quoted_at already exist on Inquiry but had no write path
    # anywhere in the codebase before this (confirmed via grep) -- a formal
    # quote is a fact once made, same write-once rule as check_in/occasion.
    quoted_amount = _coerce_number(extracted.get("quoted_amount"))
    if quoted_amount is not None and quoted_amount > 0 and inquiry.quoted_amount is None:
        from decimal import Decimal
        inquiry.quoted_amount = Decimal(str(quoted_amount))
        inquiry.quoted_at = datetime.now(timezone.utc).isoformat()
        written.append("quoted_amount")

    upsell_offered = extracted.get("upsell_offered")
    if isinstance(upsell_offered, str) and upsell_offered.strip():
        upsell_offered = upsell_offered.strip()[:255]
        if upsell_offered != inquiry.upsell_offered:
            inquiry.upsell_offered = upsell_offered
            written.append("upsell_offered")

    # Unlike the fields above, upsell_accepted's empty sentinel is None
    # (not offered / not yet answered) -- False is a real, meaningful
    # answer, so this is allowed to fill in on a later run once the guest
    # actually responds to an offer that was already recorded.
    upsell_accepted = extracted.get("upsell_accepted")
    if isinstance(upsell_accepted, bool) and inquiry.upsell_accepted is None:
        inquiry.upsell_accepted = upsell_accepted
        written.append("upsell_accepted")

    return written


MESSAGE_CHAR_BUDGET = 7000


def _stage_label(inquiry) -> str:
    """The lead's current stage as the tenant sees it (the pipeline_stages catalog), falling back to the legacy enum."""
    stage = getattr(inquiry, "pipeline_stage", None)
    if stage is not None and getattr(stage, "label", None):
        flags = []
        if getattr(stage, "is_closed_won", False):
            flags.append("closed - won")
        if getattr(stage, "is_closed_lost", False):
            flags.append("closed - lost")
        return stage.label + (f" ({', '.join(flags)})" if flags else "")
    legacy = getattr(inquiry, "stage", None)
    return legacy.value if legacy is not None and hasattr(legacy, "value") else (str(legacy) if legacy else "new")


def _linked_stays(db, tenant_id: str, inquiry) -> list:
    from app.models.property import Stay
    return (
        db.query(Stay)
        .filter(Stay.tenant_id == tenant_id, Stay.inquiry_id == inquiry.id)
        .order_by(Stay.check_in.asc())
        .all()
    )


def _booking_status_struct(db, tenant_id: str, inquiry) -> dict:
    """{"state": none|confirmed|checked_in|checked_out|cancelled, "payment": unpaid|partial|paid|None, "stays": n}"""
    try:
        from app.services import booking_service as bsvc
        stays = _linked_stays(db, tenant_id, inquiry)
        if not stays:
            return {"state": "none", "payment": None, "stays": 0}
        active = [s for s in stays if s.status in bsvc.ACTIVE_STATUSES] or [s for s in stays if s.status != "cancelled"] or stays
        main = active[0]
        fin = bsvc.financials_for(db, tenant_id, [main]).get(main.id) or {}
        return {"state": main.status, "payment": None if main.status == "cancelled" else fin.get("payment_status"), "stays": len(stays)}
    except Exception as exc:
        log.warning("generate_ai_summary_booking_status_failed", inquiry_id=getattr(inquiry, "id", None), error=str(exc))
        return {"state": "unknown", "payment": None, "stays": 0}


def _booking_status_text(db, tenant_id: str, inquiry) -> str:
    b = _booking_status_struct(db, tenant_id, inquiry)
    if b["state"] == "none":
        return "no booking exists for this enquiry yet"
    if b["state"] == "unknown":
        return "unknown"
    pay = {"unpaid": "no payment received", "partial": "part-paid", "paid": "fully paid"}.get(b["payment"] or "", "")
    return f"{b['state']}" + (f", {pay}" if pay else "")


def _previous_analysis_text(inquiry) -> str:
    """Last run's summary and analysis, so the new run updates them instead of starting from the last 30 messages alone."""
    parts = []
    # A broken stored summary (raw field dump) is not fed back as "update this": the model would copy its format.
    if inquiry.ai_summary and not summary_rejection_reason(inquiry.ai_summary):
        parts.append(f"PREVIOUS SUMMARY (update it, do not start over): {inquiry.ai_summary[:700]}")
    prev = inquiry.ai_analysis if isinstance(inquiry.ai_analysis, dict) else {}
    kept = {k: prev.get(k) for k in ("intent", "objection", "unanswered_questions", "requirements") if prev.get(k)}
    if kept:
        parts.append("PREVIOUS ANALYSIS: " + str(kept)[:500])
    return "\n".join(parts)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="app.workers.tasks.generate_ai_summary.generate_ai_summary",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def generate_ai_summary(self, inquiry_id: str, tenant_id: str):
    """
    Generate and store a 3-sentence AI summary for an inquiry.
    Gracefully degrades: on LLM failure, leaves ai_summary unchanged.
    """
    db = SessionLocal()
    try:
        from app.core.database import set_tenant_context
        set_tenant_context(db, tenant_id)
        from app.models.inquiry import Inquiry
        from app.models.conversation import Message
        from app.models.call import Call
        from app.models.conversation import Conversation
        from sqlalchemy import desc, or_

        inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
        if not inquiry:
            log.warning("generate_ai_summary_inquiry_not_found", inquiry_id=inquiry_id)
            return

        # ── Build context ──────────────────────────────────────────────────────
        from zoneinfo import ZoneInfo
        lines = [
            f"Today: {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M')} IST",
            f"Assigned agent: {inquiry.assigned_user.name if inquiry.assigned_user else 'unassigned'}",
            f"Inquiry source: {inquiry.source.value if inquiry.source else 'unknown'}",
            f"Stage: {_stage_label(inquiry)}",
            f"Booking status: {_booking_status_text(db, tenant_id, inquiry)}",
            f"Occasion: {inquiry.occasion or 'not specified'}",
            f"Intent: {inquiry.intent_tag or 'not classified'}",
            f"Check-in: {inquiry.check_in or '?'} · Check-out: {inquiry.check_out or '?'}",
            f"Adults: {inquiry.adults or '?'} · Children: {inquiry.children or '?'}",
            f"Budget: {inquiry.budget or 'not stated'} {inquiry.currency or 'INR'}",
        ]

        # Last 5 calls
        calls = (
            db.query(Call.ai_summary, Call.ai_next_action)
            .filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id)
            .order_by(desc(Call.created_at))
            .limit(5)
            .all()
        )
        for i, (summary, next_action) in enumerate(calls, 1):
            if summary:
                lines.append(f"Call {i} summary: {summary[:200]}")
            if next_action:
                lines.append(f"Call {i} next action: {next_action[:100]}")

        previous = _previous_analysis_text(inquiry)
        if previous:
            lines.append(previous)

        # The real conversation, newest 30 real messages within a size budget (was: last 10, cut at 150 characters each -- an
        # early message with the dates fell off the end of a long chat and the regenerated summary forgot them).
        conv_ids = [
            r.id for r in
            db.query(Conversation.id)
            .filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id)
            .all()
        ]
        # Anchors year-less date resolution ("sept 16-18") below -- the most
        # recent INBOUND message's own timestamp, not "now": this task can
        # run days after the guest actually spoke (debounced/catch-up runs),
        # and anchoring to run-time would wrongly roll a since-passed date
        # into next year even though the guest clearly meant the year they
        # were speaking in.
        reference_date = None
        guest_texts: list[str] = [str(s) for s, _ in calls if s]          # a headcount said on a call is the guest's too
        our_texts: list[str] = []
        if conv_ids:
            from app.services.message_author import GUEST, author_of
            messages = (
                db.query(Message.body, Message.direction, Message.created_at, Message.sender_kind, Message.sender_name,
                         Message.is_ai_generated, Message.channel_metadata)
                .filter(
                    Message.tenant_id == tenant_id,
                    Message.conversation_id.in_(conv_ids),
                    # An AI draft nobody sent is not part of the conversation: counting it made "the team told the guest X" true
                    # of something the guest never saw (and could write a quoted amount nobody quoted).
                    or_(Message.is_ai_generated.is_(None), Message.is_ai_generated.is_(False), Message.was_approved.is_(True)),
                )
                .order_by(desc(Message.created_at))
                .limit(30)
                .all()
            )
            for body, direction, created_at, *_ in messages:
                dir_label = direction.value if hasattr(direction, "value") else str(direction)
                if reference_date is None and dir_label == "inbound":
                    reference_date = created_at
            budget_left = MESSAGE_CHAR_BUDGET
            kept: list[str] = []
            # newest first, so the budget keeps the newest
            for body, direction, created_at, sender_kind, sender_name, is_ai, meta in messages:
                if not body:
                    continue
                who = author_of(direction, sender_kind=sender_kind, sender_name=sender_name, is_ai_generated=is_ai,
                                channel_metadata=meta)
                (guest_texts if who == GUEST else our_texts).append(body)
                stamp_ = created_at.date().isoformat() if created_at else "?"
                line = f"[{who.lower().replace('us: ai', 'us: AI')}] {stamp_}: {body[:300]}"
                if budget_left - len(line) < 0 and kept:
                    break
                budget_left -= len(line)
                kept.append(line)
            lines.extend(reversed(kept))

        if reference_date is None:
            reference_date = inquiry.created_at or datetime.now(timezone.utc)
        lines.insert(0, f"Reference date (when this conversation was last active): {reference_date.date().isoformat()}")

        context = "\n".join(lines)
        user_message = f"Lead context:\n{context}\n\nGenerate the JSON response."

        # ── LLM call ──────────────────────────────────────────────────────────
        adapter = get_llm("lead_summary")
        result = _run_async(
            adapter.complete(
                system_prompt=SYSTEM_PROMPT,
                user_message=user_message,
                # No explicit model= here -- let it use get_llm("lead_summary")'s
                # routed default. This used to hardcode the dead
                # nvidia/llama-3.3-nemotron-super-49b-v1.5 (EOL 2026-08-26,
                # HTTP 410), which silently overrode the routing table's
                # replacement model since an explicit model= kwarg always
                # wins over the adapter's bound default (see _build_adapter's
                # docstring) -- confirmed live as the actual cause of
                # generate_ai_summary_failed even after _TASK_ROUTES was fixed.
                # Reasoning model: internal thinking counts against the
                # completion budget — 512 truncated the visible JSON mid-key.
                max_tokens=2048,
            )
        )
        raw_text = (result.get("content") or "").strip()

        if not raw_text:
            log.warning("generate_ai_summary_empty_response", inquiry_id=inquiry_id)
            return

        summary_text, analysis, extracted, lead_analysis = _parse_summary_response(raw_text)
        if not summary_text:
            # Nothing from this run is written (the previous summary stays). Raising hands it to the retry path below: a
            # malformed reply is usually a one-off from the model. Only the reason and sizes are logged, never the text.
            reason = _rejection_reason_for(raw_text)
            log.error(
                "generate_ai_summary_rejected",
                inquiry_id=inquiry_id,
                tenant_id=tenant_id,
                reason=reason,
                raw_chars=len(raw_text),
                model=result.get("model"),
            )
            raise SummaryRejected(reason)

        # ── Write to DB ────────────────────────────────────────────────────────
        inquiry.ai_summary = summary_text
        if analysis is not None:
            # Booking state is read from the bookings themselves, never from the model's account of them.
            analysis["booking_status"] = _booking_status_struct(db, tenant_id, inquiry)
            # The stage this summary was written at: the lead page says "written when the lead was X" once the stage
            # has moved on, instead of letting an old "marked lost" summary contradict a live stage.
            stage = getattr(inquiry, "pipeline_stage", None)
            analysis["written_stage_key"] = getattr(stage, "key", None)
            analysis["written_at"] = datetime.now(timezone.utc).isoformat()
            inquiry.ai_analysis = analysis
        if lead_analysis is not None:
            inquiry.ai_lead_analysis = lead_analysis
        if extracted:
            # A headcount only WE wrote (a campaign's "8 guests each") is never stored as the guest's party size.
            from app.services.message_author import keep_guest_headcount
            extracted, dropped = keep_guest_headcount(extracted, guest_texts, our_texts)
            if dropped:
                log.info("generate_ai_summary_headcount_not_from_guest", inquiry_id=inquiry_id, dropped=dropped)
        fields_written = _apply_extracted_fields(inquiry, extracted) if extracted else []
        db.add(inquiry)
        db.commit()

        log.info(
            "generate_ai_summary_done",
            inquiry_id=inquiry_id,
            tenant_id=tenant_id,
            chars=len(summary_text),
            fields_extracted=fields_written,
            **stamp("leads360_summary", model=result.get("model")),
        )
        # Lead autopilot reads the freshly updated lead. Message bursts reach here through the summary debounce,
        # so a burst costs one evaluation.
        from app.services import lead_autopilot_service
        lead_autopilot_service.queue_evaluation(inquiry_id, tenant_id, trigger="summary")

    except Exception as exc:
        # LLM failure must never crash the task chain
        log.warning(
            "generate_ai_summary_failed",
            inquiry_id=inquiry_id,
            tenant_id=tenant_id,
            error=str(exc),
        )
        try:
            db.rollback()
        except Exception:
            pass
        # Retry twice with 60s delay on transient errors
        raise self.retry(exc=exc)
    finally:
        db.close()
