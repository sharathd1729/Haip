"""Humanizer for Marketing Studio copy: strip the machine fingerprint from AI drafts and score how human text reads.

Adapted from Jakeschincariol/instagram-agent-skill `skills/ig-human/humanize.py` and `detect.py` (MIT, Copyright (c) 2026
Jake Schincariol; docs/marketing-website/THIRD_PARTY_NOTICES.md). Word list: `marketing_slop.json` next to this file.

  * clean(text, keep_words) fixes invisible characters, em/en dashes, curly quotes, the ellipsis character and stock
    words (owner decision: automatic, recorded, one tap to undo). URLs and the workspace's keep-list are never touched;
    capitalisation is preserved. Sentence shapes ("not just X, it's Y") are only reported, never rewritten.
  * score(text) = five local heuristics (sentence variation, specificity, stock words, typographic fingerprint, voice)
    -> 0-100, higher = more human. It is NOT an AI detector and calls nothing.
  * clean_payload / undo_payload apply that to a content payload field by field, so undo restores exactly the fields
    the humanizer changed and still hold its output.
"""
import copy
import json
import re
import statistics
import unicodedata
from pathlib import Path
from typing import Optional

LEXICON = json.loads(Path(__file__).with_name("marketing_slop.json").read_text(encoding="utf-8"))

URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\S+")
SENT_RE = re.compile(r"[^.!?\n]+[.!?]*")
WORD_RE = re.compile(r"[A-Za-z']+")
CONTRACTIONS = re.compile(r"\b\w+'(?:s|t|re|ve|ll|d|m)\b", re.IGNORECASE)
PRONOUNS = re.compile(r"\b(i|me|my|mine|we|us|our|you|your)\b", re.IGNORECASE)
NUMBERS = re.compile(r"\b\d[\d,.]*%?\b|[$₹]\d")
PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b", re.MULTILINE)

# Payload keys that are not prose a guest reads, or must stay byte-exact (hashtags, the comment keyword, ids).
SKIP_KEYS = {"asset_id", "kind", "date", "valid_until", "framework", "style", "colour", "accent", "font", "logo_asset_id",
             "logo_position", "hashtags", "keyword", "slug", "alt_text", "shot_note", "audio_id"}


def _cp_map() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for e in LEXICON["invisible"]:
        a, _, b = e["cp"].partition("-")
        for n in range(int(a[2:], 16), int((b or a)[2:], 16) + 1):
            out[chr(n)] = (e["name"].split(" (")[0].lower(), e["action"])
    return out


_INVISIBLE = _cp_map()
_TYPO = {t["from"]: t for t in LEXICON["typographic"]}


def _bounded(find: str) -> re.Pattern:
    body = re.escape(find).replace(r"\ ", r"\s+")
    # \b only next to a word character: "what are your thoughts?" must still match at its "?".
    return re.compile((r"\b" if find[0].isalnum() else "") + body + (r"\b" if find[-1].isalnum() else ""), re.IGNORECASE)


_LEX = [(e, _bounded(e["find"])) for e in sorted(LEXICON["phrases"] + LEXICON["words"], key=lambda e: len(e["find"]), reverse=True)]
_STRUCTURES = []
for _s in LEXICON["structures"]:
    try:
        _STRUCTURES.append((_s, re.compile(_s["regex"], re.MULTILINE)))
    except re.error:
        pass


def _emojiish(c: str) -> bool:
    return unicodedata.category(c) in ("So", "Sk") or c == "️"


def _protect(text: str, patterns: list[re.Pattern], stash: list[str]) -> str:
    def put(m):
        stash.append(m.group(0))
        return f"\x00{len(stash) - 1}\x00"
    for p in patterns:
        text = p.sub(put, text)
    return text


def _restore(text: str, stash: list[str]) -> str:
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def _pass_invisible(text: str) -> tuple[str, list[dict]]:
    out, counts = [], {}
    for i, c in enumerate(text):
        name, action = _INVISIBLE.get(c) or (("invisible format character", "delete") if unicodedata.category(c) == "Cf" else (None, None))
        # A zero-width joiner between two emoji builds one emoji (a family, a cook); it is not an artefact.
        if c == "‍" and 0 < i < len(text) - 1 and _emojiish(text[i - 1]) and _emojiish(text[i + 1]):
            action = None
        if action is None:
            out.append(c)
            continue
        counts[name] = counts.get(name, 0) + 1
        if action == "space":
            out.append(" ")
    return "".join(out), [{"kind": "invisible", "from": n, "to": "", "count": k} for n, k in counts.items()]


