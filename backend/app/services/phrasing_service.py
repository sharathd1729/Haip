"""LLM-generated alternate phrasings for knowledge base entries.

A single stored question only covers so much. Measured against the live
embedding model, "Do you allow pets?" reliably catches "are animals
allowed" and "pet friendly?" but misses "is it ok if we get our labrador".
Rather than asking the owner to hand-write every variation -- the manual
work this feature exists to remove -- the variations are generated once per
entry and embedded individually.

Routed through `quick_classify` (meta/llama-3.1-8b): this is short-form
rewriting, not reasoning, and it runs on every knowledge entry.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

import structlog

from app.adapters.llm import get_llm

log = structlog.get_logger()

MAX_PHRASINGS = 8
# Long inputs produce essays rather than questions, and the embedding model
# truncates at 512 tokens anyway.
_MAX_INPUT_CHARS = 1200

PHRASING_TOOL = {
    "name": "generate_phrasings",
    "description": "Produce realistic ways a hotel/villa guest might ask this question over WhatsApp or Instagram DM",
    "input_schema": {
        "type": "object",
        "properties": {
            "phrasings": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Short, natural guest messages that this answer would resolve. "
                    "Vary vocabulary and formality; include at least one casual/abbreviated form."
                ),
            }
        },
        "required": ["phrasings"],
    },
}

# Plain-text output rather than tool-calling. meta/llama-3.1-8b emits a
# usable tool call for this maybe 2 times in 5: it returns the call as text,
# echoes the schema wrapper back, alternates between single and double
# quotes, and frequently truncates mid-JSON. A newline-separated list is
# something an 8B model does reliably, and parsing lines cannot fail the way
# parsing a half-written JSON object does.
_SYSTEM = """You write the different ways a real guest might ask a question, so a hospitality assistant can recognise it.

Output rules — follow exactly:
- Output ONLY the questions, one per line.
- No numbering, no bullets, no quotes, no JSON, no explanation, no blank lines.
- Exactly {n} lines.

