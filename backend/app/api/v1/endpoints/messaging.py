"""
WhatsApp Business messaging features:
  - Templates (create, list, submit to Meta for approval)
  - Campaigns (broadcast sends)
  - Subscribers (opt-in / opt-out management)
"""

import uuid
import os
import httpx
import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import Column, String, Boolean, JSON, Enum as SAEnum
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db, Base
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.base import TimestampMixin, TenantMixin, gen_uuid

router = APIRouter(prefix="/messaging", tags=["messaging"])
log = structlog.get_logger()

# ─── Inline models (avoid a new alembic migration for now) ───────────────────
# These are created via create_all on startup.

import enum

class TemplateStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUBMISSION_FAILED = "submission_failed"   # G8: distinct from PENDING -- Meta API call itself failed

class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    PAUSED = "paused"

class TemplateCategory(str, enum.Enum):
    MARKETING = "MARKETING"
    UTILITY = "UTILITY"
    AUTHENTICATION = "AUTHENTICATION"


class WATemplate(Base, TimestampMixin, TenantMixin):
    __tablename__ = "wa_templates"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    language = Column(String(10), default="en")
    category = Column(SAEnum(TemplateCategory), default=TemplateCategory.MARKETING)
    status = Column(SAEnum(TemplateStatus), default=TemplateStatus.DRAFT)
    components = Column(JSON, default=list)   # Meta template components array
    meta_template_id = Column(String(255), nullable=True)
    rejection_reason = Column(String(500), nullable=True)
    # migration 105 -- storage key of the image/video/PDF used as the header.
    # Meta only ever sees a sample of it (the handle inside `components`);
    # this is what gets sent to real recipients and shown in the preview.
    header_media_key = Column(String(500), nullable=True)


class WACampaign(Base, TimestampMixin, TenantMixin):
    __tablename__ = "wa_campaigns"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    template_id = Column(String, nullable=True)
    status = Column(SAEnum(CampaignStatus), default=CampaignStatus.DRAFT)
    audience_filter = Column(JSON, default=dict)   # e.g. {"tags": ["vip"], "property_id": "..."}
    scheduled_at = Column(String(50), nullable=True)
    sent_count = Column(String(20), default="0")
    delivered_count = Column(String(20), default="0")
    read_count = Column(String(20), default="0")
    failed_count = Column(String(20), default="0")
    # migration 105 -- how each template {{n}} is filled per recipient:
    # {"body": {"1": {"source": "first_name", "fallback": "Guest"}}, "header": {...}}
    variable_map = Column(JSON, default=dict)


class WASubscriber(Base, TimestampMixin, TenantMixin):
    __tablename__ = "wa_subscribers"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    phone = Column(String(30), nullable=False)
    name = Column(String(255), nullable=True)
    opted_in = Column(Boolean, default=True)
    opt_in_at = Column(String(50), nullable=True)
    opt_out_at = Column(String(50), nullable=True)
    source = Column(String(100), nullable=True)   # "web_widget", "import", "inbound"
    tags = Column(JSON, default=list)
    # migration 091 -- resolved at write time by phone match against Guest,
    # so VIP-tag/campaign-audience matching no longer depends on the
    # subscriber's phone having been typed in exact E.164 form.
    guest_id = Column(String, nullable=True, index=True)


class WAFlow(Base, TimestampMixin, TenantMixin):
    __tablename__ = "wa_flows"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)
    nodes = Column(JSON, default=list)    # Visual flow nodes
    edges = Column(JSON, default=list)    # Visual flow edges
    is_active = Column(Boolean, default=False)
    trigger = Column(String(100), nullable=True)  # "keyword", "opt_in", "campaign"


# ─── Pydantic schemas ────────────────────────────────────────────────────────

class TemplateComponentBody(BaseModel):
    type: str  # HEADER, BODY, FOOTER, BUTTONS
    format: Optional[str] = None   # TEXT, IMAGE, VIDEO
    text: Optional[str] = None
    buttons: Optional[list] = None
    example: Optional[dict] = None


class TemplateCreateRequest(BaseModel):
    name: str
    language: str = "en"
    category: str = "MARKETING"
    components: List[dict] = []
    # Storage key returned by POST /templates/media, for image/video/PDF headers.
    header_media_key: Optional[str] = None


class TemplateUpdateRequest(BaseModel):
    """Everything about a template except its name, which Meta ties to it."""
    language: str = "en"
    category: str = "MARKETING"
    components: List[dict] = []
    header_media_key: Optional[str] = None


