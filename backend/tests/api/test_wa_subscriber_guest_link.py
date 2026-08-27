"""
WhatsApp module bug-fix pass — subscriber/Guest linking + opt-in trigger.

Real bug: WASubscriber (the campaign/VIP-tag audience list) was matched to
Guest purely by exact phone-string equality, with zero normalization on the
subscriber side -- Guest.phone is always E.164 (normalize_phone), but a
subscriber typed as "+91 98765 43210" (the old placeholder's own format)
never matched a guest stored as "+919876543210". Migration 091 adds a real
guest_id link, resolved here at write time using the same normalize_phone()
Guest already uses.

Also covers: "opt_in" is a real Flow Builder trigger with no fire point
anywhere in the codebase until now -- the opt-in endpoint fires it once a
subscriber resolves to a guest, and skips (does not crash) otherwise.
"""
import uuid
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403

from app.models.guest import Guest
from app.api.v1.endpoints.messaging import WASubscriber


def _make_guest(db, tenant_id, phone="+919876543210"):
    from app.services.guest_service import normalize_phone
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Priya", phone=normalize_phone(phone))
    db.add(g)
    db.commit()
    return g.id


class TestSubscriberPhoneNormalization:
    def test_non_e164_input_is_normalized_on_write(self, client, db, tenant_and_user):
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
        resp = client.post(
            "/api/v1/messaging/subscribers",
            json={"phone": "+91 98765 43210", "name": "Priya", "opted_in": True},
            headers=headers,
        )
        assert resp.status_code == 201
        assert resp.json()["phone"] == "+919876543210"

    def test_upsert_matches_an_existing_subscriber_regardless_of_original_formatting(self, client, db, tenant_and_user):
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
        client.post("/api/v1/messaging/subscribers", json={"phone": "+919876543210", "name": "First"}, headers=headers)
        resp = client.post("/api/v1/messaging/subscribers", json={"phone": "+91 98765 43210", "name": "Second"}, headers=headers)

        assert resp.status_code == 201
        tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
        rows = db.query(WASubscriber).filter_by(tenant_id=tenant_id, phone="+919876543210").all()
        assert len(rows) == 1, "same number in a different format must upsert the same row, not create a duplicate"
        assert rows[0].name == "Second"


class TestSubscriberGuestLink:
    def test_upsert_resolves_guest_id_when_a_matching_guest_exists(self, client, db, tenant_and_user):
        tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
        guest_id = _make_guest(db, tenant_id, phone="+919876543210")
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

        resp = client.post("/api/v1/messaging/subscribers", json={"phone": "+91 98765 43210", "name": "Priya"}, headers=headers)

        assert resp.status_code == 201
        assert resp.json()["guest_id"] == guest_id

    def test_upsert_leaves_guest_id_null_with_no_matching_guest(self, client, db, tenant_and_user):
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
        resp = client.post("/api/v1/messaging/subscribers", json={"phone": "+919999999999", "name": "No Guest"}, headers=headers)

        assert resp.status_code == 201
        assert resp.json()["guest_id"] is None


class TestOptInFiresFlowTrigger:
    def test_opt_in_fires_trigger_when_subscriber_has_a_guest(self, client, db, tenant_and_user):
        tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
        guest_id = _make_guest(db, tenant_id)
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
        sub_id = client.post(
            "/api/v1/messaging/subscribers", json={"phone": "+919876543210", "opted_in": False}, headers=headers,
        ).json()["id"]

        with patch("app.workers.tasks.automation_engine.fire_trigger.delay") as mock_fire:
            resp = client.patch(f"/api/v1/messaging/subscribers/{sub_id}/opt-in", headers=headers)

        assert resp.status_code == 200
        mock_fire.assert_called_once()
        kwargs = mock_fire.call_args.kwargs
        assert kwargs["event"] == "opt_in"
        assert kwargs["context"]["guest_id"] == guest_id

    def test_opt_in_skips_firing_without_a_matching_guest(self, client, db, tenant_and_user):
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
        sub_id = client.post(
            "/api/v1/messaging/subscribers", json={"phone": "+911111111111", "opted_in": False}, headers=headers,
        ).json()["id"]

        with patch("app.workers.tasks.automation_engine.fire_trigger.delay") as mock_fire:
            resp = client.patch(f"/api/v1/messaging/subscribers/{sub_id}/opt-in", headers=headers)

        assert resp.status_code == 200
        mock_fire.assert_not_called()
