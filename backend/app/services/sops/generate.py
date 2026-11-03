"""Fill an SOP template for one workspace and store it as a new immutable version.

Code fills everything that must not be invented: the ranked category list (platform rules only), the photo order (vision
tags x the rules' order; a photo with people only after the owner's OK), name/address/phone, links, amenities. The model
writes only the text slots (description, Instagram bio, WhatsApp About line, Q&A), from the shared facts block
(marketing_ai_service._facts = profile + properties + approved KB + published business records, prices stripped).
Every AI text passes the price policy, the profile's avoid words and the grounding lint; a failing text falls back to the
owner's own words, or to a "fill this in HAIP" link. A missing fact is never guessed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime

import structlog
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.prompt_versions import get_version
from app.models.media_asset import MediaAsset
from app.models.property import Property
from app.models.sop import SopInstance, SopVersion
from app.models.tenant import Tenant
from app.models.website import SiteVersion
from app.schemas.marketing import PhotoTags
from app.schemas.sops import SopText
from app.services import marketing_lint, website_seo
from app.services.sops import inputs_ota, rules
from app.services.sops.catalogue import BY_KEY, Template

log = structlog.get_logger()

TASK = "sop_generate"
AI_SLOTS = ("description", "short_bio", "wa_about", "qa", "offer_text")
MAX_PHOTOS = 20
KIND_WORDS = {
    "caravan": "Caravan holidays",
    "villa": "Private villa",
    "farmhouse": "Farmhouse stay",
    "homestay": "Homestay",
    "boutique_hotel": "Boutique hotel",
    "resort": "Resort",
    "service_apartments": "Serviced apartments",
    "travel_agency": "Trips and tours",
}
STUDIO_PROFILE = "/dashboard/marketing/studio?tab=profile"
STUDIO_LIBRARY = "/dashboard/marketing/studio?tab=library"

SYSTEM = """You write the text a hospitality business pastes into its own Google Business Profile, Instagram, WhatsApp
Business, Facebook, TripAdvisor and travel-site (OTA) listings. Fill only the fields the tool asks for, from the business facts given. Plain, warm, specific:
what the place is, where it is, who it suits, what is nearby. No hashtags, no emoji, no capital-letter shouting, no
"best"/"#1", no guarantees, no links. Questions and answers come only from the facts (knowledge base and published
records); leave the list empty rather than guess. An offer name is a few words naming the season or who it suits, never a
number, a price or a discount. Answer only by calling the tool.
"""


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# ── Inputs (shared data layer only) ─────────────────────────────────────────────────────────────────────────────────


def _site(db: Session, tenant_id: str) -> dict:
    from app.services import website_service

    site = website_service.get_site(db, tenant_id)
    if site is None:
        return {"url": None, "contact": {}}
    live = db.get(SiteVersion, site.live_version_id) if site.live_version_id else None
    contact = (((live.doc or {}).get("site") or {}).get("contact") or {}) if live else {}
    return {"url": f"https://{website_service.primary_host(db, site)}" if live else None, "contact": contact}


def _photos(db: Session, tenant_id: str, property_id: str | None) -> list[dict]:
    order = (rules.get("gbp.photo_order").value if rules.get("gbp.photo_order") else []) or []
    q = db.query(MediaAsset).filter(
        MediaAsset.tenant_id == tenant_id, MediaAsset.status == "active", MediaAsset.mime_type.like("image/%")
    )
    if property_id:
        q = q.filter((MediaAsset.property_id == property_id) | (MediaAsset.property_id.is_(None)))
    out = []
    for a in q.order_by(MediaAsset.created_at.desc()).limit(200):
        try:
            tags = PhotoTags.model_validate(a.tags) if a.tags else None
        except ValidationError:
            tags = None
        if tags and tags.people and not a.people_ok:
            continue  # people need the owner's OK (agency M2 rule)
        subject = next((s for s in (tags.subjects if tags else []) if s in order), None)
        out.append(
            {
                "asset_id": a.id,
                "alt": a.alt_text or (tags.description if tags else ""),
                "subject": subject,
                "_rank": (order.index(subject) if subject else len(order), -(tags.quality if tags else 0)),
            }
        )
    out.sort(key=lambda p: p["_rank"])
    return [{k: v for k, v in p.items() if k != "_rank"} for p in out[:MAX_PHOTOS]]


def collect(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    from app.services import marketing_ai_service as ai
    from app.services import marketing_brand_kit

    t = BY_KEY[inst.template_key]
    facts = ai._facts(db, tenant, inst.property_id)
    prop_q = db.query(Property).filter(Property.tenant_id == tenant.id, Property.is_active.is_(True))
    if inst.property_id:
        prop_q = prop_q.filter(Property.id == inst.property_id)
    prop = prop_q.order_by(Property.created_at).first()
    return {
        "brand": tenant.brand_name or tenant.name,
        "kind": website_seo.business_kind(tenant.business_type),
        "facts": facts,
        "address": ", ".join(x for x in ((prop.address, prop.city, prop.state) if prop else ()) if x),
        "site": _site(db, tenant.id),
        "photos": _photos(db, tenant.id, inst.property_id),
        "logo": marketing_brand_kit.logo_id(tenant),
        **inputs_ota.collect(db, tenant, inst, t.platform, {s for st in t.steps for s in st.slots}),
    }


# ── AI text ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _limit(slot: str) -> int | None:
    key = {"description": "gbp.description_max", "short_bio": "ig.bio_max"}.get(slot)
    e = rules.get(key) if key else None
    return int(e.value) if e is not None else None


def _clean(db: Session, tenant: Tenant, data: dict, facts_text: str) -> tuple[dict, list[str]]:
    """Keep only texts that pass length, price policy, avoid words and grounding; say why the others were dropped."""
    from app.services import marketing_content_service as content_svc

    kept, notes = {}, []

    def ok(where: str, text: str) -> bool:
        lim = _limit(where.split(" ")[0])
        problems = content_svc.check_text(db, tenant.id, {where: text})
        if lim and len(text) > lim:
            problems.append(f"longer than {lim} characters")
        problems += [
            f["message"]
            for f in marketing_lint.grounding(where, text, facts_text, strict=True)
            if f["severity"] == "high"
        ]
        if problems:
            notes.append(f"{where}: {problems[0]}")
        return not problems

    for slot in ("description", "short_bio", "wa_about", "offer_text"):
        if slot == "offer_text" and data.get(slot) and any(c.isdigit() for c in data[slot]):
            notes.append("offer_text: has a figure; numbers go in the platform's own fields")
            continue
        if data.get(slot) and ok(slot, data[slot]):
            kept[slot] = data[slot]
    kept["qa"] = [p for i, p in enumerate(data.get("qa") or []) if ok(f"qa {i + 1}", f"{p['q']} {p['a']}")]
    return kept, notes


def ai_text(db: Session, tenant: Tenant, slots: set[str], facts: dict) -> tuple[dict, str | None, str | None]:
    """(texts, model, note). Celery only. A transient provider error propagates (the task retries it)."""
    from app.services import marketing_ai_service as ai
    from app.services import marketing_prompts as prompts
    from app.services import usage_service

    wanted = sorted(slots & set(AI_SLOTS))
    if not wanted:
        return {}, None, None
    facts_text = json.dumps(facts, default=str, ensure_ascii=False)
    tool = {
        "name": "submit_profile_text",
        "description": "Return the profile texts.",
        "input_schema": prompts._schema(SopText),
    }
    limits = {s: _limit(s) for s in wanted if _limit(s)}
    user = (
        f"Fields wanted: {', '.join(wanted)}. Character limits: {json.dumps(limits)}.\n\nBusiness facts:\n{facts_text}"
    )
    try:
        data, raw, provider = ai._call(TASK, tenant.id, ai._system(SYSTEM + prompts._COMMON_RULES, tenant), user, tool)
        usage_service.record_llm(
            db, tenant.id, "sops", raw, provider=provider, ref_type="sop_version", ref_id=tenant.id
        )
        texts, notes = _clean(db, tenant, SopText.model_validate(data).model_dump(), facts_text)
        return texts, raw.get("model") or provider, "; ".join(notes)[:2000] or None
    except ai.LLMTransientError:
        raise
    except (ValueError, ValidationError) as exc:
        log.warning("sop_ai_text_failed", tenant_id=tenant.id, error=str(exc)[:300])
        return {}, None, f"The AI text could not be used ({str(exc)[:200]}). Fixed wording is shown instead."


# ── Steps ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def _fill(slot: str, t: Template, inp: dict, text: dict, step: dict) -> None:
    if slot in inputs_ota.SLOTS:
        inputs_ota.fill(slot, t.platform, inp, text, step)
        return
    profile = inp["facts"].get("profile") or {}
    contact = inp["site"]["contact"] or {}
    phone = profile.get("contact_phone") or contact.get("phone") or contact.get("whatsapp")
    url = inp["site"]["url"]
    values, needs = step["values"], step["needs"]

    def need(label: str, href: str | None) -> None:
        needs.append({"label": label, "href": href})

    if slot == "categories":
        step["categories"] = rules.categories(t.platform, inp["kind"])
        if not step["categories"]:
            step["notes"].append(f"HAIP has no curated category list for this yet: {rules.CHECK_IN_PLATFORM.lower()}.")
    elif slot == "photos":
        step["photos"] = inp["photos"]
        e = rules.get("gbp.photo_min")
        if e is not None and len(inp["photos"]) < int(e.value):
            need(f"Add more photos to your library (you have {len(inp['photos'])}, aim for {e.value})", STUDIO_LIBRARY)
    elif slot == "nap":
        values.append({"label": "Name", "text": inp["brand"]})
        values.append({"label": "Address", "text": inp["address"]} if inp["address"] else None)
        values.append({"label": "Phone", "text": phone} if phone else None)
        values.append(
            {"label": "Email", "text": profile.get("contact_email")} if profile.get("contact_email") else None
        )
        if not inp["address"]:
            need("Add your address to your property", "/dashboard/properties")
        if not phone:
            need("Add your phone number to your business profile", STUDIO_PROFILE)
    elif slot in ("website", "links_url"):
        if url:
            values.append({"label": "Link", "text": f"{url}/links" if slot == "links_url" else url})
        else:
            need("Make your website first", "/dashboard/marketing/website")
    elif slot == "whatsapp_number":
        wa = contact.get("whatsapp") or phone
        values.append({"label": "WhatsApp", "text": wa} if wa else None)
        if not wa:
            need("Add your WhatsApp number to your business profile", STUDIO_PROFILE)
    elif slot == "amenities":
        found = sorted(
            {a for p in inp["facts"].get("properties") or [] for a in (p.get("amenities") or []) if isinstance(a, str)}
        )
        values.append({"label": "Amenities", "text": ", ".join(found)} if found else None)
        if not found:
            need("Add amenities to your property", "/dashboard/properties")
    elif slot == "ig_name":
        words = KIND_WORDS.get(inp["kind"] or "")
        values.append({"label": "Name", "text": f"{inp['brand']} | {words}" if words else inp["brand"]})
    elif slot == "highlights":
        e = rules.get("ig.highlights")
        values.append({"label": "Highlights", "text": ", ".join(e.value)} if e else None)
    elif slot == "logo":
        if inp["logo"]:
            step["photos"] = [{"asset_id": inp["logo"], "alt": "Logo", "subject": None}]
        else:
            need("Add your logo to the brand kit", STUDIO_PROFILE)
    elif slot == "qa":
        for p in text.get("qa") or []:
            values.append({"label": p["q"], "text": p["a"]})
        if not text.get("qa"):
            need("Add the questions guests ask to your knowledge base", "/dashboard/settings/knowledge")
    elif slot in ("description", "short_bio", "wa_about"):
        own = profile.get("description") if slot == "description" else profile.get("tagline")
        words = text.get(slot) or own
        lim = _limit(slot)
        if words and lim and len(words) > lim:
            step["notes"].append(f"Shorten this to {lim} characters before pasting.")
        values.append(
            {
                "label": {"description": "Description", "short_bio": "Bio", "wa_about": "About"}[slot],
                "text": words,
                "ai": bool(text.get(slot)),
            }
            if words
            else None
        )
        if not words:
            need("Write a description and tagline in your business profile", STUDIO_PROFILE)
    values[:] = [v for v in values if v]


def build_steps(t: Template, inp: dict, text: dict, today: date) -> list[dict]:
    out = []
    for s in t.steps:
        step = {
            "key": s.key,
            "title": s.title,
            "how": s.how,
            "verify": s.verify,
            "check": s.check,
            "link": {"label": s.link[0], "href": s.link[1]} if s.link else None,
            "values": [],
            "needs": [],
            "notes": [],
            "categories": None,
            "photos": None,
            "rules": [rules.ref(e, today) for e in (rules.get(k) for k in s.rules) if e is not None],
        }
        for slot in s.slots:
            _fill(slot, t, inp, text, step)
        step["step_sha"] = _sha({k: v for k, v in step.items() if k != "rules"})
        out.append(step)
    return out


def make_version(
    db: Session, tenant: Tenant, inst: SopInstance, *, reason: str, actor_id: str | None, use_ai: bool = True
) -> SopVersion:
    t = BY_KEY[inst.template_key]
    inp = collect(db, tenant, inst)
    slots = {s for st in t.steps for s in st.slots}
    text, model, note = ai_text(db, tenant, slots, inp["facts"]) if use_ai else ({}, None, None)
    if not use_ai and slots & set(AI_SLOTS):
        note = "The AI was not available, so your own words from the business profile are shown."
    steps = build_steps(t, inp, text, datetime.now(UTC).date())
    last = (
        db.query(SopVersion)
        .filter_by(tenant_id=tenant.id, instance_id=inst.id)
        .order_by(SopVersion.version_no.desc())
        .first()
    )
    v = SopVersion(
        tenant_id=tenant.id,
        instance_id=inst.id,
        version_no=(last.version_no + 1) if last else 1,
        template_version=t.version,
        rules_digest=rules.digest(),
        inputs_sha=_sha({k: v for k, v in inp.items() if k not in inputs_ota.VOLATILE}),
        steps=steps,
        reason=reason if last else "first",
        model=model,
        prompt_version=get_version(TASK) if model else None,
        ai_note=note,
        created_by=actor_id,
    )
    db.add(v)
    db.flush()
    inst.current_version_id, inst.generating = v.id, None
    append_audit(
        db,
        tenant_id=tenant.id,
        action="sop.version_created",
        actor_user_id=actor_id,
        target_type="sop_instance",
        target_id=inst.id,
        payload={
            "version": v.version_no,
            "reason": v.reason,
            "ai": bool(model),
            **({} if actor_id else {"actor": "system"}),
        },
    )
    return v
