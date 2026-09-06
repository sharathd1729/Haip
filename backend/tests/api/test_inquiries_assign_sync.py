"""Assign-to-me visibility fix: PATCH /inquiries/{id} {assigned_to} must also
sync Conversation.assigned_to on every conversation for that inquiry --
previously the two columns were independent, so a lead assigned via
GuestPanel/Profile 360 (the Inquiry-based path) never showed up under the
Inbox's "Assigned to Me" chip or the Worklist page (both read
Conversation.assigned_to).
"""
import uuid

import pytest

from app.models.guest import Guest
from app.models.conversation import Conversation
from app.models.inquiry import Inquiry, InquirySource
from app.models.user import User, UserRole
from app.core.security import get_password_hash


@pytest.fixture()
def auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


@pytest.fixture()
def guest(db, tenant_and_user):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id, phone="+919999000010", name="Test Guest")
    db.add(g); db.commit()
    return g


@pytest.fixture()
def agent(db, tenant_and_user):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id, name="Krishna",
        email=f"{uuid.uuid4().hex[:8]}@test.com", hashed_password=get_password_hash("pw"),
        role=UserRole.CONCIERGE, is_active=True,
    )
    db.add(u); db.commit()
    return u


@pytest.fixture()
def inquiry(db, tenant_and_user, guest):
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id, guest_id=guest.id,
        source=InquirySource.WHATSAPP if hasattr(InquirySource, "WHATSAPP") else list(InquirySource)[0],
    )
    db.add(inq); db.commit()
    return inq


def _make_conversation(db, tenant_id, guest_id, inquiry_id):
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, inquiry_id=inquiry_id, channel="whatsapp", is_open=True)
    db.add(conv); db.commit()
    return conv


class TestAssignSyncsToConversation:
    def test_assigning_inquiry_updates_its_conversation(self, client, db, auth_headers, tenant_and_user, inquiry, agent):
        conv = _make_conversation(db, tenant_and_user["tenant"].id, inquiry.guest_id, inquiry.id)
        client.headers.update(auth_headers)

        resp = client.patch(f"/api/v1/inquiries/{inquiry.id}", json={"assigned_to": agent.id})
        assert resp.status_code == 200

        db.expire_all()
        assert db.get(Conversation, conv.id).assigned_to == agent.id

    def test_updates_every_conversation_on_that_inquiry(self, client, db, auth_headers, tenant_and_user, inquiry, agent):
        """A guest can have more than one channel thread tied to the same
        inquiry (e.g. WhatsApp + a later Instagram DM) -- all must sync."""
        conv1 = _make_conversation(db, tenant_and_user["tenant"].id, inquiry.guest_id, inquiry.id)
        conv2 = _make_conversation(db, tenant_and_user["tenant"].id, inquiry.guest_id, inquiry.id)
        client.headers.update(auth_headers)

        resp = client.patch(f"/api/v1/inquiries/{inquiry.id}", json={"assigned_to": agent.id})
        assert resp.status_code == 200

        db.expire_all()
        assert db.get(Conversation, conv1.id).assigned_to == agent.id
        assert db.get(Conversation, conv2.id).assigned_to == agent.id

    def test_does_not_touch_conversations_on_other_inquiries(self, client, db, auth_headers, tenant_and_user, inquiry, agent, guest):
        other_inquiry = Inquiry(
            id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id, guest_id=guest.id,
            source=list(InquirySource)[0],
        )
        db.add(other_inquiry); db.commit()
        unrelated_conv = _make_conversation(db, tenant_and_user["tenant"].id, guest.id, other_inquiry.id)
        client.headers.update(auth_headers)

        client.patch(f"/api/v1/inquiries/{inquiry.id}", json={"assigned_to": agent.id})

        db.expire_all()
        assert db.get(Conversation, unrelated_conv.id).assigned_to is None

    def test_unrelated_field_update_does_not_touch_conversation(self, client, db, auth_headers, tenant_and_user, inquiry, agent):
        conv = _make_conversation(db, tenant_and_user["tenant"].id, inquiry.guest_id, inquiry.id)
        db.query(Conversation).filter_by(id=conv.id).update({"assigned_to": agent.id})
        db.commit()
        client.headers.update(auth_headers)

        resp = client.patch(f"/api/v1/inquiries/{inquiry.id}", json={"budget": 50000})
        assert resp.status_code == 200

        db.expire_all()
        assert db.get(Conversation, conv.id).assigned_to == agent.id
