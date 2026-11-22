"""Each call is analysed (paid for) once (AI_COST_SPEC step 0 trace: one call was read 19 times, every read successful).

tasks.analyze_call takes the call in one guarded UPDATE before any model call: a call that is already "done", or that
another worker is analysing right now, is skipped; an abandoned "processing" call (quiet past call_recovery's stall
window) and a "failed" one (its retry) are still analysed.
"""

from datetime import UTC, datetime, timedelta

from app.models.call import Call
from tests.workers import call_analysis_harness as h


def _call(db, tid, **state):
    c = h.call(db, tid)
    for k, v in state.items():
        setattr(c, k, v)
    db.commit()
    return c


def test_a_call_already_analysed_is_not_paid_for_again(db):
    tid = h.tenant(db).id
    c = _call(db, tid, ai_score_status="done", ai_score_attempts=1)
    llm = h.ScriptedLLM(h.answer())
    h.run(db, tid, c.id, llm)
    assert llm.calls == []
    db.refresh(c)
    assert c.ai_score_status == "done" and c.ai_score_attempts == 1


def test_a_call_another_worker_is_analysing_is_skipped(db):
    tid = h.tenant(db).id
    c = _call(db, tid, ai_score_status="processing", ai_score_attempts=1, updated_at=datetime.now(UTC))
    llm = h.ScriptedLLM(h.answer())
    h.run(db, tid, c.id, llm)
    assert llm.calls == []
    db.refresh(c)
    assert c.ai_score_attempts == 1


def test_an_abandoned_processing_call_is_analysed(db):
    tid = h.tenant(db).id
    c = _call(
        db, tid, ai_score_status="processing", ai_score_attempts=1, updated_at=datetime.now(UTC) - timedelta(hours=2)
    )
    llm = h.ScriptedLLM(h.answer())
    h.run(db, tid, c.id, llm)
    assert len(llm.calls) >= 1
    db.refresh(c)
    assert c.ai_score_status == "done" and c.ai_score_attempts == 2


def test_a_failed_call_is_analysed_on_retry(db):
    tid = h.tenant(db).id
    c = _call(db, tid, ai_score_status="failed", ai_score_attempts=1)
    llm = h.ScriptedLLM(h.answer())
    h.run(db, tid, c.id, llm)
    assert len(llm.calls) >= 1
    assert db.get(Call, c.id).ai_score_status == "done"


def test_a_second_copy_right_after_the_first_pays_nothing(db):
    # The transcription chain and the recovery sweep queued the same call seconds apart.
    tid = h.tenant(db).id
    c = h.call(db, tid)
    first, second = h.ScriptedLLM(h.answer()), h.ScriptedLLM(h.answer())
    h.run(db, tid, c.id, first)
    h.run(db, tid, c.id, second)
    assert len(first.calls) >= 1 and second.calls == []
    assert db.get(Call, c.id).ai_score_attempts == 1
