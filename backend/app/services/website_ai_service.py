"""The AI web developer: turns an owner's request (or "write my site") into validated operations on the head draft.

Flow: endpoint creates a SiteAiJob and queues Celery website.ai_job -> run_job() -> one LLM tool call (router task
"website_content", never inline in a request) -> apply_ops() checks every operation against the section spec ->
the result is saved as the head draft (a new draft version if the head was submitted) -> job.result lists what
changed, what was refused and which blocks to highlight. Nothing is published; approval rules are unchanged.
"""
import json
import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.prompt_versions import get_version
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.website import Site, SiteAiJob
from app.services import website_blocks as wb
from app.services import website_version_service as vs
from app.services.website_ai_prompts import EDIT_SYSTEM, EDIT_TOOL, GENERATE_SYSTEM, Changes, rules_for
from app.services.website_service import bookable_properties

TASK = "website_content"
MODULE = "website"
PRICE_RE = re.compile(r"(₹|\bRs\.?\s?\d|\bINR\s?\d|\d+\s?%\s?(off|discount)|\d[\d,]*\s?(rupees|/-))", re.I)
AI_LOCKED_FIELDS = {("Reviews", "items")}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def facts(db: Session, tenant: Tenant) -> dict:
    profile = (tenant.brand_config or {}).get("business_profile") or {}
    keep = ("tagline", "description", "audience", "tone", "usps", "avoid", "languages", "city", "region")
    props = bookable_properties(db, tenant.id)
    return {
        "business": tenant.brand_name or tenant.name, "business_type": tenant.business_type,
        "profile": {k: profile.get(k) for k in keep if profile.get(k)},
        "stays": [{"name": p.name, "type": p.type, "sleeps": int(p.max_adults or 0) + int(p.max_children or 0),
                   "bedrooms": p.bedrooms, "city": p.city, "description": (p.description or "")[:700],
                   "amenities": [a for a in (p.amenities or []) if isinstance(a, str)][:20],
                   "faqs": [f for f in (p.faqs or []) if isinstance(f, dict)][:6]} for p in props[:8]],
    }


def outline(doc: dict) -> dict:
    """What the model may touch: pages and blocks with ids, types and current values (images shown as present/empty)."""
    pages = []
    for p in doc["pages"]:
        blocks = []
        for b in p["content"]:
            vals = {}
            for f in wb.blocks()[b["type"]]["fields"]:
                v = b["props"].get(f["key"])
                vals[f["key"]] = ("[photo]" if v else "[empty]") if f["kind"] in ("image", "images") else v
            blocks.append({"block_id": b["props"]["id"], "type": b["type"], "layout": b["props"].get("layout"), "fields": vals})
        pages.append({"page_id": p["id"], "title": p["title"], "path": p["path"], "seo": p["seo"], "blocks": blocks})
    return {"theme": doc["theme"], "site": {"name": doc["site"]["name"], "tagline": doc["site"]["tagline"]}, "pages": pages}


def spec_summary() -> dict:
    s = wb.spec()
    return {"packs": s["packs"], "personalities": s["personalities"], "icons": s["icons"],
            "sections": {k: {"label": v["label"], "system": bool(v.get("system")), "layouts": v.get("layouts") or [],
                             "fields": [{"key": f["key"], "kind": f["kind"], "max": f.get("max"),
                                         "options": f.get("options") or (s.get(f.get("options_from", "")) if f.get("options_from") else None)}
                                        for f in v["fields"] if f["kind"] not in ("image", "images")]}
                         for k, v in s["blocks"].items()}}


def _coerce(field: dict, raw: Optional[str]):
    """AI values arrive as text; turn them into the field's shape before clean_field trims and checks them."""
    kind = field["kind"]
    if raw is None:
        return None
    if kind == "lines":
        return [x.strip(" -•\t") for x in str(raw).split("\n") if x.strip()]
    if kind == "tags":
        return [x.strip().lower() for x in re.split(r"[,\s]+", str(raw)) if x.strip()]
    if kind == "toggle":
        return str(raw).strip().lower() in ("true", "yes", "1", "on")
    if kind == "list":
        rows = []
        for line in str(raw).split("\n"):
            parts = [x.strip() for x in line.split("|")]
            if len(parts) >= 2 and all(parts[:2]):
                rows.append({sub["key"]: (parts[i] if i < len(parts) else "") for i, sub in enumerate(field["item"])})
        return rows
    return str(raw)