def _pass_typographic(text: str) -> tuple[str, list[dict]]:
    hits = []
    for ch, entry in _TYPO.items():
        n = text.count(ch)
        if not n:
            continue
        kind = "dash" if ch in "—–" else "quote" if ch in "‘’“”" else "ellipsis"
        hits.append({"kind": kind, "from": entry["name"].lower(), "to": entry["to"].strip() or " ", "count": n})
        if ch == "—":
            text = re.sub(r"\s*—\s*", ", ", text)
        elif ch == "–":
            text = re.sub(r"\s*–\s*(?=\d)", "-", text)      # 5–10 -> 5-10
            text = re.sub(r"\s+–\s+", ", ", text)           # used as an em dash
            text = text.replace("–", "-")
        else:
            text = text.replace(ch, entry["to"])
    if any(h["kind"] == "dash" for h in hits):
        text = re.sub(r",\s*([,.;:!?])", r"\1", text)          # a comma before existing punctuation reads wrong
        text = re.sub(r",[ \t]*\n", "\n", text)
        text = re.sub(r"(?m)^[ \t]*,[ \t]*", "", text)          # "— Ananya" on its own line
    return text, hits


def _match_case(src: str, repl: str) -> str:
    if not repl:
        return repl
    if src.isupper() and len(src) > 1:
        return repl.upper()
    if src[0].isupper():
        return repl[0].upper() + repl[1:]
    return repl


def _pass_lexical(text: str) -> tuple[str, list[dict], bool]:
    hits, deleted = [], False
    for entry, pattern in _LEX:
        found = pattern.findall(text)
        if not found:
            continue
        hits.append({"kind": "word", "from": entry["find"], "to": entry["replace"], "count": len(found)})
        deleted = deleted or not entry["replace"]
        text = pattern.sub(lambda m: _match_case(m.group(0), entry["replace"]), text)
    if hits:   # tidy what a deletion leaves behind ("system. ." or a line opening on a comma)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"(?m)^[ \t]*(?:[,.;:]+[ \t]*)+", "", text)
        text = re.sub(r"(?m)^[ \t](?=\S)", "", text)
        text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
        text = re.sub(r",\s*([,.;:!?])", r"\1", text)
        text = text.replace("...", "\x01")
        text = re.sub(r"\.[ \t]*\.+", ".", text)
        text = re.sub(r"([!?])[ \t]*\.", r"\1", text)
        text = re.sub(r"\.[ \t]*[!?]+", ".", text)    # "stay. Look no further!" -> "stay."
        text = re.sub(r"([.!?])[ \t]*,[ \t]*", r"\1 ", text)    # a sentence that now opens on a comma
        text = text.replace("\x01", "...")
        text = re.sub(r"(?m)^[ \t]+$", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text, hits, deleted


def _restore_capitals(original: str, text: str) -> str:
    """Deleting an opener leaves the next word lower case. Only fixed for writers who capitalise sentences at all."""
    starts = re.findall(r"(?:^|[.!?]\s+|\n)\s*([A-Za-z])", original)
    if not starts or sum(1 for c in starts if c.isupper()) * 2 < len(starts):
        return text
    return re.sub(r"(?:^|(?<=[.!?] )|(?<=[.!?]\n)|(?<=\n))\s*([a-z])", lambda m: m.group(0)[:-1] + m.group(1).upper(), text)


def _keep_patterns(keep_words) -> list[re.Pattern]:
    words = sorted({w.strip() for w in keep_words or [] if isinstance(w, str) and w.strip()}, key=len, reverse=True)
    return [_bounded(w) for w in words]


def clean(text: str, keep_words=None) -> tuple[str, list[dict]]:
    """(cleaned text, changes). Each change: {kind: invisible|dash|quote|ellipsis|word, from, to, count}."""
    if not text:
        return text, []
    stash: list[str] = []
    work = _protect(text, [URL_RE], stash)
    work, inv = _pass_invisible(work)
    work, typo = _pass_typographic(work)
    work = _protect(work, _keep_patterns(keep_words), stash)
    work, lexi, deleted = _pass_lexical(work)
    if deleted:
        work = _restore_capitals(text, work)
    work = _restore(work, stash).strip()
    changes = inv + typo + lexi
    return (work if changes else text), changes


def summary(changes: list[dict]) -> str:
    """'Fixed 1 em dash, swapped 2 stock words' for the draft screen."""
    def n(kind):
        return sum(c["count"] for c in changes if c["kind"] == kind)
    parts = []
    for kind, one, many in (("dash", "dash", "dashes"), ("quote", "curly quote", "curly quotes"),
                            ("invisible", "hidden character", "hidden characters"), ("ellipsis", "ellipsis", "ellipses")):
        if n(kind):
            parts.append(f"{n(kind)} {one if n(kind) == 1 else many}")
    words = n("word")
    out = ("Fixed " + ", ".join(parts)) if parts else ""
    if words:
        out += (", swapped " if out else "Swapped ") + f"{words} stock word{'' if words == 1 else 's'}"
    return out or "Nothing to fix"


# ── Score (detect.py) ────────────────────────────────────────────────────────────────────────────────────────────────

def _clamp(n: float) -> float:
    return max(0.0, min(100.0, n))


def _scale(value: float, human: float, machine: float) -> float:
    return 50.0 if human == machine else _clamp((value - machine) / (human - machine) * 100)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_RE.findall(text) if len(s.split()) > 2]


