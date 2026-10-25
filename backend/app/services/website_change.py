"""'Change something': the owner types a change to their website in plain words ("use the night photo on top", "add our
reviews", "change my WhatsApp number"). The AI (Celery website.builder_step, job kind "change"; never in a request handler)
answers with a short list of edits; HAIP applies them in code to a copy of the draft and validates the result as a
SiteSpec (types, layouts, AA contrast, no typed prices). An answer that fails gets one retry with the problems, on the
stronger model; failing again ends the job with a plain error. The draft is saved as usual (nothing goes live until it is
published) and the job keeps a copy of the page from before the change, so the screen can offer Undo (undo()).

Small task, small model (owner rule): attempt 1 runs on "website_change" (Gemini Flash-Lite), the retry on "website_plan".
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.user import User
from app.models.website import Site, SiteAiJob
from app.schemas.site_builder import ChangeOp, ChangeOut
from app.schemas.site_spec import SLOTS, catalogue
from app.services import website_spec_service as wspec
from app.services.website_service import WebsiteError

TASK, RETRY_TASK, MODULE = "website_change", "website_plan", "website"
MAX_OPS = 12
TEXT_SLOTS = ("eyebrow", "heading", "headline", "subhead", "intro", "text", "cta_label")
CONTACT_FIELDS = ("phone", "whatsapp", "email", "address")

SYSTEM = """You change a small business's website for its owner, who is not technical. Read the owner's request and answer
with the smallest set of edits that does exactly what they asked, through the tool.

Edits you can make (ops):
- set_text: change one text (field = eyebrow, heading, headline, subhead, intro, text or cta_label) of one section.
- add_section: add a section (section_type + variant from the CATALOGUE) at a position. Sections show the business's own
  data from HAIP (stays, trips, photos, reviews, FAQs); you never type that data.
- remove_section, move_section (position = new 0-based place on the page), set_layout (variant from the CATALOGUE).
- set_contact: field = phone, whatsapp, email or address, value = the new value exactly as the owner gave it.
- set_look: palette and/or display (heading font) and/or radius, only names from the lists.
- set_photo: value = a photo id from PHOTOS for the hero section (use the photo whose description fits the request).

