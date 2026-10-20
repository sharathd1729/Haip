"""The website page document: spec, validation and sanitising.

website_blocks.json is the single spec of every section and its fields; frontend/src/site-blocks/blocks.json must be an
identical copy (tests/test_website_blocks.py compares them). A document is:

    {"schema": 1,
     "theme": {"pack": "malnad", "personality": "calm"},
     "site":  {"name", "tagline", "logo", "contact": {"phone","whatsapp","email","address"}, "social": {...}},
     "pages": [{"id","key","title","path","nav","seo":{"title","description"},
                "content": [{"type": "Hero", "props": {"id", "layout", "background", ...fields}}]}]}

validate_doc() never trusts its input (an editor, an AI patch, a restore): unknown sections and fields are dropped,
text is trimmed to its limit, links must be internal paths or https/tel/mailto/wa, images must be "asset:<id>"
references (checked against the tenant's active media by the caller), and the required pages always exist.
"""
import copy
import json
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

SPEC_PATH = Path(__file__).with_name("website_blocks.json")
SCHEMA = 1
PATH_RE = re.compile(r"^/[a-z0-9\-/\[\]]{0,80}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ASSET_RE = re.compile(r"^asset:[0-9a-fA-F\-]{36}$")
LINK_PREFIXES = ("/", "https://", "tel:", "mailto:", "wa:", "#")
MAX_PAGES = 30
MAX_BLOCKS_PER_PAGE = 30


@lru_cache(maxsize=1)
def spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def blocks() -> dict:
    return spec()["blocks"]


def system_pages() -> dict:
    return spec()["system_pages"]


def new_id(prefix: str = "b") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def _options(field: dict) -> list[str]:
    if "options" in field:
        return list(field["options"])
    return list(spec().get(field.get("options_from", ""), []))


def _clean_text(v: Any, limit: int) -> str:
    if v is None:
        return ""
    s = str(v).replace("\r\n", "\n").replace("\x00", "").strip()
    return s[:limit]


def clean_link(v: Any) -> str:
    s = _clean_text(v, 500)
    if not s:
        return ""
    if s.startswith("//") or not s.startswith(LINK_PREFIXES):
        return ""
    if s.startswith("/") and not PATH_RE.match(s.split("?")[0].split("#")[0] or "/"):
        return ""
    return s


def clean_field(field: dict, value: Any, problems: list[str], where: str) -> Any:
    kind = field["kind"]
    limit = int(field.get("max", 2000))
    if kind in ("text", "textarea"):
        s = _clean_text(value, limit)
        if kind == "text":
            s = s.replace("\n", " ")
        return s
    if kind == "lines":
        raw = value if isinstance(value, list) else str(value or "").split("\n")
        items = [_clean_text(x, limit).replace("\n", " ") for x in raw]
        return [x for x in items if x][: int(field.get("max_items", 10))]
    if kind == "toggle":
        return bool(value)
    if kind == "select":
        opts = _options(field)
        s = str(value) if value is not None else ""
        return s if s in opts else (opts[0] if opts else "")
    if kind == "tags":
        opts = set(_options(field))
        raw = value if isinstance(value, list) else str(value or "").replace(",", " ").split()
        seen: list[str] = []
        for x in raw:
            if x in opts and x not in seen:
                seen.append(x)
        return seen[: int(field.get("max_items", 12))]
    if kind == "link":
        return clean_link(value)
    if kind == "date":
        s = _clean_text(value, 10)
        return s if DATE_RE.match(s) else ""
    if kind == "image":
        s = _clean_text(value, 60)
        return s if ASSET_RE.match(s) else ""
    if kind == "images":
        raw = value if isinstance(value, list) else []
        out = [x for x in (_clean_text(v, 60) for v in raw) if ASSET_RE.match(x)]
        return list(dict.fromkeys(out))[: int(field.get("max_items", 12))]
    if kind == "list":
        raw = value if isinstance(value, list) else []
        out = []
        for i, item in enumerate(raw[: int(field.get("max_items", 10))]):
            if not isinstance(item, dict):
                continue
            row = {}
            for sub in field["item"]:
                row[sub["key"]] = clean_field(sub, item.get(sub["key"]), problems, f"{where}[{i}]")
            if all(row.get(sub["key"]) for sub in field["item"] if sub.get("required")):
                out.append(row)
            else:
                problems.append(f"{where}: an item missing a required value was left out")
        return out
    problems.append(f"{where}: unknown field kind {kind}")
    return None


def clean_block(raw: Any, problems: list[str], *, allow_system: Optional[str] = None) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    btype = raw.get("type")
    spec_b = blocks().get(btype)
    if not spec_b:
        problems.append(f"Unknown section '{btype}' was removed")
        return None
    if spec_b.get("system") and btype != allow_system:
        problems.append(f"'{spec_b['label']}' can only sit on its own page and was removed")
        return None
    props_in = raw.get("props") if isinstance(raw.get("props"), dict) else {}
    bid = str(props_in.get("id") or "")
    props: dict = {"id": bid if re.match(r"^[A-Za-z0-9_\-]{3,40}$", bid) else new_id()}
    layouts = spec_b.get("layouts") or []
    lay = props_in.get("layout")
    props["layout"] = lay if lay in layouts else (layouts[0] if layouts else "")
    bg = props_in.get("background")
    props["background"] = bg if bg in spec()["backgrounds"] else "page"
    for f in spec_b["fields"]:
        props[f["key"]] = clean_field(f, props_in.get(f["key"]), problems, f"{spec_b['label']}.{f['label']}")
    return {"type": btype, "props": props}


def _clean_page(raw: dict, problems: list[str], seen_paths: set, seen_ids: set) -> Optional[dict]:
    key = raw.get("key") if raw.get("key") in system_pages() else None
    sp = system_pages().get(key) if key else None
    path = sp["path"] if sp else _clean_text(raw.get("path"), 80).lower()
    if not PATH_RE.match(path) or "[" in path and not sp:
        problems.append(f"Page '{raw.get('title')}' has an invalid address and was removed")
        return None
    if path in seen_paths:
        problems.append(f"Two pages used {path}; the second was removed")
        return None
    pid = str(raw.get("id") or "")
    if not re.match(r"^[a-z0-9\-]{2,60}$", pid) or pid in seen_ids:
        pid = key or new_id("p")
    seen_paths.add(path)
    seen_ids.add(pid)
    seo = raw.get("seo") if isinstance(raw.get("seo"), dict) else {}
    allow_system = sp.get("block") if sp else None
    content = []
    block_ids: set = set()
    for b in (raw.get("content") or [])[:MAX_BLOCKS_PER_PAGE]:
        cb = clean_block(b, problems, allow_system=allow_system)
        if not cb:
            continue
        if cb["props"]["id"] in block_ids:
            cb["props"]["id"] = new_id()
        block_ids.add(cb["props"]["id"])
        content.append(cb)
    if allow_system and not any(b["type"] == allow_system for b in content):
        content.insert(0, clean_block({"type": allow_system, "props": {}}, problems, allow_system=allow_system))
    return {
        "id": pid,
        "key": key or "",
        "title": _clean_text(raw.get("title"), 60) or (sp["title"] if sp else "Page"),
        "path": path,
        "nav": bool(raw.get("nav")),
        "seo": {"title": _clean_text(seo.get("title"), 70), "description": _clean_text(seo.get("description"), 170)},
        "content": content,
    }


def validate_doc(doc: Any) -> tuple[dict, list[str]]:
    """Return (clean document, problems). Never raises on bad input; problems say what was dropped or repaired."""
    problems: list[str] = []
    doc = doc if isinstance(doc, dict) else {}
    s = spec()
    theme_in = doc.get("theme") if isinstance(doc.get("theme"), dict) else {}
    theme = {
        "pack": theme_in.get("pack") if theme_in.get("pack") in s["packs"] else s["packs"][0],
        "personality": theme_in.get("personality") if theme_in.get("personality") in s["personalities"] else s["personalities"][0],
    }
    site_in = doc.get("site") if isinstance(doc.get("site"), dict) else {}
    contact_in = site_in.get("contact") if isinstance(site_in.get("contact"), dict) else {}
    social_in = site_in.get("social") if isinstance(site_in.get("social"), dict) else {}
    site = {
        "name": _clean_text(site_in.get("name"), 80) or "Our stay",
        "tagline": _clean_text(site_in.get("tagline"), 120),
        "logo": _clean_text(site_in.get("logo"), 60) if ASSET_RE.match(str(site_in.get("logo") or "")) else "",
        "contact": {k: _clean_text(contact_in.get(k), 300 if k == "address" else 80) for k in ("phone", "whatsapp", "email", "address")},
        "social": {k: v for k, v in ((k, clean_link(social_in.get(k))) for k in ("instagram", "facebook", "youtube")) if v.startswith("https://")},
    }
    pages: list[dict] = []
    seen_paths: set = set()
    seen_ids: set = set()
    for raw in (doc.get("pages") or [])[:MAX_PAGES]:
        if isinstance(raw, dict):
            p = _clean_page(raw, problems, seen_paths, seen_ids)
            if p:
                pages.append(p)
    for key, sp in system_pages().items():
        if sp.get("required") and not any(p["key"] == key for p in pages):
            pages.append(_clean_page({"key": key, "title": sp["title"], "nav": key == "contact", "content": []},
                                     problems, seen_paths, seen_ids))
            problems.append(f"The required '{sp['title']}' page was added")
    pages.sort(key=lambda p: (p["path"] != "/",))
    return {"schema": SCHEMA, "theme": theme, "site": site, "pages": pages}, problems


def asset_ids(doc: dict) -> set[str]:
    """Every media asset id the document references (images, galleries, logo)."""
    found: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, str) and ASSET_RE.match(v):
            found.add(v.split(":", 1)[1])
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(doc)
    return found


def strip_assets(doc: dict, keep: set[str]) -> int:
    """Blank every image reference not in keep (an archived or foreign asset). Returns how many were removed."""
    removed = 0

    def walk(v: Any) -> Any:
        nonlocal removed
        if isinstance(v, str) and ASSET_RE.match(v):
            if v.split(":", 1)[1] in keep:
                return v
            removed += 1
            return ""
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [x for x in (walk(x) for x in v) if x != ""] if all(isinstance(x, str) for x in v) else [walk(x) for x in v]
        return v
    cleaned = walk(doc)
    doc.clear()
    doc.update(cleaned)
    return removed


def find_page(doc: dict, page_id: str) -> Optional[dict]:
    return next((p for p in doc.get("pages", []) if p["id"] == page_id), None)


def copy_doc(doc: dict) -> dict:
    return copy.deepcopy(doc)
