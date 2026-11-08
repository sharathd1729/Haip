"""tasks.analyze_call (AI cost audit, 8 Nov 2026): ONE model call per phone call instead of classify + judge
(+ deep_reason re-judge) + wrap-up, the same fields written, the QA rubric maths unchanged, a re-check only for a
borderline score, no model call for an empty transcript, and a retry / recovery run that resumes instead of asking the
model again or adding a second score row. No real LLM: the model is scripted (call_analysis_harness)."""

import pytest

from app.core.prompt_versions import get_version
from app.models.call import Call, CallDisposition
from app.models.guest import Guest
from app.models.score import CallScore, Rubric
from app.models.task import Task
from app.services import call_analysis as analysis
from app.services.qa_service import compute_score
from tests.workers import call_analysis_harness as h


def _scores(db, call_id):
    return db.query(CallScore).filter_by(call_id=call_id).all()


# ── one call, every field ───────────────────────────────────────────────────────────────────────────────────────────


def test_one_model_call_writes_every_field_the_three_steps_wrote(db):
    t = h.tenant(db)
    guest = Guest(tenant_id=t.id, name="Unknown Guest")
    db.add(guest)
    db.commit()
    c = h.call(db, t.id, guest_id=guest.id)
    llm = h.ScriptedLLM(
        h.answer(
            guest_name="Priya",
            is_code_mixed="true",
            competitor_mentioned="StayVista",
            budget_signal="That's high",
            lost_reason="price",
            language="en-hi",
            next_best_action={
                "action": "Call Priya with the quote",
                "channel": "call",
                "deadline": "today before 6 PM",
            },
        )
    )
    fx = h.run(db, t.id, c.id, llm)

    assert llm.tasks() == ["call_analysis"]  # one model call, no deep_reason
    c = db.get(Call, c.id)
    # was classify
    assert (c.detected_language, c.is_code_mixed, c.occasion, c.decision_stage) == (
        "en-hi",
        True,
        "family",
        "ready_to_book",
    )
    assert (c.competitor_mentioned, c.budget_signal, c.lost_reason, c.conversion_probability) == (
        "StayVista",
        "That's high",
        "price",
        70,
    )
    assert db.get(Guest, guest.id).name == "Priya"
    # was judge
    assert c.ai_score_status == "done" and float(c.ai_score) == 100.0
    [row] = _scores(db, c.id)
    assert row.analysis_version == get_version("call_analysis") == "call-analysis-v6"
    assert float(row.ai_confidence) == 0.9 and row.model_used == "fake-call_analysis"
    # was wrap-up
    assert c.ai_summary == "Guest wants to book for 4 next weekend." and c.ai_next_action == "Send the quote"
    assert c.ai_disposition == CallDisposition.HOT
    assert c.ai_insights["outcome"] == "negotiating" and c.ai_insights["next_best_action"]["channel"] == "call"
    assert c.ai_insights["agent_strengths"] == ["Warm greeting"]  # now shown on the call page
    # effects, once each
    assert len(fx.autopilot) == 1 and len(fx.triggers) == 1 and len(fx.sse) == 1
    assert fx.triggers[0]["kwargs"]["context"]["disposition"] == "hot"
    assert "Call summary ready" in fx.pushes


def test_the_prompt_keeps_the_call_out_of_the_cached_system_text(db):
    t = h.tenant(db)
    c = h.call(db, t.id)
    llm = h.ScriptedLLM(h.answer())
    h.run(db, t.id, c.id, llm)
    [(_, kw)] = llm.calls
    assert "family of four" in kw["user_message"] and "family of four" not in kw["system_prompt"]
    assert "pii_discipline" in kw["system_prompt"] and "next_best_action" in kw["system_prompt"]
    assert len(kw["user_message"]) >= 200  # the Claude adapter caches the system block from 200 chars
    assert [tool["name"] for tool in kw["tools"]] == ["analyse_call"]


def test_qa_criterion_scores_and_auto_fail_keep_the_rubric_maths(db):
    t = h.tenant(db)
    c = h.call(db, t.id)
    crit = h.scores(discovery=2, pricing=0, empathy=1, close=0, pii_discipline=0)
    h.run(db, t.id, c.id, h.ScriptedLLM(h.answer(criterion_scores=crit, has_auto_fail=True)))
    [row] = _scores(db, c.id)
    rubric = db.query(Rubric).filter_by(tenant_id=t.id, is_default=True).one()
    total, maximum, pct = compute_score(rubric.criteria, crit)
    assert round(pct, 2) == 59.33  # 8+8+12+0+3.33+10+12+0+0+6 of 100
    assert float(row.percentage) == pytest.approx(pct, abs=0.01) and float(row.max_score) == maximum == 100
    assert row.has_auto_fail is True and row.criterion_scores == crit


