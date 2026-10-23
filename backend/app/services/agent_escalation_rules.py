"""When the AI must ask a person before answering a guest: deterministic rules, evaluated BEFORE anything is sent.

The model never decides whether to escalate. Its own soft ``needs_human`` is recorded for staff but is not a trigger; every
trigger below is code reading the guest's own words, the published business data (sales_gateway flags), the guards the reply
path already ran, and the conversation's history. Each fired rule returns a STABLE reason code (REASONS), stored on the
consult and counted by the scorecard, so renaming one is a data change.

Pure functions over plain data (TurnSignals); the caller (agent_consult_flow) gathers the inputs. No database, no network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

REASONS: dict[str, str] = {
    "quote_refused": "The price engine refused to quote these dates or this trip",
    "no_rate_for_dates": "No published rate covers these dates (peak dates are priced by a person)",
    "b2b_only": "A partner (B2B) rate was asked for",
    "unpublished_data": "The trip uses a package or route that is not published",
    "policy_unconfirmed": "The guest asked about a policy the owner has not confirmed",
    "ungrounded_claim": "The draft states something no record supports",
    "low_confidence": "The AI is not confident in its answer",
    "model_failed": "The AI could not produce an answer",
    "price_unverified": "The draft states a price that is not a published figure",
    "price_handoff": "The guest asked about price; your team shares prices",
    "discount_request": "The guest asked for a discount or a better price",
    "custom_route": "The guest wants a route or place we do not publish",
    "b2b_partner": "Travel agent / partner / B2B enquiry",
    "complaint": "Complaint or unhappy guest",
    "refund": "Refund or billing question",
    "cancellation": "Cancellation request",
    "legal": "Legal wording",
    "safety": "Safety or medical wording",
    "wants_human": "The guest asked to speak to a person",
    "frustrated": "The guest sounds frustrated",
    "repeat_question": "The guest asked the same thing again",
    "unanswered_questions": "Third question the AI could not answer",
    "over_capacity": "More guests than the vehicle takes",
    "prompt_injection": "The message tries to give the AI instructions",
    "escalation_keyword": "A keyword the owner listed",
    "policy_consult": "Your AI policy says a person decides this",
    "collab_request": "Collaboration / barter request: a person says yes or no",
}

_ESCALATION_CATEGORY = {
    "refund_billing": "refund", "cancellation": "cancellation", "complaint": "complaint", "intent": "complaint",
    "review_threat": "complaint", "legal": "legal", "safety_medical": "safety", "human_request": "wants_human",
    "tenant_custom": "escalation_keyword",
}

_DISCOUNT_RE = re.compile(
    r"\b(discount|discounts|discounted|cheaper|concession|offers?|deal|negotiable|negotiate|reduce|reduction|lower (?:the )?price|"
    r"best (?:price|rate)|last price|final price|kam karo|kam kar|kuch kam|thoda kam|less price|price (?:drop|cut))\b",
    re.IGNORECASE)
# The same ask in Hindi / Kannada script (no word boundaries: combining marks break \b in these scripts).
_DISCOUNT_NATIVE_RE = re.compile(r"(छूट|डिस्काउंट|कम कर|कम कीजिए|ರಿಯಾಯಿತಿ|ಡಿಸ್ಕೌಂಟ್|ಕಡಿಮೆ ಮಾಡಿ)")
_B2B_RE = re.compile(
    r"\b(travel agent|travel agency|tour operator|agent rate|b2b|partner rate|partner price|reseller|resell|commission|"
    r"corporate rate|net rate|trade rate|wholesale|dmc|agency rate)\b", re.IGNORECASE)
_CUSTOM_RE = re.compile(r"\b(custom (?:route|trip|itinerary|plan)|customi[sz]e|our own (?:route|itinerary|plan)|plan our own|"
                        r"different route|own route)\b", re.IGNORECASE)
_INJECTION_RE = re.compile(
    r"(ignore (?:all |your |the )?(?:previous|prior|above) (?:instructions|rules)|disregard (?:your|the) (?:rules|instructions)|"
    r"system prompt|you are now|act as (?:an? )?(?:admin|manager|developer)|developer mode|reveal (?:your )?(?:prompt|instructions)|"
    r"jailbreak|the (?:owner|manager) (?:has )?(?:approved|said you can)|new instructions?:)", re.IGNORECASE)
# The AI saying it cannot answer yet. Counted across turns for the "third unanswered question" rule.
DEFERRAL_RE = re.compile(
    r"(let me check|i(?:'ll| will) check|check with (?:our|the) team|team will (?:confirm|share|get back|reach)|get back to you|"
    r"come back to you|someone (?:from our team )?will|our team will|will confirm (?:shortly|soon)|reach out (?:to you )?personally)",
    re.IGNORECASE)
_POLICY_TOPICS = {
    "cancellation": re.compile(r"\b(cancel\w*|refund\w*|reschedul\w*|postpone\w*)\b", re.IGNORECASE),
    "payment": re.compile(r"\b(pay\w*|advance|deposit|instal\w*|upi|card|emi)\b", re.IGNORECASE),
    "stay_rules": re.compile(r"\b(rules?|pets?|smok\w*|alcohol|drinks?|music|check-?in|check-?out|timings?)\b", re.IGNORECASE),
    "reseller": _B2B_RE,
    "discount": _DISCOUNT_RE,
}
_WORD = re.compile(r"[a-z0-9ऀ-ൿ]+", re.IGNORECASE)
_STOP = frozenset("a an the to for of in on at is are am be we i you it this that and or with do does can could would will "
                  "please hi hello hey me my our your what when how much any there".split())


# A message that only acknowledges or closes ("Okay", "thanks", "👍", "okay waiting to hear from you"): no question, nothing new
# to answer. Never a repeated question and never a reason to ask a person (live: a bare "Okay" opened a consult labelled "asked
# the same thing again"). "yes" is left out on purpose: after our question it is an answer.
_ACK_WORDS = frozenset("ok okay okk okkk okie okey k kk sure thanks thank thanku thankyou thx ty tq noted alright fine cool great "
                       "good nice perfect done got".split())
_ACK_FILLER = frozenset("you u so much very lot a will wait waiting we i am be for your reply response hear from to then it "
                        "ji sir maam madam".split())


def is_acknowledgement(text: str) -> bool:
    """True for a burst made only of acknowledgement words (and filler like "waiting to hear from you"), or only emoji."""
    t = (text or "").strip()
    if not t or "?" in t:
        return False
    words = _WORD.findall(t.lower())
    if not words:
        return True                                   # emoji / punctuation only: "👍", "🙏🙏"
    if len(words) > 8:
        return False
    return any(w in _ACK_WORDS for w in words) and all(w in _ACK_WORDS or w in _ACK_FILLER for w in words)


# Words in a "destination" that are not a place ("a wildlife trip near Bangalore"): never a custom route by themselves.
_GENERIC_PLACE = frozenset("trip tour travel nature wildlife beach beaches hill hills mountain mountains forest forests jungle weekend "
                           "getaway somewhere place places near nearby around bangalore bengaluru city drive road outing day days "
                           "night nights camping safari waterfall waterfalls temple temples lake lakes river resort stay village "
                           "south india karnataka state long short overnight one two three".split())


@dataclass
class TurnSignals:
    burst_text: str = ""
    intent: str = "general"
    details: dict = field(default_factory=dict)
    grounded_facts: list = field(default_factory=list)
    reply_text: str = ""
    confidence: float = 0.0
    threshold: float = 0.78
    escalation: Optional[dict] = None
    price_mode: str = "handoff"
    price_leak: Optional[str] = None
    ungrounded: Optional[str] = None
    model_failed: bool = False
    has_phone: bool = False
    sales_owns_price: bool = False
    sales_handoff: Optional[str] = None
    availability_claim: Optional[str] = None     # a sentence saying dates are open (the caller found it)
    # Recent messages, oldest first: {"direction", "body", "ai", "sent", "intent", "human"} -- see agent_consult_flow.history
    history: list = field(default_factory=list)
    # A collaboration / barter request from this guest no person has answered yet (collab_requests.pending).
    collab_request: bool = False


@dataclass
class Verdict:
    reasons: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    def add(self, code: str, detail=None) -> None:
        if code not in REASONS:
            raise ValueError(f"unknown reason code {code}")
        if code not in self.reasons:
            self.reasons.append(code)
        if detail is not None:
            self.evidence.setdefault("detail", {})[code] = detail


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 1}


def similar(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _facts(signals: TurnSignals, tool: str) -> list[dict]:
    return [f for f in signals.grounded_facts if isinstance(f, dict) and f.get("tool") == tool]


def _published_names(signals: TurnSignals) -> set[str]:
    words: set[str] = set()
    for f in _facts(signals, "business_data"):
        body = f.get("result") or {}
        for label in ("destinations", "packages"):
            for row in body.get(label) or []:
                if isinstance(row, dict):
                    words |= _tokens(str(row.get("name") or "")) | _tokens(str(row.get("key") or "").replace("-", " "))
                    for stop in row.get("stops") or []:
                        words |= _tokens(str(stop.get("name") if isinstance(stop, dict) else stop))
    return words


def _gateway(signals: TurnSignals, v: Verdict) -> None:
    """Refused quotes and missing published data for THIS guest's request; policy flags only when the guest asked about it."""
    for f in _facts(signals, "package_quote"):
        for flag in f.get("flags") or []:
            reason = flag.split(":", 1)[1] if flag.startswith("refused:") else None
            if reason == "no_rate_for_dates":
                v.add("no_rate_for_dates", f.get("args"))
            elif reason == "b2b_only":
                v.add("b2b_only")
            elif reason in ("package_not_published", "destination_not_published"):
                v.add("unpublished_data", reason)
            elif reason == "over_capacity":
                v.add("over_capacity", (f.get("result") or {}).get("message"))
            elif reason:
                v.add("quote_refused", reason)
    if signals.sales_handoff:
        v.add("quote_refused", signals.sales_handoff)
    text = signals.burst_text or ""
    for f in _facts(signals, "business_data"):
        for flag in f.get("flags") or []:
            if flag.startswith("policy_unconfirmed:"):
                kind = flag.split(":", 1)[1].split("_policy")[0]
                topic = _POLICY_TOPICS.get(kind) or _POLICY_TOPICS.get(kind.replace("_policy", ""))
                if topic is not None and topic.search(text):
                    v.add("policy_unconfirmed", kind)