class TemplateOut(BaseModel):
    id: str
    name: str
    language: str
    category: str
    status: str
    components: list
    meta_template_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    header_media_key: Optional[str] = None
    header_media_url: Optional[str] = None   # short-lived link for the preview
    # datetime, NOT str: created_at comes from TimestampMixin and is a
    # DateTime column. Pydantic v2 will not coerce datetime -> str, so
    # declaring str here made response validation raise on every template
    # response (500 on both create and list). Serialises to the same ISO
    # string on the wire.
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CampaignCreateRequest(BaseModel):
    name: str
    template_id: Optional[str] = None
    audience_filter: Optional[dict] = {}
    scheduled_at: Optional[str] = None
    variable_map: Optional[dict] = {}


class CampaignOut(BaseModel):
    id: str
    name: str
    template_id: Optional[str] = None
    status: str
    audience_filter: dict
    scheduled_at: Optional[str] = None
    sent_count: str
    delivered_count: str
    read_count: str
    failed_count: str
    variable_map: Optional[dict] = None
    # See TemplateOut.created_at — DateTime column, not a string.
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SubscriberOut(BaseModel):
    id: str
    phone: str
    name: Optional[str] = None
    opted_in: bool
    opt_in_at: Optional[str] = None
    opt_out_at: Optional[str] = None
    source: Optional[str] = None
    tags: list
    guest_id: Optional[str] = None

    class Config:
        from_attributes = True


class SubscriberUpsertRequest(BaseModel):
    phone: str
    name: Optional[str] = None
    opted_in: bool = True
    source: Optional[str] = "import"
    tags: Optional[List[str]] = []


class FlowOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    nodes: list
    edges: list
    is_active: bool
    trigger: Optional[str] = None
    # See TemplateOut.created_at — DateTime column, not a string.
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FlowSaveRequest(BaseModel):
    name: str
    description: Optional[str] = None
    nodes: List[dict] = []
    edges: List[dict] = []
    trigger: Optional[str] = None


# ─── Templates ────────────────────────────────────────────────────────────────

def _template_out(tmpl: "WATemplate") -> TemplateOut:
    """TemplateOut plus a fresh short-lived link to the header media, so the
    editor and list can preview it. The link is generated on read, never
    stored -- same rule as inbound WhatsApp media."""
    out = TemplateOut.model_validate(tmpl)
    if tmpl.header_media_key:
        from app.services.media_storage import get_presigned_media_url
        out.header_media_url = get_presigned_media_url(tmpl.header_media_key, expires_in=3600)
    return out


def _check_template_input(tenant_id: str, components: list, header_media_key: Optional[str]) -> None:
    """400 with plain-language reasons if the template can't be saved."""
    from app.services import wa_template_service as wts
    problems = wts.validate_components(components)
    if header_media_key and not header_media_key.startswith(f"{tenant_id}/wa_templates/"):
        problems.append("The attached file doesn't belong to this workspace.")
    header = next((c for c in components if (c.get("type") or "").upper() == "HEADER"), None)
    if header and (header.get("format") or "TEXT").upper() in wts.MEDIA_FORMATS and not header_media_key:
        problems.append("Attach the header file.")
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))


def _wa_integration_and_token(db: Session, tenant_id: str):
    """The tenant's active WhatsApp integration and its access token, or
    (None, "") when WhatsApp isn't connected. kind="whatsapp_meta" is
    primary; every other WhatsApp code path also falls back to "whatsapp"."""
    from app.models.integration import Integration
    from app.workers.tasks.whatsapp import _get_wa_access_token
    wa_int = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp_meta", status="active").first()
    if not wa_int:
        wa_int = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp", status="active").first()
    # access_token is a secret and only ever lives in the encrypted
    # credentials_kms_blob, never in integration.config.
    access_token = _get_wa_access_token(db, tenant_id) if wa_int else ""
    return wa_int, access_token


@router.get("/templates", response_model=List[TemplateOut])
def list_templates(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(WATemplate)
        .filter_by(tenant_id=current_user.tenant_id)
        .order_by(WATemplate.created_at.desc())
        .offset(offset).limit(limit).all()
    )
    return [_template_out(t) for t in rows]