Content rules:
- EVERY line must be fully answerable by the answer text you are given. If the answer is about amenities, do not write questions about pets, prices, cancellations or arrival times. Staying on topic matters more than variety.
- Write what a GUEST types, never the answer and never a reply.
- Under 12 words each. WhatsApp register: lowercase, abbreviations and missing punctuation are realistic.
- Vary the vocabulary. For pets include specific animals and breeds (can i bring my dog / travelling with a labrador). For timing include indirect forms (what time can we arrive).
- Mix formal and casual, long and terse (pet friendly?).
- Do not repeat the same sentence with trivial word swaps.
- Never invent facts, prices or policies. Questions only."""


def _clean(items, *, exclude: Optional[str]) -> list[str]:
    out, seen = [], set()
    exclude_norm = _norm(exclude or "")
    for raw in items or []:
        s = re.sub(r"\s+", " ", str(raw or "")).strip().strip('"').strip()
        if not s or len(s) > 120:
            continue
        n = _norm(s)
        # Skip anything that is just the original question again, and any
        # near-duplicate of an earlier suggestion.
        if not n or n == exclude_norm or n in seen:
            continue
        seen.add(n)
        out.append(s)
        if len(out) >= MAX_PHRASINGS:
            break
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def _find_phrasings(node, depth: int = 0):
    """Dig a phrasings list out of whatever shape came back.

    meta/llama-3.1-8b does not reliably emit a real tool call for this. In
    practice it returns the call as plain text in `content`, echoes the
    schema wrapper back ({"parameters": {"properties": {"phrasings": ...}}}),
    and JSON-encodes the array into a string. The generated phrasings
    themselves are good, so the envelope is parsed leniently rather than
    escalating every knowledge entry to a larger model.
    """
    if depth > 6 or node is None:
        return None

    if isinstance(node, str):
        s = node.strip()
        if s.startswith("[") or s.startswith("{"):
            try:
                import json as _json
                return _find_phrasings(_json.loads(s), depth + 1)
            except Exception:
                return None
        return None

    if isinstance(node, list):
        # A list of plain strings is the answer itself.
        if node and all(isinstance(x, str) for x in node):
            return node
        for item in node:
            found = _find_phrasings(item, depth + 1)
            if found:
                return found
        return None

    if isinstance(node, dict):
        if "phrasings" in node:
            found = _find_phrasings(node["phrasings"], depth + 1)
            if found:
                return found
        for key in ("parameters", "properties", "input", "arguments", "tool_use"):
            if key in node:
                found = _find_phrasings(node[key], depth + 1)
                if found:
                    return found
        for value in node.values():
            found = _find_phrasings(value, depth + 1)
            if found:
                return found
    return None


# Keys from the tool schema itself. The model echoes the wrapper back, so a
# naive "grab every quoted string" fallback happily returns these as if they
# were guest questions.
_SCHEMA_TOKENS = {
    "name", "generate_phrasings", "parameters", "properties", "phrasings",
    "type", "object", "array", "items", "string", "description", "required",
    "input_schema",
}


def _extract_lines(text: str) -> list[str]:
    """Parse the expected shape: one guest question per line.

    Tolerates the model adding numbering, bullets or a preamble line anyway.
    """
    if not text or "{" in text[:40]:
        # Looks like a JSON blob rather than a list; let the JSON extractors
        # handle it.
        return []
    out = []
    for raw in text.splitlines():
        s = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw).strip()
        s = s.strip('"').strip("'").strip()
        if not (3 <= len(s) <= 120):
            continue
        # Drop conversational preambles ("Here are 6 ways guests might ask:")
        if s.endswith(":") or _norm(s) in _SCHEMA_TOKENS:
            continue
        if re.match(r"^(here are|sure|certainly|of course)\b", s, re.IGNORECASE):
            continue
        out.append(s)
    return out


def _extract_after_key(text: str) -> list[str]:
    """Pull the phrasings array straight out of the raw text.

    The 8B model's replies are frequently truncated mid-structure (observed:
    a 201-character response missing its final brace), so anything that
    requires the whole payload to be valid JSON fails on a response whose
    useful content is entirely intact. This reads from the "phrasings" key
    onwards and takes the quoted items, which survives truncation.
    """
    if not text:
        return []
    idx = text.find('"phrasings"')
    if idx == -1:
        return []
    tail = text[idx + len('"phrasings"'):]
    # The array is often JSON-encoded into a string, so quotes arrive escaped.
    tail = tail.replace('\\"', '"')
    # ...and the whole array then sits *inside* a pair of double quotes. Left
    # wrapped, the double-quote branch below matches the entire serialised
    # array as a single "phrasing". Unwrap it so the items are visible.
    tail = re.sub(r'"\s*(\[.*?)(?:\]\s*")?$', r"\1", tail, flags=re.S)
    # The model is inconsistent about quoting: the same prompt yields
    # ["can i bring my dog", ...] on one call and ['can i bring my dog', ...]
    # on the next. Matching only double quotes silently returned nothing for
    # roughly half of all entries.
    items = re.findall(r'"([^"]{3,120})"' + r"|'([^']{3,120})'", tail)
    flat = [d or s for d, s in items]
    return [s for s in flat if s and _norm(s) not in _SCHEMA_TOKENS]


def _extract_from_text(text: str) -> list[str]:
    """Last resort: pull quoted strings or bullet lines out of prose."""
    if not text:
        return []
    quoted = [
        s for s in re.findall(r'"([^"\n]{3,120})"', text.replace('\\"', '"'))
        if _norm(s) not in _SCHEMA_TOKENS
    ]
    if len(quoted) >= 2:
        return quoted
    lines = []
    for raw in text.splitlines():
        s = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw).strip().strip('"').strip(",")
        if 3 <= len(s) <= 120 and not s.endswith(":") and "{" not in s:
            lines.append(s)
    return lines


async def generate_phrasings(question: Optional[str], content: str, n: int = 6) -> list[str]:
    """Return alternate guest phrasings for an entry. [] on any failure --
    phrasings are an enhancement, so a generation outage must leave the
    entry usable with its original question rather than blocking it."""
    base = (question or "").strip() or (content or "").strip()
    if not base:
        return []

    n = max(1, min(int(n or 6), MAX_PHRASINGS))
    user = (
        f"Question guests ask: {(question or '(not given)').strip()}\n"
        f"The answer they would get: {(content or '').strip()[:_MAX_INPUT_CHARS]}"
    )

    try:
        adapter = get_llm("quick_classify")
        result = await adapter.complete(
            system_prompt=_SYSTEM.replace("{n}", str(n)),
            user_message=user,
            max_tokens=400,
        )
    except Exception as exc:
        log.warning("phrasing_generation_failed", error=str(exc))
        return []

    content = result.get("content") or ""
    # Plain lines are the expected shape now; the JSON extractors remain as
    # a safety net for the occasional call that still answers with a blob.
    phrasings = (
        _extract_lines(content)
        or _find_phrasings(result.get("tool_use"))
        or _find_phrasings(content)
        or _extract_after_key(content)
        or _extract_from_text(content)
    )

    if not phrasings:
        log.warning("phrasing_generation_unparsable", sample=(result.get("content") or "")[:200])
        return []

    return _clean(phrasings, exclude=question)


def generate_phrasings_sync(question: Optional[str], content: str, n: int = 6) -> list[str]:
    return asyncio.run(generate_phrasings(question, content, n))
