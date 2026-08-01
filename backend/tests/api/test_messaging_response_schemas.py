"""
Regression: messaging response schemas typed created_at as `str` while the
column is a DateTime (TimestampMixin). Pydantic v2 refuses to coerce
datetime -> str, so FastAPI response validation raised on every template /
campaign / flow response — a 500 on both create and list. The UI surfaced
it as a bare "Failed to create template.", and confusingly the row WAS
written: only the response blew up.

These assert the Out schemas can serialise a real ORM instance, which is
exactly what response_model= does on the way out.
"""
import uuid

import pytest

from app.api.v1.endpoints.messaging import (
    WATemplate, TemplateOut, TemplateStatus, TemplateCategory,
    WACampaign, CampaignOut, CampaignStatus,
    WAFlow, FlowOut,
)


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def test_template_out_serialises_orm_row(db, tenant_and_user):
    tmpl = WATemplate(
        id=str(uuid.uuid4()), tenant_id=_tenant_id(tenant_and_user),
        name="welcome", language="en",
        category=TemplateCategory.UTILITY, status=TemplateStatus.DRAFT,
        components=[{"type": "BODY", "text": "Hi {{1}}"}],
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)

    out = TemplateOut.model_validate(tmpl)
    assert out.name == "welcome"
    # created_at must survive the round trip as an ISO string on the wire
    assert isinstance(out.model_dump(mode="json")["created_at"], str)


def test_campaign_out_serialises_orm_row(db, tenant_and_user):
    camp = WACampaign(
        id=str(uuid.uuid4()), tenant_id=_tenant_id(tenant_and_user),
        name="Diwali blast", status=CampaignStatus.DRAFT,
        audience_filter={}, sent_count="0", delivered_count="0",
        read_count="0", failed_count="0",
    )
    db.add(camp)
    db.commit()
    db.refresh(camp)

    out = CampaignOut.model_validate(camp)
    assert out.name == "Diwali blast"
    assert isinstance(out.model_dump(mode="json")["created_at"], str)


def test_flow_out_serialises_orm_row(db, tenant_and_user):
    flow = WAFlow(
        id=str(uuid.uuid4()), tenant_id=_tenant_id(tenant_and_user),
        name="Welcome", nodes=[], edges=[], is_active=False,
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)

    out = FlowOut.model_validate(flow)
    assert out.name == "Welcome"
    assert isinstance(out.model_dump(mode="json")["created_at"], str)