def _capacity(signals: TurnSignals, v: Verdict) -> None:
    d = signals.details or {}
    try:
        party = int(d.get("adults") or 0) + int(d.get("children") or 0)
    except (TypeError, ValueError):
        return
    caps = [f.get("max_capacity_note") for f in _facts(signals, "check_availability") if f.get("max_capacity_note")]
    for f in _facts(signals, "check_availability") + _facts(signals, "property_facts"):
        rows = f.get("result") if isinstance(f.get("result"), list) else []
        caps += [r.get("max_adults") for r in rows if isinstance(r, dict) and r.get("max_adults")]
    try:
        biggest = max(int(c) for c in caps) if caps else None
    except (TypeError, ValueError):
        biggest = None
    if party and biggest and party > biggest:
        v.add("over_capacity", {"party": party, "max": biggest})


def _custom_route(signals: TurnSignals, v: Verdict) -> None:
    text = signals.burst_text or ""
    if _CUSTOM_RE.search(text):
        v.add("custom_route", "asked for a custom route")
        return
    place = (signals.details or {}).get("destination")
    names = _published_names(signals)
    words = _tokens(str(place or "")) - _GENERIC_PLACE
    if words and names and not (words & names):
        v.add("custom_route", str(place)[:80])


def _history(signals: TurnSignals, v: Verdict) -> None:
    """Loops: the same question asked again after an AI answer, or a third question the AI could only defer."""
    if is_acknowledgement(signals.burst_text):
        return                                        # "Okay" after three same-intent turns is not the same question again
    since_human = []
    for m in signals.history:
        if m.get("human"):
            since_human = []
        else:
            since_human.append(m)
    ai_sent = [m for m in since_human if m.get("ai") and m.get("direction") == "outbound"]
    answered_inbound = []
    for i, m in enumerate(since_human):
        if m.get("direction") == "inbound" and any(
                x.get("ai") and x.get("direction") == "outbound" and x.get("sent") for x in since_human[i + 1:]):
            answered_inbound.append(m)
    text = signals.burst_text or ""
    if any(similar(text, m.get("body") or "") >= 0.5 for m in answered_inbound):
        v.add("repeat_question", "asked again after an AI answer")
    elif signals.intent not in ("general", None) and \
            sum(1 for m in ai_sent if m.get("sent") and m.get("intent") == signals.intent) >= 2:
        v.add("repeat_question", f"third {signals.intent} turn without a person")
    deferred = sum(1 for m in ai_sent if not m.get("sent") or DEFERRAL_RE.search(m.get("body") or ""))
    current_defers = bool(DEFERRAL_RE.search(signals.reply_text or "")) or bool((signals.details or {}).get("questions"))
    if deferred >= 2 and current_defers:
        v.add("unanswered_questions", deferred + 1)


