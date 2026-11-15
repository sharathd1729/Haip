"""Reel hooks (Instagram toolkit phase 2): three opening lines from 26 formulas, scored; the spoken script; a timed
shot list. Adapted from Jakeschincariol/instagram-agent-skill `skills/ig-reel` (hooks.json, hookscore.py, beats.py;
MIT, Copyright (c) 2026 Jake Schincariol; docs/marketing-website/THIRD_PARTY_NOTICES.md).

  * The AI writes three options (formula + spoken line + on-screen line) and a script (`write`, prompt
    `marketing-reel-hooks-v1`, run after every reel draft in `run_content`, so the weekly agency run gets them too).
  * Code scores each option (five heuristics, `score_hook`), blocks any that breaks the price policy, runs every line
    through the phase-1 humanizer, and times the script into a shot list (`beats`). Nothing is taken from the model
    as a score.
  * A person picks one (`choose`): its on-screen line becomes the first clip's caption as a NEW version (normal
    approval rules), and the formula is saved on the content (`marketing_content.hook_formula`) for per-formula results.

The score is NOT a view predictor: upstream measured it as good at catching bad hooks (greetings, preambles, nothing
concrete, too long) and close to a coin flip at ranking two decent ones. The UI says "weak" only below 50.
"""

import copy
import json
import re
import statistics
from pathlib import Path

import structlog
from sqlalchemy.orm import Session

log = structlog.get_logger()

DATA = json.loads(Path(__file__).with_name("marketing_hooks.json").read_text(encoding="utf-8"))
FORMULAS = {h["id"]: h for h in DATA["hooks"]}
_MATCH = [(i, re.compile(FORMULAS[i]["match"], re.IGNORECASE)) for i in DATA["classify_order"]]
WEAK_BELOW = 50

# ── Hook score (hookscore.py) ────────────────────────────────────────────────────────────────────────────────────────

WORD_RE = re.compile(r"[A-Za-z0-9$₹%'’-]+")
NUMBER_RE = re.compile(
    r"[$₹]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:%|k\b|x\b|hrs?\b|hours?\b|mins?\b|minutes?\b"
    r"|days?\b|nights?\b|weeks?\b|months?\b|years?\b|km\b)?",
    re.IGNORECASE,
)
PROPER_RE = re.compile(r"(?<!^)\b[A-Z][a-z]{2,}\b")
HASHTAG_RE = re.compile(r"(?:^|\s)#\w+")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
SPOKEN_NUMBERS = {
    "zero",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "fifteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
    "dozen",
    "half",
    "twice",
    "triple",
    "lakh",
    "crore",
}
MONEY_WORDS = {"rupees", "rupee", "dollars", "percent", "price", "rent"}
STAKES = {
    "stop",
    "never",
    "wrong",
    "mistake",
    "mistakes",
    "lost",
    "lose",
    "losing",
    "cost",
    "costs",
    "broke",
    "broken",
    "failed",
    "fail",
    "nobody",
    "no",
    "not",
    "don't",
    "dont",
    "doesn't",
    "didn't",
    "can't",
    "won't",
    "quit",
    "cut",
    "beat",
    "free",
    "first",
    "worst",
    "hate",
    "wasted",
    "waste",
    "truth",
    "secret",
    "hidden",
    "before",
    "until",
    "instead",
    "but",
    "except",
    "unless",
    "problem",
    "risk",
    "warning",
    "regret",
    "wish",
    "should",
    "shouldn't",
    "still",
    "already",
    "only",
    "without",
    "versus",
    "vs",
    "actually",
    "almost",
    "last",
}
WEAK_OPENERS = [
    "so",
    "ok",
    "okay",
    "hey",
    "hi",
    "hello",
    "guys",
    "yo",
    "alright",
    "welcome",
    "today",
    "basically",
    "honestly",
    "look",
    "listen",
    "um",
    "just",
    "let",
    "lets",
    "let's",
    "i wanted",
    "i want",
    "one of",
    "have you",
    "did you",
    "do you",
    "are you",
    "in this",
    "in today",
    "the thing",
    "a lot",
    "there is",
    "there are",
    "this is",
    "it is",
    "as a",
    "when it",
    "if you've",
    "you know",
]
IMPERATIVES = {
    "stop",
    "steal",
    "copy",
    "try",
    "watch",
    "read",
    "save",
    "use",
    "build",
    "make",
    "send",
    "take",
    "start",
    "never",
    "always",
    "don't",
    "dont",
    "do",
    "put",
    "run",
    "check",
    "come",
    "book",
    "skip",
    "pack",
}
DEALBREAKERS = [
    (re.compile(r"(?i)^\s*(?:stop scrolling|don'?t scroll)"), 'Opens with "stop scrolling": asking for attention.'),
    (
        re.compile(r"(?i)\b(?:in (?:this|today'?s) (?:video|reel)|i'?m going to show you|i'?ll show you how)\b"),
        "Video preamble: open on the payoff instead.",
    ),
    (re.compile(r"(?i)^\s*(?:hey |hi |what'?s up |welcome )"), "Greeting: nobody came to the feed to be greeted."),
    (HASHTAG_RE, "Hashtag in the hook."),
    (EMOJI_RE, "Emoji in the hook: at hook size there is room for words or an emoji, not both."),
]
CHECK_LABEL = {
    "length": "Length",
    "specificity": "Something concrete",
    "stakes": "Something at stake",
    "frontload": "Point up front",
    "address": "Speaks to the viewer",
}


