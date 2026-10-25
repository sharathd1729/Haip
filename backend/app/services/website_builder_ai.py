"""The art director's AI calls (Celery website.builder_step only; never in a request handler).

One tool call per attempt through the router: planning steps on task "website_plan" (Gemini 3.6 Flash), a one-slot copy
polish on "website_copy" (Gemini 3.1 Flash-Lite: small task, small model). Every answer is checked twice: by its step model
(schemas/site_builder.py) and as a SiteSpec (schemas/site_spec.py: types, variants, AA contrast, no typed prices). An answer
that fails gets ONE retry with the problems fed back; failing again ends the job with those problems as the error.
"""
from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.prompt_versions import get_version
from app.models.website import Site, SiteAiJob
from app.schemas.site_builder import CopyOut, Sitemap, StyleDirections, Wireframe
from app.schemas.site_spec import SLOTS, Tokens, catalogue
from app.services import website_builder_prompts as P
from app.services import website_builder_service as wbs
from app.services import website_spec_service as wspec
from app.services.website_service import WebsiteError

PLAN_TASK, COPY_TASK, MODULE = "website_plan", "website_copy", "website"
NEUTRAL = {"palette": "forest-amber", "display": "fraunces", "body": "figtree", "radius": "soft", "motion": "calm"}


class Invalid(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems[:12]


def _problems(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg'].removeprefix('Value error, ')}" for e in exc.errors()][:12]
    if isinstance(exc, (Invalid, WebsiteError)):
        return list(exc.problems) or [str(exc)]
    return [str(exc)[:300]]


# ─── per-step checks: each returns the artifact to store, or raises ────────────────────────────────────

def _skeleton_page(p: dict, pi: int) -> dict:
    secs = []
    for i, s in enumerate(p["sections"]):
        sec = {"id": f"p{pi}-s{i}-{s['type']}", "type": s["type"], "variant": catalogue()["sections"][s["type"]]["variants"][0]}
        if s["type"] == "hero":
            sec["slots"] = {"headline": "x"}
        secs.append(sec)
    return {"slug": p["slug"], "title": p["title"], "nav": p["nav"], "sections": secs}


def _spec(brief: dict, pages: list[dict], tokens: dict = NEUTRAL) -> dict:
    return wbs.assemble(brief, {"pages": []}, tokens) | {"pages": pages}


def check_sitemap(data: dict, brief: dict, _prev) -> dict:
    sm = Sitemap.model_validate(data).model_dump(mode="json")
    wspec.validate(_spec(brief, [_skeleton_page(p, i) for i, p in enumerate(sm["pages"])]))      # slugs, home page, types
    if not any(s["type"] == "contact" for p in sm["pages"] for s in p["sections"]):
        raise Invalid(["the site needs a contact section on some page"])
    return sm


def check_wireframe(data: dict, brief: dict, sitemap: dict) -> dict:
    wf = Wireframe.model_validate(data).model_dump(mode="json")
    want = [(p["slug"], [s["type"] for s in p["sections"]]) for p in sitemap["pages"]]
    got = [(p["slug"], [s["type"] for s in p["sections"]]) for p in wf["pages"]]
    if got != want:
        raise Invalid([f"keep the approved sitemap exactly: pages and section types in order were {want}, you sent {got}"])
    wspec.validate(wbs.assemble(brief, wf, NEUTRAL))                         # variants, copy lengths, no typed price
    return wf


def _tokens(d: dict) -> dict:
    if d.get("palette_preset"):
        palette = d["palette_preset"]
    else:
        name = "-".join(w for w in "".join(c.lower() if c.isalnum() else " " for c in d["name"]).split())[:40] or "custom"
        palette = {"name": name, **{k: d.get(k) or "" for k in ("ink", "surface", "primary", "accent")}}
    return Tokens.model_validate({"palette": palette, "display": d["display"], "body": d["body"], "radius": d["radius"],
                                  "motion": "calm"}).model_dump(mode="json")


def check_style(data: dict, brief: dict, _wire) -> dict:
    from app.services.price_policy import detect_price
    sd = StyleDirections.model_validate(data).model_dump(mode="json")
    out, problems = [], []
    for i, d in enumerate(sd["directions"]):
        try:
            tokens = _tokens(d)
        except ValidationError as exc:
            problems += [f"direction {i + 1} ({d['name']}): {p}" for p in _problems(exc)]
            continue
        if detect_price(d["sample_headline"]):
            problems.append(f"direction {i + 1}: no prices in the sample headline")
        out.append({"name": d["name"], "mood": d["mood"], "sample_headline": d["sample_headline"], "tokens": tokens})
    looks = {(json.dumps(o["tokens"]["palette"], sort_keys=True), o["tokens"]["display"]) for o in out}
    if len(out) == 3 and len(looks) < 3:
        problems.append("the three directions must differ in palette or display face")
    if problems:
        raise Invalid(problems)
    return {"directions": out, "note": sd["note"]}


CHECKS = {"sitemap": check_sitemap, "wireframe": check_wireframe, "style": check_style}
TOOLS = {"sitemap": P.SITEMAP_TOOL, "wireframe": P.WIREFRAME_TOOL, "style": P.STYLE_TOOL}


def _system(step: str) -> str:
    cat = catalogue()
    if step == "sitemap":
        return P.SITEMAP_SYSTEM.format(library="\n".join(f"- {t}: {s['label']} (from {s['source']})" for t, s in cat["sections"].items()))
    if step == "wireframe":
        return P.WIREFRAME_SYSTEM.format(library="\n".join(f"- {t}: {', '.join(s['variants'])}" for t, s in cat["sections"].items()))
    return P.STYLE_SYSTEM.format(palettes=json.dumps({k: {c: v[c] for c in ("label", "ink", "surface", "primary", "accent")}
                                                      for k, v in cat["palettes"].items()}),
                                 display=", ".join(cat["fonts"]["display"]), body=", ".join(cat["fonts"]["body"]))


def _user(step: str, brief: dict, prev, job: SiteAiJob, current) -> str:
    parts = [f"BRIEF:\n{json.dumps(brief, ensure_ascii=False)}"]
    if prev is not None:
        parts.append(f"APPROVED {'SITEMAP' if step == 'wireframe' else 'WIREFRAME'}:\n{json.dumps(prev, ensure_ascii=False)}")
    if job.request:
        if current is not None:
            parts.append(f"YOUR PREVIOUS PROPOSAL:\n{json.dumps(current, ensure_ascii=False)}")
        parts.append(f"THE OWNER ASKED FOR THESE CHANGES: {job.request}")
    return "\n\n".join(parts)


def _attempts(db: Session, tenant_id: str, job: SiteAiJob, task: str, system: str, user: str, tool: dict, check) -> tuple[dict, int]:
    from app.services import usage_service
    from app.services.marketing_ai_service import _call
    errors: list[str] = []
    for attempt in (1, 2):
        msg = user if not errors else (user + "\n\nYOUR LAST ANSWER FAILED HAIP'S CHECKS:\n- " + "\n- ".join(errors)
                                       + "\nFix every problem and answer again through the tool.")
        data, raw, provider = _call(task, tenant_id, system, msg, tool)
        usage_service.record_llm(db, tenant_id, MODULE, raw, provider=provider, ref_type="site_ai_job", ref_id=job.id)
        job.model = raw.get("model") or job.model
        try:
            return check(data), attempt
        except (ValidationError, Invalid, WebsiteError) as exc:
            errors = _problems(exc)
    raise Invalid(errors)


def run(db: Session, tenant_id: str, job_id: str) -> SiteAiJob:
    job = db.query(SiteAiJob).filter_by(id=job_id, tenant_id=tenant_id).one()
    if job.status not in ("pending", "running"):
        return job
    job.status = "running"
    job.prompt_version = get_version(f"website_{job.kind}")
    site = db.query(Site).filter_by(id=job.site_id, tenant_id=tenant_id).one()
    try:
        if job.kind == "copy":
            return _run_copy(db, tenant_id, job, site)
        if job.kind == "change":
            from app.services import website_change
            return website_change.run(db, tenant_id, job, site)
        c = wbs.chain(db, site)
        prereq = c["brief"] if job.kind == "sitemap" else c[wbs.PREREQ[job.kind]]["approved"]
        if not prereq or prereq.id != wbs.based_on(job):
            job.status, job.error = "failed", "An earlier step changed while this ran. Run it again."
            return job
        brief = c["brief"].result["brief"]
        prev = None if job.kind == "sitemap" else wbs.artifact(prereq)
        earlier = next((j for j in wbs._q(db, site, job.kind).limit(20).all()
                        if j.id != job.id and wbs.based_on(j) == prereq.id and wbs.artifact(j)), None)
        current = wbs.artifact(earlier)          # what the owner asked to change
        art, n = _attempts(db, tenant_id, job, PLAN_TASK, _system(job.kind), _user(job.kind, brief, prev, job, current),
                           TOOLS[job.kind], lambda d: CHECKS[job.kind](d, brief, prev))
    except Invalid as exc:
        job.status = "failed"
        job.error = ("The AI's proposal didn't pass HAIP's checks twice: " + "; ".join(exc.problems))[:500]
        return job
    job.result = {**(job.result or {}), "artifact": art, "attempts": n}
    job.status, job.error = "ready", None
    return job


def _run_copy(db: Session, tenant_id: str, job: SiteAiJob, site: Site) -> SiteAiJob:
    from app.services import website_version_service as vs
    inp = (job.result or {})["input"]
    head = vs.head(db, site)
    if not wspec.is_v2(head.doc):
        job.status, job.error = "failed", "The draft is no longer a new-builder draft."
        return job
    sec = next((s for p in head.doc["pages"] if p["slug"] == inp["slug"] for s in p["sections"] if s["id"] == inp["section_id"]), None)
    if not sec:
        job.status, job.error = "failed", "That section is no longer on the page."
        return job
    limit = SLOTS[sec["type"]].model_fields[inp["slot"]].metadata
    max_len = next((getattr(m, "max_length", None) for m in limit if getattr(m, "max_length", None)), 280)
    user = (f"BUSINESS: {(head.doc.get('site') or {}).get('name')}\nSECTION: {sec['type']} ({sec['variant']})\n"
            f"SLOT: {inp['slot']} (max {max_len} characters)\nCURRENT TEXT: {sec['slots'].get(inp['slot']) or '(empty)'}\n"
            f"OWNER'S REQUEST: {job.request}")

    def check(data: dict) -> dict:
        text = CopyOut.model_validate(data).text
        doc = json.loads(json.dumps(head.doc))
        target = next(s for p in doc["pages"] if p["slug"] == inp["slug"] for s in p["sections"] if s["id"] == inp["section_id"])
        target["slots"][inp["slot"]] = text
        return {"text": text, "doc": wspec.validate(doc)}

    try:
        out, n = _attempts(db, tenant_id, job, COPY_TASK, P.COPY_SYSTEM, user, P.COPY_TOOL, check)
    except Invalid as exc:
        job.status, job.error = "failed", ("The new text didn't pass HAIP's checks twice: " + "; ".join(exc.problems))[:500]
        return job
    v, _ = vs.save_draft(db, site, out["doc"], head.sha256, actor_id=job.created_by, origin="ai",
                         note=f"AI copy: {inp['slot']} in {inp['section_id']}")
    job.result = {**(job.result or {}), "artifact": {"text": out["text"], **{k: inp[k] for k in ("slug", "section_id", "slot")}},
                  "attempts": n}
    job.result_version_id, job.status, job.error = v.id, "ready", None
    return job