@router.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    body: TemplateCreateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING)),
    db: Session = Depends(get_db),
):
    try:
        category = TemplateCategory(body.category.upper())
    except ValueError:
        category = TemplateCategory.MARKETING

    name = body.name.lower().replace(" ", "_")
    _check_template_input(current_user.tenant_id, body.components, body.header_media_key)
    if db.query(WATemplate).filter_by(tenant_id=current_user.tenant_id, name=name, language=body.language).first():
        raise HTTPException(
            status_code=409,
            detail=f"You already have a template named '{name}' in this language. Pick another name or edit that one.",
        )

    tmpl = WATemplate(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        name=name,
        language=body.language,
        category=category,
        components=body.components,
        header_media_key=body.header_media_key,
        status=TemplateStatus.DRAFT,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return _template_out(tmpl)


_EDITABLE_STATUSES = (TemplateStatus.DRAFT, TemplateStatus.REJECTED, TemplateStatus.SUBMISSION_FAILED)


@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: str,
    body: TemplateUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING)),
    db: Session = Depends(get_db),
):
    """Edit a template that isn't with Meta right now. Approved and pending
    templates are locked: Meta limits how often an approved one may change,
    and a pending one is being reviewed."""
    tmpl = db.query(WATemplate).filter_by(id=template_id, tenant_id=current_user.tenant_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    if tmpl.status not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                "An approved template can't be edited. Duplicate it and edit the copy instead."
                if tmpl.status == TemplateStatus.APPROVED
                else "A template that is with Meta for review can't be edited until it is decided."
            ),
        )
    try:
        category = TemplateCategory(body.category.upper())
    except ValueError:
        category = tmpl.category
    _check_template_input(current_user.tenant_id, body.components, body.header_media_key)

    tmpl.language = body.language
    tmpl.category = category
    tmpl.components = body.components
    tmpl.header_media_key = body.header_media_key
    tmpl.status = TemplateStatus.DRAFT       # back to "ready to (re)submit"
    tmpl.rejection_reason = None
    db.commit()
    db.refresh(tmpl)
    return _template_out(tmpl)


@router.post("/templates/media")
def upload_template_media(
    format: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING)),
    db: Session = Depends(get_db),
):
    """Upload the image / video / PDF a template header uses.

    Sends a sample to Meta (its review requires one) and keeps the file in our
    storage (that's what real recipients get). Returns the storage key to put
    on the template, and the handle Meta wants inside the HEADER example."""
    from app.services import wa_template_service as wts
    from app.services.media_storage import upload_wa_template_media, get_presigned_media_url

    fmt = (format or "").upper()
    content = file.file.read()
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    try:
        ext = wts.check_media(fmt, content_type, content)
        wa_int, access_token = _wa_integration_and_token(db, current_user.tenant_id)
        if not wa_int or not access_token:
            raise wts.TemplateError(
                "WhatsApp Business API is not connected for this workspace. "
                "Connect it under Settings -> Integrations first."
            )
        handle = wts.upload_sample_to_meta(access_token, content, content_type, file.filename or f"header.{ext}")
    except wts.TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    key = upload_wa_template_media(current_user.tenant_id, content, content_type, ext)
    log.info("wa_template_media_uploaded", tenant_id=current_user.tenant_id, format=fmt, bytes=len(content))
    return {
        "format": fmt,
        "media_key": key,
        "header_handle": handle,
        "preview_url": get_presigned_media_url(key, expires_in=3600),
    }


