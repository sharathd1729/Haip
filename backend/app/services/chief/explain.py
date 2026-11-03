"""Plain-words explanations for the AI Executive's findings (router ``chief_explain``, prompt ``chief-explain-v1``).

Code already decided each finding and its numbers; the model only says why it matters and the next step, in two short
sentences. Only called from Celery (chief.explain_tenant), never in a request handler. Every sentence is number-grounded
against that finding's own ``numbers`` (analyst/grounding.py): a sentence with any other number is dropped, and a finding
with nothing left keeps the rule's own text. A finding is re-explained when its numbers change, at most every 6 hours.
The kill switch (``brand_config.chief.paused``) stops these calls.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.orm import Session

from app.core.prompt_versions import PROMPT_VERSIONS
from app.models.insight import Insight
from app.schemas.chief import ROLE_LABELS
from app.services.analyst import grounding
from app.services.chief import catalogue
from app.services.chief import settings as chief_settings

log = structlog.get_logger()

PROMPT_KEY = "chief_explain"
TIMEOUT_S = 60
BATCH = 10
REFRESH = timedelta(hours=6)

SYSTEM_PROMPT = (
    "You are the AI Executive of an Indian hospitality business, writing for its founder. You get FINDINGS as JSON: each was "
    "detected by code, with its role, title, the rule's own text, its numbers and a suggested next step. For each finding "
    "write `why` (one sentence: why it matters to the business now) and `next_step` (one sentence: the concrete thing to do "
    "today). Rules: use ONLY numbers from that finding's numbers, copied exactly; never compute, add up or invent a number; "
    "never state a price, discount or amount of money; never name a guest or staff member; do not promise anything to a "
    "guest. Plain, calm English, no exclamation marks.\n"
    'Reply with ONE JSON object only: {"items": [{"id": str, "why": str, "next_step": str}]}'
)


def numbers_sha(numbers: dict | None) -> str:
    return hashlib.sha256(json.dumps(numbers or {}, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def due(row: Insight, now: datetime) -> bool:
    exp = row.explanation if isinstance(row.explanation, dict) else None
    if not exp:
        return True
    if exp.get("numbers_sha") == numbers_sha(row.numbers):
        return False
    at = exp.get("at")
    return not at or now - _aware(datetime.fromisoformat(at)) >= REFRESH


def pending(db: Session, tenant_id: str, now: datetime) -> list[Insight]:
    rows = (
        db.query(Insight)
        .filter(
            Insight.tenant_id == tenant_id,
            Insight.role.isnot(None),
            Insight.is_dismissed.is_(False),
            Insight.is_auto_resolved.is_(False),
        )
        .order_by(Insight.updated_at.desc())
        .limit(100)
        .all()
    )
    return [r for r in rows if due(r, now)][:BATCH]


def _payload(rows: list[Insight]) -> list[dict]:
    out = []
    for r in rows:
        det = catalogue.BY_CODE.get(r.category_code)
        out.append(
            {
                "id": r.id,
                "role": ROLE_LABELS.get(r.role or "", r.role),
                "title": r.title,
                "rule_text": r.body,
                "numbers": r.numbers or {},
                "suggested_next_step": det.next_step if det else "",
            }
        )
    return out


def _parse(resp: dict) -> list[dict]:
    raw = resp.get("tool_use") if isinstance(resp.get("tool_use"), dict) else None
    if raw is None:
        content = (resp.get("content") or "").strip()
        s, e = content.find("{"), content.rfind("}") + 1
        if s < 0 or e <= s:
            return []
        try:
            raw = json.loads(content[s:e])
        except ValueError:
            return []
    items = raw.get("items") if isinstance(raw, dict) else None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


async def _complete(rows: list[Insight]) -> dict:
    from app.adapters.llm import get_llm

    llm = get_llm(PROMPT_KEY)
    return await asyncio.wait_for(
        llm.complete(
            system_prompt=SYSTEM_PROMPT, user_message=json.dumps(_payload(rows), default=str), max_tokens=1200
        ),
        timeout=TIMEOUT_S,
    )


def explain_tenant(db: Session, tenant, now: datetime | None = None) -> dict:
    """Explain the findings that need it. Never raises on a model failure: those findings keep the rule's text and are
    retried after REFRESH. Returns counts; the caller commits."""
    now = now or datetime.now(UTC)
    cfg = chief_settings.get(tenant)
    if not cfg.enabled or cfg.paused:
        return {"explained": 0, "skipped": "paused" if cfg.enabled else "off"}
    rows = pending(db, tenant.id, now)
    if not rows:
        return {"explained": 0}
    version = PROMPT_VERSIONS[PROMPT_KEY]
    try:
        answers = {i.get("id"): i for i in _parse(asyncio.run(_complete(rows)))}
    except Exception as exc:  # noqa: BLE001 -- provider error / timeout: the rule's own text stands
        log.warning("chief_explain_failed", tenant_id=tenant.id, error=type(exc).__name__, prompt_version=version)
        answers = {}
    explained, dropped = 0, []
    for r in rows:
        a = answers.get(r.id) or {}
        allowed = grounding.allowed_numbers(r.numbers or {})
        why = grounding.clean_text(str(a.get("why") or ""), allowed, "why", dropped)[:400]
        nxt = grounding.clean_text(str(a.get("next_step") or ""), allowed, "next_step", dropped)[:400]
        source = "ai" if why and nxt else "rule"
        r.explanation = {
            "why": why if source == "ai" else None,
            "next_step": nxt if source == "ai" else None,
            "source": source,
            "numbers_sha": numbers_sha(r.numbers),
            "prompt_version": version,
            "at": now.isoformat(),
        }
        explained += source == "ai"
    if dropped:
        log.info("chief_explain_dropped", tenant_id=tenant.id, dropped=len(dropped), prompt_version=version)
    return {"explained": explained, "fallback": len(rows) - explained, "dropped": len(dropped)}
