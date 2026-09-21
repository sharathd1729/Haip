"""Calls redesign backend: the "Call back" view, a working Outcome filter,
the summary tiles, guest channel icons, and wrap-up notes that no longer
overwrite the AI summary."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.call import Call, CallDirection, CallDisposition
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.tenant import Tenant

NOW = datetime.now(timezone.utc)


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _guest(db, tid, name="Guest"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name, phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g); db.flush(); return g


def _call(db, tid, guest, *, direction="inbound", duration=0, minutes_ago=5, score=None,
          ai_disp=None, human_disp=None, recovered_by=None, dial_status=None):
    c = Call(
        id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, ivr_provider="vobiz",
        ivr_call_id=f"c-{uuid.uuid4().hex[:10]}",
        direction=CallDirection.INBOUND if direction == "inbound" else CallDirection.OUTBOUND,
        from_number=guest.phone if direction == "inbound" else "+918000000000",
        to_number="+918000000000" if direction == "inbound" else guest.phone,
        duration_seconds=duration, ai_score=score, ai_disposition=ai_disp, human_disposition=human_disp,
        recovered_by_call_id=recovered_by, ivr_dial_status=dial_status,
        created_at=NOW - timedelta(minutes=minutes_ago),
    )
    db.add(c); db.flush(); return c


def _ids(res):
    return {i["id"] for i in res.json()["items"]}


def test_needs_callback_view_lists_only_unreturned_missed_calls(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g = _guest(db, tid)
    open_missed = _call(db, tid, g)
    returned = _call(db, tid, g, direction="outbound", duration=90, dial_status="completed")
    closed_missed = _call(db, tid, g, recovered_by=returned.id)
    answered = _call(db, tid, g, duration=120, dial_status="completed")
    db.commit()

    ids = _ids(client.get("/api/v1/calls?view=needs_callback", headers=_auth(tenant_and_user)))
    assert ids == {open_missed.id}
    assert closed_missed.id not in ids and answered.id not in ids


def test_outcome_filter_now_applies(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g = _guest(db, tid)
    booked_ai = _call(db, tid, g, duration=200, dial_status="completed", ai_disp=CallDisposition.BOOKED)
    overridden = _call(db, tid, g, duration=200, dial_status="completed",
                       ai_disp=CallDisposition.BOOKED, human_disp=CallDisposition.LOST)
    _call(db, tid, g, duration=200, dial_status="completed", ai_disp=CallDisposition.HOT)
    db.commit()

    ids = _ids(client.get("/api/v1/calls?disposition=booked", headers=_auth(tenant_and_user)))
    # A human's outcome wins over the AI's.
    assert ids == {booked_ai.id}
    assert overridden.id in _ids(client.get("/api/v1/calls?disposition=lost", headers=_auth(tenant_and_user)))


def test_outcome_filter_rejects_unknown_value(client, tenant_and_user):
    res = client.get("/api/v1/calls?disposition=spam", headers=_auth(tenant_and_user))
    assert res.status_code == 422


def test_list_includes_guest_channels(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g = _guest(db, tid)
    db.add(Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.INSTAGRAM))
    c = _call(db, tid, g, duration=60, dial_status="completed")
    db.commit()
    item = next(i for i in client.get("/api/v1/calls", headers=_auth(tenant_and_user)).json()["items"] if i["id"] == c.id)
    assert item["guest_channels"] == ["instagram", "call"]


def test_summary_numbers(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g = _guest(db, tid)
    _call(db, tid, g, minutes_ago=30)                                                   # missed, open
    ret = _call(db, tid, g, direction="outbound", duration=100, dial_status="completed", score=90)
    _call(db, tid, g, minutes_ago=20, recovered_by=ret.id)                              # missed, returned
    _call(db, tid, g, duration=200, dial_status="completed", score=70)                  # answered in
    _call(db, tid, g, duration=300, dial_status="completed")                            # answered in
    db.commit()

    body = client.get("/api/v1/calls/summary?date_preset=today", headers=_auth(tenant_and_user)).json()
    assert body["total"] == 5
    assert body["inbound"] == 4 and body["outbound"] == 1
    assert body["missed"] == 2
    assert body["missed_not_called_back"] == 1
    assert body["answer_rate"] == 50
    assert body["avg_answered_seconds"] == 200
    assert body["avg_qa_score"] == 80.0


def test_summary_is_tenant_scoped_and_needs_auth(client, db, tenant_and_user):
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.flush()
    _call(db, other.id, _guest(db, other.id))
    db.commit()
    body = client.get("/api/v1/calls/summary", headers=_auth(tenant_and_user)).json()
    assert body["total"] == 0
    assert client.get("/api/v1/calls/summary").status_code in (401, 403)


def test_wrap_up_notes_do_not_overwrite_ai_summary(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _call(db, tid, _guest(db, tid), duration=200, dial_status="completed")
    c.ai_summary = "AI: booked Coorg for 6."
    db.commit()

    res = client.post(f"/api/v1/calls/{c.id}/wrap-up", json={"disposition": "booked", "notes": "Wants veg menu"},
                      headers=_auth(tenant_and_user))
    assert res.status_code == 200
    db.refresh(c)
    assert c.ai_summary == "AI: booked Coorg for 6."
    assert c.disposition_note == "Wants veg menu"
    detail = client.get(f"/api/v1/calls/{c.id}", headers=_auth(tenant_and_user)).json()
    assert detail["wrap_up_notes"] == "Wants veg menu"
    assert detail["ai_summary"] == "AI: booked Coorg for 6."