# ── no model call ───────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["no_row", "silent"])
def test_empty_transcript_is_skipped_without_a_model_call(db, kind):
    t = h.tenant(db)
    c = h.call(
        db, t.id, with_transcript=(kind == "silent"), turns=[{"speaker": "unknown", "t0": 0, "t1": 1, "text": "   "}]
    )
    llm = h.ScriptedLLM(h.answer())
    fx = h.run(db, t.id, c.id, llm)
    c = db.get(Call, c.id)
    assert llm.calls == [] and c.ai_score_status == "skipped_no_transcript" and c.ai_score_attempts == 0
    assert fx.triggers == [] and _scores(db, c.id) == []


def test_another_tenants_call_is_never_read(db):
    t, other = h.tenant(db), h.tenant(db)
    c = h.call(db, other.id)
    llm = h.ScriptedLLM(h.answer())
    h.run(db, t.id, c.id, llm)
    assert llm.calls == [] and db.get(Call, c.id).ai_score_status != "done"


def test_each_tenant_is_scored_on_its_own_rubric(db):
    t, other = h.tenant(db), h.tenant(db)
    db.add(
        Rubric(
            tenant_id=other.id,
            name="other_rubric",
            version="9",
            is_default=True,
            is_active=True,
            criteria=[{"id": "secret_rule", "weight": 50, "method": "YES_NO", "description": "x"}],
        )
    )
    db.commit()
    c = h.call(db, t.id)
    llm = h.ScriptedLLM(h.answer())
    h.run(db, t.id, c.id, llm)
    system = llm.calls[0][1]["system_prompt"]
    assert "secret_rule" not in system and "greeting" in system


# ── borderline re-check ─────────────────────────────────────────────────────────────────────────────────────────────


def test_a_clear_score_is_not_rechecked(db):
    t = h.tenant(db)
    c = h.call(db, t.id)
    llm = h.ScriptedLLM(h.answer(confidence=0.6))  # was below 0.78 -> deep_reason re-ran the whole prompt
    h.run(db, t.id, c.id, llm)
    assert llm.tasks() == ["call_analysis"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"confidence": 0.4},  # the model says it is guessing
        {"criterion_scores": h.scores(pricing=0, greeting=0)},  # 82%: within 5 of the 80 pass mark
    ],
)
def test_a_borderline_score_is_rechecked_from_the_first_answer_only(db, overrides):
    t = h.tenant(db)
    c = h.call(db, t.id)
    fixed = h.scores(pricing=0, greeting=0, close=0)  # 70%
    llm = h.ScriptedLLM(
        h.answer(**overrides), recheck={"criterion_scores": fixed, "has_auto_fail": False, "confidence": 0.8}
    )
    h.run(db, t.id, c.id, llm)
    assert llm.tasks() == ["call_analysis", "deep_reason"]
    recheck_kw = llm.calls[1][1]
    assert "family of four" not in recheck_kw["user_message"]  # never the transcript again
    assert "quoted turn" in recheck_kw["user_message"]  # the first answer's evidence
    [row] = _scores(db, c.id)
    assert row.criterion_scores == fixed and float(row.percentage) == 70.0
    assert row.model_used == "fake-deep_reason_review"


def test_a_failed_recheck_keeps_the_first_answer(db):
    t = h.tenant(db)
    c = h.call(db, t.id)
    llm = h.ScriptedLLM(h.answer(confidence=0.3), recheck_error=RuntimeError("500 from provider"))
    h.run(db, t.id, c.id, llm)
    c = db.get(Call, c.id)
    assert c.ai_score_status == "done" and float(c.ai_score) == 100.0


def test_borderline_rule():
    crit = [{"id": "a", "weight": 100, "method": "ZERO_THREE"}]
    assert analysis.is_borderline({"criterion_scores": [{"id": "a", "score": 2.4}], "confidence": 0.9}, crit)  # 80%
    assert not analysis.is_borderline({"criterion_scores": [{"id": "a", "score": 3}], "confidence": 0.9}, crit)
    assert not analysis.is_borderline({"criterion_scores": [{"id": "a", "score": 1}], "confidence": 0.9}, crit)
    assert analysis.is_borderline({"criterion_scores": [{"id": "a", "score": 1}], "confidence": 0.49}, crit)
    assert not analysis.is_borderline({"criterion_scores": [], "confidence": 0.1}, crit)


