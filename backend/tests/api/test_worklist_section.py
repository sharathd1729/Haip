"""GET /worklist/section/{key} -- the "Load more" page request.

GET /worklist itself always caps each section at SECTION_LIMIT rows (it
builds all five sections in one call), so a widget past 50 real rows has
no way to see the rest without a dedicated per-section, offset-aware
fetch. Confirmed live on Ratha: "Shared their details" showed "Showing
first 50 of 113" with no way to reach the other 63.
"""
import uuid
from datetime import datetime, timezone

from tests.conftest import *  # noqa: F401,F403

from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.models.guest import Guest


def _conv(db, tenant_id, *, name="Guest"):
    g = Guest(tenant_id=tenant_id, name=name)
    db.add(g); db.flush()
    c = Conversation(tenant_id=tenant_id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c); db.commit()
    return g, c


def _msg(db, tenant_id, c, *, minutes_ago=5):
    m = Message(
        tenant_id=tenant_id, conversation_id=c.id, direction=MessageDirection.INBOUND,
        channel=ChannelType.WHATSAPP, body="hi", is_internal=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(m); db.commit()
    return m


class TestWorklistSectionEndpoint:
    def test_offset_returns_the_next_page(self, client, db, tenant_and_user):
        tenant = tenant_and_user["tenant"]
        tenant_id = tenant["id"] if isinstance(tenant, dict) else tenant.id
        for i in range(5):
            _, c = _conv(db, tenant_id, name=f"Guest{i}")
            _msg(db, tenant_id, c)
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

        first = client.get("/api/v1/worklist/section/new_dms", params={"hours": 0, "limit": 2, "offset": 0}, headers=headers)
        second = client.get("/api/v1/worklist/section/new_dms", params={"hours": 0, "limit": 2, "offset": 2}, headers=headers)

        assert first.status_code == 200 and second.status_code == 200
        first_ids = {r["conversation_id"] for r in first.json()["rows"]}
        second_ids = {r["conversation_id"] for r in second.json()["rows"]}
        assert len(first_ids) == 2
        assert len(second_ids) == 2
        assert first_ids.isdisjoint(second_ids)

    def test_unknown_section_404s(self, client, tenant_and_user):
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
        resp = client.get("/api/v1/worklist/section/not_a_real_section", headers=headers)
        assert resp.status_code == 404

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/worklist/section/new_dms")
        assert resp.status_code in (401, 403)

    def test_cross_tenant_isolation(self, client, db, tenant_and_user):
        """A section fetch must never surface another tenant's rows,
        offset page or not."""
        from app.models.tenant import Tenant
        other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(other); db.commit()
        _, c = _conv(db, other.id, name="OtherTenantGuest")
        _msg(db, other.id, c)

        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
        resp = client.get("/api/v1/worklist/section/new_dms", params={"hours": 0}, headers=headers)

        assert resp.status_code == 200
        names = {r["lead"]["name"] for r in resp.json()["rows"]}
        assert "OtherTenantGuest" not in names
