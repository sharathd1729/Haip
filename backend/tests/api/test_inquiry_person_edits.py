"""A trip field a PERSON types on a lead is theirs: PATCH /inquiries/{id} records it in custom_fields["set_by_person"]
and the AI summary stops writing it (owner, 28 Nov 2026). Clearing the field hands it back to the AI.
"""
import uuid

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.inquiry_service import fields_set_by_person
from app.workers.tasks.generate_ai_summary import _apply_extracted_fields


@pytest.fixture()
def auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


@pytest.fixture()
def inquiry(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, phone="+919999000321", name="Test Guest")
    db.add(g); db.commit()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, source=InquirySource.WA_DIRECT,
                  adults=4, check_in="2026-12-20", dates_from_chat=True, route_mentioned="Pune to Goa",
                  custom_fields={"pickup": "Airport"})
    db.add(inq); db.commit()
    return inq


def test_what_a_person_types_is_kept_from_the_ai(client, db, auth_headers, inquiry):
    r = client.patch(f"/api/v1/inquiries/{inquiry.id}", headers=auth_headers,
                     json={"adults": 6, "check_in": "2026-12-24", "occasion": "anniversary"})
    assert r.status_code == 200, r.text
    db.refresh(inquiry)
    assert fields_set_by_person(inquiry) == {"adults", "check_in", "occasion"}
    assert inquiry.custom_fields["pickup"] == "Airport"       # the other keys kept there survive
    assert inquiry.dates_from_chat is False                    # a typed date is no longer the chat's guess

    # the next summary run re-reads the old chat: the typed fields stay, an untouched one still updates
    written = _apply_extracted_fields(inquiry, {"adults": 4, "check_in": "2026-12-20", "occasion": "family trip", "children": 2})
    assert (inquiry.adults, inquiry.check_in, inquiry.occasion) == (6, "2026-12-24", "anniversary")
    assert written == ["children"]


def test_clearing_a_field_hands_it_back_to_the_ai(client, db, auth_headers, inquiry):
    assert client.patch(f"/api/v1/inquiries/{inquiry.id}", headers=auth_headers, json={"route_mentioned": "Pune to Hampi"}).status_code == 200
    db.refresh(inquiry)
    assert fields_set_by_person(inquiry) == {"route_mentioned"}

    assert client.patch(f"/api/v1/inquiries/{inquiry.id}", headers=auth_headers, json={"route_mentioned": ""}).status_code == 200
    db.refresh(inquiry)
    assert inquiry.route_mentioned is None
    assert fields_set_by_person(inquiry) == set()
    assert "set_by_person" not in inquiry.custom_fields

    assert "route_mentioned" in _apply_extracted_fields(inquiry, {"route_mentioned": "Pune to Gokarna"})
    assert inquiry.route_mentioned == "Pune to Gokarna"


def test_an_edit_that_is_not_a_trip_field_marks_nothing(client, db, auth_headers, inquiry):
    assert client.patch(f"/api/v1/inquiries/{inquiry.id}", headers=auth_headers, json={"pickup": "Station"}).status_code == 200
    db.refresh(inquiry)
    assert fields_set_by_person(inquiry) == set()
    assert inquiry.custom_fields == {"pickup": "Station"}


def test_another_workspace_cannot_edit_or_mark_the_lead(client, db, inquiry):
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.commit()
    outsider = User(id=str(uuid.uuid4()), tenant_id=other.id, name="Outsider", email=f"{uuid.uuid4().hex[:8]}@test.com",
                    hashed_password=get_password_hash("pw"), role=UserRole.OWNER, is_active=True)
    db.add(outsider); db.commit()
    token = create_access_token({"sub": outsider.id, "tenant_id": other.id, "role": "owner"})
    r = client.patch(f"/api/v1/inquiries/{inquiry.id}", headers={"Authorization": f"Bearer {token}"}, json={"adults": 9})
    assert r.status_code == 404
    db.refresh(inquiry)
    assert inquiry.adults == 4 and fields_set_by_person(inquiry) == set()
