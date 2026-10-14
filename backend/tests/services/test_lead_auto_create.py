"""
Tests for lead_auto_create.py + inquiry_service.get_or_create_from_chat --
Leads360 chat auto-create (WhatsApp/Instagram first-message routing).
"""
import uuid
import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.services import lead_auto_create as lac
from app.services.inquiry_service import get_or_create_from_chat, get_or_create_from_call


def _make_tenant(db, name="TenantLeadAuto"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"lac-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_guest(db, tenant_id):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone="")
    db.add(g)
    db.flush()
    return g


def _make_stage(db, tenant_id, key, order, **kwargs):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key=key, label=key.title(), order=order, **kwargs)
    db.add(s)
    db.flush()
    return s


# ── keyword / phone detection helpers ───────────────────────────────────────

def test_is_collab_message_matches_keywords():
    assert lac.is_collab_message("Hi, interested in a collab with your resort")
    assert lac.is_collab_message("We are a B2B travel agency")
    assert lac.is_collab_message("I'm a content creator, want to partner?")
    assert not lac.is_collab_message("What's the tariff for 2 nights?")
    assert not lac.is_collab_message("")


def test_text_contains_phone():
    assert lac.text_contains_phone("call me at 9876543210")
    assert lac.text_contains_phone("+91 98765 43210")
    assert not lac.text_contains_phone("looking for a villa this weekend")


# ── resolve_entry_stage_id ───────────────────────────────────────────────────

def test_resolve_entry_stage_id_routes_by_flags(db):
    t = _make_tenant(db)
    default_stage = _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    valid_stage = _make_stage(db, t.id, "active", 1, category="valid", is_valid_lead_entry=True)
    collab_stage = _make_stage(db, t.id, "collab", 2, category="marketing", is_collab_entry=True)

    assert lac.resolve_entry_stage_id(db, t.id, is_collab=True, has_phone=True) == collab_stage.id
    assert lac.resolve_entry_stage_id(db, t.id, is_collab=False, has_phone=True) == valid_stage.id
    assert lac.resolve_entry_stage_id(db, t.id, is_collab=False, has_phone=False) == default_stage.id


def test_resolve_entry_stage_id_falls_back_to_none_when_untagged(db):
    t = _make_tenant(db)
    _make_stage(db, t.id, "new", 0)
    assert lac.resolve_entry_stage_id(db, t.id, is_collab=False, has_phone=True) is None


# ── get_or_create_from_chat: end-to-end routing + dedup ─────────────────────

def test_get_or_create_from_chat_whatsapp_always_routes_valid(db):
    t = _make_tenant(db)
    _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    valid_stage = _make_stage(db, t.id, "active", 1, category="valid", is_valid_lead_entry=True)
    guest = _make_guest(db, t.id)

    inquiry = get_or_create_from_chat(
        db, t.id, guest.id, source=InquirySource.WA_DIRECT.value, message_text="Hi, is the villa free this weekend?",
    )
    assert inquiry.stage_id == valid_stage.id
    assert inquiry.source == InquirySource.WA_DIRECT


def test_get_or_create_from_chat_instagram_no_phone_routes_default(db):
    t = _make_tenant(db)
    default_stage = _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    _make_stage(db, t.id, "active", 1, category="valid", is_valid_lead_entry=True)
    guest = _make_guest(db, t.id)

    inquiry = get_or_create_from_chat(
        db, t.id, guest.id, source=InquirySource.META_IG.value, message_text="Do you have availability?",
    )
    assert inquiry.stage_id == default_stage.id


def test_get_or_create_from_chat_instagram_with_phone_routes_valid(db):
    t = _make_tenant(db)
    _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    valid_stage = _make_stage(db, t.id, "active", 1, category="valid", is_valid_lead_entry=True)
    guest = _make_guest(db, t.id)

    inquiry = get_or_create_from_chat(
        db, t.id, guest.id, source=InquirySource.META_IG.value, message_text="call me on 9876543210 please",
    )
    assert inquiry.stage_id == valid_stage.id


def test_get_or_create_from_chat_collab_keyword_routes_collab_over_phone(db):
    t = _make_tenant(db)
    _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    _make_stage(db, t.id, "active", 1, category="valid", is_valid_lead_entry=True)
    collab_stage = _make_stage(db, t.id, "collab", 2, category="marketing", is_collab_entry=True)
    guest = _make_guest(db, t.id)

    inquiry = get_or_create_from_chat(
        db, t.id, guest.id, source=InquirySource.WA_DIRECT.value,
        message_text="Hi I'm a content creator, keen on a UGC collab -- 9876543210",
    )
    assert inquiry.stage_id == collab_stage.id