def _clamp(n: float) -> float:
    return max(0.0, min(100.0, n))


def _words(text: str) -> list[str]:
    return WORD_RE.findall(re.sub(r"(?<=\d),(?=\d)", "", text))  # "18,000" is one spoken word


def _low(text: str) -> list[str]:
    return [w.lower().strip("'’") for w in _words(text)]


def _length(text):
    n, chars = len(_words(text)), len(text.strip())
    score = 100.0 if 5 <= n <= 12 else _clamp(100 - (5 - n) * 20) if n < 5 else _clamp(100 - (n - 12) * 11)
    if chars > 60:
        score -= 12
    return _clamp(score), f"{n} words, about {n / 2.75:.1f}s to say (want 5-12 words)"


def _specificity(text):
    nums = [n.strip() for n in NUMBER_RE.findall(text) if n.strip()]
    propers = set(PROPER_RE.findall(text))
    spoken = [w for w in _low(text) if w in SPOKEN_NUMBERS or w in MONEY_WORDS]
    hits = len(nums) + len(propers) + len(spoken)
    return (15.0 if hits == 0 else _clamp(45 + hits * 30)), (
        f"{hits} number(s) or name(s)" if hits else "No number, no name, nothing checkable"
    )


def _stakes(text):
    markers = sorted({w for w in _low(text) if w in STAKES})
    return {0: 20.0, 1: 70.0}.get(len(markers), 100.0), (
        f"Tension: {', '.join(markers[:3])}" if markers else "Nothing is at stake in this line"
    )


def _frontload(text):
    w = _words(text)
    if not w:
        return 0.0, "Empty"
    low = [x.lower().strip("'’") for x in w]
    opener = " ".join(low[:2])
    weak = next((o for o in WEAK_OPENERS if opener.startswith(o) or low[0] == o), None)
    payload = next(
        (
            i
            for i, t in enumerate(low)
            if t in STAKES
            or t in SPOKEN_NUMBERS
            or t in MONEY_WORDS
            or NUMBER_RE.match(w[i])
            or (i and PROPER_RE.match(w[i]))
        ),
        None,
    )
    if payload is None:
        base, where = 30.0, "No payload word in the line"
    elif payload <= 3:
        base, where = 100.0, f"Point at word {payload + 1}"
    elif payload <= 6:
        base, where = 70.0, f"Point at word {payload + 1}; could move forward"
    else:
        base, where = 40.0, f"Point at word {payload + 1}; too late"
    return _clamp(base - (30 if weak else 0)), where + (f'; weak opener "{weak}"' if weak else "")


