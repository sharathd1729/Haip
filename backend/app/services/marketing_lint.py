"""Deterministic checks on a draft's text (agency M1). Pure functions: payload in, findings out, no AI, no database.

Four families, each finding says where, quotes the words and suggests a fix:
  * grounding   -- "[NEED: ...]" left by the copywriter (a fact it did not have), and numbers with a unit (km, guests,
                   bedrooms...) that appear nowhere in the facts the copywriter was given;
  * ai_tells    -- patterns small models produce and readers recognise as machine-written;
  * compliance  -- guarantees and competitor names (high); unproven superlatives and unattributed testimonials (medium);
  * structure   -- carousel cover promising N items that the slides don't deliver; caption repeating slide 1.
Only `high` findings block the agency from sending a draft for approval (marketing_review_service).

The AI-tell list, carousel rules and edit discipline adapt coreyhaines31/marketingskills (`social`, `copy-editing`,
MIT); the compliance flags adapt anthropics/knowledge-work-plugins `brand-review` (Apache-2.0). Notices:
docs/marketing-website/THIRD_PARTY_NOTICES.md.
"""
import re
from typing import Iterable, Optional

_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

NEED = re.compile(r"\[NEED:\s*([^\]]{1,120})\]", re.I)
_UNIT_NUMBER = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(km|kms|kilometres|kilometers|minutes|mins|hours|hrs|bedrooms?|beds|guests|people|acres?|"
    r"sq\.?\s?ft|square feet|feet|ft|metres|meters|%|percent|years|rooms|seater|seats|pools|bathrooms?)\b", re.I)

_CONTRAST = re.compile(
    r"\b(?:it|this|that)(?:'s|’s| is)\s+not\s+(?:just\s+)?[^.?!\n]{1,50}?[,;:.–—-]+\s*(?:it|this|that)(?:'s|’s| is)\b"
    r"|\bisn(?:'|’)?t\s+just\b[^.?!\n]{1,60}?[,;:–—-]+\s*(?:it|this|that)(?:'s|’s| is)\b", re.I)
_BAIT = re.compile(r"(?:^|[\s.!])(agree\?|thoughts\?|who else\b[^?\n]*\?|double[- ]tap\b|comment ['\"“]?yes\b)", re.I)
_TAG = re.compile(r"\btag (?:a|someone|your)\b[^.\n]{0,40}\bwho\b", re.I)
_SELF_ANSWER = re.compile(r"\?\s*(?:Simple|Easy|Here(?:'|’)s (?:how|why|the thing)|The answer)\b", re.I)
STOCK = ("nestled", "hidden gem", "look no further", "unforgettable experience", "hustle and bustle",
         "escape the hustle", "a perfect blend", "whether you're", "whether you’re", "embark on", "elevate your",
         "unwind and rejuvenate", "rejuvenate your", "a haven of", "tapestry", "delve into", "game-changer",
         "fast-paced world", "something for everyone", "awaits you", "experience the magic", "picture this",
         "imagine waking up", "in the heart of", "a symphony of")
_EMOJI_LINE = re.compile(r"^\s*[☀-➿\U0001F300-\U0001FAFF]")

_GUARANTEE = re.compile(r"\b(guarantee[ds]?|100\s?%|risk[- ]free|assured|always available|never booked out)\b", re.I)
_SUPERLATIVE = re.compile(r"\b(the best|best in|no\.?\s?1|number one|#1|the only|unmatched|unbeatable|world[- ]class|"
                          r"finest|most luxurious)\b", re.I)
_TESTIMONIAL = re.compile(r"[\"“][^\"”]{12,}[\"”]\s*[-–—]\s*[A-Z][a-z]+|\bguests (?:say|call it|love it)\b")

_COUNT = re.compile(r"\b(\d{1,2}|two|three|four|five|six|seven|eight|nine|ten)\s+(?:[\w’'-]+\s+){0,2}?"
                    r"(ways|reasons|things|places|stops|tips|days|spots|moments|ideas|experiences|views|routes|mornings|"
                    r"nights|secrets|rules|questions|lessons|signs)\b", re.I)
