"""The Inbox's read-only flag: `can_send` on GET /conversations and GET /conversations/{id} is false where HAIP cannot reply
(personal WhatsApp mirror, Meta lead form), so the screen shows "Read only: HAIP can't reply here" and no draft box."""

import uuid

import pytest

from app.core.security import create_access_token
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest

pytestmark = pytest.mark.usefixtures("capabilities_seeded")


def _conv(db, tid, channel, source=None):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=channel, is_open=True, source=source)
    db.add(c)
    db.commit()
    return c


def _h(tenant_and_user):
    u, t = tenant_and_user["user"], tenant_and_user["tenant"]
    return {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'tenant_id': t.id, 'role': u.role.value})}"}


def test_read_only_threads_say_so_in_the_list_and_the_detail(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    official = _conv(db, tid, ChannelType.WHATSAPP)
    bridge = _conv(db, tid, ChannelType.WHATSAPP, "personal_bridge")
    form = _conv(db, tid, ChannelType.FACEBOOK, "lead_form")
    h = _h(tenant_and_user)
    for conv, expected in ((official, True), (bridge, False), (form, False)):
        res = client.get(f"/api/v1/conversations/{conv.id}", headers=h)
        assert res.status_code == 200, res.text
        assert res.json()["can_send"] is expected
    res = client.get("/api/v1/conversations", params={"filter": "all", "limit": 50}, headers=h)
    assert res.status_code == 200, res.text
    listed = {c["id"]: c["can_send"] for c in res.json()}
    assert listed.get(official.id) is True
    assert all(listed[c.id] is False for c in (bridge, form) if c.id in listed)
