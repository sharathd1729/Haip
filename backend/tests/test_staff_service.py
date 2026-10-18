"""Staff profiles: number lookup used on every inbound message, and the personal WhatsApp bridge never turning staff into leads."""
import uuid

import pytest
from fastapi import HTTPException

from app.models.conversation import Conversation
from app.models.guest import Guest
from app.schemas.ops import DutyAssignment, StaffCreate, StaffUpdate
from app.services import staff_service
from app.services import whatsapp_personal_service as wps
from tests.ops_helpers import staff, tenant
from tests.services.test_whatsapp_personal_service import _make_agent, _make_session


def test_find_active_staff_by_phone_matches_whatsapp_style_numbers(db):
    t = tenant(db)
    s = staff(db, t.id, "Ravi", "maintenance")
    assert staff_service.find_active_staff_by_phone(db, t.id, s.phone_e164).id == s.id
    assert staff_service.find_active_staff_by_phone(db, t.id, s.phone_e164.lstrip("+")).id == s.id
    s.active = False
    db.commit()
    assert staff_service.find_active_staff_by_phone(db, t.id, s.phone_e164) is None


def test_find_active_staff_by_phone_is_tenant_isolated(db):
    t1, t2 = tenant(db), tenant(db)
    s = staff(db, t2.id, "Theirs", "maintenance")
    assert staff_service.find_active_staff_by_phone(db, t1.id, s.phone_e164) is None


def test_create_and_update_staff(db):
    t = tenant(db)
    created = staff_service.create_staff(db, t.id, StaffCreate(
        name=" Ravi ", phone="098450 12345", whatsapp_opt_in=True,
        duties=[DutyAssignment(duty="maintenance"), DutyAssignment(duty="maintenance")]))
    assert created.name == "Ravi" and created.phone_e164 == "+919845012345" and created.whatsapp_opt_in_at
    assert len(staff_service.duties_of(db, t.id, [created.id])[created.id]) == 1          # duplicates collapse
    updated = staff_service.update_staff(db, t.id, created.id, StaffUpdate(whatsapp_opt_in=False, duties=[]))
    assert updated.whatsapp_opt_in_at is None and staff_service.duties_of(db, t.id, [created.id])[created.id] == []
    with pytest.raises(HTTPException) as exc:
        staff_service.create_staff(db, t.id, StaffCreate(name="Dup", phone="+919845012345"))
    assert exc.value.status_code == 409


def test_staff_chat_on_personal_bridge_is_mirrored_but_never_a_lead(db):
    t = tenant(db)
    agent = _make_agent(db, t.id)
    session = _make_session(db, t.id, agent.id)
    s = staff(db, t.id, "Driver", "driver")
    m = wps.ingest_chat_message(db, session, bridge_message_id=f"m-{uuid.uuid4().hex[:8]}", from_phone=s.phone_e164,
                                from_name="Driver", body="Reached Coorg", chat_jid=f"{s.phone_e164.lstrip('+')}@s.whatsapp.net")
    conv = db.query(Conversation).filter_by(id=m.conversation_id).one()
    assert conv.inquiry_id is None
    assert db.query(Guest).filter_by(id=conv.guest_id).one().lead_identified_at is None
