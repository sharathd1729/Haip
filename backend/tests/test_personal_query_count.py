"""Yaad's /me screens felt slow. The SQL statements each screen runs must not grow with the number of calls (no N+1),
and the lists must not load every call's full memory to build a short list. Made-up data only."""

import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import event

from app.models.call import Call, CallDirection
from app.services import personal_calls as pc
from tests.conftest import engine
from tests.test_personal_calls import MEMORY, _auth, _personal, _tid

NOW = datetime.now(UTC)


def _seed(db, tid, n):
    memory = pc.normalise({**MEMORY, "upcoming": [{"what": "Site visit", "date": "2099-01-05"}]})
    for k in range(n):
        c = Call(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            ivr_provider="mobile_app",
            ivr_call_id=f"m-{uuid.uuid4().hex[:10]}",
            direction=CallDirection.INBOUND,
            from_number=f"+9198{k:08d}",
            to_number="+919800000000",
            duration_seconds=90,
            recording_s3_key=f"{tid}/calls/{k}.mp3",
            transcription_status="done",
            created_at=NOW - timedelta(hours=7 * k),  # ~400 calls over ~115 days
        )
        pc.store(c, memory)
        db.add(c)
    db.commit()


def _measure(client, url, headers):
    statements = []

    def count(conn, cursor, statement, *a):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        t0 = time.perf_counter()
        r = client.get(url, headers=headers)
        ms = (time.perf_counter() - t0) * 1000
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert r.status_code == 200, r.text
    return len(statements), ms, r.json()


def test_me_screens_run_a_fixed_number_of_statements(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    headers = _auth(tenant_and_user)
    _seed(db, tid, 40)
    small = {u: _measure(client, u, headers)[0] for u in ("/api/v1/me/calls", "/api/v1/me/reminders")}
    _seed(db, tid, 360)
    for url, before in small.items():
        n, ms, body = _measure(client, url, headers)
        print(f"{url}: {n} statements, {ms:.0f} ms")
        assert n == before, f"{url} grew from {before} to {n} statements with more calls"
        assert ms < 1500, f"{url} took {ms:.0f} ms on 400 calls"
    calls = _measure(client, "/api/v1/me/calls", headers)[2]
    assert len(calls["calls"]) == 40 and calls["upcoming"]
