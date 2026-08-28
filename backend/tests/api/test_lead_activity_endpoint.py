"""GET /leads-activity -- role-scoped, same query the daily reports use."""
import uuid
from datetime import datetime, timezone

from tests.conftest import *  # noqa: F401,F403

from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.user import User, UserRole

TODAY = datetime.now(timezone.utc).date().isoformat()
NOON_TODAY = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_lead_for(db, tenant_id, agent_id, guest_name="Chitra"):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=guest_name, phone="+919999000005")
    db.add(guest); db.flush()
    inquiry = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, source=InquirySource.WA_DIRECT)
    db.add(inquiry); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, inquiry_id=inquiry.id,
                         channel=ChannelType.WHATSAPP, human_owned=True)
    db.add(conv); db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
                    direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
                    body="Hi", sender_id=agent_id, created_at=NOON_TODAY))
    db.commit()


class TestSelfScoping:
    def test_non_owner_always_sees_only_their_own_leads(self, client, db, tenant_and_user):
        """tenant_and_user's default role is owner-ish per conftest; use a
        real non-owner agent explicitly to prove self-scoping."""
        tenant_id = _tenant_id(tenant_and_user)
        agent = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email="agent@t.com", name="Agent", role=UserRole.RESERVATIONS)
        db.add(agent); db.commit()
        other_agent = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email="other@t.com", name="Other", role=UserRole.RESERVATIONS)
        db.add(other_agent); db.commit()
        _make_lead_for(db, tenant_id, other_agent.id, "OtherAgentsLead")

        from app.core.security import create_access_token
        token = create_access_token({"sub": agent.id, "tenant_id": tenant_id, "role": agent.role.value})
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get(f"/api/v1/leads-activity?date={TODAY}&agent_id={other_agent.id}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        # A non-owner cannot escape self-scoping even by passing agent_id.
        assert body["agent_id"] == agent.id
        assert body["leads"] == []


class TestOwnerScoping:
    def test_owner_can_view_a_specific_agent(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        agent = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email="agent2@t.com", name="Agent2", role=UserRole.RESERVATIONS)
        db.add(agent); db.commit()
        _make_lead_for(db, tenant_id, agent.id, "Chitra")
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

        resp = client.get(f"/api/v1/leads-activity?date={TODAY}&agent_id={agent.id}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent_id"] == agent.id
        assert len(body["leads"]) == 1
        assert body["leads"][0]["guest_name"] == "Chitra"

    def test_owner_without_agent_id_sees_every_agent(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        a1 = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email="a1@t.com", name="A1", role=UserRole.RESERVATIONS)
        a2 = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email="a2@t.com", name="A2", role=UserRole.RESERVATIONS)
        db.add_all([a1, a2]); db.commit()
        _make_lead_for(db, tenant_id, a1.id, "Lead1")
        _make_lead_for(db, tenant_id, a2.id, "Lead2")
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

        resp = client.get(f"/api/v1/leads-activity?date={TODAY}", headers=headers)
        assert resp.status_code == 200
        names = {l["guest_name"] for l in resp.json()["leads"]}
        assert names == {"Lead1", "Lead2"}
