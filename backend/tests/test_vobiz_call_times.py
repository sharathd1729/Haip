"""Vobiz call times are stored as ISO-8601 UTC.

Vobiz's answer callback sends no StartTime and the recording callback's
RecordingEndMs is raw epoch ms, so calls landed with started_at "" and
ended_at "1793595257042": every report comparing started_at to an ISO date
dropped them. Covers the webhook helper chain and the backfill script.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.api.v1.endpoints.webhooks_vobiz import _cache_key, _call_times, _iso_utc
from app.core.cache import get_cached, set_cached
from app.models.call import Call, CallDirection
from app.models.tenant import Tenant
from tests.test_vobiz_ivr import _connect_vobiz

END_MS = "1793595257042"  # 2026-11-02T04:54:17.042Z
END_ISO = "2026-11-02T04:54:17.042000+00:00"


@pytest.mark.parametrize("raw, expected", [
    (END_MS, END_ISO),
    ("1793595257", "2026-11-02T04:54:17+00:00"),
    ("2026-07-26T10:00:00Z", "2026-07-26T10:00:00+00:00"),
    ("2026-07-26 10:00:00", "2026-07-26T10:00:00+00:00"),
    ("2026-07-26T15:30:00+05:30", "2026-07-26T10:00:00+00:00"),
    ("", ""), (None, ""), ("garbage", ""), ("9" * 30, ""),
])
def test_iso_utc(raw, expected):
    assert _iso_utc(raw) == expected


def test_call_times_prefers_start_time_then_recording_start_then_answer_then_duration():
    data = {"RecordingEndMs": END_MS, "RecordingStartMs": "1793595200000", "RecordingDuration": "57"}
    assert _call_times({"started_at": "2026-11-02T08:50:00Z", "answered_at": "x"}, data) == (
        "2026-11-02T08:50:00+00:00", END_ISO)
    assert _call_times({"started_at": "", "answered_at": "2026-11-02T08:49:00+00:00"}, data)[0] == (
        "2026-11-02T04:53:20+00:00")
    no_rec_start = {k: v for k, v in data.items() if k != "RecordingStartMs"}
    assert _call_times({"started_at": "", "answered_at": "2026-11-02T08:49:00+00:00"}, no_rec_start)[0] == (
        "2026-11-02T08:49:00+00:00")
    # cache expired: only the recording callback is left
    assert _call_times({}, no_rec_start) == ("2026-11-02T04:53:20.042000+00:00", END_ISO)
    assert _call_times({}, {}) == ("", "")


def _post(client, tenant, path, data):
    return client.post(f"/api/v1/webhooks/vobiz/{tenant.slug}/s3cret/{path}", data=data)


def _capture(monkeypatch):
    from app.workers.tasks import call_ingest
    out = {}
    monkeypatch.setattr(call_ingest.ingest_call, "delay", lambda **kw: out.update(kw))
    return out


def test_answer_without_start_time_caches_arrival_time_and_recording_gets_iso(client, tenant_and_user, db, monkeypatch):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="s3cret", forward_number="+919000000000")
    before = datetime.now(timezone.utc).isoformat()
    assert _post(client, tenant, "answer", {"CallUUID": "c-1", "From": "+919876543210",
                                            "To": "+912271264296"}).status_code == 200
    cached = get_cached(_cache_key(tenant.id, "c-1"))
    assert cached["started_at"] == ""
    assert cached["answered_at"] >= before

    sent = _capture(monkeypatch)
    _post(client, tenant, "recording", {"CallUUID": "c-1", "RecordingDuration": "57", "RecordingEndMs": END_MS,
                                        "RecordFile": "https://api.vobiz.ai/r/1"})
    assert sent["payload"]["ended_at"] == END_ISO
    assert sent["payload"]["started_at"] == cached["answered_at"]


def test_answer_with_start_time_and_recording_start_ms(client, tenant_and_user, db, monkeypatch):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="s3cret", forward_number="+919000000000")
    _post(client, tenant, "answer", {"CallUUID": "c-2", "From": "+919876543210", "StartTime": "2026-11-02 08:50:00"})
    assert get_cached(_cache_key(tenant.id, "c-2"))["started_at"] == "2026-11-02T08:50:00+00:00"

    # a cache that predates answered_at, with no StartTime: RecordingStartMs wins
    set_cached(_cache_key(tenant.id, "c-3"), {"From": "+919876543210", "To": "", "Direction": "inbound",
                                               "started_at": ""}, ttl=60)
    sent = _capture(monkeypatch)
    _post(client, tenant, "recording", {"CallUUID": "c-3", "RecordingStartMs": "1793595200000",
                                        "RecordingEndMs": END_MS, "RecordingDuration": "57"})
    assert sent["payload"]["started_at"] == "2026-11-02T04:53:20+00:00"
    assert sent["payload"]["ended_at"] == END_ISO


def test_outbound_answer_caches_arrival_time(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="s3cret", forward_number="+919000000000")
    res = client.post(f"/api/v1/webhooks/vobiz/{tenant.slug}/s3cret/outbound-answer?guest_number=9876543210",
                      data={"CallUUID": "c-out"})
    assert res.status_code == 200
    cached = get_cached(_cache_key(tenant.id, "c-out"))
    assert cached["started_at"] == "" and cached["answered_at"].endswith("+00:00")


# ── backfill script ─────────────────────────────────────────────────────────

def _call(db, tenant_id, **kw):
    c = Call(id=str(uuid.uuid4()), tenant_id=tenant_id, ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
             direction=CallDirection.INBOUND, from_number="+919876543210", to_number="+912271264296", **kw)
    db.add(c)
    db.commit()
    return c


def test_backfill_dry_run_then_apply(db, tenant_and_user):
    from scripts.backfill_call_timestamps import run
    tid = tenant_and_user["tenant"].id
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    a = _call(db, tid, started_at="", ended_at=END_MS, duration_seconds=57)
    b = _call(db, tid, started_at=None, ended_at=None, duration_seconds=0,
              created_at=datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc))
    ok = _call(db, tid, started_at="2026-11-01T05:00:00+00:00", ended_at="2026-11-01T05:01:00+00:00")
    foreign = _call(db, other.id, started_at="", ended_at=END_MS, duration_seconds=10)

    dry = run(db, tid)
    assert dry["calls_checked"] == 2
    assert dry["ended_at_converted"] == 1
    assert dry["started_from_end_minus_duration"] == 1
    assert dry["started_from_created_at"] == 1
    db.refresh(a)  # dry run never sets attributes (no rollback: on SQLite it erases the test's rows)
    assert a.ended_at == END_MS and a.started_at == ""

    run(db, tid, apply=True)
    db.commit()
    for c in (a, b, ok, foreign):
        db.refresh(c)
    assert (a.started_at, a.ended_at) == ("2026-11-02T04:53:20.042000+00:00", END_ISO)
    assert b.started_at.startswith("2026-11-01T06:00:00")
    assert ok.started_at == "2026-11-01T05:00:00+00:00"
    assert foreign.ended_at == END_MS  # other tenant untouched
    assert run(db, tid)["calls_checked"] == 0