@router.post("/templates/lint")
def lint_template(
    body: TemplateCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """T4 — Pre-submit linter: returns lint findings before sending to Meta."""
    from app.services.template_linter import lint_template as _lint, lint_to_dict

    # Extract body text and header text from components
    body_text   = ""
    header_text = None
    sample_values: dict = {}
    for comp in (body.components or []):
        ctype = (comp.get("type") or "").upper()
        if ctype == "BODY":
            body_text = comp.get("text", "")
            # The example values the author typed, keyed by variable number --
            # without them the linter warns that every variable has no sample.
            examples = ((comp.get("example") or {}).get("body_text") or [[]])[0]
            sample_values = {str(i + 1): v for i, v in enumerate(examples) if str(v).strip()}
        elif ctype == "HEADER":
            header_text = comp.get("text")

    findings = _lint(
        body=body_text,
        header=header_text,
        category=body.category or "UTILITY",
        sample_values=sample_values,
    )
    errors = [f for f in findings if f.level == "error"]
    return {
        "findings":  lint_to_dict(findings),
        "has_errors": len(errors) > 0,
        "can_submit": len(errors) == 0,
    }


def _missing_variable_examples(components: list) -> list[str]:
    """Meta rejects a template component containing {{n}} placeholders
    unless it also carries a matching example (header_text / body_text).
    The create form now collects these, but a template created before that
    fix (or via direct API) can still reach here without them -- fail
    loudly with the exact field, rather than let Meta's opaque rejection
    be the first sign anything was wrong."""
    import re
    var_pattern = re.compile(r"\{\{(\d+)\}\}")
    missing = []
    for comp in components or []:
        ctype = (comp.get("type") or "").upper()
        text = comp.get("text") or ""
        var_indices = sorted({int(m) for m in var_pattern.findall(text)})
        if not var_indices:
            continue
        example = comp.get("example") or {}
        if ctype == "HEADER":
            values = example.get("header_text") or []
            if not values or not str(values[0]).strip():
                missing.append("header")
        elif ctype == "BODY":
            values = (example.get("body_text") or [[]])[0]
            if len(values) < len(var_indices) or any(not str(v).strip() for v in values[:len(var_indices)]):
                missing.extend(f"body {{{{{i}}}}}" for i in var_indices)
    return missing


@router.post("/templates/{template_id}/submit")
def submit_template(
    template_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Submit template to Meta for approval."""
    tmpl = db.query(WATemplate).filter_by(id=template_id, tenant_id=current_user.tenant_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    if tmpl.status not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"This template is already {tmpl.status.value}; it can't be submitted again.",
        )

    missing = _missing_variable_examples(tmpl.components)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing example value for: {', '.join(missing)}. "
                    "Meta requires an example for every {{n}} variable — edit the template and add one before submitting.",
        )
    from app.services import wa_template_service as wts
    problems = wts.validate_components(tmpl.components)
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))

    # Fail loudly if WhatsApp isn't connected. The integration lookup falls
    # back from kind="whatsapp_meta" to "whatsapp" like every other WhatsApp
    # code path -- without that, submission silently skipped Meta for tenants
    # on the "whatsapp" kind and the template sat at "Pending" forever.
    wa_int, access_token = _wa_integration_and_token(db, current_user.tenant_id)

    if not wa_int or not access_token or not wa_int.config.get("waba_id"):
        # Fail loudly instead of silently marking the template "Pending" --
        # that used to return 200 with no indication nothing was actually
        # submitted to Meta.
        raise HTTPException(
            status_code=400,
            detail="WhatsApp Business API is not connected for this workspace. "
                    "Connect it under Settings -> Integrations before submitting a template.",
        )

    try:
        if tmpl.meta_template_id:
            # Meta already has this template (it was rejected): changing it
            # is an edit of that record, not a second create, which Meta
            # would refuse because the name is taken.
            resp = httpx.post(
                f"https://graph.facebook.com/v18.0/{tmpl.meta_template_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"category": tmpl.category.value, "components": tmpl.components},
                timeout=15,
            )
        else:
            resp = httpx.post(
                f"https://graph.facebook.com/v18.0/{wa_int.config['waba_id']}/message_templates",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "name": tmpl.name,
                    "language": tmpl.language,
                    "category": tmpl.category.value,
                    "components": tmpl.components,
                },
                timeout=15,
            )
        data = resp.json()
        if "id" in data or data.get("success") is True:
            tmpl.meta_template_id = data.get("id") or tmpl.meta_template_id
            tmpl.rejection_reason = None
            tmpl.status = TemplateStatus.PENDING
        else:
            tmpl.rejection_reason = data.get("error", {}).get("message", "Unknown error")
            tmpl.status = TemplateStatus.REJECTED
    except Exception as e:
        log.error("wa_template_submission_failed", template_id=template_id, error=str(e))
        tmpl.status = TemplateStatus.SUBMISSION_FAILED
        tmpl.rejection_reason = f"Submission request failed: {e}"[:500]

    db.commit()
    return {"status": tmpl.status.value, "meta_template_id": tmpl.meta_template_id, "rejection_reason": tmpl.rejection_reason}


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    tmpl = db.query(WATemplate).filter_by(id=template_id, tenant_id=current_user.tenant_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(tmpl)
    db.commit()


# ─── Campaigns ────────────────────────────────────────────────────────────────

@router.get("/campaigns", response_model=List[CampaignOut])
def list_campaigns(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(WACampaign)
        .filter_by(tenant_id=current_user.tenant_id)
        .order_by(WACampaign.created_at.desc())
        .offset(offset).limit(limit).all()
    )


def _check_campaign_variables(db: Session, tenant_id: str, template_id: Optional[str], variable_map: Optional[dict]) -> None:
    """A campaign can't go out with template variables nobody has said how to
    fill -- Meta rejects the message and every recipient would just fail."""
    if not template_id:
        return
    from app.services import wa_template_service as wts
    tmpl = db.query(WATemplate).filter_by(id=template_id, tenant_id=tenant_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    missing = wts.unmapped_variables(tmpl.components, variable_map)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Say what to fill in for: {', '.join(missing)}.",
        )


@router.post("/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
def create_campaign(
    body: CampaignCreateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING)),
    db: Session = Depends(get_db),
):
    _check_campaign_variables(db, current_user.tenant_id, body.template_id, body.variable_map)
    campaign = WACampaign(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        name=body.name,
        template_id=body.template_id,
        audience_filter=body.audience_filter or {},
        variable_map=body.variable_map or {},
        scheduled_at=body.scheduled_at,
        status=CampaignStatus.DRAFT,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


# Fields a client may change. The old handler copied any attribute name in the
# request body onto the row -- including tenant_id, id and status.
_CAMPAIGN_EDITABLE = ("name", "template_id", "audience_filter", "scheduled_at", "variable_map")


@router.patch("/campaigns/{campaign_id}")
def update_campaign(
    campaign_id: str,
    body: dict,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING)),
    db: Session = Depends(get_db),
):
    campaign = db.query(WACampaign).filter_by(id=campaign_id, tenant_id=current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    changes = {k: v for k, v in body.items() if k in _CAMPAIGN_EDITABLE}
    _check_campaign_variables(
        db, current_user.tenant_id,
        changes.get("template_id", campaign.template_id),
        changes.get("variable_map", campaign.variable_map),
    )
    for field, value in changes.items():
        setattr(campaign, field, value)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.post("/campaigns/{campaign_id}/launch")
def launch_campaign(
    campaign_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    campaign = db.query(WACampaign).filter_by(id=campaign_id, tenant_id=current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
        raise HTTPException(status_code=400, detail=f"Cannot launch campaign in {campaign.status} status")
    _check_campaign_variables(db, current_user.tenant_id, campaign.template_id, campaign.variable_map)
    campaign.status = CampaignStatus.RUNNING
    db.commit()

    # Enqueue the batch-send worker
    from app.workers.tasks.run_campaign import run_campaign
    run_campaign.apply_async(
        kwargs={
            "campaign_id": campaign_id,
            "tenant_id": current_user.tenant_id,
        },
        queue="whatsapp",
    )

    return {"status": "running"}


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    campaign_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING)),
    db: Session = Depends(get_db),
):
    campaign = db.query(WACampaign).filter_by(id=campaign_id, tenant_id=current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == CampaignStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Cannot delete a running campaign")
    db.delete(campaign)
    db.commit()


# ─── Subscribers ─────────────────────────────────────────────────────────────

@router.get("/subscribers", response_model=List[SubscriberOut])
def list_subscribers(
    opted_in: Optional[bool] = None,
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(WASubscriber).filter_by(tenant_id=current_user.tenant_id)
    if opted_in is not None:
        q = q.filter_by(opted_in=opted_in)
    if search:
        q = q.filter(
            (WASubscriber.phone.ilike(f"%{search}%")) |
            (WASubscriber.name.ilike(f"%{search}%"))
        )
    return q.order_by(WASubscriber.created_at.desc()).offset(offset).limit(limit).all()


@router.post("/subscribers", response_model=SubscriberOut, status_code=status.HTTP_201_CREATED)
def upsert_subscriber(
    body: SubscriberUpsertRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING)),
    db: Session = Depends(get_db),
):
    # Normalize to E.164 -- Guest.phone already is (guest_service.normalize_phone),
    # and matching WASubscriber to Guest by exact phone string (VIP tags,
    # campaign audience) silently failed whenever this wasn't typed in
    # exact "+91XXXXXXXXXX" form, which the old "+91 98765 43210"-style
    # placeholder actively invited.
    from app.services.guest_service import normalize_phone
    from app.models.guest import Guest

    phone = normalize_phone(body.phone)
    sub = db.query(WASubscriber).filter_by(tenant_id=current_user.tenant_id, phone=phone).first()
    now = datetime.now(timezone.utc).isoformat()
    guest = db.query(Guest).filter_by(tenant_id=current_user.tenant_id, phone=phone, is_deleted=False).first()

    if not sub:
        sub = WASubscriber(
            id=str(uuid.uuid4()),
            tenant_id=current_user.tenant_id,
            phone=phone,
            name=body.name,
            opted_in=body.opted_in,
            opt_in_at=now if body.opted_in else None,
            opt_out_at=None if body.opted_in else now,
            source=body.source,
            tags=body.tags or [],
            guest_id=guest.id if guest else None,
        )
        db.add(sub)
    else:
        sub.name = body.name or sub.name
        sub.opted_in = body.opted_in
        if body.opted_in:
            sub.opt_in_at = now
            sub.opt_out_at = None
        else:
            sub.opt_out_at = now
        if body.tags:
            sub.tags = list(set((sub.tags or []) + body.tags))
        if not sub.guest_id and guest:
            sub.guest_id = guest.id

    db.commit()
    db.refresh(sub)
    return sub


@router.patch("/subscribers/{subscriber_id}/opt-out")
def opt_out(
    subscriber_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(WASubscriber).filter_by(id=subscriber_id, tenant_id=current_user.tenant_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    sub.opted_in = False
    sub.opt_out_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    return {"status": "opted_out"}


@router.patch("/subscribers/{subscriber_id}/opt-in")
def opt_in(
    subscriber_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(WASubscriber).filter_by(id=subscriber_id, tenant_id=current_user.tenant_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    sub.opted_in = True
    sub.opt_in_at = datetime.now(timezone.utc).isoformat()
    sub.opt_out_at = None
    db.commit()

    # "opt_in" is a real Flow Builder trigger option (flows/page.tsx) that
    # had no fire point anywhere in the codebase -- a flow set to fire on
    # opt-in silently never ran. Only fires when the subscriber resolves to
    # a real guest (every flow trigger requires guest_id, same as every
    # other trigger -- see automation_engine._fire_matching_flows).
    if sub.guest_id:
        from app.workers.tasks.automation_engine import fire_trigger
        fire_trigger.delay(
            event="opt_in",
            tenant_id=current_user.tenant_id,
            context={"guest_id": sub.guest_id, "subscriber_id": sub.id},
        )

    return {"status": "opted_in"}


# ─── Flow Builder ─────────────────────────────────────────────────────────────

@router.get("/flows", response_model=List[FlowOut])
def list_flows(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(WAFlow)
        .filter_by(tenant_id=current_user.tenant_id)
        .order_by(WAFlow.created_at.desc())
        .offset(offset).limit(limit).all()
    )


@router.post("/flows", response_model=FlowOut, status_code=status.HTTP_201_CREATED)
def create_flow(
    body: FlowSaveRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    flow = WAFlow(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        name=body.name,
        description=body.description,
        nodes=body.nodes,
        edges=body.edges,
        trigger=body.trigger,
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return flow


@router.put("/flows/{flow_id}", response_model=FlowOut)
def save_flow(
    flow_id: str,
    body: FlowSaveRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    flow = db.query(WAFlow).filter_by(id=flow_id, tenant_id=current_user.tenant_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    flow.name = body.name
    flow.description = body.description
    flow.nodes = body.nodes
    flow.edges = body.edges
    flow.trigger = body.trigger
    db.commit()
    db.refresh(flow)
    return flow


@router.patch("/flows/{flow_id}/activate")
def activate_flow(
    flow_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    flow = db.query(WAFlow).filter_by(id=flow_id, tenant_id=current_user.tenant_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    flow.is_active = not flow.is_active
    db.commit()
    return {"is_active": flow.is_active}


@router.get("/flows/{flow_id}/runs")
def list_flow_runs(
    flow_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """T2.3: execution log per flow -- one row per node executed, so
    agents can see why a flow did or didn't fire (previously zero
    visibility, since no flow execution happened at all before Phase 2)."""
    from app.models.flow_execution import WAFlowRun

    flow = db.query(WAFlow).filter_by(id=flow_id, tenant_id=current_user.tenant_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    runs = (
        db.query(WAFlowRun)
        .filter_by(tenant_id=current_user.tenant_id, flow_id=flow_id)
        .order_by(WAFlowRun.ran_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id, "guest_id": r.guest_id, "node_id": r.node_id, "node_type": r.node_type,
            "status": r.status, "detail": r.detail, "error": r.error,
            "ran_at": r.ran_at.isoformat() if r.ran_at else None,
        }
        for r in runs
    ]


@router.delete("/flows/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flow(
    flow_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    flow = db.query(WAFlow).filter_by(id=flow_id, tenant_id=current_user.tenant_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    db.delete(flow)
    db.commit()
