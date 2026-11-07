"""conversations.ai_mode holds a per-thread override only ("off") -- never a copy of the workspace setting (7 Nov 2026).

Live: 1,141 Ratha threads read 'shadow' while the real mode came from the workspace setting (ai_mode_service). Writers now
leave the column NULL unless a real "off" is set, the backfill clears old copies without touching "off", and the Inbox list
reports the resolved mode.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import ai_mode_service


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _other_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t.id


def _conv(db, tid, ai_mode=None, channel=ChannelType.WHATSAPP):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone=f"+9197{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=channel, is_open=True, ai_mode=ai_mode,
                     last_message_at=datetime.now(timezone.utc).isoformat())
    db.add(c)
    db.flush()
    return c


def test_new_conversation_stores_no_mode(db, tenant_and_user):
    c = _conv(db, _tid(tenant_and_user))
    db.refresh(c)
    assert c.ai_mode is None


def test_whatsapp_webhook_does_not_copy_the_workspace_mode(db, tenant_and_user):
    from app.workers.tasks.whatsapp import _handle_inbound_message
    tid = _tid(tenant_and_user)
    db.query(Tenant).filter_by(id=tid).update({"wa_ai_mode_default": "autonomous"})
    db.commit()
    tenant = db.query(Tenant).filter_by(id=tid).one()
    phone = f"9198{uuid.uuid4().int % 10**8:08d}"
    with patch("app.workers.tasks.concierge_draft.concierge_draft.apply_async"):
        _handle_inbound_message(db, tenant, {"id": f"wamid.{uuid.uuid4().hex}", "from": phone, "type": "text",
                                             "text": {"body": "Hi, is the caravan free?"}}, contacts=[])
    db.commit()
    conv = db.query(Conversation).filter_by(tenant_id=tid, channel=ChannelType.WHATSAPP).one()
    assert conv.ai_mode is None
    assert ai_mode_service.resolve_mode(tenant, conv) == "autonomous"
    # The workspace switch now reaches the thread with no copy to go stale.
    tenant.wa_ai_mode_default = "shadow"
    assert ai_mode_service.resolve_mode(tenant, conv) == "shadow"


def test_off_is_kept_and_wins(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = db.query(Tenant).filter_by(id=tid).one()
    tenant.wa_ai_mode_default = "autonomous"
    c = _conv(db, tid, ai_mode="off")
    db.refresh(c)
    assert c.ai_mode == "off" and ai_mode_service.resolve_mode(tenant, c) == "off"


def test_backfill_clears_copies_leaves_off_and_other_tenants(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    other = _other_tenant(db)
    rows = {v: _conv(db, tid, ai_mode=v) for v in ("shadow", "autonomous", "off", "OFF", "")}
    empty = _conv(db, tid, ai_mode=None)
    foreign = _conv(db, other, ai_mode="shadow")
    db.commit()

    dry = ai_mode_service.clear_derived_modes(db, tid, apply=False)
    assert dry == {"shadow": 1, "autonomous": 1, "": 1}
    db.expire_all()
    assert rows["shadow"].ai_mode == "shadow"  # dry run wrote nothing

    done = ai_mode_service.clear_derived_modes(db, tid, apply=True)
    db.commit()
    db.expire_all()
    assert done == dry
    assert rows["shadow"].ai_mode is None and rows["autonomous"].ai_mode is None and rows[""].ai_mode is None
    assert rows["off"].ai_mode == "off" and rows["OFF"].ai_mode == "OFF" and empty.ai_mode is None
    assert foreign.ai_mode == "shadow"  # another workspace is untouched
    assert ai_mode_service.clear_derived_modes(db, tid, apply=True) == {}  # idempotent


def test_inbox_list_reports_the_resolved_mode(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    db.query(Tenant).filter_by(id=tid).update({"ig_ai_mode_default": "autonomous"})
    stale = _conv(db, tid, ai_mode="shadow", channel=ChannelType.INSTAGRAM)  # pre-fix copy: must not be reported
    muted = _conv(db, tid, ai_mode="off", channel=ChannelType.INSTAGRAM)
    plain = _conv(db, tid, channel=ChannelType.INSTAGRAM)
    foreign = _conv(db, _other_tenant(db), ai_mode="off", channel=ChannelType.INSTAGRAM)
    db.commit()

    res = client.get("/api/v1/conversations", headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})
    assert res.status_code == 200
    by_id = {c["id"]: c for c in res.json()}
    assert by_id[stale.id]["ai_mode"] == "autonomous"
    assert by_id[plain.id]["ai_mode"] == "autonomous"
    assert by_id[muted.id]["ai_mode"] == "off" and by_id[muted.id]["ai_enabled"] is False
    assert foreign.id not in by_id
