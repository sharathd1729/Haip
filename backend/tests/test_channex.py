"""Channel manager via Channex (adapters/pms/channex.py, services/channex_service.py, endpoints/channex.py, migration 205).
Nothing here talks to Channex: the adapter runs on httpx.MockTransport, the service on a fake client."""
import json
import uuid
from datetime import date
from unittest.mock import patch

import httpx
import pytest

from app.adapters.pms.channex import ChannexClient, ChannexError
from app.models.channex import ChannexBookingLink, ChannexMapping
from app.models.property import BlockedDate, Property, RatePlan, SeasonalRate, Stay
from app.models.task import Task
from app.models.tenant import Tenant
from app.services import channex_service as svc

D0 = date(2026, 12, 1)


# ─── Adapter ─────────────────────────────────────────────────────────────────


def test_adapter_sends_the_key_batches_values_and_collects_warnings():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.headers.get("user-api-key"), json.loads(req.content or b"{}")))
        return httpx.Response(200, json={"meta": {"warnings": [{"x": 1}]}})

    c = ChannexClient("key-123", transport=httpx.MockTransport(handler))
    warnings = c.push_availability([{"availability": 1}] * 600)
    assert [s[1] for s in seen] == ["/api/v1/availability"] * 2 and seen[0][2] == "key-123"
    assert len(seen[0][3]["values"]) == 500 and len(warnings) == 2
    assert c.push_restrictions([]) == [] and len(seen) == 2


def test_adapter_refuses_other_hosts_and_names_auth_failures():
    with pytest.raises(ChannexError):
        ChannexClient("k", "https://evil.example.com/api/v1")
    with pytest.raises(ChannexError):
        ChannexClient("k", "http://staging.channex.io/api/v1")
    c = ChannexClient("k", transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(ChannexError) as exc:
        c.booking_feed()
    assert exc.value.status == 401


# ─── Availability and rates ──────────────────────────────────────────────────


def _world(db, name="Villa A", package=False):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"cx-{uuid.uuid4().hex[:6]}", plan="scale")
    db.add(t)
    db.flush()
    p = Property(id=str(uuid.uuid4()), tenant_id=t.id, name=name, slug=f"p-{uuid.uuid4().hex[:6]}",
                 type="caravan" if package else "villa", is_active=True)
    db.add(p)
    db.flush()
    m = ChannexMapping(tenant_id=t.id, property_id=p.id, channex_property_id="cxp", channex_room_type_id=f"rt-{p.id[:6]}",
                       channex_rate_plan_id="rp1", push_rates=True)
    db.add(m)
    db.commit()
    return t, p, m


def _guest(db, tid):
    from app.models.guest import Guest

    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone="+919800000051")
    db.add(g)
    db.flush()
    return g


def test_availability_is_zero_on_booked_and_blocked_nights_as_ranges(db):
    t, p, m = _world(db)
    g = _guest(db, t.id)
    db.add(Stay(tenant_id=t.id, guest_id=g.id, property_id=p.id, check_in=date(2026, 12, 3), check_out=date(2026, 12, 5),
                status="confirmed"))
    db.add(Stay(tenant_id=t.id, guest_id=g.id, property_id=p.id, check_in=date(2026, 12, 7), check_out=date(2026, 12, 8),
                status="cancelled"))
    db.add(BlockedDate(tenant_id=t.id, property_id=p.id, blocked_from="2026-12-09", blocked_to="2026-12-10", reason="paint"))
    db.commit()
    vals = svc.availability_values(db, t.id, m, D0, 10)
    assert [(v["date_from"], v["date_to"], v["availability"]) for v in vals] == [
        ("2026-12-01", "2026-12-02", 1), ("2026-12-03", "2026-12-04", 0), ("2026-12-05", "2026-12-08", 1),
        ("2026-12-09", "2026-12-09", 0), ("2026-12-10", "2026-12-10", 1)]
    assert all(v["room_type_id"] == m.channex_room_type_id for v in vals)


def test_rates_follow_the_calendar_and_only_when_switched_on(db):
    t, p, m = _world(db)
    db.add(RatePlan(tenant_id=t.id, property_id=p.id, name="Base", base_price_per_night=10000, is_active=True))
    db.add(SeasonalRate(tenant_id=t.id, property_id=p.id, name="Xmas", date_from="2026-12-24", date_to="2026-12-26",
                        price_per_night=18000, priority=10, is_active=True))
    db.commit()
    vals = svc.rate_values(db, t.id, m, date(2026, 12, 23), 5)
    assert [(v["date_from"], v["date_to"], v["rate"]) for v in vals] == [
        ("2026-12-23", "2026-12-23", "10000.00"), ("2026-12-24", "2026-12-26", "18000.00"), ("2026-12-27", "2026-12-27", "10000.00")]
    m.push_rates = False
    assert svc.rate_values(db, t.id, m, D0, 5) == []


def test_package_priced_units_never_send_a_rate(db):
    t, p, m = _world(db, package=True)
    db.add(RatePlan(tenant_id=t.id, property_id=p.id, name="Base", base_price_per_night=9000, is_active=True))
    db.commit()
    with patch("app.services.price_policy.package_priced", return_value=True):
        assert svc.rate_values(db, t.id, m, D0, 5) == []


# ─── Bookings ────────────────────────────────────────────────────────────────


class _Fake:
    def __init__(self, revs):
        self.revs, self.acked, self.avail, self.restr = list(revs), [], [], []

    def booking_feed(self):
        return list(self.revs)

    def ack(self, rid):
        self.acked.append(rid)

    def push_availability(self, values):
        self.avail += values
        return []

    def push_restrictions(self, values):
        self.restr += values
        return []

    def close(self):
        pass