def _has_price(v) -> bool:
    if isinstance(v, str):
        return bool(PRICE_RE.search(v))
    if isinstance(v, list):
        return any(_has_price(x) for x in v)
    if isinstance(v, dict):
        return any(_has_price(x) for x in v.values())
    return False


def apply_ops(doc: dict, ops: list[dict]) -> tuple[dict, list[str], list[str], set[str]]:
    """Return (new doc, changes, refused, changed block ids). Never raises on a bad op; it is refused instead."""
    doc = wb.copy_doc(doc)
    changes, refused, touched = [], [], set()
    aliases: dict[str, str] = {}
    spec = wb.spec()

    def page_of(pid):
        return wb.find_page(doc, aliases.get(pid or "", pid or ""))

    def block_of(page, bid):
        bid = aliases.get(bid, bid)
        return next((b for b in page["content"] if b["props"]["id"] == bid), None) if page else None

    for raw in ops[:40]:
        op = raw.get("op")
        page = page_of(raw.get("page_id"))
        try:
            if op == "set":
                b = block_of(page, raw.get("block_id"))
                if not b:
                    refused.append("A change pointed at a section that doesn't exist.")
                    continue
                f = next((x for x in wb.blocks()[b["type"]]["fields"] if x["key"] == raw.get("field")), None)
                if not f or f["kind"] in ("image", "images"):
                    refused.append(f"'{raw.get('field')}' can't be set on {wb.blocks()[b['type']]['label']}.")
                    continue
                if (b["type"], f["key"]) in AI_LOCKED_FIELDS:
                    refused.append("Reviews are pasted from real guests; the AI doesn't write them.")
                    continue
                val = wb.clean_field(f, _coerce(f, raw.get("value")), [], f["key"])
                if _has_price(val):
                    refused.append("Prices and discounts come from HAIP Bookings, so the AI doesn't write them.")
                    continue
                b["props"][f["key"]] = val
                touched.add(b["props"]["id"])
                changes.append(f"{wb.blocks()[b['type']]['label']} on {page['title']}: {f['label'].split(' (')[0].lower()} updated")
            elif op == "add_block":
                btype = raw.get("block_type")
                bs = wb.blocks().get(btype)
                if not page or not bs or bs.get("system"):
                    refused.append(f"A '{btype}' section can't be added there.")
                    continue
                new = wb.clean_block({"type": btype, "props": {}}, [])
                after = block_of(page, raw.get("after_block_id")) if raw.get("after_block_id") else None
                idx = page["content"].index(after) + 1 if after else len(page["content"])
                page["content"].insert(idx, new)
                if raw.get("block_id"):
                    aliases[raw["block_id"]] = new["props"]["id"]
                touched.add(new["props"]["id"])
                changes.append(f"Added a {bs['label']} section to {page['title']}")
            elif op == "remove_block":
                b = block_of(page, raw.get("block_id"))
                if not b or wb.blocks()[b["type"]].get("system"):
                    refused.append("That section can't be removed.")
                    continue
                page["content"].remove(b)
                changes.append(f"Removed the {wb.blocks()[b['type']]['label']} section from {page['title']}")
            elif op == "move_block":
                b = block_of(page, raw.get("block_id"))
                if not b:
                    refused.append("A move pointed at a section that doesn't exist.")
                    continue
                page["content"].remove(b)
                page["content"].insert(max(0, min(int(raw.get("to_index") or 0), len(page["content"]))), b)
                touched.add(b["props"]["id"])
                changes.append(f"Moved {wb.blocks()[b['type']]['label']} on {page['title']}")
            elif op == "add_page":
                path = "/" + re.sub(r"[^a-z0-9\-]+", "-", str(raw.get("path") or raw.get("title") or "").lower().strip("/")).strip("-")
                if path == "/" or any(p["path"] == path for p in doc["pages"]) or len(doc["pages"]) >= wb.MAX_PAGES:
                    refused.append(f"A page at {path} can't be added.")
                    continue
                pid = path.strip("/")[:60] or wb.new_id("p")
                doc["pages"].append({"id": pid, "key": "", "title": str(raw.get("title") or pid)[:60], "path": path,
                                     "nav": True, "seo": {"title": "", "description": ""}, "content": []})
                if raw.get("page_id"):
                    aliases[raw["page_id"]] = pid
                changes.append(f"Added the page {path}")
            elif op == "set_seo":
                if not page or raw.get("field") not in ("title", "description"):
                    refused.append("A search preview change pointed at a missing page.")
                    continue
                val = str(raw.get("value") or "")[:70 if raw["field"] == "title" else 170]
                if _has_price(val):
                    refused.append("Search previews can't carry prices.")
                    continue
                page["seo"][raw["field"]] = val
                changes.append(f"Search {raw['field']} for {page['title']} written")
            elif op == "set_site":
                if raw.get("field") == "tagline" and not _has_price(raw.get("value")):
                    doc["site"]["tagline"] = str(raw.get("value") or "")[:120]
                    changes.append("Site tagline updated")
            elif op == "set_theme":
                if raw.get("pack") in spec["packs"]:
                    doc["theme"]["pack"] = raw["pack"]
                if raw.get("personality") in spec["personalities"]:
                    doc["theme"]["personality"] = raw["personality"]
                changes.append(f"Look set to {doc['theme']['pack']} / {doc['theme']['personality']}")
            else:
                refused.append(f"Unknown change '{op}'.")
        except (TypeError, ValueError, KeyError):
            refused.append("One change was malformed and skipped.")
    # add_page ids may be referenced by later ops in the same batch (resolved by find_page on the new id)
    clean, _ = wb.validate_doc(doc)
    return clean, changes, refused, touched