def _burstiness(text):
    lens = [len(s.split()) for s in _sentences(text)]
    if len(lens) < 4:
        return None, "Too short to judge"
    mean = statistics.mean(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0
    return _scale(cv, human=0.70, machine=0.22), f"Sentence length varies {cv:.2f} across {len(lens)} sentences (want 0.55+)"


def _specificity(text):
    w = WORD_RE.findall(text)
    if len(w) < 25:
        return None, "Too short to judge"
    hits = len(NUMBERS.findall(text)) + len(set(PROPER.findall(text)))
    density = hits * 100 / len(w)
    return _scale(density, human=6.0, machine=0.5), f"{hits} names or numbers, {density:.1f} per 100 words (want 4+)"


def _slop(text):
    w = WORD_RE.findall(text)
    if not w:
        return None, "No words"
    found = [(e["find"], len(p.findall(text))) for e, p in _LEX]
    found = [(f, k) for f, k in found if k]
    hits = sum(k for _, k in found)
    detail = f"{hits} stock word{'' if hits == 1 else 's'}" + (f" ({', '.join(sorted(f for f, _ in found)[:4])})" if found else "")
    return _scale(hits * 100 / len(w), human=0.0, machine=4.0), detail


def _fingerprint(text):
    invisible = sum(1 for c in text if unicodedata.category(c) == "Cf" and c != "‍")
    em = text.count("—")
    curly = sum(text.count(c) for c in "‘’“”")
    ellip = text.count("…")
    nbsp = sum(text.count(c) for c in "   ")
    per1k = (invisible * 4 + em * 2 + curly + ellip + nbsp) * 1000 / max(len(text), 1)
    return _scale(per1k, human=0.0, machine=12.0), f"{invisible} hidden, {em} em dash, {curly} curly quote, {ellip} ellipsis, {nbsp} hard space"


def _voice(text):
    w = WORD_RE.findall(text)
    if len(w) < 25:
        return None, "Too short to judge"
    per100 = 100 / len(w)
    contractions = len(CONTRACTIONS.findall(text)) * per100
    person = len(PRONOUNS.findall(text)) * per100
    names = [s["name"] for s, p in _STRUCTURES if p.search(text)]
    tells = sum(len(p.findall(text)) for _, p in _STRUCTURES)
    score = (_scale(contractions, human=3.0, machine=0.0) * 0.35 + _scale(person, human=8.0, machine=1.0) * 0.35
             + _clamp(100 - tells * 22) * 0.30)
    detail = f"{contractions:.1f} contractions and {person:.1f} we/you per 100 words"
    if names:
        detail += "; " + ", ".join(names[:3])
    return _clamp(score), detail


_CHECKS = (("variation", "Sentence variety", _burstiness), ("specificity", "Specific details", _specificity),
           ("stock_words", "Stock words", _slop), ("fingerprint", "Typing marks", _fingerprint), ("voice", "Voice", _voice))


def score(text: str, keep_words=None) -> dict:
    """{score 0-100, verdict pass|review|flagged, checks:[{key, label, score|None, detail}]}.

    Unlike detect.py, a check that is too short to judge is left out of the score instead of counting as 50: most
    captions are short, and a 50 floor would mark every one of them "review". URLs and keep-list words never count."""
    if not (text or "").strip():
        return {"score": None, "verdict": "review", "checks": []}
    text = URL_RE.sub(" ", text)
    for p in _keep_patterns(keep_words):
        text = p.sub("Keep", text)      # still a name for "specific details", never a stock word
    checks = []
    for key, label, fn in _CHECKS:
        value, detail = fn(text)
        checks.append({"key": key, "label": label, "score": None if value is None else round(value), "detail": detail})
    judged = [c["score"] for c in checks if c["score"] is not None]
    if not judged:
        return {"score": None, "verdict": "review", "checks": checks}
    overall = statistics.mean(judged) * 0.6 + min(judged) * 0.4      # the weakest signal drags the verdict
    verdict = "pass" if overall >= 70 and min(judged) >= 55 else "review" if overall >= 50 else "flagged"
    return {"score": round(overall), "verdict": verdict, "checks": checks}


# ── Payloads ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _walk(value, path: list, fn):
    if isinstance(value, str):
        return fn(path, value)
    if isinstance(value, dict):
        return {k: (x if k in SKIP_KEYS else _walk(x, path + [k], fn)) for k, x in value.items()}
    if isinstance(value, list):
        return [_walk(x, path + [i], fn) for i, x in enumerate(value)]
    return value


def prose_of(payload: dict) -> str:
    """The text the humanizer reads and scores: every prose field, one per line."""
    parts: list[str] = []
    _walk(payload or {}, [], lambda _p, s: parts.append(s) or s)
    return "\n".join(p for p in parts if p)


def _merge(changes: list[dict]) -> list[dict]:
    merged: dict[tuple, dict] = {}
    for c in changes:
        key = (c["kind"], c["from"].lower(), c["to"])
        if key in merged:
            merged[key]["count"] += c["count"]
        else:
            merged[key] = dict(c)
    return list(merged.values())


def clean_payload(payload: dict, keep_words=None) -> tuple[dict, Optional[dict]]:
    """(cleaned payload, record or None). record = {fields: [{path, before, after}], changes: [...]}: what undo needs."""
    fields, changes = [], []

    def fix(path, s):
        out, ch = clean(s, keep_words)
        if out != s:
            fields.append({"path": path, "before": s, "after": out})
            changes.extend(ch)
            return out
        return s

    cleaned = _walk(payload, [], fix)
    if not fields:
        return payload, None
    return cleaned, {"fields": fields, "changes": _merge(changes)}


def _get(obj, path):
    for p in path:
        try:
            obj = obj[p]
        except (KeyError, IndexError, TypeError):
            return None
    return obj


def undoable(payload: dict, record: Optional[dict]) -> list[dict]:
    """The recorded fields that still hold the humanizer's output (a person may have rewritten the others since)."""
    return [f for f in ((record or {}).get("fields") or []) if _get(payload, f["path"]) == f["after"]]


def undo_payload(payload: dict, record: Optional[dict]) -> tuple[dict, int]:
    """(payload with the original text back in every still-unchanged field, how many fields were restored)."""
    out = copy.deepcopy(payload)
    fields = undoable(payload, record)
    for f in fields:
        parent = _get(out, f["path"][:-1])
        parent[f["path"][-1]] = f["before"]
    return out, len(fields)


def keep_words(tenant) -> list[str]:
    """The workspace's own brand words the humanizer never swaps (brand_config.marketing_studio.keep_words)."""
    cfg = ((getattr(tenant, "brand_config", None) or {}).get("marketing_studio") or {})
    words = cfg.get("keep_words") if isinstance(cfg, dict) else None
    return [w for w in words if isinstance(w, str) and w.strip()] if isinstance(words, list) else []


MAX_KEEP_WORDS, MAX_KEEP_LEN = 50, 40


def set_keep_words(db, tenant, words: list[str], actor_id: str) -> list[str]:
    """Owner setting: brand words kept as written (e.g. "curated", "unwind"). Audited."""
    from sqlalchemy.orm.attributes import flag_modified
    from app.core.audit import append_audit

    clean: list[str] = []
    for w in words:
        w = " ".join(str(w).split())[:MAX_KEEP_LEN]
        if w and w.lower() not in {x.lower() for x in clean}:
            clean.append(w)
    clean = clean[:MAX_KEEP_WORDS]
    before = keep_words(tenant)
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get("marketing_studio") or {})
    section["keep_words"] = clean
    cfg["marketing_studio"] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.keep_words.updated", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": clean})
    return clean
