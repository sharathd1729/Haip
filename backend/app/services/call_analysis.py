"""One AI read per phone call (AI cost audit, 8 Nov 2026): QA score + wrap-up + call details in ONE tool call.

Replaces three LLM calls on the full transcript (quick_classify call-classify-v2, call_scoring call-judge-v3 with a
deep_reason re-judge below 0.78 confidence, call_analysis call-wrap-up-v5). The task is workers/tasks/call_analysis.py.

* Prompt: app/prompts/call_analysis.jinja is the SYSTEM text and holds no call data (rubric + rules only), so the Claude
  adapter caches it per tenant (it marks the system block cache_control once the user message is >= 200 chars); the
  call context + transcript is the user message.
* Re-check (was deep_reason on most calls): only a BORDERLINE score -- confidence < LOW_CONFIDENCE, or the percentage
  within BORDERLINE_BAND of PASS_MARK -- and it sends the first answer's criterion scores + evidence quotes, never the
  transcript again. A failed re-check keeps the first answer.
* The model's answer is kept in Redis (RESULT_TTL) before any DB write: a retry after a DB failure, or call_recovery's
  next run, writes the kept answer instead of asking the model again.
"""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader

from app.adapters.llm import get_llm
from app.core import cache
from app.core.prompt_versions import get_version
from app.models.call import CallDisposition
from app.services import ai_actionable
from app.services.transcription_service import redact_pii

log = structlog.get_logger()

ANALYSIS_VERSION = get_version("call_analysis")
LLM_TASK = "call_analysis"  # Sonnet under the Claude switch (CLAUDE.md routing table)
RECHECK_TASK = "deep_reason"

# Re-check rule. 80 = the QA report's "pass" verdict (reports.py) and the score ring's top band; +-5 around it is where
# one criterion's point flips a call between pass and review. Below 0.5 the model itself says it is guessing.
PASS_MARK = 80.0
BORDERLINE_BAND = 5.0
LOW_CONFIDENCE = 0.5

RESULT_TTL = 24 * 3600

_jinja_env = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "prompts")))

DISPOSITION_MAP = {
    "hot": CallDisposition.HOT,
    "quoted": CallDisposition.QUOTED,
    "booked": CallDisposition.BOOKED,
    "lost": CallDisposition.LOST,
    "callback": CallDisposition.CALLBACK,
    "no_answer": CallDisposition.NO_ANSWER,
    "voicemail": CallDisposition.VOICEMAIL,
}

# Values a model echoes from the transcript/notes that are not a name (seen live: Guest.name == "Unknown").
_NOT_A_NAME = {"unknown", "unnamed", "n/a", "na", "none", "unidentified"}

_STR = {"type": "string"}
_NUM = {"type": "number"}
_CRITERION_SCORES = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"id": _STR, "score": _NUM, "evidence": _STR},
        "required": ["id", "score", "evidence"],
    },
}

# Canonical ToolSpec shape (adapters/llm/tools.py); each adapter renders its own dialect.
CALL_ANALYSIS_TOOL = {
    "name": "analyse_call",
    "description": "Return the QA score, the after-call wrap-up and the details of the call",
    "input_schema": {
        "type": "object",
        "properties": {
            # Part 1: QA
            "criterion_scores": _CRITERION_SCORES,
            "has_auto_fail": {"type": "boolean"},
            "confidence": _NUM,
            "agent_strengths": {"type": "array", "items": _STR},
            "agent_growth_areas": {"type": "array", "items": _STR},
            # Part 2: wrap-up (ai_actionable cleans the actionable block)
            "summary": _STR,
            "suggested_disposition": _STR,
            "next_action": _STR,
            "outcome": _STR,
            "decline_reason": _STR,
            "decline_quote": _STR,
            "next_best_action": {
                "type": "object",
                "properties": {"action": _STR, "owner": _STR, "channel": _STR, "deadline": _STR, "why": _STR},
            },
            "blocking_objection": {"type": "object", "properties": {"objection": _STR, "counter": _STR}},
            "missed_revenue": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": _STR,
                        "what": _STR,
                        "est_inr": _NUM,
                        "grounded": {"type": "boolean"},
                        "evidence": _STR,
                    },
                },
            },
            "temperature": {"type": "object", "properties": {"value": _STR, "reason": _STR}},
            "haip_updates": {
                "type": "array",
                "items": {"type": "object", "properties": {"field": _STR, "value": _STR, "why": _STR}},
            },
            # Part 3: call details
            "language": _STR,
            "is_code_mixed": {"type": "boolean"},
            "occasion": _STR,
            "budget_signal": _STR,
            "decision_stage": _STR,
            "competitor_mentioned": _STR,
            "conversion_probability": _NUM,
            "lost_reason": _STR,
            "guest_name": _STR,
        },
        "required": [
            "criterion_scores",
            "has_auto_fail",
            "confidence",
            "summary",
            "suggested_disposition",
            "next_action",
            "outcome",
            "language",
            "guest_name",
        ],
    },
}

