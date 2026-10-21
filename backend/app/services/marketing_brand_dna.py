"""Brand DNA draft (agency M2): a first draft of the business profile's voice, written from what the business has
already published -- its HAIP website (live version), its recent Instagram captions and its property descriptions.

It is a SUGGESTION only: stored in brand_config.marketing_studio.profile_draft and shown next to the profile, where
the owner edits and saves what they agree with. Nothing is applied automatically. Suggested claims stay suggestions
until the owner saves them into the profile (then they count as approved). Runs in Celery
(`marketing_studio.draft_profile`), prompt `marketing-brand-dna-v1`, task route `marketing_brand_dna`.
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.prompt_versions import get_version
from app.models.tenant import Tenant
from app.schemas.marketing import ApprovedClaim, ChannelTone, VoiceTrait, strings_of
from app.services import marketing_ai_service as ai
from app.services import usage_service

log = structlog.get_logger()

SETTINGS_KEY = "marketing_studio"
DRAFT_KEY = "profile_draft"
MAX_SOURCE_CHARS = 6000


class BrandDnaDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tagline: Optional[str] = Field(default=None, max_length=160)
    audience: Optional[str] = Field(default=None, max_length=600)
    tone: Optional[str] = Field(default=None, max_length=300)
    usps: list[str] = Field(default_factory=list, max_length=8)
    voice: list[VoiceTrait] = Field(default_factory=list, max_length=5)
    channel_tone: ChannelTone = Field(default_factory=ChannelTone)
    claims: list[ApprovedClaim] = Field(default_factory=list, max_length=15)
    gaps: list[str] = Field(default_factory=list, max_length=6)       # what the sources don't say and the owner should


SYSTEM = """You are a brand strategist at a hospitality marketing agency, writing the first draft of a client's brand
voice from what they have already published. Use ONLY the sources given (their website, Instagram captions, property
descriptions). Every claim you suggest must appear in the sources, word for word or nearly, with the source named.
- voice: 3-5 traits, each with what the brand IS and what it is NOT (the line it must not cross), and a short line
  that sounds like the brand (taken or adapted from the sources) and one that does not.
- tone: one sentence for overall tone; channel_tone for Instagram, WhatsApp, review replies and ads.
- usps: what makes them different, as stated in the sources.
- gaps: questions the owner should answer because the sources don't say (e.g. who the guests are).
Never invent awards, numbers, amenities or reviews. Answer only by calling the tool.
""" + "\n- {price_rule}"

TOOL = {"name": "submit_brand_draft", "description": "Return the brand voice draft.", "input_schema": None}


def _tool() -> dict:
    from app.services.marketing_prompts import _schema
    return {**TOOL, "input_schema": _schema(BrandDnaDraft)}


def sources(db: Session, tenant: Tenant) -> dict:
    """The business's own published words: live website text, recent captions, property descriptions."""
    from app.models.property import Property
    from app.models.website import Site, SiteVersion
    from app.workers.tasks.instagram_insights_poll import InstagramPostSnapshot

    site_text = ""
    site = db.query(Site).filter_by(tenant_id=tenant.id).first()
    if site is not None and site.live_version_id:
        live = db.query(SiteVersion).filter_by(id=site.live_version_id, tenant_id=tenant.id).first()
        if live is not None:
            site_text = " ".join(t for t in strings_of(live.doc or {}) if len(t) > 3 and not t.startswith(("http", "/")))
    captions = [c for (c,) in db.query(InstagramPostSnapshot.caption).filter(InstagramPostSnapshot.tenant_id == tenant.id,
                                                                           InstagramPostSnapshot.caption.isnot(None))
                .order_by(InstagramPostSnapshot.posted_at.desc()).limit(12) if c]
    props = [f"{p.name}: {p.description}" for p in db.query(Property).filter(Property.tenant_id == tenant.id,
                                                                             Property.is_active.is_(True)).limit(10)
             if p.description]
    return {"website": site_text[:MAX_SOURCE_CHARS], "instagram_captions": [c[:400] for c in captions],
            "properties": [p[:800] for p in props]}


def _section(tenant: Tenant) -> dict:
    cfg = (tenant.brand_config or {}).get(SETTINGS_KEY) if tenant is not None else None
    return dict(cfg) if isinstance(cfg, dict) else {}


def get_draft(tenant: Tenant) -> Optional[dict]:
    return _section(tenant).get(DRAFT_KEY)


def _store(tenant: Tenant, value: dict) -> None:
    cfg = dict(tenant.brand_config or {})
    section = _section(tenant)
    section[DRAFT_KEY] = value
    cfg[SETTINGS_KEY] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")


def mark_pending(tenant: Tenant, actor_id: str) -> None:
    _store(tenant, {"status": "pending", "requested_by": actor_id, "requested_at": datetime.now(timezone.utc).isoformat()})


def run(db: Session, tenant_id: str) -> dict:
    """Write the draft. A transient provider error raises ai.LLMTransientError; anything else is stored as failed."""
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    src = sources(db, tenant)
    base = {"requested_at": (get_draft(tenant) or {}).get("requested_at"), "prompt_version": get_version("marketing_brand_dna"),
            "sources": {"website_chars": len(src["website"]), "captions": len(src["instagram_captions"]),
                        "properties": len(src["properties"])}}
    if not (src["website"] or src["instagram_captions"] or src["properties"]):
        _store(tenant, {**base, "status": "failed", "error": "Nothing published yet to learn from: publish the website, "
                        "connect Instagram or add property descriptions first."})
        return get_draft(tenant)
    user = (f"Brand name: {tenant.brand_name or tenant.name}\nCurrent profile: {ai.get_profile(tenant)}\n\n"
            f"SOURCES\nWebsite: {src['website'] or '(none)'}\nInstagram captions: {src['instagram_captions'] or '(none)'}\n"
            f"Properties: {src['properties'] or '(none)'}")
    try:
        data, raw, provider = ai._call("marketing_brand_dna", tenant_id, ai._system(SYSTEM, tenant), user, _tool())
        usage_service.record_llm(db, tenant_id, ai.MODULE, raw, provider=provider, ref_type="tenant", ref_id=tenant_id)
        draft = BrandDnaDraft.model_validate(data).model_dump(mode="json")
        _store(tenant, {**base, "status": "ready", "draft": draft, "model": raw.get("model"),
                        "created_at": datetime.now(timezone.utc).isoformat()})
    except ValidationError as exc:
        _store(tenant, {**base, "status": "failed", "error": f"The draft did not fit the format: {ai._errors(exc)}"})
    except ValueError as exc:
        _store(tenant, {**base, "status": "failed", "error": str(exc)[:500]})
    return get_draft(tenant)
