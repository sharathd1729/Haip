"""Yaad folders (owner spec 15 Nov): the person makes folders (never Yaad), each with a name, keywords and a sorting rule in
their own words. A summarised call is filed into every folder whose keywords appear in it (no AI) or whose rule the model
says it fits (task `personal_folder`, Gemini Flash-Lite, never NVIDIA; prompt personal_folder.jinja). The person can add a
call by hand or take one out; a call taken out keeps its row with excluded=True, so sorting never puts it back. Calls in no
folder are "Unclassified". Ask Yaad can be limited to one folder's calls.

Tables yaad_folders / yaad_folder_calls (migration 205, models/yaad_folder.py).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from app.adapters.llm import get_llm
from app.models.call import Call
from app.models.yaad_folder import YaadFolder, YaadFolderCall
from app.services import personal_calls as pc
from app.services.call_analysis import _run_async

log = structlog.get_logger()

LLM_TASK = "personal_folder"  # Gemini Flash-Lite, never NVIDIA
COLORS = ("mango", "tomato", "leaf", "sky", "plum", "stone")
MAX_FOLDERS = 50
MAX_KEYWORDS = 20
RESORT_DAYS = 90
RESORT_LIMIT = 200
AI_BATCH = 20

_env = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "prompts")))
FILE_TOOL = {
    "name": "file_calls",
    "description": "The folders each call belongs in",
    "input_schema": {
        "type": "object",
        "properties": {
            "calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "call": {"type": "integer"},
                        "folders": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["call", "folders"],
                },
            }
        },
        "required": ["calls"],
    },
}


# ─── Folders ─────────────────────────────────────────────────────────────────


def clean(fields: dict) -> dict:
    """Name, colour, keywords (trimmed, unique, case-insensitive, <= 20) and rule, only the ones given."""
    out: dict = {}
    if "name" in fields:
        out["name"] = (fields["name"] or "").strip()[:80]
        if not out["name"]:
            raise ValueError("Give the folder a name.")
    if "color" in fields:
        out["color"] = fields["color"] if fields["color"] in COLORS else "mango"
    if "keywords" in fields:
        seen, words = set(), []
        for w in fields["keywords"] or []:
            w = (w or "").strip()[:40]
            if w and w.lower() not in seen:
                seen.add(w.lower())
                words.append(w)
        out["keywords"] = words[:MAX_KEYWORDS]
    if "prompt" in fields:
        out["prompt"] = (fields["prompt"] or "").strip()[:1000]
    return out


def create(db: Session, tenant_id: str, user_id: str, fields: dict) -> YaadFolder:
    if db.query(func.count(YaadFolder.id)).filter(YaadFolder.tenant_id == tenant_id).scalar() >= MAX_FOLDERS:
        raise ValueError(f"You can have up to {MAX_FOLDERS} folders.")
    data = clean({"keywords": [], "prompt": "", "color": "mango", **fields})
    if "name" not in data:
        raise ValueError("Give the folder a name.")
    folder = YaadFolder(tenant_id=tenant_id, created_by=user_id, **data)
    db.add(folder)
    db.flush()
    return folder


def get(db: Session, tenant_id: str, folder_id: str) -> YaadFolder | None:
    return db.query(YaadFolder).filter_by(id=folder_id, tenant_id=tenant_id).first()


def _in_folder(tenant_id: str):
    return and_(YaadFolderCall.tenant_id == tenant_id, YaadFolderCall.excluded.is_(False))


def listing(db: Session, tenant_id: str) -> dict:
    """Folders with how many calls each holds, plus the Unclassified count (summarised calls in no folder)."""
    counts = dict(
        db.query(YaadFolderCall.folder_id, func.count(YaadFolderCall.id))
        .filter(_in_folder(tenant_id))
        .group_by(YaadFolderCall.folder_id)
        .all()
    )
    folders = db.query(YaadFolder).filter(YaadFolder.tenant_id == tenant_id).order_by(YaadFolder.name).all()
    unclassified = (
        db.query(func.count(Call.id))
        .filter(Call.tenant_id == tenant_id, Call.ai_insights.isnot(None), ~in_any_folder(tenant_id))
        .scalar()
    )
    return {"folders": [view(f, counts.get(f.id, 0)) for f in folders], "unclassified": unclassified}


def view(f: YaadFolder, count: int | None = None) -> dict:
    out = {"id": f.id, "name": f.name, "color": f.color, "keywords": f.keywords or [], "prompt": f.prompt or ""}
    if count is not None:
        out["count"] = count
    return out


# ─── Which calls ─────────────────────────────────────────────────────────────


def in_folder(tenant_id: str, folder_id: str):
    """A filter on Call: the call is in this folder (not taken out)."""
    return exists().where(
        _in_folder(tenant_id), YaadFolderCall.folder_id == folder_id, YaadFolderCall.call_id == Call.id
    )


def in_any_folder(tenant_id: str):
    return exists().where(_in_folder(tenant_id), YaadFolderCall.call_id == Call.id)


def folders_of(db: Session, tenant_id: str, call_id: str) -> list[dict]:
    rows = (
        db.query(YaadFolder)
        .join(YaadFolderCall, YaadFolderCall.folder_id == YaadFolder.id)
        .filter(_in_folder(tenant_id), YaadFolderCall.call_id == call_id)
        .order_by(YaadFolder.name)
        .all()
    )
    return [{"id": f.id, "name": f.name, "color": f.color} for f in rows]


def _row(db: Session, tenant_id: str, folder_id: str, call_id: str) -> YaadFolderCall | None:
    return db.query(YaadFolderCall).filter_by(tenant_id=tenant_id, folder_id=folder_id, call_id=call_id).first()


def put(db: Session, tenant_id: str, folder_id: str, call_id: str) -> None:
    """The person adds a call (or brings back one they took out)."""
    row = _row(db, tenant_id, folder_id, call_id)
    if row is None:
        db.add(YaadFolderCall(tenant_id=tenant_id, folder_id=folder_id, call_id=call_id, source="manual"))
    else:
        row.excluded, row.source = False, "manual"


def take_out(db: Session, tenant_id: str, folder_id: str, call_id: str) -> None:
    """The person takes a call out; the row stays (excluded) so automatic sorting never files it here again."""
    row = _row(db, tenant_id, folder_id, call_id)
    if row is None:
        db.add(
            YaadFolderCall(tenant_id=tenant_id, folder_id=folder_id, call_id=call_id, source="manual", excluded=True)
        )
    else:
        row.excluded = True


# ─── Automatic sorting ───────────────────────────────────────────────────────


def call_text(call: Call, contact: str = "") -> str:
    m = pc.memory_of(call) or {}
    parts = [contact, m.get("title", ""), m.get("decision", ""), " ".join(m.get("tags") or [])]
    parts += [p.get("name", "") + " " + p.get("role", "") for p in m.get("participants") or []]
    for s in m.get("sections") or []:
        parts += [s.get("heading", "")] + list(s.get("bullets") or [])
    parts += [a.get("text", "") for a in m.get("action_items") or []]
    return " ".join(p for p in parts if p)


def keyword_match(folder: YaadFolder, text: str) -> bool:
    """A keyword as a whole word or phrase, any case ("tile" matches "tile", not "tilt"; "tiles" needs its own word)."""
    low = text.lower()
    return any(re.search(rf"(?<!\w){re.escape(k.lower())}(?!\w)", low) for k in folder.keywords or [] if k.strip())


def _ai_file(folders: list[YaadFolder], calls: list[tuple[Call, str]], owner_name: str) -> dict[int, set[int]]:
    """{call index: {folder index}} for calls the model says fit a folder's rule. Any model failure = nothing filed."""
    system = _env.get_template("personal_folder.jinja").render(owner_name=owner_name, folders=folders)
    lines = []
    for n, (c, contact) in enumerate(calls, 1):
        m = pc.memory_of(c) or {}
        lines.append(f"[{n}] {m.get('title', '')} · with {contact or 'unknown'} · {call_text(c)[:600]}")
    try:
        out = _run_async(
            get_llm(LLM_TASK).complete(
                system_prompt=system, user_message="CALLS\n" + "\n".join(lines), tools=[FILE_TOOL], max_tokens=1500
            )
        )
    except Exception as exc:  # noqa: BLE001 -- sorting is a convenience: keyword matches still stand
        log.warning("personal_folder_ai_failed", error=str(exc)[:200])
        return {}
    result: dict[int, set[int]] = {}
    for item in (out.get("tool_use") or {}).get("calls") or []:
        i = item.get("call") if isinstance(item, dict) else None
        if isinstance(i, int) and 1 <= i <= len(calls):
            result[i - 1] = {f - 1 for f in item.get("folders") or [] if isinstance(f, int) and 1 <= f <= len(folders)}
    return result


