"""
Real translate + real tone-fix for a pending AI draft (HAIP Inbox
prototype-wiring plan, ticket 3). The prototype's Translate/Tone Fix buttons
were fake local string-templating with no LLM call; this is the real thing,
rewriting an existing draft Message.body in place via a small, cheap
NVIDIA-tier rewrite -- never inline in a request handler, per CLAUDE.md.

Deliberately narrower than concierge_draft: no context gathering, no
grounding loop -- it rewrites already-approved-safe text, it doesn't draft
new claims, so the prompt's own instruction to preserve every fact/number/
date is the guard here, not a second grounded_facts pass.
"""
import asyncio
from celery.exceptions import SoftTimeLimitExceeded
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal, set_tenant_context
from app.models.conversation import Message
from app.adapters.llm import get_llm
from app.core.prompt_versions import stamp
import structlog

log = structlog.get_logger()

REWRITE_TOOL = {
    "name": "rewrite_message",
    "description": "Rewrite a WhatsApp/Instagram draft reply",
    "input_schema": {
        "type": "object",
        "properties": {
            "rewritten_text": {"type": "string"},
        },
        "required": ["rewritten_text"],
    },
}

_VALID_TONES = {"warm", "formal", "brief", "persuasive"}

# Every click on an AI rewrite button is a paid provider request, so it is bounded. The NVIDIA client is built without a
# timeout (the openai SDK then waits up to 10 minutes) and the worker runs only 2 processes shared by every queue, so one
# hung request used to be able to hold a slot for ~10 minutes. The same wait_for pattern concierge_draft uses applies here.
#
#   * One provider request may take at most REWRITE_TIMEOUT_SECONDS.
#   * A timeout is NOT retried (it is the signature of a hung request, and the person asked a moment ago). Draft: the
#     draft is left as it was. Composer: the job is marked failed with error "timeout".
#   * Any other provider error: draft retries ONCE after 10 s (max_retries=1, was 3); composer never retries.
#   * Worst case per click: composer 30 s; draft 30 s on timeout, or 30 + 10 + 30 = 70 s on a provider error.
#   * REWRITE_SOFT/HARD_TIME_LIMIT are Celery backstops for anything that is not the provider call (they apply to one
#     execution of the task, and the soft limit is handled like a timeout).
REWRITE_TIMEOUT_SECONDS = 30
REWRITE_SOFT_TIME_LIMIT = REWRITE_TIMEOUT_SECONDS + 15
REWRITE_HARD_TIME_LIMIT = REWRITE_TIMEOUT_SECONDS + 30


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _rewrite_completion(adapter, system_prompt: str) -> dict:
    """One bounded provider request; raises asyncio.TimeoutError after REWRITE_TIMEOUT_SECONDS."""
    return _run_async(
        asyncio.wait_for(
            adapter.complete(
                system_prompt=system_prompt,
                user_message="Rewrite the message per the instructions above.",
                tools=[REWRITE_TOOL],
            ),
            timeout=REWRITE_TIMEOUT_SECONDS,
        )
    )


def _build_system_prompt(original_text: str, tone: str | None, target_language: str | None) -> str:
    instructions = []
    if tone in _VALID_TONES:
        tone_desc = {
            "warm": "warm and personable -- like a host who genuinely knows this guest",
            "formal": "formal and precise -- polished, minimal small talk",
            "brief": "brief -- shortest version that fully keeps the meaning, no filler",
            "persuasive": "persuasive -- gently build interest without overstating anything",
        }[tone]
        instructions.append(f"Rewrite the tone to be {tone_desc}.")
    if target_language:
        instructions.append(f"Translate the message into {target_language}.")
    if not instructions:
        instructions.append("Lightly polish the message for clarity.")

    return (
        "You are rewriting an already-approved WhatsApp/Instagram draft reply for a "
        "hospitality guest.\n\n"
        f"ORIGINAL MESSAGE:\n\"{original_text}\"\n\n"
        "INSTRUCTIONS\n"
        f"- {' '.join(instructions)}\n"
        "- Never change, add, or remove any price, date, number, or availability "
        "claim -- preserve every fact in the original exactly, only change wording/tone/language.\n"
        "- Keep it under 90 words.\n"
        "- Return STRICTLY via tool-use: {\"rewritten_text\": \"<message text>\"}"
    )


@celery_app.task(
    bind=True, max_retries=1, default_retry_delay=10, name="tasks.rewrite_draft",
    soft_time_limit=REWRITE_SOFT_TIME_LIMIT, time_limit=REWRITE_HARD_TIME_LIMIT,
)
def rewrite_draft(self, message_id: str, tenant_id: str, tone: str | None = None, target_language: str | None = None):
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        msg = db.query(Message).filter_by(id=message_id, tenant_id=tenant_id).first()
        if not msg:
            log.error("rewrite_draft_message_not_found", message_id=message_id)
            return
        if not msg.is_ai_generated or msg.was_approved is not None:
            log.warning("rewrite_draft_skipped_not_pending_draft", message_id=message_id)
            return

        system_prompt = _build_system_prompt(msg.body or "", tone, target_language)
        adapter = get_llm("concierge_rewrite")
        result = _rewrite_completion(adapter, system_prompt)
        rewritten = (result.get("tool_use") or {}).get("rewritten_text")
        if not rewritten:
            log.warning("rewrite_draft_empty_result", message_id=message_id)
            return

        msg.body = rewritten
        db.commit()
        log.info("rewrite_draft_applied", message_id=message_id, tone=tone,
                  target_language=target_language, **stamp("concierge_rewrite"))
    except (asyncio.TimeoutError, SoftTimeLimitExceeded):
        # Deliberately not retried: see the comment on REWRITE_TIMEOUT_SECONDS. The draft keeps its current text.
        log.warning("rewrite_draft_timed_out", message_id=message_id, timeout_sec=REWRITE_TIMEOUT_SECONDS)
        return
    except Exception as exc:
        log.error("rewrite_draft_failed", message_id=message_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
