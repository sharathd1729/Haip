"""Tests for HAIP Inbox UI-fidelity pass, ticket 2: list_conversations was
already eager-loading Conversation.assigned_to and Conversation.inquiry for
every row, but ConversationOut never surfaced owner/stage/completeness/SLA
from them -- the confirmed root cause of "lead owner not showing" / "lead
stage not there" in the inbox left-list."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.conversation import Conversation, Message, ChannelType
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.inquiry import Inquiry, InquiryStage
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _make_guest(db, tenant_id, phone="+919999011223"):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Priya", phone=phone)
    db.add(guest); db.commit()
    return guest


class TestListConversationsEnrichment:
    def test_surfaces_owner_stage_and_completeness(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        owner = tenant_and_user["user"]
        guest = _make_guest(db, tenant_id)
        db.add(GuestIdentity(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            identity_type="phone", identity_value=guest.phone, confidence=0.90,
        ))
        stage = PipelineStage(
            id=str(uuid.uuid4()), tenant_id=tenant_id, key="active", label="Active",
            order=1, category="valid",
        )
        db.add(stage); db.flush()

        inquiry = Inquiry(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            stage=InquiryStage.RESPONDING, stage_id=stage.id,
            first_response_at=datetime.now(timezone.utc).isoformat(),
        )
        db.add(inquiry); db.flush()

        conv = Conversation(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            inquiry_id=inquiry.id, assigned_to=owner.id,
            channel=ChannelType.WHATSAPP, is_open=True,
        )
        db.add(conv); db.commit()
        db.add(Message(
            id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
            direction="inbound", channel="whatsapp", body="Is the villa free next week?",
        ))
        db.commit()

        resp = client.get("/api/v1/conversations", headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json() if r["id"] == conv.id)

        assert row["assigned_owner_name"] == owner.name
        assert row["stage_key"] == "active"
        assert row["stage_label"] == "Active"
        assert row["profile_completeness_pct"] == 80  # phone-only tier, per _COMPLETENESS_MAP
        assert row["is_waiting_reply"] is True
        assert row["sla_status"] == "on_time"  # already has first_response_at

    def test_sla_breached_when_unresponded_past_30_minutes(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id, phone="+919999022334")

        old_created = datetime.now(timezone.utc) - timedelta(minutes=45)
        inquiry = Inquiry(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            stage=InquiryStage.NEW, created_at=old_created,
        )
        db.add(inquiry); db.flush()

        conv = Conversation(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            inquiry_id=inquiry.id, channel=ChannelType.WHATSAPP, is_open=True,
        )
        db.add(conv); db.commit()

        resp = client.get("/api/v1/conversations", headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json() if r["id"] == conv.id)

        assert row["sla_status"] == "breached"
        assert row["assigned_owner_name"] is None
        assert row["stage_key"] is None

    def test_no_inquiry_yields_null_stage_and_sla(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id, phone="+919999033445")
        conv = Conversation(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            channel=ChannelType.WHATSAPP, is_open=True,
        )
        db.add(conv); db.commit()

        resp = client.get("/api/v1/conversations", headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json() if r["id"] == conv.id)

        assert row["sla_status"] is None
        assert row["stage_key"] is None
        assert row["profile_completeness_pct"] == 0

    def test_cross_tenant_owner_not_leaked(self, client, db, tenant_and_user):
        """An assigned_to id that happens to belong to a different tenant's
        user (shouldn't occur in practice, but the batch query filters on
        tenant_id -- guards against ever resolving a cross-tenant name)."""
        tenant_id = _tenant_id(tenant_and_user)
        other_tenant_id = str(uuid.uuid4())
        db.add(Tenant(id=other_tenant_id, name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth"))
        db.commit()

        from app.models.user import User, UserRole
        from app.core.security import get_password_hash
        stranger = User(
            id=str(uuid.uuid4()), tenant_id=other_tenant_id, name="Stranger",
            email=f"stranger-{uuid.uuid4().hex[:6]}@test.com",
            hashed_password=get_password_hash("testpassword123"),
            role=UserRole.OWNER, is_active=True,
        )
        db.add(stranger); db.commit()

        guest = _make_guest(db, tenant_id, phone="+919999044556")
        conv = Conversation(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            assigned_to=stranger.id, channel=ChannelType.WHATSAPP, is_open=True,
        )
        db.add(conv); db.commit()

        resp = client.get("/api/v1/conversations", headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json() if r["id"] == conv.id)
        assert row["assigned_owner_name"] is None
