"""Instagram profile score out of 100 (Instagram toolkit phase 3): twelve items, a fix for every point lost.

Rubric adapted from Jakeschincariol/instagram-agent-skill `skills/ig-profile/rubric.json` (MIT, Copyright (c) 2026 Jake
Schincariol; docs/marketing-website/THIRD_PARTY_NOTICES.md). The SAME items are the steps of the dynamic SOP
`instagram_profile` (services/sops/catalogue.py, each step carries its points), so ticking a step raises the score:

  * measured items (name, bio, link, handle, recent posts) are judged by the SOP's automatic checks, which read the
    workspace's own Instagram through its own token from Celery (services/sops/checks.py) and store their points;
  * the rest (pinned posts, highlights, grid, photo, category/contact, stories) score full marks once every step of the
    item is ticked done (a skipped step scores nothing).

Nothing here calls Instagram: `score()` only reads the checklist's stored progress, so it is safe in a request handler.
"""
import json
import re
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

RUBRIC = json.loads(Path(__file__).with_name("marketing_profile_rubric.json").read_text(encoding="utf-8"))
ITEMS = {i["id"]: i for i in RUBRIC["items"]}
STEP_POINTS = {i["steps"][0]: i["points"] for i in RUBRIC["items"]}      # the step that carries an item's points
STAY_WORDS = re.compile(r"(?i)\b(stay|stays|villa|villas|caravan|homestay|resort|hotel|cottage|cottages|camp|camping|"
                        r"retreat|farmstay|bnb|b&b|boutique|lodge|glamping|suites?|rooms?|estate|bungalow|houseboat)\b")


def _sep_or_stay(text: str, city: Optional[str]) -> bool:
    return bool(re.search(r"[|·•—-]", text) or STAY_WORDS.search(text) or (city and city.lower() in text.lower()))


# ── Measured items (pure; called by the SOP checks with the account's fields) ───────────────────────────────────────

def name_points(name: str, brand: str, city: Optional[str] = None) -> tuple[int, str]:
    name = (name or "").strip()
    if not name:
        return 0, "The Name field is empty."
    if _sep_or_stay(name, city) and name.casefold() != (brand or "").strip().casefold():
        return 12, f"“{name}” says what you are."
    return 4, f"“{name}” is a name only; guests search for what you are and where."


def bio_line_points(bio: str, city: Optional[str] = None) -> tuple[int, str]:
    first = (bio or "").strip().split("\n", 1)[0].strip()
    if not first:
        return 0, "The bio is empty."
    if first.count("|") >= 2 or first.count("•") >= 2:
        return 4, "The first line is a list between bars, not a sentence."
    if len(first) >= 20 and (STAY_WORDS.search(first) or (city and city.lower() in first.lower()) or
                             re.search(r"(?i)\b(you|your|families|couples|guests|friends)\b", first)):
        return 12, "The first line says who it is for and what they get."
    return 6, "The first line does not say who the stay is for or what they get."


def bio_body_points(bio: str) -> tuple[int, str]:
    parts = (bio or "").strip().split("\n", 1)
    rest = parts[1].strip() if len(parts) > 1 else ""
    if not rest and len((bio or "").strip()) > 60:        # one long line: a second sentence counts as the body
        sentences = re.split(r"(?<=[.!?])\s+", bio.strip())
        rest = " ".join(sentences[1:])
    if not rest:
        return 0, "Nothing after the first line: no proof and no way to book."
    if rest.count("|") >= 2:
        return 4, "The rest of the bio is a list between bars."
    return (8, "The bio carries proof or how to book.") if len(rest) >= 15 else (4, "The rest of the bio is very short.")


def link_points(website: str) -> tuple[int, str]:
    return (8, f"Links to {website}.") if (website or "").strip() else (0, "No link on the profile.")


def handle_points(username: str) -> tuple[int, str]:
    u = (username or "").strip().lower()
    if not u:
        return 0, "HAIP could not read the handle."
    if "__" in u or ".." in u or re.search(r"[a-z]\d+[a-z]", u) or len(u) > 24:
        return 3, f"@{u} is hard to say or spell after hearing it once."
    return 6, f"@{u} is easy to say."


# ── Score (reads the checklist only) ─────────────────────────────────────────────────────────────────────────────────

def _instance(db: Session, tenant_id: str):
    from app.models.sop import SopInstance
    return (db.query(SopInstance).filter(SopInstance.tenant_id == tenant_id, SopInstance.template_key == "instagram_profile",
                                         SopInstance.status != "archived")
            .order_by(SopInstance.created_at.desc()).first())


def score(db: Session, tenant) -> dict:
    """{score, total, started, sop_id, items: [{id, label, points, max, source, detail, fix}]} for this workspace."""
    from app.services.sops import service as sop_svc

    inst = _instance(db, tenant.id)
    steps = {s["key"]: s for s in sop_svc._steps(db, inst)} if inst is not None else {}
    items = []
    for item in RUBRIC["items"]:
        got, source, detail = 0, "todo", "Not done yet."
        rows = [steps.get(k) for k in item["steps"]]
        main = rows[0]
        check = (main or {}).get("check_result") or {}
        if item["measured"] and isinstance(check.get("points"), int):
            got, source, detail = min(check["points"], item["points"]), "measured", check.get("detail") or ""
        elif rows and all(r is not None and r["status"] == "done" for r in rows):
            got, source, detail = item["points"], "checklist", "Ticked on the checklist."
        elif check.get("result") == "unknown":
            detail = check.get("detail") or detail
        items.append({"id": item["id"], "label": item["label"], "points": got, "max": item["points"], "source": source,
                      "detail": detail, "fix": item["fix"] if got < item["points"] else None})
    items_sorted = sorted(items, key=lambda i: i["points"] - i["max"])      # most points lost first
    return {"score": sum(i["points"] for i in items), "total": RUBRIC["total"], "started": inst is not None,
            "sop_id": inst.id if inst is not None else None, "items": items_sorted}
