"""The MCP list_bookings tool calls the bookings endpoint as a plain function. A filter added to that
endpoint but not passed by the tool arrives as a truthy Query(...) placeholder and breaks every call
(this happened when property_id and payment_status were added). Keep the tool and the endpoint in step."""
import inspect
import uuid
from datetime import date, timedelta

from app.api.v1.endpoints import bookings as bookings_ep
from app.mcp import tools as mcp_tools
from app.models.base import gen_uuid
from app.models.guest import Guest
from app.models.property import Property, Stay


def _seed(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = Property(id=gen_uuid(), tenant_id=tid, name="Caravan 1", slug=f"c-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    guest = Guest(id=gen_uuid(), tenant_id=tid, name="Asha", phone="+919876543210")
    db.add_all([prop, guest])
    db.flush()
    db.add(Stay(id=gen_uuid(), tenant_id=tid, guest_id=guest.id, property_id=prop.id, check_in=date.today() + timedelta(days=3),
                check_out=date.today() + timedelta(days=4), status="confirmed", total_amount=25000, channel_source="direct"))
    db.commit()
    return prop


def test_list_bookings_tool_works_with_no_arguments_and_with_new_filters(db, tenant_and_user):
    prop = _seed(db, tenant_and_user)
    user, tid = tenant_and_user["user"], tenant_and_user["tenant"].id

    out = mcp_tools._list_bookings(db, user, tid, {})
    assert out["meta"]["total"] == 1 and out["data"][0]["total"] == 25000

    assert mcp_tools._list_bookings(db, user, tid, {"property_id": prop.id})["meta"]["total"] == 1
    assert mcp_tools._list_bookings(db, user, tid, {"property_id": "nope"})["meta"]["total"] == 0
    assert mcp_tools._list_bookings(db, user, tid, {"payment_status": "unpaid"})["meta"]["total"] == 1
    assert mcp_tools._list_bookings(db, user, tid, {"payment_status": "paid"})["meta"]["total"] == 0


def test_tool_passes_every_parameter_the_endpoint_has():
    """Fails the moment someone adds a parameter to the endpoint and forgets the tool."""
    endpoint_params = set(inspect.signature(bookings_ep.list_bookings).parameters) - {"current_user", "db"}
    source = inspect.getsource(mcp_tools._list_bookings)
    missing = [p for p in endpoint_params if f"{p}=" not in source]
    assert not missing, f"MCP list_bookings does not pass: {missing}"