def test_get_or_create_from_chat_dedupes_existing_open_inquiry(db):
    t = _make_tenant(db)
    _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    valid_stage = _make_stage(db, t.id, "active", 1, category="valid", is_valid_lead_entry=True)
    guest = _make_guest(db, t.id)

    first = get_or_create_from_chat(
        db, t.id, guest.id, source=InquirySource.WA_DIRECT.value, message_text="hello",
    )
    second = get_or_create_from_chat(
        db, t.id, guest.id, source=InquirySource.WA_DIRECT.value, message_text="collab please",
    )
    assert first.id == second.id
    assert second.stage_id == valid_stage.id  # unchanged, no re-routing on repeat message


def test_get_or_create_from_chat_tenant_isolation(db):
    t1 = _make_tenant(db, "T1")
    t2 = _make_tenant(db, "T2")
    _make_stage(db, t1.id, "active", 0, category="valid", is_valid_lead_entry=True, is_default_entry=True)
    t2_valid = _make_stage(db, t2.id, "active", 0, category="valid", is_valid_lead_entry=True, is_default_entry=True)
    guest = _make_guest(db, t2.id)

    inquiry = get_or_create_from_chat(
        db, t2.id, guest.id, source=InquirySource.WA_DIRECT.value, message_text="hi",
    )
    assert inquiry.tenant_id == t2.id
    assert inquiry.stage_id == t2_valid.id

    count_t1 = db.query(Inquiry).filter_by(tenant_id=t1.id).count()
    assert count_t1 == 0


# ── resolve_call_entry_stage_id + get_or_create_from_call ──────────────────

def test_resolve_call_entry_stage_id_routes_by_answered(db):
    t = _make_tenant(db)
    default_stage = _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    rnr_stage = _make_stage(db, t.id, "rnr", 1, category="invalid")
    valid_stage = _make_stage(db, t.id, "active", 2, category="valid", is_valid_lead_entry=True)

    assert lac.resolve_call_entry_stage_id(db, t.id, answered=False) == rnr_stage.id
    assert lac.resolve_call_entry_stage_id(db, t.id, answered=True) == valid_stage.id


def test_resolve_call_entry_stage_id_falls_back_without_rnr_stage(db):
    t = _make_tenant(db)
    default_stage = _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    _make_stage(db, t.id, "active", 1, category="valid", is_valid_lead_entry=True)

    assert lac.resolve_call_entry_stage_id(db, t.id, answered=False) == default_stage.id


def test_get_or_create_from_call_answered_routes_active(db):
    t = _make_tenant(db)
    _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    _make_stage(db, t.id, "rnr", 1, category="invalid")
    valid_stage = _make_stage(db, t.id, "active", 2, category="valid", is_valid_lead_entry=True)
    guest = _make_guest(db, t.id)

    inquiry = get_or_create_from_call(db, t.id, guest.id, direction="inbound", answered=True)
    assert inquiry.stage_id == valid_stage.id
    assert inquiry.source == InquirySource.ORGANIC_CALL   # an inbound call with no ad behind it


def test_get_or_create_from_call_unanswered_routes_rnr(db):
    t = _make_tenant(db)
    _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    rnr_stage = _make_stage(db, t.id, "rnr", 1, category="invalid")
    _make_stage(db, t.id, "active", 2, category="valid", is_valid_lead_entry=True)
    guest = _make_guest(db, t.id)

    inquiry = get_or_create_from_call(db, t.id, guest.id, direction="inbound", answered=False)
    assert inquiry.stage_id == rnr_stage.id


def test_get_or_create_from_call_outbound_source(db):
    t = _make_tenant(db)
    _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    _make_stage(db, t.id, "active", 1, category="valid", is_valid_lead_entry=True)
    guest = _make_guest(db, t.id)

    inquiry = get_or_create_from_call(db, t.id, guest.id, direction="outbound", answered=True)
    assert inquiry.source == InquirySource.OUTBOUND_CALL


def test_get_or_create_from_call_dedupes_existing_open_inquiry(db):
    t = _make_tenant(db)
    _make_stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    rnr_stage = _make_stage(db, t.id, "rnr", 1, category="invalid")
    valid_stage = _make_stage(db, t.id, "active", 2, category="valid", is_valid_lead_entry=True)
    guest = _make_guest(db, t.id)

    first = get_or_create_from_call(db, t.id, guest.id, direction="inbound", answered=True)
    second = get_or_create_from_call(db, t.id, guest.id, direction="inbound", answered=False)
    assert first.id == second.id
    assert second.stage_id == valid_stage.id  # unchanged by the second (unanswered) call


def test_get_or_create_from_call_tenant_isolation(db):
    t1 = _make_tenant(db, "T1")
    t2 = _make_tenant(db, "T2")
    _make_stage(db, t2.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    t2_valid = _make_stage(db, t2.id, "active", 1, category="valid", is_valid_lead_entry=True)
    guest = _make_guest(db, t2.id)

    inquiry = get_or_create_from_call(db, t2.id, guest.id, direction="inbound", answered=True)
    assert inquiry.tenant_id == t2.id
    assert inquiry.stage_id == t2_valid.id
    assert db.query(Inquiry).filter_by(tenant_id=t1.id).count() == 0
