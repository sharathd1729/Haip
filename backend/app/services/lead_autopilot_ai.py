"""Lead autopilot: the AI classifier, for leads no deterministic rule decides.

Runs ONLY inside the lead_autopilot Celery task (never in a request handler), through the router
(get_llm("lead_stage_classify"), NVIDIA openai/gpt-oss-20b with the Gemini fallback). Prompt key
"lead_autopilot_classify" in core/prompt_versions.py.

The model reads the lead's facts, its recent messages and calls -- each tagged with a reference like [m:<id>] or
[c:<id>] -- and answers with one decision (lost | qualified | booked | none), a lost reason from the fixed taxonomy, a
confidence and evidence: references + the exact words. Evidence is checked against what was actually sent: a reference
that was not in the context, or a quote that is not in that message/call, is dropped. A decision with no valid evidence
is never applied automatically (it can still be a suggestion), and "booked" is never applied by the AI at all -- a Sold
lead needs a real booking.

Malformed output (not JSON, truncated, unknown decision) means "no decision": nothing moves.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.services.ai_actionable import LOST_REASONS
from app.services.lead_autopilot_rules import Decision, StageMap

log = structlog.get_logger()

PROMPT_KEY = "lead_autopilot_classify"
TASK_KEY = "lead_stage_classify"
DECISIONS = ("lost", "qualified", "booked", "none")
_MAX_MESSAGES = 25
_CHAR_BUDGET = 6000

SYSTEM_PROMPT = """You are the sales-pipeline assistant of a luxury hospitality business in India (caravan and villa stays).
Decide whether this lead's stage should change, using ONLY the conversation and call notes given. Each message or call
is tagged with a reference like [m:abc] or [c:abc]. Each message also names who wrote it: [guest] is the guest;
[us: team member], [us: AI assistant] and [us: automated message] are what we sent; [us: campaign broadcast] is a marketing
message we sent to many guests at once. Only [guest] lines show what the guest wants or declined; a guest not answering a
campaign broadcast or an automated message is not a decline, and our own words are never the guest's evidence.

Respond with ONLY a JSON object (no markdown fences, no other text):
{
  "decision": "<one of: lost | qualified | booked | none>",
  "lost_reason": "<only when decision is lost, one of: price | dates | no_response | booked_elsewhere | not_suitable | other>",
  "confidence": <0.0-1.0, how sure you are>,
  "reason": "<one plain sentence for the sales team>",
  "evidence": [{"ref": "<a reference from the data, e.g. m:abc>", "quote": "<the guest's or agent's EXACT words from that message/call>"}]
}

Meaning of each decision:
- lost: the guest clearly will not book with us now (said no, booked elsewhere, cancelled the trip, the price is a firm
  no after an offer, the dates do not work and they will not move them). An objection that is still being negotiated
  ("bit expensive, any discount?") is NOT lost.
- qualified: a real prospect -- they gave a phone number AND a concrete requirement (dates, route, group size) and are
  still engaged.
- booked: they confirmed a booking or a payment in the conversation.
- none: anything else, or when unsure. Prefer none over guessing.

