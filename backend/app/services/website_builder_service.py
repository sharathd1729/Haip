"""The website art director (W2): brief -> sitemap -> wireframe -> 3 style directions -> a v2 draft.

Each step is a site_ai_jobs row (kind brief|sitemap|wireframe|style|copy; no new table). `result` = {"based_on": the id of
the APPROVED previous step it was built from, "artifact": the validated output}. A step counts only while its based_on is
still the approved previous step, so re-approving an earlier step makes the later ones stale by itself.

  status  brief: approved (saved by the owner)   steps: pending -> running -> ready | failed; ready -> approved (owner)

AI work runs in Celery (website.builder_step -> website_builder_ai.run); nothing here calls a model. Picking a style
direction assembles the full SiteSpec and creates a v2 draft through website_spec_service.create_draft; publishing stays
the normal approval flow.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.tenant import Tenant
from app.models.user import User
from app.models.website import Site, SiteAiJob
from app.schemas.site_builder import STEPS, BriefOwner
from app.schemas.site_spec import SLOTS
from app.services import website_spec_service as wspec
from app.services.website_service import WebsiteError

PREREQ = {"sitemap": "brief", "wireframe": "sitemap", "style": "wireframe"}
JOBS_PER_HOUR = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── the brief ─────────────────────────────────────────────────────────────────────────────────────────

def brief_facts(db: Session, tenant: Tenant, site: Site) -> dict:
    """Everything HAIP already knows that a designer would ask for. Text that states a price is left out."""
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry
    from app.models.knowledge import KnowledgeEntry
    from app.models.marketing import MarketingGuestReview
    from app.models.website import SiteVersion
    from app.services import business_data_service as bds
    from app.services import marketing_brand_kit
    from app.services.bio_packages import _length
    from app.services.marketing_photos import library
    from app.services.price_policy import price_mode
    from app.services.website_bindings import _clean
    from app.services.website_service import bookable_properties

    prof = (tenant.brand_config or {}).get("business_profile") or {}
    kit = marketing_brand_kit.get_kit(tenant)
    head = db.get(SiteVersion, site.draft_version_id) if site.draft_version_id else None
    sb = ((head.doc if head else {}) or {}).get("site") or {}
    contact = sb.get("contact") or {}
    phone = contact.get("whatsapp") or contact.get("phone") or prof.get("contact_phone") or ""
    dests = {r.key: bds.parse(r) for r in bds.list_effective(db, tenant.id, "destination")}
    pkgs = [(r.key, bds.parse(r)) for r in bds.list_effective(db, tenant.id, "package")]
    its = [(r.key, bds.parse(r)) for r in bds.list_effective(db, tenant.id, "itinerary")]
    faqs = (db.query(KnowledgeEntry.question).filter(
        KnowledgeEntry.tenant_id == tenant.id, KnowledgeEntry.category == "faq", KnowledgeEntry.is_active.is_(True),
        KnowledgeEntry.review_status == "approved", KnowledgeEntry.stale_since.is_(None), KnowledgeEntry.question.isnot(None))
        .order_by(KnowledgeEntry.priority.desc()).limit(40).all())
    rated = [r for (r,) in db.query(MarketingGuestReview.rating).filter(
        MarketingGuestReview.tenant_id == tenant.id, MarketingGuestReview.rating.isnot(None)).all()]
    usable = db.query(func.count(MarketingGuestReview.id)).filter(
        MarketingGuestReview.tenant_id == tenant.id, MarketingGuestReview.consent_at.isnot(None),
        MarketingGuestReview.rating >= 4).scalar() or 0
    since = _now() - timedelta(days=365)
    leads = (db.query(Inquiry.occasion, Inquiry.adults, Inquiry.children, Inquiry.source, Guest.city)
             .outerjoin(Guest, Guest.id == Inquiry.guest_id)
             .filter(Inquiry.tenant_id == tenant.id, Inquiry.created_at >= since).limit(2000).all())
    props = bookable_properties(db, tenant.id)
    facts = {
        "business": {"name": (sb.get("name") or tenant.brand_name or tenant.name or "")[:80], "type": tenant.business_type,
                     "tagline": sb.get("tagline") or prof.get("tagline") or "", "description": (prof.get("description") or "")[:600],
                     "usps": prof.get("usps") or [], "languages": prof.get("languages") or []},
        "location": {"city": prof.get("city") or next((p.city for p in props if p.city), ""), "region": prof.get("region") or "",
                     "address": contact.get("address") or ""},
        "contact": {"phone": contact.get("phone") or phone, "whatsapp": phone, "email": contact.get("email") or prof.get("contact_email") or "",
                    "address": contact.get("address") or ""},
        "social": {k: v for k, v in (sb.get("social") or {}).items() if k in ("instagram", "facebook", "youtube")},
        "brand_kit": {"primary": kit.get("primary"), "accent": kit.get("accent"), "font": kit.get("font"),
                      "has_logo": bool(kit.get("logo_asset_id"))},
        "price_policy": price_mode(tenant),
        "packages": [{"key": k, "name": p.name, "length": _length(p), "summary": (p.summary or "")[:240],
                      "destinations": [dests[d].name for d in p.destination_keys if d in dests]}
                     for k, p in pkgs if p.audience != "b2b"][:12],
        "destinations": [{"key": k, "name": d.name, "best_months": d.best_months, "about": (d.description or "")[:240]}
                         for k, d in dests.items()][:12],
        "itineraries": [{"key": k, "name": i.name, "nights": i.nights, "days": len(i.days), "packages": i.package_keys} for k, i in its][:12],
        "stays": [{"name": p.name, "type": p.type, "city": p.city, "sleeps": int(p.max_adults or 0) + int(p.max_children or 0)}
                  for p in props][:12],
        "content": {"faq_questions": [q for (q,) in faqs][:8], "faq_count": len(faqs), "approved_photos": len(library(db, tenant.id)),
                    "reviews_usable": usable, "reviews_rated": len(rated),
                    "average_rating": round(sum(rated) / len(rated), 1) if rated else None},
        "guests_last_year": _guest_mix(leads),
    }
    return _clean(facts)


def _guest_mix(rows) -> dict:
    if not rows:
        return {"enquiries": 0}
    occ = Counter(o for o, *_ in rows if o)
    cities = Counter(c for *_, c in rows if c)
    src = Counter(getattr(s, "value", s) for _, _, _, s, _ in rows if s)
    adults = [a for _, a, *_ in rows if a]
    return {"enquiries": len(rows), "occasions": dict(occ.most_common(5)), "top_cities": [c for c, _ in cities.most_common(5)],
            "sources": dict(src.most_common(5)), "average_adults": round(sum(adults) / len(adults), 1) if adults else None,
            "share_with_children": round(sum(1 for _, _, ch, *_ in rows if ch) / len(rows), 2)}


def save_brief(db: Session, tenant: Tenant, site: Site, owner: BriefOwner, actor: User) -> SiteAiJob:
    job = SiteAiJob(created_at=_now(), tenant_id=site.tenant_id, site_id=site.id, kind="brief", status="approved", created_by=actor.id,
                    result={"brief": {"facts": brief_facts(db, tenant, site), "owner": owner.model_dump(mode="json")}},
                    base_version_id=site.draft_version_id)
    db.add(job)
    db.flush()
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.builder_brief",
                 target_type="site_ai_job", target_id=job.id, payload={"owner": owner.model_dump(mode="json")})
    return job


# ─── the approved chain ────────────────────────────────────────────────────────────────────────────────

def _q(db: Session, site: Site, kind: str):
    return (db.query(SiteAiJob).filter_by(tenant_id=site.tenant_id, site_id=site.id, kind=kind)
            .order_by(SiteAiJob.created_at.desc(), SiteAiJob.id.desc()))


def based_on(job: Optional[SiteAiJob]) -> Optional[str]:
    return (job.result or {}).get("based_on") if job else None


def chain(db: Session, site: Site) -> dict:
    """{"brief": job, "<step>": {"approved": job|None, "latest": job|None}} following approved links only."""
    brief = _q(db, site, "brief").first()
    out: dict = {"brief": brief}
    prev = brief
    for step in STEPS:
        rows = _q(db, site, step).limit(50).all() if prev else []
        mine = [j for j in rows if based_on(j) == prev.id] if prev else []
        approved = next((j for j in mine if j.status == "approved"), None)
        out[step] = {"approved": approved, "latest": mine[0] if mine else None}
        prev = approved
    return out


def artifact(job: Optional[SiteAiJob]):
    return (job.result or {}).get("artifact") if job else None


def job_out(job: Optional[SiteAiJob]) -> Optional[dict]:
    if not job:
        return None
    r = job.result or {}
    return {"id": job.id, "kind": job.kind, "status": job.status, "feedback": job.request, "error": job.error,
            "artifact": r.get("artifact"), "picked": r.get("picked"), "attempts": r.get("attempts"),
            "version_id": job.result_version_id, "model": job.model,
            "created_at": job.created_at.isoformat() if job.created_at else None}


def state(db: Session, site: Site) -> dict:
    c = chain(db, site)
    steps, nxt = {}, None
    prev_ok = c["brief"] is not None
    for step in STEPS:
        approved, latest = c[step]["approved"], c[step]["latest"]
        steps[step] = {"latest": job_out(latest), "approved_id": approved.id if approved else None, "can_run": prev_ok}
        if nxt is None and not approved:
            nxt = step
        prev_ok = approved is not None
    brief = c["brief"]
    style = c["style"]["approved"]
    return {"brief": (brief.result or {}).get("brief") if brief else None, "brief_id": brief.id if brief else None,
            "steps": steps, "next": "brief" if not brief else nxt or "done",
            "draft_version_id": style.result_version_id if style else None,
            "busy": any((steps[s]["latest"] or {}).get("status") in ("pending", "running") for s in STEPS)}


# ─── run / approve / pick ──────────────────────────────────────────────────────────────────────────────

def _guard_rate(db: Session, site: Site) -> None:
    since = _now() - timedelta(hours=1)
    recent = db.query(func.count(SiteAiJob.id)).filter(SiteAiJob.tenant_id == site.tenant_id, SiteAiJob.created_at >= since,
                                                       SiteAiJob.kind != "brief").scalar() or 0
    if recent >= JOBS_PER_HOUR:
        raise WebsiteError(429, "ai_busy", "That's a lot of requests this hour. Try again shortly.")
    busy = db.query(SiteAiJob.id).filter(SiteAiJob.site_id == site.id, SiteAiJob.tenant_id == site.tenant_id,
                                         SiteAiJob.status.in_(("pending", "running")),
                                         SiteAiJob.created_at >= _now() - timedelta(minutes=10)).first()
    if busy:
        raise WebsiteError(409, "ai_running", "The art director is still working on your last request.")


def request_step(db: Session, site: Site, step: str, actor: User, feedback: Optional[str]) -> SiteAiJob:
    if step not in STEPS:
        raise WebsiteError(404, "unknown_step", "No such step.")
    c = chain(db, site)
    prev = c["brief"] if step == "sitemap" else c[PREREQ[step]]["approved"]
    if not prev:
        raise WebsiteError(409, "previous_step_not_approved",
                           "Save the brief first." if step == "sitemap" else f"Approve the {PREREQ[step]} first.")
    _guard_rate(db, site)
    job = SiteAiJob(created_at=_now(), tenant_id=site.tenant_id, site_id=site.id, kind=step, status="pending", request=(feedback or None),
                    result={"based_on": prev.id}, base_version_id=site.draft_version_id, created_by=actor.id)
    db.add(job)
    db.flush()
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.builder_run", target_type="site_ai_job",
                 target_id=job.id, payload={"step": step, "feedback": (feedback or "")[:600]})
    return job


def request_copy(db: Session, site: Site, actor: User, body: dict) -> SiteAiJob:
    from app.services import website_version_service as vs
    head = vs.head(db, site)
    if not wspec.is_v2(head.doc):
        raise WebsiteError(409, "not_v2", "Copy polish works on new-builder drafts. Pick a style direction first.")
    page = next((p for p in head.doc["pages"] if p["slug"] == body["slug"]), None)
    sec = next((s for s in (page or {}).get("sections", []) if s["id"] == body["section_id"]), None)
    if not sec or body["slot"] not in SLOTS[sec["type"]].model_fields:
        raise WebsiteError(422, "unknown_slot", "That section has no such text.")
    _guard_rate(db, site)
    job = SiteAiJob(created_at=_now(), tenant_id=site.tenant_id, site_id=site.id, kind="copy", status="pending", request=body["instruction"],
                    result={"based_on": head.id, "input": body}, base_version_id=head.id, created_by=actor.id)
    db.add(job)
    db.flush()
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.builder_copy", target_type="site_ai_job",
                 target_id=job.id, payload={k: body[k] for k in ("slug", "section_id", "slot")})
    return job


def _current_ready(db: Session, site: Site, step: str, job_id: str) -> SiteAiJob:
    latest = chain(db, site)[step]["latest"]
    if not latest or latest.id != job_id:
        raise WebsiteError(409, "not_current", "This isn't the current version of that step. Reload.")
    if latest.status != "ready":
        raise WebsiteError(409, "not_ready", f"A {latest.status} step can't be approved.")
    return latest


def _mark_approved(db: Session, job: SiteAiJob, result: Optional[dict] = None) -> None:
    upd = {"status": "approved", "updated_at": _now()}
    if result is not None:
        upd["result"] = result
    n = db.query(SiteAiJob).filter_by(id=job.id, tenant_id=job.tenant_id, status="ready").update(upd, synchronize_session=False)
    if n != 1:
        raise WebsiteError(409, "not_ready", "This step changed while you were approving it. Reload.")
    db.refresh(job)


def approve(db: Session, site: Site, step: str, job_id: str, actor: User) -> SiteAiJob:
    if step not in ("sitemap", "wireframe"):
        raise WebsiteError(422, "pick_a_direction", "Style is approved by picking one of the three directions.")
    job = _current_ready(db, site, step, job_id)
    _mark_approved(db, job)
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.builder_approved",
                 target_type="site_ai_job", target_id=job.id, payload={"step": step})
    return job


def assemble(brief: dict, wireframe: dict, tokens: dict) -> dict:
    """The full v2 spec from the approved wireframe and the picked direction (validated by create_draft)."""
    f = brief["facts"]
    pages = []
    for p in wireframe["pages"]:
        sections = []
        for s in p["sections"]:
            allowed = SLOTS[s["type"]].model_fields
            slots = {k: v for k, v in s.items() if k in allowed and v not in (None, "")}
            sections.append({"id": s["id"], "type": s["type"], "variant": s["variant"], "slots": slots})
        pages.append({"slug": p["slug"], "title": p["title"], "nav": p["nav"],
                      "seo": {"title": p.get("seo_title") or "", "description": p.get("seo_description") or ""}, "sections": sections})
    return {"spec_version": 2,
            "site": {"name": f["business"]["name"] or "Our stay", "tagline": (f["business"].get("tagline") or "")[:120],
                     "contact": {k: (f["contact"].get(k) or "")[:300 if k == "address" else 40 if k != "email" else 120]
                                 for k in ("phone", "whatsapp", "email", "address")},
                     "social": f.get("social") or {}},
            "tokens": tokens, "pages": pages}


def pick(db: Session, site: Site, job_id: str, index: int, actor: User):
    job = _current_ready(db, site, "style", job_id)
    c = chain(db, site)
    directions = (artifact(job) or {}).get("directions") or []
    if index >= len(directions):
        raise WebsiteError(422, "no_such_direction", "Pick one of the three directions.")
    spec = assemble(c["brief"].result["brief"], artifact(c["wireframe"]["approved"]), directions[index]["tokens"])
    v, problems = wspec.create_draft(db, site, spec, actor_id=actor.id, origin="ai",
                                     note=f"Art director: {directions[index]['name']}"[:200])
    _mark_approved(db, job, {**(job.result or {}), "picked": index})
    job.result_version_id = v.id
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.builder_picked", target_type="site_ai_job",
                 target_id=job.id, payload={"index": index, "name": directions[index]["name"], "version": v.number})
    return v, problems


def mark_failed(db: Session, tenant_id: str, job_id: str, message: str) -> None:
    job = db.query(SiteAiJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job and job.status in ("pending", "running"):
        job.status, job.error = "failed", message[:500]
