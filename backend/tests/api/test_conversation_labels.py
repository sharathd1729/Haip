"""Chat labels on conversations (migration 212): set with PATCH, filter the inbox with ?label=, list with counts."""
import uuid

import pytest

from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.tenant import Tenant


def _conv(db, tid, labels=None):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True,
                     labels=labels, last_message_at="2026-11-16T10:00:00+00:00")
    db.add(c)
    db.commit()
    return c


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def test_labels_are_cleaned_saved_and_filtered(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    c1, c2 = _conv(db, tid), _conv(db, tid, labels=["VIP guest"])
    res = client.patch(f"/api/v1/conversations/{c1.id}", json={"labels": ["  VIP ", "Wedding", "vip"]}, headers=_h(tenant_and_user))
    assert res.status_code == 200 and res.json()["labels"] == ["VIP", "Wedding"]
    ids = [c["id"] for c in client.get("/api/v1/conversations", params={"label": "VIP"}, headers=_h(tenant_and_user)).json()]
    assert ids == [c1.id]                                     # "VIP guest" is a different label
    got = client.get("/api/v1/conversations/labels", headers=_h(tenant_and_user)).json()
    assert {"label": "VIP", "count": 1} in got and {"label": "VIP guest", "count": 1} in got


@pytest.mark.parametrize("bad", [["x" * 25], ['quote"s'], [f"L{i}" for i in range(11)], "VIP"])
def test_bad_labels_are_refused(client, db, tenant_and_user, bad):
    c = _conv(db, tenant_and_user["tenant"].id)
    assert client.patch(f"/api/v1/conversations/{c.id}", json={"labels": bad}, headers=_h(tenant_and_user)).status_code == 422


def test_labels_stay_in_the_workspace(client, db, tenant_and_user):
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = _conv(db, other.id, labels=["Secret"])
    assert client.get("/api/v1/conversations/labels", headers=_h(tenant_and_user)).json() == []
    assert client.get("/api/v1/conversations", params={"label": "Secret"}, headers=_h(tenant_and_user)).json() == []
    assert client.patch(f"/api/v1/conversations/{theirs.id}", json={"labels": ["Mine"]}, headers=_h(tenant_and_user)).status_code == 404


def test_the_conversation_detail_carries_its_labels(client, db, tenant_and_user):
    c = _conv(db, tenant_and_user["tenant"].id, labels=["Wedding"])
    res = client.get(f"/api/v1/conversations/{c.id}", headers=_h(tenant_and_user))
    assert res.status_code == 200 and res.json()["labels"] == ["Wedding"]
