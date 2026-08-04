"""Tests for HAIP Inbox prototype-wiring plan, ticket 4: route/quote
share-card -- calculator_service.build_route_quote() and the channel-aware,
route-aware _action_send_quote dispatch action."""
import uuid
from decimal import Decimal
from unittest.mock import patch

from app.models.conversation import Conversation, ChannelType
from app.models.guest import Guest
from app.models.property import Property
from app.services.calculator_service import calculator_service


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _make_caravan(db, tenant_id, routes=None, price_per_km=Decimal("50")):
    prop = Property(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="Ratha Caravan #1",
        slug=f"caravan-{uuid.uuid4().hex[:6]}", type="caravan", price_per_km=price_per_km,
        routes=routes or [{"from": "Goa", "to": "Coorg", "km": 420}],
    )
    db.add(prop); db.commit()
    return prop


class TestBuildRouteQuote:
    def test_happy_path(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        prop = _make_caravan(db, tenant_id)

        quote = calculator_service.build_route_quote(
            db, tenant_id=tenant_id, property_id=prop.id, from_city="Goa", to_city="Coorg",
        )
        assert quote is not None
        assert quote["km"] == 420
        assert quote["subtotal"] == Decimal("21000")  # 420 * 50
        assert quote["gst"] == Decimal("2520")         # 12%
        assert quote["total"] == Decimal("23520")

    def test_case_insensitive_and_whitespace_tolerant_city_match(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        prop = _make_caravan(db, tenant_id)
        quote = calculator_service.build_route_quote(
            db, tenant_id=tenant_id, property_id=prop.id, from_city="  goa ", to_city="COORG",
        )
        assert quote is not None
        assert quote["km"] == 420

    def test_no_matching_route_returns_none(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        prop = _make_caravan(db, tenant_id)
        quote = calculator_service.build_route_quote(
            db, tenant_id=tenant_id, property_id=prop.id, from_city="Mumbai", to_city="Pune",
        )
        assert quote is None

    def test_non_caravan_property_returns_none(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        prop = Property(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="Villa", slug=f"villa-{uuid.uuid4().hex[:6]}",
            type="villa",
        )
        db.add(prop); db.commit()
        quote = calculator_service.build_route_quote(
            db, tenant_id=tenant_id, property_id=prop.id, from_city="Goa", to_city="Coorg",
        )
        assert quote is None

    def test_no_price_per_km_returns_none(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        prop = _make_caravan(db, tenant_id, price_per_km=None)
        quote = calculator_service.build_route_quote(
            db, tenant_id=tenant_id, property_id=prop.id, from_city="Goa", to_city="Coorg",
        )
        assert quote is None


class TestSendQuoteActionRouteAndChannel:
    @patch("app.workers.tasks.send_instagram_dm.send_instagram_dm.delay")
    def test_route_quote_sent_on_instagram_conversation(self, mock_ig_delay, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        prop = _make_caravan(db, tenant_id)
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="IG Guest", phone="+919999099999")
        db.add(guest); db.flush()
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.INSTAGRAM, is_open=True)
        db.add(conv); db.commit()

        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "send_quote",
                "entity_refs": {"guest_id": guest.id, "property_id": prop.id},
                "action_config": {"property_id": prop.id, "from_city": "Goa", "to_city": "Coorg"},
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200, resp.text
        assert "instagram" in resp.json()["detail"]
        mock_ig_delay.assert_called_once()

    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_per_night_quote_still_works_on_whatsapp(self, mock_wa_delay, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        prop = Property(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="Villa", slug=f"villa-{uuid.uuid4().hex[:6]}",
            type="villa",
        )
        db.add(prop); db.commit()
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="WA Guest", phone="+919999088888")
        db.add(guest); db.flush()
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(conv); db.commit()

        fake_quote = type("Q", (), {"subtotal": Decimal("1000"), "gst": Decimal("120"), "total": Decimal("1120"), "advance_amount": Decimal("336")})()
        with patch("app.services.calculator_service.calculator_service.build_quote", return_value=fake_quote):
            resp = client.post(
                "/api/v1/automations/actions/execute",
                json={
                    "action_type": "send_quote",
                    "entity_refs": {"guest_id": guest.id, "property_id": prop.id},
                    "action_config": {"property_id": prop.id, "checkin": "2026-12-10", "checkout": "2026-12-12"},
                },
                headers=_auth_headers(tenant_and_user),
            )
        assert resp.status_code == 200, resp.text
        assert "whatsapp" in resp.json()["detail"]
        mock_wa_delay.assert_called_once()

    def test_route_quote_missing_route_is_skipped(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        prop = _make_caravan(db, tenant_id)
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone="+919999077777")
        db.add(guest); db.commit()

        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "send_quote",
                "entity_refs": {"guest_id": guest.id, "property_id": prop.id},
                "action_config": {"property_id": prop.id, "from_city": "Mumbai", "to_city": "Pune"},
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200
        assert "no route quote available" in resp.json()["detail"]