def _llm(tenant: Tenant, system: str, user: str) -> tuple[Changes, dict, str]:
    from app.services.marketing_ai_service import _call
    data, raw, provider = _call(TASK, tenant.id, system, user, EDIT_TOOL)
    return Changes.model_validate(data), raw, provider


def run_job(db: Session, tenant_id: str, job_id: str) -> SiteAiJob:
    from app.services import usage_service
    from app.services.price_policy import price_mode

    job = db.query(SiteAiJob).filter_by(id=job_id, tenant_id=tenant_id).one()
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    site = db.query(Site).filter_by(id=job.site_id, tenant_id=tenant_id).one()
    job.status, job.prompt_version = "running", get_version("website_generate" if job.kind == "generate" else "website_edit")
    head = vs.head(db, site)
    system = (GENERATE_SYSTEM if job.kind == "generate" else EDIT_SYSTEM).format(price_rule=rules_for(price_mode(tenant)))
    user = (f"BUSINESS FACTS:\n{json.dumps(facts(db, tenant), ensure_ascii=False, default=str)}\n\n"
            f"SECTION SPEC:\n{json.dumps(spec_summary(), ensure_ascii=False)}\n\n"
            f"OUTLINE (current draft):\n{json.dumps(outline(head.doc), ensure_ascii=False)}\n\n"
            + (f"OWNER'S BRIEF: {job.request}" if job.kind == "generate" and job.request else
               "TASK: write the whole site." if job.kind == "generate" else f"OWNER'S REQUEST: {job.request}"))
    try:
        result, raw, provider = _llm(tenant, system, user)
    except ValidationError:
        job.status, job.error = "failed", "The AI's answer didn't match the expected format. Try again."
        return job
    usage_service.record_llm(db, tenant_id, MODULE, raw, provider=provider, ref_type="site_ai_job", ref_id=job.id)
    job.model = raw.get("model")
    db.refresh(site)
    head = vs.head(db, site)          # apply to the latest draft: the owner may have kept editing while the AI worked
    new_doc, changes, refused, touched = apply_ops(head.doc, [o.model_dump() for o in result.ops])
    refused = list(dict.fromkeys(refused + [r for r in result.refused if r]))[:12]
    version_id = None
    if changes:
        v, _problems = vs.save_draft(db, site, new_doc, head.sha256, actor_id=job.created_by, origin="ai",
                                     note=f"AI: {(job.request or 'site copy')[:200]}")
        version_id = v.id
    job.result = {"reply": result.reply[:600], "changes": changes[:60], "refused": refused, "touched": sorted(touched)}
    job.result_version_id, job.status, job.error = version_id, "ready", None
    return job


def mark_failed(db: Session, tenant_id: str, job_id: str, message: str) -> None:
    job = db.query(SiteAiJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job:
        job.status, job.error = "failed", message[:500]


def job_out(job: SiteAiJob) -> dict:
    return {"id": job.id, "kind": job.kind, "request": job.request, "status": job.status, "result": job.result,
            "error": job.error, "result_version_id": job.result_version_id,
            "created_at": job.created_at.isoformat() if job.created_at else None}