Rules: change only what was asked. Never invent facts, awards, prices, ratings or offers; never type a price (prices only
come from HAIP's price rules). If the request can't be done with these edits (e.g. "take payments", "add a blog"), make no
edits and say so kindly in one sentence. The reply is one or two short plain sentences an owner understands (no jargon:
say "section", "photo", "button", never "slot", "variant", "spec")."""

TOOL = {"name": "submit_changes", "description": "Return the edits to make and a short reply to the owner.",
        "input_schema": ChangeOut.model_json_schema()}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def request(db: Session, site: Site, actor: User, text: str) -> SiteAiJob:
    from app.services import website_builder_service as wbs
    from app.services import website_version_service as vs
    head = vs.head(db, site)
    if not wspec.is_v2(head.doc):
        raise WebsiteError(409, "not_v2", "Tap \"Make my website\" first; then you can change anything in your own words.")
    wbs._guard_rate(db, site)
    job = SiteAiJob(created_at=_now(), tenant_id=site.tenant_id, site_id=site.id, kind="change", status="pending", request=text,
                    result={"based_on": head.id}, base_version_id=head.id, created_by=actor.id)
    db.add(job)
    db.flush()
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.change_requested", target_type="site_ai_job",
                 target_id=job.id, payload={"chars": len(text)})
    return job


def _sections(doc: dict) -> list[dict]:
    return doc["pages"][0]["sections"]


def _find(doc: dict, section_id: str) -> dict:
    s = next((s for s in _sections(doc) if s["id"] == section_id), None)
    if not s:
        raise ValueError(f"no section '{section_id}' on the page")
    return s


def _new_id(doc: dict, stype: str) -> str:
    ids = {s["id"] for p in doc["pages"] for s in p["sections"]}
    base, n = stype.replace("booking-cta", "cta"), 2
    out = base
    while out in ids:
        out, n = f"{base}-{n}", n + 1
    return out


def _cta_index(doc: dict) -> int:
    secs = _sections(doc)
    return next((i for i, s in enumerate(secs) if s["type"] in ("booking-cta", "contact")), len(secs))


def apply_ops(doc: dict, ops: list[ChangeOp], photo_ids: set[str]) -> dict:
    """A validated copy of `doc` with every edit applied (home page). Raises ValueError / WebsiteError naming the problem."""
    cat = catalogue()
    out = json.loads(json.dumps(doc))
    if len(ops) > MAX_OPS:
        raise ValueError(f"at most {MAX_OPS} edits at once")
    for op in ops:
        if op.op == "set_text":
            s = _find(out, op.section_id)
            if op.field not in TEXT_SLOTS or op.field not in SLOTS[s["type"]].model_fields:
                raise ValueError(f"a {s['type']} section has no '{op.field}' text")
            s["slots"][op.field] = op.value
        elif op.op == "add_section":
            sec = cat["sections"].get(op.section_type)
            if not sec:
                raise ValueError(f"unknown section type '{op.section_type}'")
            variant = op.variant if op.variant in sec["variants"] else sec["variants"][0]
            pos = _cta_index(out) if op.position < 0 else min(op.position, len(_sections(out)))
            _sections(out).insert(pos, {"id": _new_id(out, op.section_type), "type": op.section_type, "variant": variant, "slots": {}})
        elif op.op == "remove_section":
            s = _find(out, op.section_id)
            if s["type"] == "contact" and sum(1 for x in _sections(out) if x["type"] == "contact") == 1:
                raise ValueError("the page must keep its contact section")
            _sections(out).remove(s)
        elif op.op == "move_section":
            s = _find(out, op.section_id)
            _sections(out).remove(s)
            _sections(out).insert(max(0, min(op.position if op.position >= 0 else _cta_index(out), len(_sections(out)))), s)
        elif op.op == "set_layout":
            s = _find(out, op.section_id)
            if op.variant not in cat["sections"][s["type"]]["variants"]:
                raise ValueError(f"'{op.variant}' isn't a layout of {s['type']} ({', '.join(cat['sections'][s['type']]['variants'])})")
            s["variant"] = op.variant
        elif op.op == "set_contact":
            if op.field not in CONTACT_FIELDS:
                raise ValueError(f"contact field must be one of {', '.join(CONTACT_FIELDS)}")
            out["site"]["contact"][op.field] = op.value
        elif op.op == "set_look":
            t = out["tokens"]
            if op.palette:
                if op.palette not in cat["palettes"]:
                    raise ValueError(f"unknown palette '{op.palette}'")
                t["palette"] = op.palette
            if op.display:
                t["display"] = op.display
            if op.radius:
                t["radius"] = op.radius
        elif op.op == "set_photo":
            s = _find(out, op.section_id or "hero")
            if s["type"] != "hero" or op.value not in photo_ids:
                raise ValueError("set_photo needs the hero section and a photo id from PHOTOS")
            s["slots"]["media"] = f"asset:{op.value}"
    return wspec.validate(out)


def _user(doc: dict, photos: list, text: str) -> str:
    cat = catalogue()
    secs = [{"id": s["id"], "type": s["type"], "layout": s["variant"], "texts": {k: v for k, v in s["slots"].items() if k in TEXT_SLOTS and v}}
            for s in _sections(doc)]
    lines = [
        f"OWNER'S REQUEST: {text}",
        f"PAGE SECTIONS (top to bottom): {json.dumps(secs, ensure_ascii=False)}",
        f"CONTACT: {json.dumps(doc['site']['contact'], ensure_ascii=False)}",
        f"LOOK: palette {doc['tokens']['palette'].get('name') if isinstance(doc['tokens']['palette'], dict) else doc['tokens']['palette']}, "
        f"heading font {doc['tokens']['display']}, corners {doc['tokens']['radius']}",
        "CATALOGUE (section type: layouts): " + "; ".join(f"{k}: {', '.join(v['variants'])}" for k, v in cat["sections"].items()),
        "PALETTES: " + ", ".join(f"{k} ({v['label']})" for k, v in cat["palettes"].items()),
        "HEADING FONTS: " + ", ".join(cat["fonts"]["display"]),
        "PHOTOS (id: description): " + ("; ".join(f"{a.id}: {(getattr(a, 'alt_text', None) or 'no description')[:80]}" for a in photos[:40]) or "none"),
    ]
    return "\n".join(lines)


def run(db: Session, tenant_id: str, job: SiteAiJob, site: Site) -> SiteAiJob:
    from app.services import usage_service
    from app.services import website_version_service as vs
    from app.services.marketing_ai_service import _call
    from app.services.marketing_photos import library
    head = vs.head(db, site)
    if not wspec.is_v2(head.doc) or head.id != (job.result or {}).get("based_on"):
        job.status, job.error = "failed", "Your website changed while this ran. Ask again."
        return job
    photos = library(db, tenant_id)
    ids = {a.id for a in photos}
    user = _user(head.doc, photos, job.request or "")
    errors: list[str] = []
    for attempt, task in ((1, TASK), (2, RETRY_TASK)):
        msg = user if not errors else (user + "\n\nYOUR LAST ANSWER FAILED HAIP'S CHECKS:\n- " + "\n- ".join(errors)
                                       + "\nFix every problem and answer again through the tool.")
        data, raw, provider = _call(task, tenant_id, SYSTEM, msg, TOOL)
        usage_service.record_llm(db, tenant_id, MODULE, raw, provider=provider, ref_type="site_ai_job", ref_id=job.id)
        job.model = raw.get("model") or job.model
        try:
            out = ChangeOut.model_validate(data)
            new_doc = apply_ops(head.doc, out.ops, ids) if out.ops else None
            break
        except Exception as exc:  # noqa: BLE001 -- validation problems go back to the model once
            from app.services.website_builder_ai import _problems
            errors = _problems(exc) if not isinstance(exc, ValueError) else [str(exc)]
    else:
        job.status, job.error = "failed", ("I couldn't make that change safely: " + "; ".join(errors))[:500]
        return job
    version_id: Optional[str] = None
    before = json.loads(json.dumps(head.doc))       # save_draft updates this row in place: keep the old page for Undo
    if new_doc is not None:
        v, _ = vs.save_draft(db, site, new_doc, head.sha256, actor_id=job.created_by, origin="ai",
                             note=f"Changed: {(job.request or '')[:150]}")
        version_id = v.id
    job.result = {**(job.result or {}), "artifact": {"reply": out.reply, "edits": len(out.ops), "can_undo": new_doc is not None},
                  "attempts": attempt, "before": before if new_doc is not None else None,
                  "after_sha": vs.head(db, site).sha256 if new_doc is not None else None}
    job.result_version_id, job.status, job.error = version_id, "ready", None
    return job


def undo(db: Session, site: Site, job_id: str, actor: User) -> None:
    """Put the page back as it was before this change, if nothing else changed it since."""
    from app.services import website_version_service as vs
    job = db.query(SiteAiJob).filter_by(id=job_id, tenant_id=site.tenant_id, site_id=site.id, kind="change").first()
    res = (job.result or {}) if job else {}
    if not job or job.status != "ready" or not res.get("before"):
        raise WebsiteError(404, "nothing_to_undo", "There's nothing to undo for that change.")
    head = vs.head(db, site)
    if head.sha256 != res.get("after_sha"):
        raise WebsiteError(409, "changed_since", "Your website changed after this, so it can't be undone on its own.")
    vs.save_draft(db, site, res["before"], head.sha256, actor_id=actor.id, origin="human", note="Undo")
    job.result = {**res, "before": None, "artifact": {**res.get("artifact", {}), "can_undo": False, "undone": True}}
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.change_undone", target_type="site_ai_job",
                 target_id=job.id, payload={})
