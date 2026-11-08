"""Claude Message Batches for nightly jobs (adapters/llm/batch.py + workers/tasks/llm_batch.py). Mocked Anthropic client,
no network: collect -> submit -> poll -> replay, results matched by custom_id, misses and failures fall back to normal calls."""

import asyncio
from types import SimpleNamespace

import pytest

from app.adapters.llm import batch, metered
from app.adapters.llm.base import LLMAdapter
from app.adapters.llm.scope import llm_scope
from app.workers.tasks import llm_batch

TENANT = "tenant-a"


class _Live(LLMAdapter):
    provider, _default_model = "claude", "claude-sonnet-5-5"

    def __init__(self):
        self.calls = []

    async def complete(self, system_prompt, user_message, **kw):
        self.calls.append(user_message)
        return {"content": f"live:{user_message}", "model": "claude-sonnet-5-5", "input_tokens": 10, "output_tokens": 5}


def _msg(text, inp=1000, out=200):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        model="claude-sonnet-5-5",
        usage=SimpleNamespace(
            input_tokens=inp, output_tokens=out, cache_read_input_tokens=0, cache_creation_input_tokens=0
        ),
    )


class _Batches:
    def __init__(self):
        self.created, self.results_by_id, self.state, self.cancelled, self.fail_create = (
            [],
            {},
            "in_progress",
            [],
            False,
        )

    def create(self, requests):
        if self.fail_create:
            raise RuntimeError("batch API down")
        self.created.append(requests)
        return SimpleNamespace(id="msgbatch_1", processing_status="in_progress")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status=self.state)

    def results(self, batch_id):
        return iter(self.results_by_id.get(batch_id, []))

    def cancel(self, batch_id):
        self.cancelled.append(batch_id)


@pytest.fixture
def env(monkeypatch):
    from app.core import cache
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_FORCE_PROVIDER", "claude")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "test-key")
    batches = _Batches()
    monkeypatch.setattr(batch, "_client", lambda: SimpleNamespace(messages=SimpleNamespace(batches=batches)))
    live = _Live()
    monkeypatch.setattr("app.adapters.llm._unmetered_llm", lambda task, tenant_id=None: live)
    rows, queued, claimed, done = [], [], set(), []
    monkeypatch.setattr(metered, "write_rows", lambda r: rows.extend(r))
    monkeypatch.setattr(llm_batch.poll, "apply_async", lambda args, countdown: queued.append(args))
    monkeypatch.setattr(cache, "idem_check_and_set", lambda key, ttl=0: not (key in claimed or claimed.add(key)))

    def job(tenant_id, final, items=("A", "B"), task="outcome_reason"):
        from app.adapters.llm import get_llm

        for item in items:
            with llm_scope(tenant_id=tenant_id, module="leads", ref_type="inquiry", ref_id=item):
                out = asyncio.run(get_llm(task).complete(system_prompt="sys", user_message=item, max_tokens=900))
            if final:
                done.append((item, out["content"]))
        return len(items)

    monkeypatch.setitem(llm_batch.JOBS, "toy", job)
    return SimpleNamespace(batches=batches, live=live, rows=rows, queued=queued, done=done)


def _cid(item, tenant=TENANT):
    return batch.custom_id("outcome_reason", tenant, "sys", item, 900, None)


def test_submit_collects_without_calling_the_provider_and_queues_a_poll(env):
    out = llm_batch.submit.run("toy", TENANT, {})
    assert out["batch_id"] == "msgbatch_1" and out["requests"] == 2
    assert env.live.calls == [] and env.done == [] and env.rows == []  # collect pass: no call, no meter, nothing kept
    (requests,) = env.batches.created
    assert {r["custom_id"] for r in requests} == {_cid("A"), _cid("B")}
    params = requests[0]["params"]
    assert params["model"] == "claude-sonnet-5-5" and params["output_config"] == {"effort": "medium"}
    (args,) = env.queued
    assert args[0] == "toy" and args[1] == TENANT and args[3] == "msgbatch_1" and set(args[4]) == {_cid("A"), _cid("B")}