# ── retries and recovery resume ─────────────────────────────────────────────────────────────────────────────────────


def test_a_db_failure_after_the_model_retries_without_a_second_model_call(db):
    t = h.tenant(db)
    c = h.call(db, t.id)
    llm = h.ScriptedLLM(h.answer())
    real_apply = analysis.apply_result
    calls = {"n": 0}

    def flaky_apply(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database went away")
        return real_apply(*a, **kw)

    fx = h.Effects()
    from unittest.mock import patch

    with patch.object(analysis, "apply_result", flaky_apply):
        with pytest.raises(RuntimeError):
            h.run(db, t.id, c.id, llm, fx)  # .run() re-raises where Celery would retry
        db.expire_all()
        assert db.get(Call, c.id).ai_score_status == "failed" and fx.triggers == []
        h.run(db, t.id, c.id, llm, fx)  # the retry

    c = db.get(Call, c.id)
    assert llm.tasks() == ["call_analysis"]  # the kept answer was written
    assert c.ai_score_status == "done" and len(_scores(db, c.id)) == 1
    assert len(fx.triggers) == 1 and len(fx.autopilot) == 1  # effects once, after the write


def test_a_recovery_run_updates_the_score_row_instead_of_adding_one(db):
    t = h.tenant(db)
    c = h.call(db, t.id)
    h.run(db, t.id, c.id, h.ScriptedLLM(h.answer()))
    # a later run (recovery, a deliberate re-run) with a different answer for the same transcript
    db.query(Call).filter_by(id=c.id).update({"ai_score_status": "failed"})
    db.commit()
    llm = h.ScriptedLLM(h.answer(criterion_scores=h.scores(close=0)))
    h.run(db, t.id, c.id, llm)
    [row] = _scores(db, c.id)
    assert float(row.percentage) == 88.0 and db.get(Call, c.id).ai_score_attempts == 2


def test_a_person_overridden_score_is_left_alone(db):
    t = h.tenant(db)
    c = h.call(db, t.id)
    h.run(db, t.id, c.id, h.ScriptedLLM(h.answer()))
    [row] = _scores(db, c.id)
    row.is_overridden = True
    db.commit()
    h.run(db, t.id, c.id, h.ScriptedLLM(h.answer(criterion_scores=h.scores(close=0))))
    [row] = _scores(db, c.id)
    assert float(row.percentage) == 100.0


def test_a_model_failure_marks_failed_and_counts_the_attempt(db):
    from unittest.mock import patch

    from celery.exceptions import MaxRetriesExceededError

    t = h.tenant(db)
    c = h.call(db, t.id)
    llm = h.ScriptedLLM(error=RuntimeError("provider down"))
    with patch.object(h.task_mod.analyze_call, "retry", side_effect=MaxRetriesExceededError("exhausted")):
        h.run(db, t.id, c.id, llm)  # must not raise
    c = db.get(Call, c.id)
    assert c.ai_score_status == "failed" and c.ai_score_attempts == 1


def test_callback_disposition_creates_one_reminder(db):
    t = h.tenant(db)
    guest = Guest(tenant_id=t.id, name="Kiran")
    db.add(guest)
    db.commit()
    for _ in range(2):
        c = h.call(db, t.id, guest_id=guest.id)
        h.run(db, t.id, c.id, h.ScriptedLLM(h.answer(suggested_disposition="callback")))
    [task] = db.query(Task).filter_by(tenant_id=t.id, guest_id=guest.id).all()
    assert task.title == "Callback requested — Kiran" and task.priority == "high" and task.due_date is not None


# ── routing ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_task_and_its_old_names_route_to_ai_scoring():
    from app.workers.celery_app import celery_app

    for name in ("tasks.analyze_call", "tasks.classify", "tasks.judge", "tasks.wrap_up"):
        assert name in celery_app.tasks
        assert celery_app.amqp.router.route({}, name)["queue"].name == "ai_scoring"


def test_old_task_names_hand_over_to_the_single_analysis():
    from unittest.mock import patch

    with patch.object(h.task_mod.analyze_call, "delay") as delay:
        h.task_mod.judge.run(call_id="c1", tenant_id="t1", classification={"sentiment": "positive"})
        h.task_mod.wrap_up.run(call_id="c1", tenant_id="t1", classification={}, judge_result={})
    assert [kw for _, kw in delay.call_args_list] == [{"call_id": "c1", "tenant_id": "t1"}] * 2
