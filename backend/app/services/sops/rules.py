"""Platform rules for SOPs: app/data/sop_rules/<platform>.json, curated by the HAIP team (pull request), never by the AI.

A step that needs a fact this catalogue does not hold says "Check in the platform" (the caller's job, see generate.py).
An entry older than STALE_DAYS is flagged `stale` so the screen says it may be out of date.
"""

import hashlib
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.schemas.sops import PLATFORMS, RuleEntry

RULES_DIR = Path(__file__).resolve().parents[2] / "data" / "sop_rules"
STALE_DAYS = 180
CHECK_IN_PLATFORM = "Check in the platform"


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, RuleEntry], str]:
    entries: dict[str, RuleEntry] = {}
    h = hashlib.sha256()
    for platform in PLATFORMS:
        raw = (RULES_DIR / f"{platform}.json").read_bytes()
        h.update(raw)
        for item in json.loads(raw):
            e = RuleEntry.model_validate(item)
            if e.platform != platform or e.key in entries:
                raise ValueError(f"sop rule {e.key}: wrong file or duplicate key")
            entries[e.key] = e
    return entries, h.hexdigest()


def all_rules() -> dict[str, RuleEntry]:
    return _load()[0]


def digest() -> str:
    return _load()[1]


def get(key: str) -> RuleEntry | None:
    return all_rules().get(key)


def limit(key: str) -> int:
    """A text_limit rule's number. Raises KeyError if the catalogue lost it (a test pins every key the code uses)."""
    e = all_rules()[key]
    if e.kind != "text_limit" or not isinstance(e.value, int):
        raise KeyError(f"{key} is not a numeric text_limit")
    return e.value


def ref(e: RuleEntry, today: date | None = None) -> dict:
    today = today or date.today()
    return {
        "key": e.key,
        "status": e.status,
        "as_of": e.as_of.isoformat(),
        "source_url": str(e.source_url) if e.source_url else None,
        "source_note": e.source_note,
        "stale": (today - e.as_of).days > STALE_DAYS,
    }


def categories(platform: str, kind: str | None) -> list[dict]:
    """Catalogue categories that fit this kind of business, best first. Empty = nothing curated: check in the platform."""
    found = [
        (e.ranks[kind], e)
        for e in all_rules().values()
        if e.platform == platform and e.kind == "category" and kind in e.ranks
    ]
    return [{"name": e.value, "rank": r, **ref(e)} for r, e in sorted(found, key=lambda x: (x[0], x[1].key))]
