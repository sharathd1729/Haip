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

PROMPT_VERSION = "leads360-summary-v2"

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
  }
}

Be specific and concise. If data is missing, state what's unknown rather than
inventing it. Output only the JSON object."""


_ANALYSIS_KEYS = ("intent", "sentiment", "objection", "reply_urgency", "next_action")


def _parse_summary_response(raw: str) -> tuple[str, dict | None]:
    """Parse the v2 JSON response into (summary_text, analysis_dict).

    Degrades gracefully: if the model ignored the JSON instruction and
    returned prose (or wrapped JSON in markdown fences), keep whatever prose
    we can as the summary and return analysis=None — never lose the summary
    over a formatting miss."""
    import json as _json

    text = raw.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = _json.loads(text)
    except (ValueError, TypeError):
        return raw, None

    if not isinstance(parsed, dict):
        return raw, None

    summary = str(parsed.get("summary") or "").strip()
    analysis_raw = parsed.get("analysis")
    analysis = None
    if isinstance(analysis_raw, dict):
        analysis = {k: analysis_raw.get(k) for k in _ANALYSIS_KEYS}
    return summary or raw, analysis


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
                model="nvidia/llama-3.1-nemotron-70b-instruct",
                max_tokens=512,
            )
        )
        raw_text = (result.get("content") or "").strip()

        if not raw_text:
            log.warning("generate_ai_summary_empty_response", inquiry_id=inquiry_id)
            return

        summary_text, analysis = _parse_summary_response(raw_text)
        if not summary_text:
            log.warning("generate_ai_summary_unparseable", inquiry_id=inquiry_id)
            return

        # ── Write to DB ────────────────────────────────────────────────────────
        inquiry.ai_summary = summary_text
        if analysis is not None:
            inquiry.ai_analysis = analysis
        db.add(inquiry)
        db.commit()

        log.info(
            "generate_ai_summary_done",
            inquiry_id=inquiry_id,
            tenant_id=tenant_id,
            chars=len(summary_text),
            prompt_version=PROMPT_VERSION,
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