def _address(text):
    low, w = text.lower(), _low(text)
    if re.search(r"\b(you|your|you're|youre|yourself)\b", low):
        return 100.0, "Speaks to the viewer"
    if w and w[0] in IMPERATIVES:
        return 90.0, f'Opens with an instruction ("{w[0]}")'
    if re.search(r"\b(i|my|me|we|our)\b", low):
        return 70.0, "First person, no viewer named"
    return 35.0, "Third person, nobody in the room"


_CHECKS = (
    ("length", _length),
    ("specificity", _specificity),
    ("stakes", _stakes),
    ("frontload", _frontload),
    ("address", _address),
)


def score_hook(text: str) -> dict:
    """{score 0-100, verdict strong|ok|weak, checks:{key: {score, detail}}, weakest, flags}."""
    checks = {k: fn(text or "") for k, fn in _CHECKS}
    flags = [msg for pattern, msg in DEALBREAKERS if pattern.search(text or "")]
    scores = [v[0] for v in checks.values()]
    overall = _clamp(statistics.mean(scores) * 0.6 + min(scores) * 0.4 - len(flags) * 15)
    verdict = (
        "strong" if overall >= 70 and min(scores) >= 55 and not flags else "ok" if overall >= WEAK_BELOW else "weak"
    )
    weakest = min(checks, key=lambda k: checks[k][0])
    return {
        "score": round(overall),
        "verdict": verdict,
        "weakest": weakest,
        "flags": flags,
        "checks": {k: {"score": round(v[0]), "detail": v[1]} for k, v in checks.items()},
    }


def classify(text: str) -> int | None:
    """The formula a hook found in the wild follows (most specific first), or None."""
    for fid, pattern in _MATCH:
        if pattern.search(text or ""):
            return fid
    return None


# ── Beat sheet (beats.py) ────────────────────────────────────────────────────────────────────────────────────────────

HOOK_WINDOW, MAX_BEAT, ABSTRACT_RUN, WPM = 3.0, 4.0, 3, 165
CONCRETE_RE = re.compile(r"[$₹]\s?\d|\b\d[\d,.]*\b|(?<!^)\b[A-Z][a-z]{2,}\b", re.MULTILINE)
STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "if",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "that",
    "this",
    "it",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "you",
    "your",
    "i",
    "my",
    "me",
    "we",
    "our",
    "they",
    "them",
    "so",
    "just",
    "not",
    "no",
    "do",
    "did",
    "does",
    "have",
    "has",
    "had",
    "will",
    "can",
    "at",
    "as",
    "by",
    "from",
    "out",
    "up",
    "off",
    "one",
    "all",
    "us",
}


def beats(lines: list[dict], wpm: int = WPM, target: float | None = None) -> dict:
    """Timed shot list from [{line, shot}] (the hook first). Timings = word count at `wpm`: an estimate to plan the
    edit, not a recording."""
    wps = wpm / 60.0
    rows, clock = [], 0.0
    for i, item in enumerate(x for x in lines if (x.get("line") or "").strip()):
        n = len(_words(item["line"]))
        dur = n / wps
        rows.append(
            {
                "n": i + 1,
                "start": round(clock, 1),
                "seconds": round(dur, 1),
                "line": item["line"],
                "shot": item.get("shot") or "",
                "label": "",
                "flags": [],
                "concrete": len(CONCRETE_RE.findall(item["line"])),
            }
        )
        clock += dur
    if not rows:
        return {"total_seconds": 0, "rows": [], "notes": []}
    for r in rows:
        if r["n"] == 1:
            r["label"] = "Hook"
    rows[-1]["label"] = "Ask" if len(rows) > 1 else "Hook"
    notes = []
    if rows[0]["seconds"] > HOOK_WINDOW:
        rows[0]["flags"].append(f"Hook takes {rows[0]['seconds']:.1f}s, past {HOOK_WINDOW:.0f}s")
        notes.append(
            f"The hook takes {rows[0]['seconds']:.1f}s to say; cut it to {int(HOOK_WINDOW * wps)} words or fewer."
        )
    for r in rows:
        if r["seconds"] > MAX_BEAT:
            r["flags"].append(f"{r['seconds']:.1f}s on one shot")
    run = 0
    for r in rows:
        run = run + 1 if r["concrete"] == 0 else 0
        if run == ABSTRACT_RUN:
            notes.append(f"Lines {r['n'] - 2}-{r['n']} have nothing concrete: put a place, a time or a detail in one.")
    first = {w.lower() for w in _words(rows[0]["line"]) if w.lower() not in STOPWORDS}
    last = {w.lower() for w in _words(rows[-1]["line"]) if w.lower() not in STOPWORDS}
    notes.append(
        "Loops back to the hook (" + ", ".join(sorted(first & last)[:3]) + "): replays come free."
        if first & last
        else "The last line shares no word with the hook; echo one so the replay lands."
    )
    if target and abs(clock - target) > target * 0.1:
        notes.append(f"{abs(clock - target):.0f}s {'over' if clock > target else 'under'} the {target:.0f}s target.")
    for r in rows:
        r.pop("concrete")
    return {"total_seconds": round(clock, 1), "rows": rows, "notes": notes}


