"""Number grounding for the analyst's text (the same idea as assessment_narrative.check_numbers and marketing_lint): every number a
sentence states must exist in the facts. A sentence that fails is DROPPED and recorded; it is never shown.

Allowed forms of a fact number: as written (commas removed), rounded to a whole number or one decimal, and a 0-1 share written as
a percentage (0.4235 -> 42 / 42.4). Numbers inside dates in the facts (2026-10-19 -> 2026, 10, 19) are allowed too, and the
same for integers the period itself names (its length in days). A rupee amount is compared without its commas.
"""
from __future__ import annotations

import re
from typing import Iterable

_NUM = re.compile(r"(?<![\w.])[0-9][0-9,]*(?:\.[0-9]+)?")
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _forms(value: float) -> set[str]:
    out = {f"{value:g}", str(int(round(value)))}
    out.add(f"{round(value, 1):g}")
    if 0 <= value <= 1:
        out |= {str(int(round(value * 100))), f"{round(value * 100, 1):g}"}
    return out


def allowed_numbers(facts) -> set[str]:
    out: set[str] = set()

    def walk(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            out.update(_forms(float(v)))
        elif isinstance(v, str):
            m = _DATE.match(v)
            if m:
                out.update({str(int(g)) for g in m.groups()} | set(m.groups()))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
    walk(facts)
    return out


def numbers_in(text: str) -> list[str]:
    return [m.group(0).replace(",", "").rstrip(".") for m in _NUM.finditer(text or "")]


def unsupported(text: str, allowed: set[str]) -> list[str]:
    bad = []
    for n in numbers_in(text):
        norm = n.lstrip("0") or "0"
        if n in allowed or norm in allowed:
            continue
        try:
            if f"{float(n):g}" in allowed:
                continue
        except ValueError:
            pass
        bad.append(n)
    return bad


def clean_text(text: str, allowed: set[str], field: str, dropped: list[dict]) -> str:
    """Keep only the sentences whose numbers are all grounded."""
    kept = []
    for sentence in _SENTENCE.split((text or "").strip()):
        if not sentence:
            continue
        bad = unsupported(sentence, allowed)
        if bad:
            dropped.append({"field": field, "sentence": sentence[:300], "numbers": bad})
        else:
            kept.append(sentence)
    return " ".join(kept)


def clean_list(items: Iterable[str], allowed: set[str], field: str, dropped: list[dict]) -> list[str]:
    out = []
    for item in items:
        t = clean_text(item, allowed, field, dropped)
        if t:
            out.append(t)
    return out
