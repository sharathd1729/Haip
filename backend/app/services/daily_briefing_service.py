"""Today (Worklist) — AI Daily Briefing.

One short narrative + a handful of flags summarizing *patterns across* a
tenant's whole current worklist snapshot (repeated questions worth one
saved reply, a missed-call time cluster, etc.) — distinct from the
per-lead `ai_summary` already on each row. Cached ~30 min, never
regenerated inline in a request handler (same debounce discipline as
Leads360's `generate_ai_summary`).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.core.cache import cache_key, get_cached, set_cached
from app.services import worklist_service
from app.services.ai_actionable import clean_next_action

log = structlog.get_logger()

CACHE_TTL = 35 * 60  # beat regenerates every 30 min; 5 min grace before a stale read

SYSTEM_PROMPT = """You are a hospitality operations assistant. You are given
a snapshot of everyone a sales/support team currently needs to contact
(guests waiting on a reply, missed calls, newly shared contact details,
new messages, overdue follow-ups) plus their timestamps and message text.

Respond with ONLY a JSON object (no markdown fences, no other text):

{
  "narrative": "<2-3 sentences: the most useful pattern(s) across everyone listed -- repeated questions, a time cluster of missed calls, an unusual volume spike. Reference real counts/names from the data. If nothing patterned stands out, say so plainly.>",
  "flags": [
    {"type": "quick_win", "text": "<one specific, actionable observation, or omit this flag type entirely if none applies>"},
    {"type": "coverage_gap", "text": "<one specific gap, e.g. a time window with several missed calls, or omit if none applies>"}
  ],
  "actions": [
    {"lead": "<the guest's name exactly as listed>", "action": "<ONE concrete step, e.g. 'Call back about the missed call and confirm 24-25 Oct'>", "owner": "<the assigned agent if listed, else 'team'>", "channel": "<call | whatsapp | instagram | email>", "deadline": "<e.g. 'within 1 hour', 'today before 6 PM'>", "why": "<short reason from the data>"}
  ]
}

"actions" lists the (at most 3) most valuable next steps across the whole snapshot, most urgent first -- people waiting
longest, missed calls, overdue follow-ups. Each names a real listed guest, one channel and a deadline. Omit "actions"
(or use []) when nothing is outstanding.

Only state what is directly supported by the data given to you -- never
invent a name, count, or pattern that isn't there. Omit a flag entirely
rather than inventing one to fill it. At most 3 flags total. Output only
the JSON object."""


def _cache_key(tenant_id: str) -> str:
    return cache_key("daily_briefing", tenant_id)


def get_cached_briefing(tenant_id: str) -> Optional[dict]:
    return get_cached(_cache_key(tenant_id))


def _row_line(row: dict) -> str:
    lead = row.get("lead") or {}
    name = lead.get("name") or "Unnamed lead"
    text = (row.get("last_message") or row.get("body") or row.get("title") or "").strip()
    when = row.get("last_message_at") or row.get("received_at") or row.get("missed_at") or row.get("shared_at") or row.get("due_date") or ""
    line = f"- {name}"
    if when:
        line += f" ({when})"
    if text:
        line += f': "{text[:140]}"'
    return line


def _build_context(snapshot: dict) -> str:
    lines = [f"Time window: last {snapshot.get('window_hours') or 'all'} hours" if snapshot.get("window_hours") else "Time window: all time"]
    section_labels = {
        "awaiting_reply": "Waiting on us (they messaged last, nobody replied)",
        "missed_calls": "Missed calls",
        "shared_details": "Shared contact details",
        "new_dms": "New messages",
        "overdue_followups": "Overdue follow-ups",
    }
    for key, label in section_labels.items():
        rows = snapshot.get(key) or []
        count = snapshot.get("counts", {}).get(key, len(rows))
        lines.append(f"\n{label}: {count} total")
        for row in rows[:8]:
            lines.append(_row_line(row))
    return "\n".join(lines)


def _parse_response(raw: str) -> Optional[dict]:
    text = raw.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    narrative = parsed.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        return None
    flags = []
    for f in (parsed.get("flags") or [])[:3]:
        if isinstance(f, dict) and isinstance(f.get("text"), str) and f["text"].strip():
            flags.append({
                "type": f.get("type") if f.get("type") in ("quick_win", "coverage_gap", "pattern") else "pattern",
                "text": f["text"].strip(),
            })
    actions = []
    for a in (parsed.get("actions") or [])[:3] if isinstance(parsed.get("actions"), list) else []:
        nba = clean_next_action(a)
        lead = a.get("lead") if isinstance(a, dict) and isinstance(a.get("lead"), str) else None
        if nba and lead and lead.strip():
            actions.append({"lead": lead.strip()[:80], **nba})
    return {"narrative": narrative.strip(), "flags": flags, "actions": actions}


def generate_briefing(db: Session, tenant_id: str) -> Optional[dict]:
    """Build, cache, and return the briefing dict -- or None on any failure
    (LLM error, unparseable output, nothing to summarize). Never raises;
    callers treat None as "not available yet", not an error to surface."""
    snapshot = worklist_service.build_worklist(db, tenant_id, hours=24)
    total = sum(snapshot.get("counts", {}).values())

    if total == 0:
        result = {"narrative": "Nothing outstanding right now — all caught up.", "flags": [], "actions": []}
    else:
        try:
            from app.adapters.llm import get_llm
            from app.core.prompt_versions import stamp

            context = _build_context(snapshot)
            adapter = get_llm("daily_briefing")
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                raw = loop.run_until_complete(
                    adapter.complete(
                        system_prompt=SYSTEM_PROMPT,
                        user_message=f"Worklist snapshot:\n{context}\n\nGenerate the JSON response.",
                        # No explicit model= -- let it use get_llm("daily_briefing")'s
                        # routed default. Used to hardcode the dead
                        # nvidia/llama-3.3-nemotron-super-49b-v1.5 (EOL
                        # 2026-08-26), which silently overrode the routing
                        # table's replacement model via an explicit kwarg.
                        max_tokens=800,
                    )
                )
            finally:
                loop.close()

            text = (raw.get("content") or "").strip()
            parsed = _parse_response(text) if text else None
            if parsed is None:
                log.warning("daily_briefing_unparseable", tenant_id=tenant_id)
                return None
            result = parsed
            log.info("daily_briefing_generated", tenant_id=tenant_id, **stamp("daily_briefing", model=raw.get("model")))
        except Exception as exc:
            log.warning("daily_briefing_failed", tenant_id=tenant_id, error=str(exc))
            return None

    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    set_cached(_cache_key(tenant_id), result, ttl=CACHE_TTL)
    return result