_ASK = re.compile(r"\b(dm|message|book|link|reply|save|send|call|enquire|inquire|whatsapp|write to us|tap)\b", re.I)


def _f(rule: str, severity: str, where: str, message: str, quote: Optional[str] = None,
       suggestion: Optional[str] = None) -> dict:
    return {"rule": rule, "severity": severity, "where": where, "message": message[:300],
            "quote": (quote or None) and quote.strip()[:200], "suggestion": (suggestion or None) and suggestion[:300]}


def segments(kind: str, payload: dict) -> list[tuple[str, str]]:
    """(where, text) for every guest-visible text field, in reading order."""
    out: list[tuple[str, str]] = []

    def add(where: str, value) -> None:
        if isinstance(value, str) and value.strip():
            out.append((where, value))
    if kind == "carousel":
        for i, s in enumerate(payload.get("slides") or [], start=1):
            add(f"slide {i}", " ".join(x for x in (s.get("headline"), s.get("body")) if x))
    elif kind == "story":
        for i, fr in enumerate(payload.get("frames") or [], start=1):
            sticker = (fr.get("sticker") or {}).get("text")
            add(f"frame {i}", " ".join(x for x in (fr.get("text"), fr.get("cta"), sticker) if x))
    elif kind == "promo":
        for key in ("headline", "offer", "body", "cta"):
            add(key, payload.get(key))
    else:
        add("text on image", payload.get("overlay_text"))
    add("caption", payload.get("caption"))
    add("first comment", payload.get("first_comment"))
    dm = payload.get("comment_dm") or {}
    add("comment DM", dm.get("message"))
    add("comment reply", dm.get("public_reply"))
    return out


# ── Families ────────────────────────────────────────────────────────────────────────────────────────────────────────

def grounding(where: str, text: str, facts_text: str, *, strict: bool) -> list[dict]:
    out = [_f("missing_fact", "high", where, f"The copywriter needs a fact it doesn't have: {m.group(1).strip()}.",
              m.group(0), "Add the fact to the business profile or property, or remove the sentence.")
           for m in NEED.finditer(text)]
    known = set(re.findall(r"\d+(?:[.,]\d+)?", facts_text or ""))
    for m in _UNIT_NUMBER.finditer(text):
        if m.group(1) not in known:
            out.append(_f("unverified_number", "high" if strict else "medium", where,
                          f"\"{m.group(0)}\" is not in your business data. Check it before it is posted.",
                          m.group(0), "Use the figure from the property details, or take it out."))
    return out


def ai_tells(where: str, text: str) -> list[dict]:
    out = []
    for m in _CONTRAST.finditer(text):
        out.append(_f("contrast_reveal", "high", where, "\"It's not X, it's Y\" reads as machine-written.", m.group(0),
                      "Say the positive thing directly."))
    if where == "caption":
        for m in _BAIT.finditer(text):
            out.append(_f("engagement_bait", "high", where, "Engagement bait: Instagram demotes it and readers skip it.",
                          m.group(1), "End with a real question about their trip, or a clear ask."))
        for m in _TAG.finditer(text):
            out.append(_f("tag_bait", "medium", where, "\"Tag someone who...\" is engagement bait.", m.group(0)))
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        short = [ln for ln in lines if len(ln.split()) <= 8 and len(re.findall(r"[.!?]", ln.rstrip(".!?"))) == 0]
        if len(lines) >= 5 and len(short) >= 0.7 * len(lines):
            out.append(_f("one_line_sentences", "medium", where,
                          "One short sentence per line reads as machine-written.", lines[0],
                          "Join related sentences into 2-4 short paragraphs."))
        if sum(1 for ln in lines if _EMOJI_LINE.match(ln)) >= 3:
            out.append(_f("emoji_bullets", "low", where, "Emoji used as bullet points.", None,
                          "Use at most one or two emoji, inside sentences."))
    for m in _SELF_ANSWER.finditer(text):
        out.append(_f("self_answered_question", "medium", where, "A question answered by the writer itself.", m.group(0)))
    found = [p for p in STOCK if p in text.lower()]
    if found:
        out.append(_f("stock_phrases", "medium", where, "Stock travel phrases: " + ", ".join(found) + ".",
                      found[0], "Replace each with a specific detail of this stay."))
    if text.count("—") >= 3:
        out.append(_f("dashes", "low", where, "Many long dashes; they read as machine-written.", None,
                      "Use full stops or commas."))
    return out