Rules: quote words exactly as written (any language); never invent a reference; at most 3 evidence items; a decision
without evidence must be "none"."""


def _snippet(text: Optional[str], limit: int = 300) -> str:
    """Whitespace-collapsed and PII-redacted (phones, emails, ID numbers never reach the model)."""
    from app.services.transcription_service import redact_pii
    return " ".join(redact_pii(text or "").split())[:limit]


def build_context(db: Session, tenant_id: str, inquiry, stages: StageMap) -> tuple[str, dict[str, str], str]:
    """(prompt text, {ref: source text}, fingerprint of the newest activity)."""
    from sqlalchemy import or_
    from app.models.call import Call
    from app.models.conversation import Conversation, Message
    from app.services.message_author import author

    current = stages.by_id(inquiry.stage_id)
    lines = [
        f"Current stage: {current.label if current else 'unknown'}",
        f"Check-in: {inquiry.check_in or 'not stated'} | Check-out: {inquiry.check_out or 'not stated'}",
        f"Guests: {inquiry.adults or '?'} adults, {inquiry.children or 0} children | Route: {inquiry.route_mentioned or 'not stated'}",
        f"Quoted amount: {inquiry.quoted_amount or 'none'}",
    ]
    index: dict[str, str] = {}

    calls = (db.query(Call).filter_by(tenant_id=tenant_id, guest_id=inquiry.guest_id)
             .order_by(Call.created_at.desc()).limit(3).all())
    for call in reversed(calls):
        ref = f"c:{call.id}"
        insights = call.ai_insights if isinstance(call.ai_insights, dict) else {}
        text = _snippet(" ".join(x for x in (call.ai_summary, call.disposition_note, insights.get("decline_quote")) if x), 500)
        disp = getattr(call.human_disposition or call.ai_disposition, "value", None)
        lines.append(f"[{ref}] call {getattr(call.direction, 'value', call.direction)} "
                     f"{call.created_at.date() if call.created_at else '?'} outcome={disp or 'unknown'}: {text or '(no summary)'}")
        index[ref] = text

    conv_ids = [r[0] for r in db.query(Conversation.id).filter(
        Conversation.tenant_id == tenant_id,
        or_(Conversation.inquiry_id == inquiry.id, Conversation.guest_id == inquiry.guest_id)).all()]
    newest_msg_id = ""
    if conv_ids:
        msgs = (db.query(Message)
                .filter(Message.tenant_id == tenant_id, Message.conversation_id.in_(conv_ids), Message.is_internal.is_(False),
                        or_(Message.is_ai_generated.is_(False), Message.is_ai_generated.is_(None),
                            Message.was_approved.is_(True), Message.sent_autonomously.is_(True)))
                .order_by(Message.created_at.desc()).limit(_MAX_MESSAGES).all())
        newest_msg_id = msgs[0].id if msgs else ""
        kept, budget = [], _CHAR_BUDGET
        for m in msgs:                                       # newest first, so the budget keeps the newest
            if not m.body:
                continue
            ref = f"m:{m.id}"
            body = _snippet(m.body)
            who = author(m).lower().replace("us: ai", "us: AI")             # message_author: never a bare [outbound]
            line = f"[{ref}] [{who}] {m.created_at.date() if m.created_at else '?'}: {body}"
            if budget - len(line) < 0 and kept:
                break
            budget -= len(line)
            kept.append(line)
            index[ref] = body
        lines.extend(reversed(kept))
    fingerprint = f"{inquiry.stage_id}:{newest_msg_id}:{calls[0].id if calls else ''}"
    return "\n".join(lines), index, fingerprint


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


def parse(raw: str) -> Optional[dict]:
    text = re.sub(r"<think>.*?</think>", "", (raw or "").strip(), flags=re.DOTALL).strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.startswith("json") else text
    try:
        data = json.loads(text.strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("decision") not in DECISIONS:
        return None
    conf = data.get("confidence")
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = 0.0
    data["confidence"] = min(max(conf, 0.0), 1.0)
    return data


def valid_evidence(evidence, index: dict[str, str]) -> list[dict]:
    """Keep only references that were in the context and quotes that really appear in them."""
    out = []
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        ref, quote = str(item.get("ref") or "").strip().strip("[]"), str(item.get("quote") or "").strip()
        if ref not in index or not quote or _norm(quote) not in _norm(index[ref]):
            continue
        kind, _, ident = ref.partition(":")
        out.append({"kind": "message" if kind == "m" else "call", "id": ident, "quote": quote[:200]})
    return out[:3]


def to_decision(data: dict, index: dict[str, str], stages: StageMap, model: Optional[str]) -> Optional[Decision]:
    from app.core.prompt_versions import get_version

    decision = data["decision"]
    evidence = valid_evidence(data.get("evidence"), index)
    target = {"lost": stages.lost, "qualified": stages.qualified, "booked": stages.won}.get(decision)
    if target is None:
        return None
    lost_reason = None
    if decision == "lost":
        lost_reason = data.get("lost_reason") if data.get("lost_reason") in LOST_REASONS else "other"
    reason = _snippet(data.get("reason"), 240) or f"The AI read this lead as {decision}"
    return Decision(
        to_stage=target, rule="ai_classifier", source="ai", reason=reason, lost_reason=lost_reason,
        confidence=round(data["confidence"], 2), evidence=evidence,
        prompt_version=get_version(PROMPT_KEY), model=model,
        # No evidence = never automatic. "booked" = never automatic: a Sold lead needs a real booking.
        apply_allowed=bool(evidence) and decision != "booked",
    )


def classify(db: Session, tenant_id: str, inquiry, stages: StageMap) -> Optional[Decision]:
    """One LLM call. Returns None on no decision, unusable output or a provider error (logged, never raised)."""
    from app.adapters.llm import get_llm
    from app.core.prompt_versions import stamp

    context, index, _ = build_context(db, tenant_id, inquiry, stages)
    if not index:
        return None                                        # nothing said yet: nothing to read
    try:
        adapter = get_llm(TASK_KEY, tenant_id=tenant_id)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(adapter.complete(
                system_prompt=SYSTEM_PROMPT,
                user_message=f"Lead data:\n{context}\n\nReturn the JSON object.",
                max_tokens=1200,
            ))
        finally:
            loop.close()
    except Exception as exc:
        log.warning("lead_autopilot_ai_failed", inquiry_id=inquiry.id, tenant_id=tenant_id, error=str(exc)[:300])
        return None
    data = parse(result.get("content") or "")
    if data is None:
        log.warning("lead_autopilot_ai_unparseable", inquiry_id=inquiry.id, tenant_id=tenant_id)
        return None
    log.info("lead_autopilot_ai_done", inquiry_id=inquiry.id, decision=data["decision"], confidence=data["confidence"],
             **stamp(PROMPT_KEY, model=result.get("model")))
    if data["decision"] == "none":
        return None
    return to_decision(data, index, stages, result.get("model"))