def sort_calls(
    db: Session, tenant_id: str, calls: list[Call], folders: list[YaadFolder], *, owner_name: str, contact=None
) -> int:
    """File each summarised call into the folders it fits, skipping any folder that already has a row for it (filed, or
    taken out by the person). Keywords first (no AI); folders with a rule ask the model in batches. Returns rows added."""
    if not folders or not calls:
        return 0
    contact = contact or (lambda c: "")
    have = {
        (fid, cid)
        for fid, cid in db.query(YaadFolderCall.folder_id, YaadFolderCall.call_id).filter(
            YaadFolderCall.tenant_id == tenant_id,
            YaadFolderCall.call_id.in_([c.id for c in calls]),
            YaadFolderCall.folder_id.in_([f.id for f in folders]),
        )
    }
    added: set[tuple[str, str]] = set()
    ask: list[tuple[Call, str]] = []
    for c in calls:
        if not pc.memory_of(c):
            continue
        text = call_text(c, contact(c))
        for f in folders:
            if (f.id, c.id) not in have and keyword_match(f, text):
                added.add((f.id, c.id))
        ask.append((c, contact(c)))
    ruled = [f for f in folders if (f.prompt or "").strip()]
    for start in range(0, len(ask) if ruled else 0, AI_BATCH):
        batch = ask[start : start + AI_BATCH]
        for ci, fis in _ai_file(ruled, batch, owner_name).items():
            for fi in fis:
                key = (ruled[fi].id, batch[ci][0].id)
                if key not in have:
                    added.add(key)
    for fid, cid in added:
        db.add(YaadFolderCall(tenant_id=tenant_id, folder_id=fid, call_id=cid, source="auto"))
    return len(added)


def recent_calls(db: Session, tenant_id: str, folder: YaadFolder | None = None) -> list[Call]:
    """Summarised calls of the last RESORT_DAYS (newest first, <= RESORT_LIMIT) that have no row for `folder` yet."""
    q = db.query(Call).filter(
        Call.tenant_id == tenant_id,
        Call.ai_insights.isnot(None),
        Call.created_at >= datetime.now(UTC) - timedelta(days=RESORT_DAYS),
    )
    if folder is not None:
        q = q.filter(~exists().where(YaadFolderCall.folder_id == folder.id, YaadFolderCall.call_id == Call.id))
    return [c for c in q.order_by(Call.created_at.desc()).limit(RESORT_LIMIT).all() if pc.memory_of(c)]


def all_folders(db: Session, tenant_id: str) -> list[YaadFolder]:
    return db.query(YaadFolder).filter(YaadFolder.tenant_id == tenant_id).all()


def folder_call_ids(db: Session, tenant_id: str, folder_id: str):
    return select(YaadFolderCall.call_id).where(_in_folder(tenant_id), YaadFolderCall.folder_id == folder_id)
