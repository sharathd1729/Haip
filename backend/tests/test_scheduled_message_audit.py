"""The read-only audit that must be run before any scheduled-send task is enabled (scripts/audit_scheduled_messages.py).

Legacy rows: `Message.scheduled_for` was stored for a long time and never sent. These tests pin that every such row is classified,
that only recently-due, unflagged rows could be picked up by a first sweep, that old rows are `stale` (never to be sent
automatically), and that the audit changes nothing and prints no message content.
"""
import importlib.util
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState
from app.models.consent import Consent
from app.models.guest import Guest
from app.models.tenant import Tenant

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "audit_scheduled_messages.py"
spec = importlib.util.spec_from_file_location("audit_scheduled_messages", SCRIPT)
audit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_mod)

NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)


def _iso(delta: timedelta, z=True) -> str:
    dt = (NOW + delta)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if z else dt.replace(tzinfo=None).isoformat()


@pytest.fixture()
def world(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth", timezone="Asia/Kolkata")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Asha", phone="+919800000042")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c)
    db.commit()
    return t, g, c


def _msg(db, t, c, scheduled, body="See you soon", **kw):
    m = Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction="outbound", channel="whatsapp",
                body=body, scheduled_for=scheduled, **kw)
    db.add(m)
    db.commit()
    return m.id


def test_every_legacy_row_is_classified_and_only_recent_clean_rows_could_go_out(db, world):
    t, g, c = world
    future = _msg(db, t, c, _iso(timedelta(hours=3)), body="future")
    recent = _msg(db, t, c, _iso(-timedelta(minutes=5)), body="recent")
    stale_day = _msg(db, t, c, _iso(-timedelta(days=1)), body="a day late")
    stale_month = _msg(db, t, c, _iso(-timedelta(days=45)), body="six weeks late")
    junk = _msg(db, t, c, "tomorrow morning", body="junk")
    note = _msg(db, t, c, _iso(-timedelta(minutes=1)), body="note", is_internal=True)
    sent = _msg(db, t, c, _iso(-timedelta(minutes=2)), body="already", delivery_state=MessageDeliveryState.SENT, channel_message_id="wamid.X")

    r = audit_mod.audit(db, now=NOW)

    assert r["total"] == 7
    assert dict(r["classes"]) == {"future": 1, "due_within_grace": 1, "stale": 2, "unparseable": 1, "internal_note": 1, "already_handled": 1}
    assert set(r["ids"]["stale"]) == {stale_day, stale_month}                    # old rows are never "due": they are stale
    assert r["ids"]["would_send_on_first_sweep"] == [recent]                     # the only candidate a first sweep may take
    assert r["would_send_on_first_sweep"] == 1


def test_a_naive_time_is_read_in_the_tenant_timezone_and_z_is_utc(db, world):
    t, g, c = world
    # 17:30 IST == 12:00 UTC == NOW: due right now when read in Asia/Kolkata; 5.5 h in the future if misread as UTC
    ist_naive = _msg(db, t, c, "2026-10-14T17:30:00", body="ist")
    utc_z = _msg(db, t, c, "2026-10-14T12:00:00Z", body="utc")
    r = audit_mod.audit(db, now=NOW)
    assert set(r["ids"]["due_within_grace"]) == {ist_naive, utc_z}
    assert audit_mod.parse_scheduled("2026-10-14T17:30:00", "Asia/Kolkata") == NOW


def test_opted_out_guests_duplicates_and_orphans_are_flagged_and_excluded_from_a_first_sweep(db, world):
    t, g, c = world
    a = _msg(db, t, c, _iso(-timedelta(minutes=3)), body="same text")
    b = _msg(db, t, c, _iso(-timedelta(minutes=3)), body="same text")            # duplicate of a
    db.add(Consent(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel="whatsapp", scope="marketing", granted=False,
                   recorded_at=NOW.isoformat(), withdrawn_at=NOW.isoformat()))
    db.commit()
    r = audit_mod.audit(db, now=NOW)
    assert r["flags"]["opted_out"] == 2 and r["flags"]["duplicate"] == 1
    assert r["would_send_on_first_sweep"] == 0                                    # opted out: nothing is eligible


def test_the_audit_is_read_only_and_prints_no_message_content(db, world, capsys):
    t, g, c = world
    mid = _msg(db, t, c, _iso(-timedelta(minutes=2)), body="SECRET-BODY-TEXT +919800000042")
    before = db.query(Message).filter_by(id=mid).one()
    snapshot = (before.delivery_state, before.scheduled_for, before.body, before.was_approved)
    report = audit_mod.audit(db, now=NOW)
    audit_mod._print(report, show_ids=True)
    out = capsys.readouterr().out
    assert "SECRET-BODY-TEXT" not in out and "919800000042" not in out
    db.expire_all()
    after = db.query(Message).filter_by(id=mid).one()
    assert snapshot == (after.delivery_state, after.scheduled_for, after.body, after.was_approved)


def test_tenant_filter_does_not_include_other_tenants_rows(db, world):
    t, g, c = world
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.flush()
    og = Guest(id=str(uuid.uuid4()), tenant_id=other.id, name="Z", phone="+919800000099")
    db.add(og)
    db.flush()
    oc = Conversation(id=str(uuid.uuid4()), tenant_id=other.id, guest_id=og.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(oc)
    db.commit()
    mine = _msg(db, t, c, _iso(timedelta(hours=1)))
    theirs = _msg(db, other, oc, _iso(timedelta(hours=1)))
    r = audit_mod.audit(db, now=NOW, tenant_id=t.id)
    assert r["total"] == 1 and r["ids"]["future"] == [mine] and theirs not in r["ids"]["future"]
