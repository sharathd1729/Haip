"""MCP list tools return a slim row by default and the old payload with fields="full".

list_leads returned 112k characters for 50 rows (list_calls 50k), so AI readers were cut off.
Totals and pagination must survive the slimming.
"""
import json
import uuid
from datetime import date, timedelta

from app.mcp import tools as mcp_tools
from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.property import Property, Stay


def _seed(db, tid):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Asha Rao", phone="+919876543210")
    prop = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:6]}",
                    type="caravan", is_active=True)
    db.add_all([guest, prop])
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, property_id=prop.id, status="confirmed",
                check_in=date.today() + timedelta(days=3), check_out=date.today() + timedelta(days=5),
                total_amount=25000))
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
                direction=CallDirection.INBOUND, from_number="+919876543210", to_number="+912271264296",
                guest_id=guest.id, duration_seconds=42, ai_summary="long summary " * 50,
                started_at="2026-11-02T04:53:20+00:00"))
    db.add(Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, inquiry_id=inq.id,
                        channel=ChannelType.WHATSAPP, is_open=True))
    db.commit()


def _size(obj) -> int:
    return len(json.dumps(obj, default=str))


def test_slim_by_default_full_on_request(db, tenant_and_user):
    user, tid = tenant_and_user["user"], tenant_and_user["tenant"].id
    _seed(db, tid)

    cases = (
        (mcp_tools._list_leads, "leads", ("total", "page", "page_size", "stages"), mcp_tools._SLIM_LEAD),
        (mcp_tools._list_calls, "items", ("total", "page", "limit"), mcp_tools._SLIM_CALL),
        (mcp_tools._list_bookings, "data", ("meta",), mcp_tools._SLIM_BOOKING + ("property_name", "guest_name")),
    )
    for handler, rows_key, totals, allowed in cases:
        slim = handler(db, user, tid, {})
        full = handler(db, user, tid, {"fields": "full"})
        assert len(slim[rows_key]) == len(full[rows_key]) == 1, handler.__name__
        assert set(slim[rows_key][0]) <= set(allowed), handler.__name__
        assert all(slim[k] == full[k] for k in totals), handler.__name__
        assert _size(slim) < _size(full), handler.__name__

    booking = mcp_tools._list_bookings(db, user, tid, {})["data"][0]
    assert booking["property_name"] == "Ratha 1" and booking["guest_name"] == "Asha Rao"
    assert "phone" not in json.dumps(booking, default=str)
    assert "ai_summary" not in mcp_tools._list_calls(db, user, tid, {})["items"][0]

    convs = mcp_tools._list_recent_conversations(db, user, tid, {})
    assert convs and set(convs[0]) <= set(mcp_tools._SLIM_CONVERSATION)
    assert "last_message" not in convs[0]
    assert "last_message" in mcp_tools._list_recent_conversations(db, user, tid, {"fields": "full"})[0]


def test_every_list_tool_advertises_the_fields_option():
    by_name = {t["name"]: t for t in mcp_tools.TOOLS}
    for name in ("list_leads", "list_calls", "list_recent_conversations", "list_bookings"):
        assert by_name[name]["inputSchema"]["properties"]["fields"]["enum"] == ["slim", "full"]
