"""
X9 — In-app changelog endpoint.

Reads versioned markdown files from app/data/changelog/, parses YAML frontmatter,
and returns a sorted list of changelog entries for the frontend gift-icon modal.
"""

from pathlib import Path
from typing import Any
import re
import structlog

from fastapi import APIRouter, Depends
from app.api.v1.deps import get_current_user
from app.models.user import User

log = structlog.get_logger()
router = APIRouter(prefix="/changelog", tags=["changelog"])

_CHANGELOG_DIR = Path(__file__).parent.parent.parent.parent / "data" / "changelog"


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (metadata_dict, body_markdown)."""
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_block = text[3:end].strip()
    body = text[end + 4:].strip()

    meta: dict[str, Any] = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()

        # Handle quoted strings
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]

        # Handle inline lists like [inbox, calls, workflow]
        if val.startswith("[") and val.endswith("]"):
            items = [t.strip() for t in val[1:-1].split(",")]
            meta[key] = items
        else:
            meta[key] = val

    return meta, body


def _load_entries() -> list[dict[str, Any]]:
    """Load + parse all changelog markdown files, sorted newest-first."""
    if not _CHANGELOG_DIR.exists():
        return []

    entries = []
    for md_file in sorted(_CHANGELOG_DIR.glob("*.md"), reverse=True):
        try:
            text = md_file.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)

            # Extract bullet items from the body for a brief preview list
            bullets: list[str] = []
            for line in body.splitlines():
                line = line.strip()
                # Match **Bold** — description lines
                m = re.match(r"\*\*(.+?)\*\*\s*[—–-]\s*(.+)", line)
                if m:
                    bullets.append({"title": m.group(1).strip(), "detail": m.group(2).strip()})
                if len(bullets) >= 8:
                    break

            entries.append({
                "slug": md_file.stem,
                "date": meta.get("date", ""),
                "title": meta.get("title", md_file.stem),
                "summary": meta.get("summary", ""),
                "version": meta.get("version", ""),
                "tags": meta.get("tags", []),
                "items": bullets,
            })
        except Exception as exc:
            log.warning("changelog_parse_error", file=md_file.name, error=str(exc))

    return entries


@router.get("")
def list_changelog(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return all changelog entries, newest first.
    The frontend uses `version` to compare against localStorage `changelog_last_seen`.
    """
    entries = _load_entries()
    latest_version = entries[0]["version"] if entries else ""
    return {
        "entries": entries,
        "latest_version": latest_version,
        "count": len(entries),
    }
