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
from fastapi import APIRouter, Depends, HTTPException, Query, status
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


class TemplateOut(BaseModel):
    id: str
    name: str
    language: str
    category: str
    status: str
    components: list
    meta_template_id: Optional[str] = None
    rejection_reason: Optional[str] = None
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

@router.get("/templates", response_model=List[TemplateOut])
def list_templates(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(WATemplate)
        .filter_by(tenant_id=current_user.tenant_id)
        .order_by(WATemplate.created_at.desc())
        .offset(offset).limit(limit).all()
    )


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

    tmpl = WATemplate(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        name=body.name.lower().replace(" ", "_"),
        language=body.language,
        category=category,
        components=body.components,
        status=TemplateStatus.DRAFT,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return tmpl


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
    for comp in (body.components or []):
        ctype = (comp.get("type") or "").upper()
        if ctype == "BODY":
            body_text   = comp.get("text", "")
        elif ctype == "HEADER":
            header_text = comp.get("text")

    findings = _lint(
        body=body_text,
        header=header_text,
        category=body.category or "UTILITY",
    )
    errors = [f for f in findings if f.level == "error"]
    return {
        "findings":  lint_to_dict(findings),
        "has_errors": len(errors) > 0,
        "can_submit": len(errors) == 0,
    }


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

    # Try to submit via Meta Graph API if WhatsApp is connected
    from app.models.integration import Integration
    wa_int = db.query(Integration).filter_by(tenant_id=current_user.tenant_id, kind="whatsapp_meta", status="active").first()

    if wa_int and wa_int.config.get("access_token") and wa_int.config.get("waba_id"):
        try:
            resp = httpx.post(
                f"https://graph.facebook.com/v18.0/{wa_int.config['waba_id']}/message_templates",
                headers={"Authorization": f"Bearer {wa_int.config['access_token']}"},
                json={
                    "name": tmpl.name,
                    "language": tmpl.language,
                    "category": tmpl.category.value,
                    "components": tmpl.components,
                },
                timeout=15,
            )
            data = resp.json()
            if "id" in data:
                tmpl.meta_template_id = data["id"]
                tmpl.status = TemplateStatus.PENDING
            else:
                tmpl.rejection_reason = data.get("error", {}).get("message", "Unknown error")
                tmpl.status = TemplateStatus.REJECTED
        except Exception as e:
            log.error("wa_template_submission_failed", template_id=template_id, error=str(e))
            tmpl.status = TemplateStatus.SUBMISSION_FAILED
            tmpl.rejection_reason = f"Submission request failed: {e}"[:500]
    else:
        tmpl.status = TemplateStatus.PENDING

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


@router.post("/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
def create_campaign(
    body: CampaignCreateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING)),
    db: Session = Depends(get_db),
):
    campaign = WACampaign(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        name=body.name,
        template_id=body.template_id,
        audience_filter=body.audience_filter or {},
        scheduled_at=body.scheduled_at,
        status=CampaignStatus.DRAFT,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


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
    for field, value in body.items():
        if hasattr(campaign, field):
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
    sub = db.query(WASubscriber).filter_by(tenant_id=current_user.tenant_id, phone=body.phone).first()
    now = datetime.now(timezone.utc).isoformat()

    if not sub:
        sub = WASubscriber(
            id=str(uuid.uuid4()),
            tenant_id=current_user.tenant_id,
            phone=body.phone,
            name=body.name,
            opted_in=body.opted_in,
            opt_in_at=now if body.opted_in else None,
            opt_out_at=None if body.opted_in else now,
            source=body.source,
            tags=body.tags or [],
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
