"""
Leads360 — Async AI Summary Generation Task

Generates a 3-sentence narrative for an inquiry and writes it to
inquiries.ai_summary. Called by:
  - leads_service.trigger_summary_refresh() on inquiry creation
  - classify task (after call.analyzed — immediate, no debounce)
  - concierge_draft / message handlers (debounced 30 min via Redis TTL)
  - POST /leads/{inquiry_id}/refresh-summary (manual — always immediate)

Constitution checks:
  ✓ Uses get_llm("concierge_draft") — never direct Claude import
  ✓ Phone never logged in plaintext
  ✓ LLM failure does not crash the task — graceful degradation
"""

import asyncio
import logging

from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.adapters.llm import get_llm

log = logging.getLogger(__name__)

PROMPT_VERSION = "leads360-summary-v1"

SYSTEM_PROMPT = """You are a hospitality sales intelligence assistant.
Given a lead's inquiry details, recent conversation, and call notes,
write exactly 3 sentences:
  1. What the guest wants (destination, dates, occasion, group)
  2. Budget signal or pricing concern (if any)
  3. Recommended next action for the sales agent

Be specific, concise, and actionable. If data is missing, state what's unknown.
Do not include pleasantries or filler. Output only the 3 sentences, nothing else."""


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
        user_message = f"Lead context:\n{context}\n\nGenerate the 3-sentence summary."

        # ── LLM call ──────────────────────────────────────────────────────────
        adapter = get_llm("concierge_draft")
        result = _run_async(
            adapter.complete(
                system_prompt=SYSTEM_PROMPT,
                user_message=user_message,
                max_tokens=256,
            )
        )
        summary_text = (result.get("content") or "").strip()

        if not summary_text:
            log.warning("generate_ai_summary_empty_response", inquiry_id=inquiry_id)
            return

        # ── Write to DB ────────────────────────────────────────────────────────
        inquiry.ai_summary = summary_text
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
