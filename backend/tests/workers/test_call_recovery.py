"""AI call scoring recovery (Ratha, Oct 2026): calls from 28 Sep sat at
"failed" and older calls at "pending". The recovery task was never in the
beat schedule, only looked at "pending", and went oldest-first so calls that
could never be scored crowded newer ones out of its limit window.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session as SASession

from app.models.call import Call, CallDirection
from app.models.tenant import Tenant
from app.models.transcript import Transcript
from app.workers.tasks import call_recovery as rec
from app.workers.tasks.judge import judge

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_now():
    """NOW is set at import (collection); a full run reaches these tests 30+ min later, ageing every "N minutes ago" past
    its threshold. Re-read the clock per test."""
    global NOW
    NOW = datetime.now(timezone.utc)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"cr-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.commit()
    return t


def _call(db, tid, *, status="pending", hours_ago=5, attempts=0, transcription="done", quiet_minutes=120):
    c = Call(
        id=str(uuid.uuid4()), tenant_id=tid, ivr_provider="vobiz", ivr_call_id=f"c-{uuid.uuid4().hex[:8]}",
        direction=CallDirection.INBOUND, from_number="+919800000001", to_number="+912200000000",
        duration_seconds=120, started_at=(NOW - timedelta(hours=hours_ago)).isoformat(),
        transcription_status=transcription, ai_score_status=status, ai_score_attempts=attempts,
    )
    db.add(c); db.commit()
    c.updated_at = NOW - timedelta(minutes=quiet_minutes)
    db.commit()
    return c


def _recover(db, tid, limit=100):
    dispatched = []
    with patch.object(rec, "SessionLocal", return_value=SASession(bind=db.connection())), \
         patch("app.workers.tasks.judge.judge.delay", side_effect=lambda **kw: dispatched.append(kw["call_id"])):
        rec.recover_stalled_call_scoring.run(tid, limit=limit)
    return dispatched



def test_pending_call_is_redispatched(db):
    t = _tenant(db)
    c = _call(db, t.id, status="pending")
    assert _recover(db, t.id) == [c.id]


def test_a_failed_call_is_redispatched_once_it_has_been_quiet(db):
    t = _tenant(db)
    c = _call(db, t.id, status="failed", quiet_minutes=120)
    assert _recover(db, t.id) == [c.id]


def test_a_just_failed_call_is_left_alone_while_judges_own_retries_run(db):
    t = _tenant(db)
    _call(db, t.id, status="failed", quiet_minutes=2)
    assert _recover(db, t.id) == []


def test_a_call_that_keeps_failing_stops_being_retried(db):
    t = _tenant(db)
    _call(db, t.id, status="failed", attempts=rec.MAX_SCORE_ATTEMPTS)
    assert _recover(db, t.id) == []


def test_old_failures_are_not_retried(db):
    t = _tenant(db)
    _call(db, t.id, status="failed", hours_ago=24 * (rec.FAILED_LOOKBACK_DAYS + 2))
    assert _recover(db, t.id) == []


def test_scored_skipped_and_untranscribed_calls_are_left_alone(db):
    t = _tenant(db)
    _call(db, t.id, status="done")
    _call(db, t.id, status="skipped_short_call")
    _call(db, t.id, status="skipped_no_transcript")
    _call(db, t.id, status="pending", transcription="failed")
    assert _recover(db, t.id) == []


def test_other_tenants_calls_are_never_touched(db):
    t, other = _tenant(db), _tenant(db)
    _call(db, other.id, status="failed")
    assert _recover(db, t.id) == []


def test_newest_calls_win_the_limit_window(db):
    t = _tenant(db)
    old = [_call(db, t.id, status="pending", hours_ago=500 + i) for i in range(3)]
    new = _call(db, t.id, status="pending", hours_ago=3)
    got = _recover(db, t.id, limit=1)
    assert got == [new.id]


def test_recovery_is_scheduled_in_beat():
    from app.workers.celery_app import celery_app
    tasks = {v["task"] for v in celery_app.conf.beat_schedule.values()}
    assert "calls.recover_stalled_scoring_all_tenants" in tasks


# ── judge() no longer leaves un-scoreable calls looping ─────────────────────

def _run_judge(db, tid, call):
    with patch("app.workers.tasks.judge.SessionLocal", return_value=SASession(bind=db.connection())):
        judge.run(call_id=call.id, tenant_id=tid)
    db.expire_all()
    return db.query(Call).get(call.id)


def test_a_call_with_no_transcript_row_is_skipped_not_left_pending(db):
    t = _tenant(db)
    c = _call(db, t.id, status="pending")
    assert _run_judge(db, t.id, c).ai_score_status == "skipped_no_transcript"


def test_an_empty_transcript_is_skipped(db):
    t = _tenant(db)
    c = _call(db, t.id, status="pending")
    db.add(Transcript(id=str(uuid.uuid4()), tenant_id=t.id, call_id=c.id, provider="sarvam", language="en",
                      turns=json.dumps([{"speaker": "unknown", "t0": 0, "t1": 1, "text": "  "}]), raw_text=""))
    db.commit()
    assert _run_judge(db, t.id, c).ai_score_status == "skipped_no_transcript"


def test_judge_counts_its_attempts_and_marks_failure(db):
    t = _tenant(db)
    c = _call(db, t.id, status="pending")
    db.add(Transcript(id=str(uuid.uuid4()), tenant_id=t.id, call_id=c.id, provider="sarvam", language="en",
                      turns=json.dumps([{"speaker": "agent", "t0": 0, "t1": 2, "text": "Hello, Ratha caravans."}]),
                      raw_text="Hello"))
    db.commit()

    class _Boom:
        async def complete(self, **kw):
            raise RuntimeError("provider down")

    from celery.exceptions import MaxRetriesExceededError
    with patch("app.workers.tasks.judge.get_llm", return_value=_Boom()), \
         patch.object(judge, "retry", side_effect=MaxRetriesExceededError("exhausted")):
        got = _run_judge(db, t.id, c)           # must not raise
    assert got.ai_score_status == "failed"
    assert got.ai_score_attempts == 1


def test_a_transcriptless_call_is_skipped_once_and_never_redispatched(db):
    """Register P-1. judge() skips a call with no transcript row; recovery must then leave it alone on every later
    pass. When the status did not fit the column on PostgreSQL the write failed, the call fell back to "failed" with
    ai_score_attempts still 0, and recovery re-dispatched it every 30 minutes for 14 days."""
    t = _tenant(db)
    c = _call(db, t.id, status="pending")

    judged = _run_judge(db, t.id, c)

    assert judged.ai_score_status == "skipped_no_transcript"
    assert judged.ai_score_attempts == 0          # a skip is not a scoring attempt
    for _ in range(3):                            # three recovery passes, each after a quiet period
        judged.updated_at = NOW - timedelta(minutes=120)
        db.commit()
        assert _recover(db, t.id) == []
