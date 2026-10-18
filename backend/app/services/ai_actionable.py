"""The actionable block every AI read of a lead returns (call wrap-up v5, lead summary v8, daily briefing v2).

Owner ask (Ratha, Oct 2026): "the AI analysis is not actionable enough". Each analysis now ends in the same shape:

    next_best_action   ONE action with an owner, a channel and a deadline
                       ("Call Kiran today before 6 PM: confirm 24-25 Oct, offer KRS as fallback")
    blocking_objection what stops the guest from booking + a suggested counter
    missed_revenue     flags; a rupee estimate only when a real figure was said (grounded), never a guess
    temperature        hot | warm | cold, with the reason
    haip_updates       what staff should update in HAIP (field, value, why)

The model writes free text; this module is the one place that decides what is kept, so a malformed or half-filled answer
degrades to empty fields instead of a crash or a made-up number. Fields are added, never renamed: older readers keep
working on the old keys.
"""
from __future__ import annotations

from typing import Any, Optional

CHANNELS = ("call", "whatsapp", "instagram", "email", "in_person", "internal")
TEMPERATURES = ("hot", "warm", "cold")
LOST_REASONS = ("price", "dates", "no_response", "booked_elsewhere", "not_suitable", "other")
CALL_OUTCOMES = ("booked", "declined", "negotiating", "callback", "undecided", "no_conversation")

PROMPT_SPEC = """
  "next_best_action": {
    "action": "<ONE concrete step written as an instruction, naming the guest and the specifics, e.g. 'Call Kiran: confirm 24-25 Oct for 4 adults, offer the Coorg route as fallback'>",
    "owner": "<who does it: the assigned agent's name if known, else a role: agent | manager | owner>",
    "channel": "<one of: call | whatsapp | instagram | email | in_person | internal>",
    "deadline": "<when, as plain words tied to the reference date, e.g. 'today before 6 PM', 'tomorrow 11 AM', 'before 20 Oct'>",
    "why": "<one short reason grounded in the data>"
  },
  "blocking_objection": {"objection": "<what stops this guest from booking, in their terms>", "counter": "<a suggested, honest reply or offer the agent can use>"} or null,
  "missed_revenue": [{"kind": "<e.g. upsell, extra_night, add_on, lost_booking, slow_reply>", "what": "<one sentence>", "est_inr": <number ONLY if an exact figure was stated in the data, else null>, "grounded": <true only when est_inr comes from a figure stated in the data>, "evidence": "<the exact words it rests on>"}],
  "temperature": {"value": "<hot | warm | cold>", "reason": "<one short reason grounded in the data>"},
  "haip_updates": [{"field": "<what to update in HAIP, e.g. check_in, adults, stage, lost_reason, follow_up, notes>", "value": "<new value>", "why": "<short reason>"}]"""

PROMPT_RULES = """Rules for the actionable fields:
- next_best_action is ONE action, never a list. It must say who, how (channel) and by when. If nothing is due, say so
  ("No action: booking confirmed and paid") with channel "internal".
- Never invent a rupee figure. est_inr is null unless the exact amount was stated in the data; then grounded is true.
- haip_updates only lists fields whose correct value is stated in the data and differs from what HAIP shows.
- Ground every reason in what is actually in the data; never invent facts."""


def _text(value: Any, limit: int) -> Optional[str]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] if value else None


def _choice(value: Any, allowed: tuple[str, ...]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    norm = value.strip().lower().replace("-", "_").replace(" ", "_")
    return norm if norm in allowed else None


def _amount(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("₹", "").strip()
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, (int, float)) and 0 < value < 100_000_000:
        return float(value)
    return None


def clean_next_action(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        text = _text(raw, 300)
        return {"action": text, "owner": None, "channel": None, "deadline": None, "why": None} if text else None
    action = _text(raw.get("action"), 300)
    if not action:
        return None
    return {
        "action": action,
        "owner": _text(raw.get("owner"), 60),
        "channel": _choice(raw.get("channel"), CHANNELS),
        "deadline": _text(raw.get("deadline"), 60),
        "why": _text(raw.get("why"), 200),
    }


def clean_objection(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    objection = _text(raw.get("objection"), 200)
    if not objection:
        return None
    return {"objection": objection, "counter": _text(raw.get("counter"), 300)}


def clean_missed_revenue(raw: Any) -> list[dict]:
    out: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        what = _text(item.get("what"), 200) or _text(item.get("kind"), 60)
        if not what:
            continue
        evidence = _text(item.get("evidence"), 200)
        amount = _amount(item.get("est_inr", item.get("est_value")))
        grounded = item.get("grounded") is True and amount is not None and bool(evidence)
        out.append({
            "kind": _text(item.get("kind"), 40) or "other",
            "what": what,
            # An estimate nobody can trace to a stated figure is a guess: dropped, the flag itself stays.
            "est_inr": amount if grounded else None,
            "grounded": grounded,
            "evidence": evidence,
        })
    return out[:4]


def clean_temperature(raw: Any) -> Optional[dict]:
    if isinstance(raw, str):
        value = _choice(raw, TEMPERATURES)
        return {"value": value, "reason": None} if value else None
    if not isinstance(raw, dict):
        return None
    value = _choice(raw.get("value"), TEMPERATURES)
    if not value:
        return None
    return {"value": value, "reason": _text(raw.get("reason"), 200)}


def clean_updates(raw: Any) -> list[dict]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        field = _text(item.get("field"), 40)
        value = _text(item.get("value"), 120)
        if field and value:
            out.append({"field": field, "value": value, "why": _text(item.get("why"), 160)})
    return out[:5]


def clean_actionable(raw: Any) -> dict:
    """Normalise the five actionable fields. Always returns every key (None / [] when absent or malformed)."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "next_best_action": clean_next_action(raw.get("next_best_action")),
        "blocking_objection": clean_objection(raw.get("blocking_objection")),
        "missed_revenue": clean_missed_revenue(raw.get("missed_revenue")),
        "temperature": clean_temperature(raw.get("temperature")),
        "haip_updates": clean_updates(raw.get("haip_updates")),
    }


def next_action_text(block: Optional[dict]) -> Optional[str]:
    """One line for the old free-text next_action fields: "Call Kiran ... (call, today before 6 PM)"."""
    if not block or not block.get("action"):
        return None
    extra = ", ".join(x for x in (block.get("channel"), block.get("deadline")) if x)
    return f"{block['action']} ({extra})" if extra else block["action"]


def clean_call_insights(raw: Any) -> Optional[dict]:
    """Wrap-up v5 output -> calls.ai_insights. None when the model gave nothing usable."""
    if not isinstance(raw, dict):
        return None
    out = clean_actionable(raw)
    out["outcome"] = _choice(raw.get("outcome"), CALL_OUTCOMES)
    out["decline_reason"] = _choice(raw.get("decline_reason"), LOST_REASONS) if out["outcome"] == "declined" else None
    out["decline_quote"] = _text(raw.get("decline_quote"), 240) if out["outcome"] == "declined" else None
    conf = raw.get("confidence")
    out["confidence"] = round(float(conf), 2) if isinstance(conf, (int, float)) and not isinstance(conf, bool) and 0 <= conf <= 1 else None
    if not any(out.get(k) for k in ("next_best_action", "blocking_objection", "missed_revenue", "temperature", "haip_updates", "outcome")):
        return None
    return out