# ── Options, plan, AI step ───────────────────────────────────────────────────────────────────────────────────────────


def build_plan(draft: dict, price_mode: str, keep_words=None) -> dict:
    """Score, block and humanize the AI's options; time the script under the best usable hook."""
    from app.services import marketing_humanize as human
    from app.services import price_policy

    def tidy(s: str) -> str:
        return human.clean(s, keep_words)[0]

    options = []
    for o in draft["options"]:
        spoken, on_screen = tidy(o["spoken"]), tidy(o["on_screen"])
        fid = o["formula_id"] if o["formula_id"] in FORMULAS else (classify(spoken) or 0)
        s = score_hook(spoken)
        price = price_mode == "handoff" and (price_policy.detect_price(spoken) or price_policy.detect_price(on_screen))
        reason = (
            "Mentions a price; this workspace never shows prices."
            if price
            else s["flags"][0]
            if s["flags"] and s["score"] < WEAK_BELOW
            else f"Weak: {CHECK_LABEL[s['weakest']].lower()} ({s['checks'][s['weakest']]['detail']})"
            if s["score"] < WEAK_BELOW
            else None
        )
        options.append(
            {
                "formula_id": fid,
                "formula": FORMULAS.get(fid, {}).get("name", "Unnamed"),
                "spoken": spoken,
                "on_screen": on_screen,
                "score": s["score"],
                "verdict": s["verdict"],
                "checks": s["checks"],
                "flags": s["flags"],
                "blocked": bool(price),
                "reason": reason,
            }
        )
    script = [{"line": tidy(x["line"]), "shot": tidy(x["shot"])} for x in draft["script"]]
    plan = {"status": "ready", "options": options, "script": script, "chosen": None}
    return with_beats(plan)


def best_usable(plan: dict) -> int | None:
    usable = [i for i, o in enumerate(plan.get("options") or []) if not o["blocked"]]
    return max(usable, key=lambda i: plan["options"][i]["score"]) if usable else None


def with_beats(plan: dict) -> dict:
    i = plan.get("chosen") if plan.get("chosen") is not None else best_usable(plan)
    hook = plan["options"][i] if i is not None else None
    lines = ([{"line": hook["spoken"], "shot": f"On screen: {hook['on_screen']}"}] if hook else []) + plan["script"]
    return {**plan, "beats": beats(lines), "beats_for": i}


def _formulas_text() -> str:
    return "\n".join(
        f"{h['id']}. {h['name']}: {h['template']} | for: {h['best_for']} | avoid: {h['trap']}" for h in DATA["hooks"]
    )