def test_poll_applies_results_by_custom_id_meters_half_price_and_is_idempotent(env):
    llm_batch.submit.run("toy", TENANT, {})
    env.batches.state = "ended"
    env.batches.results_by_id["msgbatch_1"] = [  # any order; B errored
        SimpleNamespace(custom_id=_cid("B"), result=SimpleNamespace(type="errored")),
        SimpleNamespace(custom_id=_cid("A"), result=SimpleNamespace(type="succeeded", message=_msg("batch:A"))),
    ]
    out = llm_batch.poll.run(*env.queued[0])
    assert out["from_batch"] == 1
    assert env.done == [("A", "batch:A"), ("B", "live:B")] and env.live.calls == ["B"]  # B fell back to a normal call
    batch_row = next(r for r in env.rows if r["meta"].get("batch"))
    assert batch_row["tenant_id"] == TENANT and batch_row["ref_id"] == "A" and batch_row["module"] == "leads"
    assert batch_row["meta"]["cost_usd"] == round((1000 * 2.0 + 200 * 10.0) / 1e6 / 2, 6)
    assert sum(1 for r in env.rows if not r["meta"].get("batch")) == 1  # the live call, metered normally
    before = len(env.rows)
    assert llm_batch.poll.run(*env.queued[0])["status"] == "already_applied"
    assert len(env.done) == 2 and len(env.rows) == before


def test_still_processing_requeues_then_times_out_into_normal_calls(env):
    llm_batch.submit.run("toy", TENANT, {})
    args = env.queued[0]
    assert llm_batch.poll.run(*args)["status"] == "processing" and len(env.queued) == 2
    expired = (*args[:5], "2000-01-01T00:00:00+00:00")
    out = llm_batch.poll.run(*expired)
    assert env.batches.cancelled == ["msgbatch_1"] and out["from_batch"] == 0 and env.live.calls == ["A", "B"]


def test_batch_create_failure_runs_normal_calls_now(env):
    env.batches.fail_create = True
    out = llm_batch.submit.run("toy", TENANT, {})
    assert out["from_batch"] == 0 and env.live.calls == ["A", "B"] and env.queued == []


def test_non_claude_provider_never_batches(env, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_FORCE_PROVIDER", "")
    assert not batch.enabled("outcome_reason")
    llm_batch.submit.run("toy", TENANT, {})
    assert env.batches.created == [] and env.live.calls == ["A", "B"]


def test_only_listed_tasks_and_this_tenants_calls_are_collected(env):
    with batch.collecting(TENANT) as col:
        for task, tid in (("outcome_reason", TENANT), ("concierge_draft", TENANT), ("outcome_reason", "tenant-b")):
            with llm_scope(tenant_id=tid):
                from app.adapters.llm import get_llm

                out = asyncio.run(get_llm(task).complete(system_prompt="sys", user_message="x", max_tokens=900))
                assert out["batch_deferred"] and out["content"] == ""
    assert list(col.requests) == [_cid("x")] and env.live.calls == []
    assert batch.BATCH_TASKS["outcome_reason"] and not batch.BATCH_TASKS["analyst_brief"]  # opt-in list


def test_unusable_batch_answer_is_metered_but_replayed_live(env):
    llm_batch.submit.run("toy", TENANT, {"items": ["A"]})
    env.batches.state = "ended"
    refusal = _msg("")
    refusal.stop_reason = "refusal"
    env.batches.results_by_id["msgbatch_1"] = [
        SimpleNamespace(custom_id=_cid("A"), result=SimpleNamespace(type="succeeded", message=refusal))
    ]
    llm_batch.poll.run(*env.queued[0])
    assert env.done == [("A", "live:A")] and any(r["meta"].get("batch") for r in env.rows)


def test_lead_outcome_sweep_queues_one_batch_job_per_tenant(env, monkeypatch, db, tenant_and_user):
    from app.workers.tasks import lead_outcome as task_mod

    sent = []
    monkeypatch.setattr(llm_batch.submit, "delay", lambda *a: sent.append(a))
    monkeypatch.setattr(task_mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    out = task_mod.sweep_all_tenants.run()
    assert out["batched_tenants"] >= 1 and (("lead_outcome_sweep", tenant_and_user["tenant"].id, {}) in sent)


def test_lead_outcome_job_keeps_nothing_from_the_collect_pass(env, monkeypatch):
    from app.services import lead_outcome

    calls = []
    fake_db = SimpleNamespace(
        commit=lambda: calls.append("commit"), rollback=lambda: calls.append("rollback"), close=lambda: None
    )
    monkeypatch.setattr(llm_batch, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(llm_batch, "set_tenant_context", lambda db, tid: None)
    monkeypatch.setattr(lead_outcome, "unconfirmed_closed", lambda db, tid: [(SimpleNamespace(id="i1"), "lost")])
    monkeypatch.setattr(lead_outcome, "propose", lambda db, tid, iid, kind: calls.append("propose"))
    llm_batch._lead_outcome_sweep(TENANT, False)
    assert "commit" not in calls and calls.count("propose") == 1
    calls.clear()
    llm_batch._lead_outcome_sweep(TENANT, True)
    assert calls[:2] == ["propose", "commit"]


def test_batch_tasks_are_routed_to_ai_scoring():
    from app.workers.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert routes["llm_batch.submit"] == routes["llm_batch.poll"] == {"queue": "ai_scoring"}
