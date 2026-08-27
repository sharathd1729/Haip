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
    "next_action": "<one specific action for the sales agent>"
  },
  "extracted": {
    "check_in": "<ISO date YYYY-MM-DD ONLY if the guest explicitly stated a check-in/travel date, else null>",
    "check_out": "<ISO date YYYY-MM-DD ONLY if the guest explicitly stated a check-out/return date, else null>",
    "adults": "<integer number of adults ONLY if explicitly stated, else null>",
    "children": "<integer number of children ONLY if explicitly stated, else null>",
    "occasion": "<short phrase, e.g. 'anniversary', ONLY if explicitly stated, else null>",
    "budget": "<number, the guest's stated budget in INR, ONLY if explicitly stated, else null>",
    "special_requests": "<short phrase of a specific request the guest explicitly made (dietary, accessibility, celebration setup, etc.), else null>"
  }
}

Be specific and concise. If data is missing, state what's unknown rather than
inventing it. "extracted" fields are a strict, literal readback of what the
guest actually said in this conversation -- never infer, guess, or estimate
a value the guest did not state. When in doubt, use null. Output only the
JSON object."""


_ANALYSIS_KEYS = ("intent", "sentiment", "objection", "reply_urgency", "next_action")
_EXTRACTED_KEYS = ("check_in", "check_out", "adults", "children", "occasion", "budget", "special_requests")


def _parse_summary_response(raw: str) -> tuple[str, dict | None, dict | None]:
    """Parse the v3 JSON response into (summary_text, analysis_dict, extracted_dict).

    Degrades gracefully: markdown fences and reasoning-model <think> blocks
    are stripped; a truncated JSON payload (max_tokens hit mid-object) still
    yields its "summary" field via regex instead of leaking raw JSON into
    the UI (analysis/extracted are simply absent in that case); plain prose
    is kept as-is with analysis=extracted=None."""
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
            analysis = {k: analysis_raw.get(k) for k in _ANALYSIS_KEYS}
        extracted_raw = parsed.get("extracted")
        extracted = None
        if isinstance(extracted_raw, dict):
            extracted = {k: extracted_raw.get(k) for k in _EXTRACTED_KEYS}
        return summary or raw, analysis, extracted

    # Truncated/malformed JSON: salvage the summary value rather than storing
    # a raw JSON fragment as the "prose" summary.
    if text.startswith("{"):
        m = _re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if m:
            try:
                salvaged = _json.loads(f'"{m.group(1)}"')  # unescape
            except (ValueError, TypeError):
                salvaged = m.group(1)
            if salvaged.strip():
                return salvaged.strip(), None, None
        return "", None, None   # unusable JSON fragment — caller logs + keeps old summary

    return raw, None, None


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


def _apply_extracted_fields(inquiry, extracted: dict) -> list[str]:
    """Fill in Inquiry trip fields the guest explicitly stated in chat, but
    ONLY where the column is currently empty -- never overwrites a value
    that came from manual staff entry, a Dograh voice-call event, or PMS
    sync (all of which are more authoritative than a chat-text guess).
    Returns the list of field names actually written, for logging."""
    written = []

    check_in = _valid_iso_date(extracted.get("check_in"))
    if check_in and not inquiry.check_in:
        inquiry.check_in = check_in
        written.append("check_in")

    check_out = _valid_iso_date(extracted.get("check_out"))
    if check_out and not inquiry.check_out:
        inquiry.check_out = check_out
        written.append("check_out")

    adults = _coerce_number(extracted.get("adults"))
    if adults is not None and adults > 0 and inquiry.adults is None:
        inquiry.adults = int(adults)
        written.append("adults")

    children = _coerce_number(extracted.get("children"))
    if children is not None and children >= 0 and inquiry.children is None:
        inquiry.children = int(children)
        written.append("children")

    occasion = extracted.get("occasion")
    if isinstance(occasion, str) and occasion.strip() and not inquiry.occasion:
        inquiry.occasion = occasion.strip()[:100]
        written.append("occasion")

    budget = _coerce_number(extracted.get("budget"))
    if budget is not None and budget > 0 and inquiry.budget is None:
        from decimal import Decimal
        inquiry.budget = Decimal(str(budget))
        written.append("budget")

    special_requests = extracted.get("special_requests")
    if isinstance(special_requests, str) and special_requests.strip() and not inquiry.special_requests:
        inquiry.special_requests = special_requests.strip()
        written.append("special_requests")

    return written


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
        from app.models.inquiry import Inquiry
        from app.models.conversation import Message
        from app.models.call import Call
        from app.models.conversation import Conversation
        from sqlalchemy import desc

        inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
        if not inquiry:
            log.warning("generate_ai_summary_inquiry_not_found", inquiry_id=inquiry_id)
            return

        # ── Build context ──────────────────────────────────────────────────────
        lines = [
            f"Inquiry source: {inquiry.source.value if inquiry.source else 'unknown'}",
            f"Stage: {inquiry.stage.value if inquiry.stage else 'new'}",
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

        # Last 10 messages
        conv_ids = [
            r.id for r in
            db.query(Conversation.id)
            .filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id)
            .all()
        ]
        if conv_ids:
            messages = (
                db.query(Message.body, Message.direction)
                .filter(
                    Message.tenant_id == tenant_id,
                    Message.conversation_id.in_(conv_ids),
                )
                .order_by(desc(Message.created_at))
                .limit(10)
                .all()
            )
            for body, direction in reversed(messages):
                if body:
                    dir_label = direction.value if hasattr(direction, "value") else str(direction)
                    lines.append(f"[{dir_label}] {body[:150]}")

        context = "\n".join(lines)
        user_message = f"Lead context:\n{context}\n\nGenerate the JSON response."

        # ── LLM call ──────────────────────────────────────────────────────────
        adapter = get_llm("lead_summary")
        result = _run_async(
            adapter.complete(
                system_prompt=SYSTEM_PROMPT,
                user_message=user_message,
                model="nvidia/llama-3.3-nemotron-super-49b-v1.5",
                # Reasoning model: internal thinking counts against the
                # completion budget — 512 truncated the visible JSON mid-key.
                max_tokens=2048,
            )
        )
        raw_text = (result.get("content") or "").strip()

        if not raw_text:
            log.warning("generate_ai_summary_empty_response", inquiry_id=inquiry_id)
            return

        summary_text, analysis, extracted = _parse_summary_response(raw_text)
        if not summary_text:
            log.warning("generate_ai_summary_unparseable", inquiry_id=inquiry_id)
            return

        # ── Write to DB ────────────────────────────────────────────────────────
        inquiry.ai_summary = summary_text
        if analysis is not None:
            inquiry.ai_analysis = analysis
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