def _rev(m, rid, status="new", ci="2026-12-10", co="2026-12-12", booking="b1", room_type=None):
    return {"id": rid, "booking_id": booking, "status": status, "ota_name": "Booking.com", "ota_reservation_code": "998877",
            "amount": "24000.00", "customer": {"name": "Asha", "surname": "Rao", "phone": "+919811112222"},
            "rooms": [{"room_type_id": room_type or m.channex_room_type_id, "checkin_date": ci, "checkout_date": co,
                       "occupancy": {"adults": 2, "children": 1}}]}


def _stay(db, tid):
    link = db.query(ChannexBookingLink).filter_by(tenant_id=tid, channex_booking_id="b1").one()
    return db.get(Stay, link.stay_id), link


def test_a_new_ota_booking_becomes_a_haip_booking_once_then_changes_then_cancels(db):
    t, p, m = _world(db)
    fake = _Fake([_rev(m, "r1")])
    assert svc.pull_tenant(db, t.id, client=fake) == {"created": 1}
    stay, link = _stay(db, t.id)
    assert (stay.property_id, stay.check_in, stay.check_out, stay.channel_source) == (p.id, date(2026, 12, 10), date(2026, 12, 12), "channex")
    assert (stay.adults, stay.children, float(stay.total_amount)) == (2, 1, 24000.0) and link.ota_name == "Booking.com"
    assert fake.acked == ["r1"] and any(v["availability"] == 0 for v in fake.avail)   # pushed back so other channels see it
    assert svc.pull_tenant(db, t.id, client=_Fake([_rev(m, "r1")])) == {"unchanged": 1}          # re-delivered: no-op
    svc.pull_tenant(db, t.id, client=_Fake([_rev(m, "r2", status="modified", ci="2026-12-11", co="2026-12-14")]))
    db.expire_all()
    stay, _ = _stay(db, t.id)
    assert (stay.check_in, stay.check_out) == (date(2026, 12, 11), date(2026, 12, 14))
    svc.pull_tenant(db, t.id, client=_Fake([_rev(m, "r3", status="cancelled")]))
    db.expire_all()
    assert _stay(db, t.id)[0].status == "cancelled"
    assert db.query(Stay).filter_by(tenant_id=t.id).count() == 1


def test_overbooking_is_stored_and_flagged_and_unmapped_rooms_wait(db):
    t, p, m = _world(db)
    g = _guest(db, t.id)
    db.add(Stay(tenant_id=t.id, guest_id=g.id, property_id=p.id, check_in=date(2026, 12, 10), check_out=date(2026, 12, 11),
                status="confirmed"))
    db.commit()
    fake = _Fake([_rev(m, "r1"), _rev(m, "r9", booking="b9", room_type="unknown-room")])
    assert svc.pull_tenant(db, t.id, client=fake) == {"created": 1, "unmapped": 1}
    titles = [x.title for x in db.query(Task).filter_by(tenant_id=t.id)]
    assert any(x.startswith("Overbooking") for x in titles) and any(x.startswith("Map Booking.com room type") for x in titles)
    assert fake.acked == ["r1"]                                           # the unmapped one stays in Channex's feed


def test_another_workspaces_mapping_is_never_used(db):
    t, p, m = _world(db)
    other, _p2, m2 = _world(db, name="Other villa")
    assert svc.pull_tenant(db, t.id, client=_Fake([_rev(m2, "rx")])) == {"unmapped": 1}
    assert db.query(Stay).filter_by(tenant_id=t.id).count() == 0 and db.query(Stay).filter_by(tenant_id=other.id).count() == 0


# ─── Endpoints ───────────────────────────────────────────────────────────────


def _auth(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _entitle(db, tid):
    from app.core import cache
    from app.models.module import Module, WorkspaceModule

    mod = db.query(Module).filter_by(code="channel_manager").first()
    if mod is None:
        mod = Module(id=str(uuid.uuid4()), code="channel_manager", name="Channel manager")
        db.add(mod)
        db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=tid, module_id=mod.id, enabled=True))
    db.commit()
    cache.ctx_bust(tid)


def test_connect_map_and_status(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    h = _auth(tenant_and_user)
    assert client.get("/api/v1/channex/status", headers=h).status_code == 403          # module off
    _entitle(db, tid)
    p = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Villa A", slug=f"p-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(p)
    db.commit()
    with patch("app.adapters.pms.channex.ChannexClient.properties", side_effect=ChannexError("Channex refused the API key", 401)):
        assert client.post("/api/v1/channex/connect", json={"api_key": "bad-key-123"}, headers=h).status_code == 422
    with patch("app.adapters.pms.channex.ChannexClient.properties", return_value=[{"id": "cxp"}]):
        r = client.post("/api/v1/channex/connect", json={"api_key": "good-key-123"}, headers=h)
    assert r.status_code == 200 and r.json()["channex_properties"] == 1
    body = {"mappings": [{"property_id": p.id, "channex_property_id": "cxp", "channex_room_type_id": "rt1"}]}
    assert client.put("/api/v1/channex/mappings", json=body, headers=h).status_code == 200
    foreign = {"mappings": [{"property_id": str(uuid.uuid4()), "channex_property_id": "cxp", "channex_room_type_id": "rt2"}]}
    assert client.put("/api/v1/channex/mappings", json=foreign, headers=h).status_code == 404
    st = client.get("/api/v1/channex/status", headers=h).json()
    assert st["connected"] is True and st["units"][0]["mapped"] is True and st["units"][0]["channex_room_type_id"] == "rt1"
    assert "good-key-123" not in json.dumps(st)
    with patch("app.workers.tasks.channex_sync.sync_tenant.delay") as q:
        assert client.post("/api/v1/channex/sync", headers=h).status_code == 202 and q.call_count == 1