def evaluate(signals: TurnSignals) -> Verdict:
    """Every trigger that fires for this turn, in a stable order. Empty = the AI may answer on its own."""
    v = Verdict(evidence={"intent": signals.intent, "confidence": round(float(signals.confidence or 0), 3)})
    text = signals.burst_text or ""
    if signals.model_failed:
        v.add("model_failed")
    if signals.escalation:
        v.add(_ESCALATION_CATEGORY.get(signals.escalation.get("category"), "escalation_keyword"), signals.escalation.get("keyword"))
    d = signals.details or {}
    if d.get("wants_human"):
        v.add("wants_human")
    if d.get("sentiment") == "frustrated":
        v.add("frustrated")
    if _INJECTION_RE.search(text):
        v.add("prompt_injection")
    if _B2B_RE.search(text):
        v.add("b2b_partner")
    if signals.collab_request:
        v.add("collab_request")
    if _DISCOUNT_RE.search(text) or _DISCOUNT_NATIVE_RE.search(text):
        v.add("discount_request")
    _gateway(signals, v)
    _custom_route(signals, v)
    _capacity(signals, v)
    if signals.ungrounded:
        v.add("ungrounded_claim", signals.ungrounded[:200])
    dated_check = any((f.get("args") or {}).get("checkin") for f in _facts(signals, "check_availability"))
    if signals.availability_claim and not dated_check:
        v.add("ungrounded_claim", f"says dates are open without a calendar check: {signals.availability_claim[:160]}")
    if signals.price_leak:
        v.add("price_unverified", str(signals.price_leak)[:200])
    if (signals.price_mode != "grounded" and signals.intent == "price_quote" and signals.has_phone
            and not signals.sales_owns_price):
        v.add("price_handoff")
    if not signals.model_failed and float(signals.confidence or 0) < float(signals.threshold or 0):
        v.add("low_confidence", round(float(signals.confidence or 0), 3))
    _history(signals, v)
    flags = sorted({fl for f in signals.grounded_facts if isinstance(f, dict) for fl in (f.get("flags") or [])})
    sources = [s for f in signals.grounded_facts if isinstance(f, dict) for s in (f.get("sources") or [])][:12]
    if flags:
        v.evidence["flags"] = flags
    if sources:
        v.evidence["sources"] = sources
    return v


def labels(codes) -> list[dict]:
    return [{"code": c, "label": REASONS.get(c, c)} for c in codes or []]