def write(db: Session, tenant, item) -> dict:
    """Ask the AI for three hook options + a script for a reel draft; store the scored plan on item.hook_plan.
    Never raises for a bad answer (recorded as failed); provider errors propagate to the caller."""
    from pydantic import ValidationError
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.prompt_versions import get_version
    from app.schemas.marketing_hooks import ReelHookDraft
    from app.services import marketing_ai_service as ai
    from app.services import marketing_content_service as content_svc
    from app.services import marketing_humanize as human
    from app.services import marketing_prompts as prompts
    from app.services import price_policy, usage_service

    version = content_svc.get_version(db, tenant.id, item.current_version_id)
    if version is None or item.kind != "reel":
        return item.hook_plan or {}
    p = version.payload
    draft_view = {
        "caption": p.get("caption"),
        "cover_text": p.get("cover_text"),
        "clips": [
            {
                "seconds": c.get("seconds"),
                "caption": c.get("caption"),
                "shot_note": c.get("shot_note"),
                "footage": (c.get("media") or {}).get("alt_text"),
            }
            for c in p.get("clips") or []
        ],
    }
    user = (
        f"Business facts:\n{ai._facts(db, tenant, item.property_id)}\n\nReel draft:\n"
        f"{json.dumps(draft_view, ensure_ascii=False)}\n\nHook formulas:\n{_formulas_text()}\n\nRules:\n- "
        + "\n- ".join(DATA["rules"])
    )
    try:
        data, raw, provider = ai._call(
            "marketing_content", tenant.id, ai._system(prompts.REEL_HOOKS_SYSTEM, tenant), user, prompts.REEL_HOOKS_TOOL
        )
        usage_service.record_llm(
            db, tenant.id, ai.MODULE, raw, provider=provider, ref_type="marketing_hooks", ref_id=item.id
        )
        draft = ReelHookDraft.model_validate(data or {}).model_dump()
        plan = build_plan(draft, price_policy.price_mode(tenant), human.keep_words(tenant))
        plan.update(version_id=version.id, prompt_version=get_version("marketing_reel_hooks"), model=raw.get("model"))
    except (ValidationError, ValueError) as exc:
        plan = {"status": "failed", "error": f"The AI's hook options did not fit the format: {str(exc)[:300]}"}
    item.hook_plan = plan
    flag_modified(item, "hook_plan")
    return plan


def choose(db: Session, tenant_id: str, item_id: str, n: int, seen_version_id: str, actor):
    """Use option n: its on-screen line becomes the first clip's caption (a new version) and its formula is saved."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.audit import append_audit
    from app.services import marketing_content_service as content_svc

    item = content_svc.get_item(db, tenant_id, item_id)
    plan = item.hook_plan or {}
    options = plan.get("options") or []
    if plan.get("status") != "ready" or not 0 <= n < len(options):
        raise content_svc.MarketingError(404, "no_such_hook", "That opening line is not available. Write new options.")
    option = options[n]
    if option["blocked"]:
        raise content_svc.MarketingError(
            409, "hook_blocked", option["reason"] or "This opening line breaks a workspace rule."
        )
    if item.current_version_id != seen_version_id:
        raise content_svc.MarketingError(
            409, "version_changed", "A newer version was saved since you opened this. Reload and try again."
        )
    current = content_svc.get_version(db, tenant_id, seen_version_id)
    payload = copy.deepcopy(current.payload)
    if payload.get("clips"):
        payload["clips"][0]["caption"] = option["on_screen"][:80]
    version = content_svc.add_version(
        db,
        tenant_id,
        item.id,
        payload,
        origin="human",
        actor_id=actor.id,
        note=f"Opening line: {option['formula']}: {option['spoken']}"[:1000],
    )
    item.hook_plan = with_beats({**plan, "chosen": n})
    item.hook_formula = option["formula"][:60]
    flag_modified(item, "hook_plan")
    append_audit(
        db,
        tenant_id=tenant_id,
        action="marketing.content.hook_chosen",
        actor_user_id=actor.id,
        target_type="marketing_content",
        target_id=item.id,
        payload={"option": n, "formula_id": option["formula_id"], "version_id": version.id},
    )
    return item
