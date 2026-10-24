"""Reputation loop (agency M7): a 5-star review becomes a post (only after the guest agreed), then an ad through the
normal approval and "Promote as an ad"; and OTA listing copy drafts (Airbnb, Booking.com, MakeMyTrip).

Review -> post: a person records how the guest agreed (consent_note, who, when; audited). HAIP then drafts a normal
content item quoting the review word for word with the guest's first name only; it goes through the same brand review,
approval, publishing and ads as any post. A review can become a post once.

OTA copy: the AI (task `marketing_ota_copy`, prompt marketing-ota-copy-v2) writes each platform's fields from the
property's own facts; the result is re-validated against the platform's limits, the workspace's price policy and the
deterministic checks (numbers not in the facts, guarantees, stock phrases). There is no OTA API: a person copies it in.
Runs in Celery (`marketing_studio.ota_copy`), never in a request handler.
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.prompt_versions import get_version
from app.models.marketing_partners import MarketingOtaCopy
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.marketing_partners import OTA_MODELS, OtaCopyIn, ReviewPostIn
from app.services import marketing_ai_service as ai
from app.services import marketing_content_service as content_svc
from app.services import marketing_guest_reviews as reviews
from app.services import marketing_lint
from app.services import marketing_prompts as prompts
from app.services import usage_service
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

QUOTE_MAX = 400


# ── Review -> post ──────────────────────────────────────────────────────────────────────────────────────────────────

def _quote(text: str) -> str:
    t = " ".join((text or "").split())
    if len(t) <= QUOTE_MAX:
        return t
    cut = t[:QUOTE_MAX].rsplit(" ", 1)[0]
    return cut + "…"


def review_to_post(db: Session, tenant: Tenant, review_id: str, data: dict, actor: User):
    try:
        body = ReviewPostIn.model_validate(data)
    except ValueError as exc:
        raise MarketingError(422, "consent_note_needed", "Write down how the guest agreed (e.g. “said yes on WhatsApp, 20 Oct”).",
                             [str(exc)[:300]])
    row = reviews.get(db, tenant.id, review_id)
    if (row.rating or 0) < 5 or not (row.comment or "").strip():
        raise MarketingError(422, "not_five_star", "Only a 5-star review with words in it becomes a post.")
    if row.content_id:
        raise MarketingError(409, "already_posted", "This review is already a post.")
    first = ((row.reviewer or "").split() or ["A guest"])[0]
    quote = _quote(row.comment)
    caption = f"“{quote}”\n— {first}, a recent guest\n\nThank you, {first}. Message us to plan your stay."
    item = content_svc.create_item(db, tenant.id, kind="post", title=f"Guest review: {first}", actor_id=actor.id,
                                   payload={"caption": caption, "overlay_text": f"“{quote[:100]}”" if len(quote) > 100
                                            else f"“{quote}”", "design": {"style": "panel"}})
    row.content_id, row.consent_note, row.consent_by, row.consent_at = (item.id, body.consent_note, actor.id,
                                                                         datetime.now(timezone.utc))
    append_audit(db, tenant_id=tenant.id, action="marketing.review.to_post", actor_user_id=actor.id,
                 target_type="marketing_guest_review", target_id=row.id,
                 payload={"content_id": item.id, "consent_note": body.consent_note})
    return item


# ── OTA copy ────────────────────────────────────────────────────────────────────────────────────────────────────────

def request_copy(db: Session, tenant: Tenant, data: dict, actor_id: str) -> MarketingOtaCopy:
    try:
        body = OtaCopyIn.model_validate(data)
    except ValueError as exc:
        raise MarketingError(422, "bad_request", "Choose a property and a platform.", [str(exc)[:300]])
    if db.query(Property.id).filter_by(id=body.property_id, tenant_id=tenant.id).first() is None:
        raise MarketingError(404, "property_not_found", "No such property in this workspace.")
    row = MarketingOtaCopy(tenant_id=tenant.id, property_id=body.property_id, platform=body.platform, status="pending",
                           created_by=actor_id)
    db.add(row)
    db.flush()
    return row


def ota_tool(platform: str) -> dict:
    return {"name": "submit_listing", "description": f"Return the {platform} listing copy.",
            "input_schema": prompts._schema(OTA_MODELS[platform])}


def _texts(body: dict) -> list[tuple[str, str]]:
    out = []
    for k, v in body.items():
        if isinstance(v, str):
            out.append((k, v))
        elif isinstance(v, list):
            out += [(f"{k} {i + 1}", x) for i, x in enumerate(v) if isinstance(x, str)]
    return out


def run_copy(db: Session, tenant_id: str, row_id: str) -> MarketingOtaCopy:
    """Celery only. A transient provider error raises ai.LLMTransientError; anything else is recorded on the row."""
    row = db.query(MarketingOtaCopy).filter_by(id=row_id, tenant_id=tenant_id).one()
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    row.prompt_version = get_version("marketing_ota_copy")
    facts = f"{ai._facts(db, tenant, row.property_id)}"          # the same flattened text the prompt gets
    try:
        user = f"Platform: {row.platform}\n\nBusiness and property facts:\n{facts}"
        data, raw, provider = ai._call("marketing_ota_copy", tenant_id, ai._system(prompts.OTA_SYSTEM, tenant), user,
                                       ota_tool(row.platform))
        usage_service.record_llm(db, tenant_id, ai.MODULE, raw, provider=provider, ref_type="marketing_ota_copy",
                                 ref_id=row.id)
        copy = OTA_MODELS[row.platform].model_validate(data).model_dump()
        problems = content_svc.check_text(db, tenant_id, copy)          # price policy + the profile's avoid words
        if problems:
            raise ValueError("; ".join(problems))
        checks = []
        for where, text in _texts(copy):
            checks += marketing_lint.grounding(where, text, facts, strict=True)
            checks += marketing_lint.ai_tells(where, text)
            checks += marketing_lint.compliance(where, text, [])
        row.body = {"copy": copy, "checks": checks}
        row.model, row.status, row.error = raw.get("model"), "ready", None
    except ValidationError as exc:
        row.status, row.error = "failed", f"The AI's answer did not fit the listing limits: {ai._errors(exc)}"[:2000]
    except ValueError as exc:
        row.status, row.error = "failed", str(exc)[:2000]
    return row


def copy_dict(r: MarketingOtaCopy) -> dict:
    return {"id": r.id, "property_id": r.property_id, "platform": r.platform, "status": r.status,
            "copy": (r.body or {}).get("copy"), "checks": (r.body or {}).get("checks") or [], "error": r.error,
            "created_at": r.created_at, "prompt_version": r.prompt_version}


def latest_copies(db: Session, tenant_id: str, property_id: Optional[str] = None) -> list[dict]:
    q = db.query(MarketingOtaCopy).filter_by(tenant_id=tenant_id)
    if property_id:
        q = q.filter_by(property_id=property_id)
    return [copy_dict(r) for r in q.order_by(MarketingOtaCopy.created_at.desc()).limit(30)]