def compliance(where: str, text: str, competitors: Iterable[str]) -> list[dict]:
    out = [_f("guarantee", "high", where, "A promise the business may not be able to keep.", m.group(0),
              "Describe what is included instead of promising an outcome.") for m in _GUARANTEE.finditer(text)]
    out += [_f("superlative", "medium", where, "A superlative with no evidence.", m.group(0),
               "Keep it only if you can show it (an award, a rating); otherwise be specific.")
            for m in _SUPERLATIVE.finditer(text)]
    out += [_f("testimonial", "medium", where, "A guest quote or claim about guests. Use only real reviews, with permission.",
               m.group(0)) for m in _TESTIMONIAL.finditer(text)]
    low = text.lower()
    for name in {c.strip().lstrip("@").lower() for c in competitors if c and len(c.strip().lstrip("@")) >= 4}:
        if re.search(rf"(?<![\w@]){re.escape(name)}(?!\w)|@{re.escape(name)}\b", low):
            out.append(_f("competitor_named", "high", where, "Names a competitor.", name,
                          "Talk about what this stay offers, never about other businesses."))
    return out


def structure(kind: str, payload: dict) -> list[dict]:
    if kind != "carousel":
        return []
    out = []
    slides = payload.get("slides") or []
    cover = (slides[0].get("headline") or "") if slides else ""
    m = _COUNT.search(cover)
    if m:
        raw = m.group(1).lower()
        n = int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw, 0)
        content = len(slides) - 1
        if n and n not in (content, content - 1):
            out.append(_f("count_mismatch", "high", "slide 1", f"The cover promises {n} {m.group(2)}, but there are "
                          f"{content} slides after it.", m.group(0), f"Write exactly {n} slides, or change the cover."))
    first_line = ((payload.get("caption") or "").strip().split("\n", 1)[0]).strip().lower()
    if cover and first_line and (first_line.rstrip(".!?") == cover.strip().lower().rstrip(".!?")
                                 or first_line.startswith(cover.strip().lower())):
        out.append(_f("caption_repeats_cover", "medium", "caption", "The caption opens with slide 1's words.",
                      cover, "Give the caption its own first line; people see both."))
    if slides:
        last = " ".join(x for x in (slides[-1].get("headline"), slides[-1].get("body")) if x)
        if last and not _ASK.search(last):
            out.append(_f("no_ask", "low", f"slide {len(slides)}", "The last slide doesn't ask for anything.",
                          last, "End with one clear ask, e.g. \"DM us your dates\"."))
    return out


def comment_dm(payload: dict) -> list[dict]:
    """A "comment KEYWORD" trigger only works if the caption tells people the keyword."""
    dm = payload.get("comment_dm") or {}
    kw = (dm.get("keyword") or "").strip()
    if kw and kw.lower() not in (payload.get("caption") or "").lower():
        return [_f("comment_keyword_missing", "high", "caption", f"The caption never tells people to comment “{kw}”.",
                   None, f"Add a line like “Comment {kw.upper()} and we'll send you the dates.”")]
    return []


def check(kind: str, payload: dict, *, facts_text: str = "", competitors: Iterable[str] = (),
          strict_numbers: bool = True) -> list[dict]:
    """Every finding for a payload, high first."""
    competitors = list(competitors)
    out: list[dict] = []
    for where, text in segments(kind, payload):
        out += grounding(where, text, facts_text, strict=strict_numbers)
        out += ai_tells(where, text)
        out += compliance(where, text, competitors)
    out += structure(kind, payload)
    out += comment_dm(payload)
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda f: order[f["severity"]])


def blocking(findings: list[dict]) -> bool:
    return any(f["severity"] == "high" for f in findings)