RECHECK_TOOL = {
    "name": "recheck_scores",
    "description": "Return the checked rubric scores",
    "input_schema": {
        "type": "object",
        "properties": {"criterion_scores": _CRITERION_SCORES, "has_auto_fail": {"type": "boolean"}, "confidence": _NUM},
        "required": ["criterion_scores", "has_auto_fail", "confidence"],
    },
}

_RECHECK_SYSTEM = """You are HAIP's QA reviewer. Another reviewer scored a hospitality phone call against the rubric
below; the score is borderline. You get each criterion's score and the verbatim evidence quote it rests on (not the
whole call). Check every score against its evidence and the rubric: lower a score its evidence does not support, raise
one only when its own evidence shows the criterion was met, keep the rest. Never invent evidence. AUTO_FAIL criteria:
has_auto_fail=true and score=0 only when the evidence shows it. Return every criterion via the recheck_scores tool.

RUBRIC
{criteria}"""


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def coerce_bool(value, default: bool = False) -> bool:
    """A model can send is_code_mixed as the string "true"/"false"; SQLAlchemy's Boolean raises on non-bools (seen live
    under a former quick_classify model: every run crashed). bool("false") is True, so it is never used here."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return default


def has_speech(turns: list) -> bool:
    """The judge's rule: a transcript where nobody said anything is not worth a model call."""
    return any((t.get("text") or "").strip() for t in turns)


def transcript_text(turns: list) -> str:
    return redact_pii("\n".join(f"[{t['t0']:.1f}s] {t['speaker'].upper()}: {t['text']}" for t in turns))


def build_prompts(
    *, rubric, call, turns: list, language: str | None, property_name: str, agent_name: str, guest_name: str | None
) -> tuple[str, str]:
    """(system, user). The system text depends only on the tenant's rubric, so it caches across that tenant's calls."""
    system = _jinja_env.get_template("call_analysis.jinja").render(
        rubric=rubric,
        vertical="luxury",
        actionable_spec=ai_actionable.PROMPT_SPEC.rstrip(),
        actionable_rules=ai_actionable.PROMPT_RULES,
    )
    direction = call.direction.value if hasattr(call.direction, "value") else call.direction
    user = "\n".join(
        [
            "CALL CONTEXT",
            f"- Property: {property_name}",
            f"- Agent: {agent_name}",
            f"- Guest: {guest_name or '(unknown)'}",
            f"- Direction: {direction} · Duration: {call.duration_seconds}s",
            f"- Language (from transcription): {language or 'en'}",
            f"- Call date (reference for deadlines): {call.created_at.date().isoformat() if call.created_at else 'today'}",
            "",
            "TRANSCRIPT (PII redacted)",
            transcript_text(turns),
            "",
            "Analyse this call.",
        ]
    )
    return system, user


def _result_key(tenant_id: str, call_id: str, system: str, user: str) -> str:
    digest = hashlib.sha256((system + "\x00" + user).encode()).hexdigest()[:16]
    return f"haip:call_analysis:{tenant_id}:{call_id}:{ANALYSIS_VERSION}:{digest}"


def percentage(rubric_criteria: list, criterion_scores: list) -> float:
    from app.services.qa_service import compute_score

    return compute_score(rubric_criteria, criterion_scores)[2]


def is_borderline(result: dict, rubric_criteria: list) -> bool:
    if not result.get("criterion_scores"):
        return False
    conf = result.get("confidence")
    if isinstance(conf, (int, float)) and not isinstance(conf, bool) and conf < LOW_CONFIDENCE:
        return True
    return abs(percentage(rubric_criteria, result["criterion_scores"]) - PASS_MARK) <= BORDERLINE_BAND


def _recheck(tenant_id: str, call_id: str, rubric_criteria: list, first: dict) -> dict | None:
    criteria = "\n".join(
        f"- {c['id']} [weight={c.get('weight', 10)}] ({c.get('method', 'YES_NO')}): {c.get('description', '')}"
        for c in rubric_criteria
    )
    first_answer = {k: first.get(k) for k in ("criterion_scores", "has_auto_fail", "confidence")}
    try:
        out = _run_async(
            get_llm(RECHECK_TASK).complete(
                system_prompt=_RECHECK_SYSTEM.format(criteria=criteria),
                user_message="FIRST SCORING\n" + json.dumps(first_answer, ensure_ascii=False),
                tools=[RECHECK_TOOL],
            )
        )
    except Exception as exc:  # noqa: BLE001 -- the first answer is a real score; keep it
        log.warning("call_analysis_recheck_failed", call_id=call_id, tenant_id=tenant_id, error=str(exc)[:200])
        return None
    checked = out.get("tool_use") or {}
    if not checked.get("criterion_scores"):
        return None
    return {**checked, "model": out.get("model") or RECHECK_TASK}


