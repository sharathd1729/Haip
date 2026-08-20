"""Tests for HAIP_AI_Autonomy_Plan.md Phase 2's broader one-click action set:
move_stage, assign_to, hold_dates, send_quote -- fired via
POST /automations/actions/execute, the same endpoint AIRecommendationCard uses.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, BlockedDate
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.core.security import get_password_hash


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _make_stage(db, tenant_id, key, order, **kwargs):
    stage = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key=key, label=key.title(), order=order, **kwargs)
    db.add(stage)
    return stage


def _make_inquiry(db, tenant_id, stage_id):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Test Guest", phone=f"+9199998{uuid.uuid4().hex[:5]}")
    db.add(guest); db.flush()
    inquiry = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, stage_id=stage_id, source=InquirySource.PHONE)
    db.add(inquiry); db.commit()
    return inquiry, guest


def _make_property(db, tenant_id, **kwargs):
    prop = Property(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Test Villa", slug=f"villa-{uuid.uuid4().hex[:6]}", **kwargs)
    db.add(prop); db.commit()
    return prop


class TestMoveStage:
    def test_forward_move_happy_path(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        stage_a = _make_stage(db, tenant_id, "general_enquiry", order=1)
        stage_b = _make_stage(db, tenant_id, "active", order=2, category="valid")
        db.commit()
        inquiry, _ = _make_inquiry(db, tenant_id, stage_a.id)

        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "move_stage",
                "entity_refs": {"inquiry_id": inquiry.id},
                "action_config": {"new_stage_id": stage_b.id},
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "success"

        db.refresh(inquiry)
        assert inquiry.stage_id == stage_b.id

    def test_backward_move_without_reason_is_rejected(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        stage_a = _make_stage(db, tenant_id, "general_enquiry", order=1)
        stage_b = _make_stage(db, tenant_id, "active", order=2, category="valid")
        db.commit()
        inquiry, _ = _make_inquiry(db, tenant_id, stage_b.id)  # start ahead

        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "move_stage",
                "entity_refs": {"inquiry_id": inquiry.id},
                "action_config": {"new_stage_id": stage_a.id},  # backward, no reason
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200
        assert "reason is required" in resp.json()["detail"].lower()

        db.refresh(inquiry)
        assert inquiry.stage_id == stage_b.id  # unchanged

    def test_cross_tenant_inquiry_not_found(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        stage_b = _make_stage(db, tenant_id, "active", order=2, category="valid")
        db.commit()

        other_tenant_id = str(uuid.uuid4())
        db.add(Tenant(id=other_tenant_id, name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth"))
        db.commit()
        other_stage_a = _make_stage(db, other_tenant_id, "general_enquiry", order=1)
        db.commit()
        other_inquiry, _ = _make_inquiry(db, other_tenant_id, other_stage_a.id)

        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "move_stage",
                "entity_refs": {"inquiry_id": other_inquiry.id},
                "action_config": {"new_stage_id": stage_b.id},
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200
        assert "not found" in resp.json()["detail"].lower()


class TestAssignTo:
    def test_happy_path(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        stage = _make_stage(db, tenant_id, "active", order=1, category="valid")
        db.commit()
        inquiry, _ = _make_inquiry(db, tenant_id, stage.id)

        assignee = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="Concierge Two",
            email=f"c2-{uuid.uuid4().hex[:6]}@test.com", hashed_password=get_password_hash("x"),
            role=UserRole.CONCIERGE, is_active=True,
        )
        db.add(assignee); db.commit()

        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "assign_to",
                "entity_refs": {"inquiry_id": inquiry.id},
                "action_config": {"user_id": assignee.id},
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200, resp.text
        db.refresh(inquiry)
        assert inquiry.assigned_to == assignee.id


class TestHoldDates:
    def test_happy_path_creates_blocked_date(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        prop = _make_property(db, tenant_id)

        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "hold_dates",
                "entity_refs": {"property_id": prop.id},
                "action_config": {"property_id": prop.id, "from": "2026-12-10", "to": "2026-12-12"},
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200, resp.text

        blocks = db.query(BlockedDate).filter_by(tenant_id=tenant_id, property_id=prop.id).all()
        assert len(blocks) == 1
        assert blocks[0].reason == "hold"
        assert blocks[0].is_active is True

    def test_property_not_found(self, client, tenant_and_user):
        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "hold_dates",
                "entity_refs": {"property_id": str(uuid.uuid4())},
                "action_config": {"property_id": str(uuid.uuid4()), "from": "2026-12-10", "to": "2026-12-12"},
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200
        assert "not found" in resp.json()["detail"].lower()


class TestSendQuote:
    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_happy_path_sends_text_quote(self, mock_delay, client, db, tenant_and_user):
        from app.models.conversation import Conversation, ChannelType

        tenant_id = _tenant_id(tenant_and_user)
        prop = _make_property(db, tenant_id)
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Quote Guest", phone="+919999012345")
        db.add(guest); db.flush()
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(conv); db.commit()

        fake_quote = MagicMock(subtotal=20000, gst=2400, total=22400, advance_amount=6720, currency="INR")
        with patch("app.services.calculator_service.calculator_service.build_quote", return_value=fake_quote):
            resp = client.post(
                "/api/v1/automations/actions/execute",
                json={
                    "action_type": "send_quote",
                    "entity_refs": {"guest_id": guest.id, "property_id": prop.id},
                    "action_config": {"property_id": prop.id, "checkin": "2026-12-10", "checkout": "2026-12-12", "adults": 2},
                },
                headers=_auth_headers(tenant_and_user),
            )
        assert resp.status_code == 200, resp.text
        mock_delay.assert_called_once()

        from app.models.conversation import Message
        quote_msg = db.query(Message).filter_by(conversation_id=conv.id, direction="outbound").first()
        assert quote_msg is not None
        assert "22400" in quote_msg.body

    def test_guest_without_phone_is_skipped(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        prop = _make_property(db, tenant_id)
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="No Phone Guest", phone=None)
        db.add(guest); db.commit()

        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "send_quote",
                "entity_refs": {"guest_id": guest.id, "property_id": prop.id},
                "action_config": {"property_id": prop.id, "checkin": "2026-12-10", "checkout": "2026-12-12"},
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200
        assert "no phone" in resp.json()["detail"].lower()


class TestRegenerateDraftTone:
    def test_ai_draft_request_accepts_and_forwards_tone(self, client, db, tenant_and_user, monkeypatch):
        from app.models.conversation import Conversation, ChannelType

        tenant_id = _tenant_id(tenant_and_user)
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Tone Guest", phone="+919999054321")
        db.add(guest); db.flush()
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(conv); db.commit()

        captured = {}
        def _fake_delay(**kwargs):
            captured.update(kwargs)
        monkeypatch.setattr("app.workers.tasks.concierge_draft.concierge_draft.delay", _fake_delay)

        resp = client.post(
            f"/api/v1/conversations/{conv.id}/messages/ai-draft",
            json={"tone": "persuasive"},
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200, resp.text
        assert captured.get("tone") == "persuasive"

    def test_concierge_draft_task_renders_tone_instruction(self):
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader("app/prompts"))
        template = env.get_template("concierge_reply.jinja")

        class T:
            brand_name = "Ratha"; name = "Ratha"; brand_config = {}
        class G:
            name = "Priya"; language_pref = "en"; total_stays = 1
            predicted_csat = None; vip_tier = "standard"; tags = []

        # Asserts the tone branch renders *a* tone instruction, not one exact
        # sentence -- the previous "Tone: brief" literal broke on a pure
        # rewording of the prompt (v6) even though the behaviour was intact.
        out_with_tone = template.render(
            tenant=T(), guest=G(), inquiry=None, recent_messages=[], call_summaries=[],
            kb_snippets=[], grounded_facts=[], tone="brief",
        )
        assert "brief" in out_with_tone.lower()

        out_without_tone = template.render(
            tenant=T(), guest=G(), inquiry=None, recent_messages=[], call_summaries=[],
            kb_snippets=[], grounded_facts=[], tone=None,
        )
        # The other tones' instruction lines must not leak in when no tone is set.
        for other in ("warm and personable", "formal and precise", "maximally brief", "persuasive"):
            assert other not in out_without_tone.lower()