def analyse(*, tenant_id: str, call_id: str, system: str, user: str, rubric_criteria: list) -> dict:
    """The model's read of the call, from the kept answer when there is one. Raises when the model gives nothing."""
    key = _result_key(tenant_id, call_id, system, user)
    kept = cache.get_cached(key)
    if isinstance(kept, dict) and kept.get("criterion_scores") is not None:
        log.info("call_analysis_resumed_from_kept_answer", call_id=call_id, tenant_id=tenant_id)
        return kept

    out = _run_async(
        get_llm(LLM_TASK).complete(system_prompt=system, user_message=user, tools=[CALL_ANALYSIS_TOOL], max_tokens=4096)
    )
    result = dict(out.get("tool_use") or {})
    if not result:
        raise ValueError("call analysis: the model returned no tool call")
    result["model_used"] = out.get("model") or LLM_TASK

    if is_borderline(result, rubric_criteria):
        log.info("call_analysis_rechecking", call_id=call_id, confidence=result.get("confidence"))
        checked = _recheck(tenant_id, call_id, rubric_criteria, result)
        if checked:
            result.update(
                criterion_scores=checked["criterion_scores"],
                has_auto_fail=coerce_bool(checked.get("has_auto_fail"), False),
                confidence=checked.get("confidence", result.get("confidence")),
                model_used=f"{checked['model']}_review",
            )
            result["rechecked"] = True

    cache.set_cached(key, result, ttl=RESULT_TTL)
    return result


def _confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
        return round(float(value), 2)
    return None


def _phrases(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [p for p in (ai_actionable._text(v, 160) for v in value) if p][:3]


def apply_result(db, *, call, tenant_id: str, rubric, result: dict) -> str:
    """Write the read onto the call, the guest's name (only when unnamed) and ONE call_scores row for this version.
    Does not commit. Returns the normalised disposition string (for the automation trigger)."""
    from app.models.guest import Guest
    from app.services.qa_service import store_score

    # Call details (was classify)
    call.detected_language = (result.get("language") or call.detected_language or "")[:10] or None
    call.is_code_mixed = coerce_bool(result.get("is_code_mixed"), False)
    for field, limit in (
        ("occasion", 50),
        ("budget_signal", 100),
        ("decision_stage", 50),
        ("competitor_mentioned", 255),
        ("lost_reason", 100),
    ):
        value = result.get(field)
        if isinstance(value, str) and value.strip():
            setattr(call, field, value.strip()[:limit])
    prob = result.get("conversion_probability")
    if isinstance(prob, (int, float)) and not isinstance(prob, bool):
        call.conversion_probability = max(0, min(100, int(prob)))

    guest_name = (result.get("guest_name") or "").strip()
    if guest_name.lower() in _NOT_A_NAME:
        guest_name = ""
    if guest_name and call.guest_id:
        guest = db.query(Guest).filter_by(id=call.guest_id, tenant_id=tenant_id).first()
        if guest and (not guest.name or guest.name == "Unknown Guest"):
            guest.name = guest_name[:255]
            log.info("guest_name_detected_from_call", call_id=call.id, guest_id=guest.id)

    # QA score (was judge)
    score = store_score(
        db,
        call_id=call.id,
        tenant_id=tenant_id,
        rubric_id=rubric.id,
        result={**result, "confidence": _confidence(result.get("confidence"))},
        analysis_version=ANALYSIS_VERSION,
    )
    call.ai_score = float(score.percentage)

    # Wrap-up
    call.ai_summary = result.get("summary") or call.ai_summary
    insights = ai_actionable.clean_call_insights(result)
    if insights is not None:
        strengths, growth = _phrases(result.get("agent_strengths")), _phrases(result.get("agent_growth_areas"))
        if strengths or growth:
            insights.update(agent_strengths=strengths, agent_growth_areas=growth)
    call.ai_insights = insights
    call.ai_next_action = result.get("next_action") or ai_actionable.next_action_text(
        (insights or {}).get("next_best_action")
    )
    # A missing/unknown disposition is None, never CALLBACK (an ANSWERED value: a nobody-answered call once read as
    # "answered, wants a callback"); None lets is_missed_call() fall back to dial status / duration.
    disposition = (result.get("suggested_disposition") or "").strip().lower()
    call.ai_disposition = DISPOSITION_MAP.get(disposition)
    return disposition
