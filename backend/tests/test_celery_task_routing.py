"""
Regression test for the celery_app.py task-routing bug found in
production (July 2026): tasks registered with a short name (e.g.
name="tasks.send_whatsapp") instead of the full dotted module path don't
match the "app.workers.tasks.X.*" glob patterns in task_routes, silently
fall through to Celery's implicit default "celery" queue, and never run
since the worker's --queues flag doesn't include it. ~9800 tasks were
found stuck in that unconsumed queue in production before this was found
and fixed.

This test enumerates every task actually registered on the Celery app
(after importing every module in the `include` list) and asserts each one
resolves, via Celery's real router, to one of the queues this codebase's
worker actually consumes.
"""
import pytest

# Every queue name the production worker is configured to consume
# (docker-compose.prod.yml's `--queues=` flag). "celery" (Colery's
# built-in default) is deliberately NOT in this set -- that's the queue
# this test exists to make sure nothing silently falls into.
_CONSUMED_QUEUES = {"transcription", "ai_scoring", "whatsapp", "call_ingest", "default"}

# Celery's own housekeeping/internal task names, not app tasks -- excluded
# since they're never expected to be routed by this app's task_routes.
_CELERY_INTERNAL_PREFIXES = ("celery.",)


@pytest.fixture(scope="module")
def celery_app_instance():
    from app.workers.celery_app import celery_app
    return celery_app


def _import_every_task_module():
    """Register every task in the codebase, not just the ones other tests happened to import.

    The sweep below used to depend on which modules the rest of the suite had loaded, so it
    passed when run alone and failed in the full run -- the failure was real (tasks that never
    run in production), it just only showed up sometimes.
    """
    import importlib
    import pkgutil

    import app.workers.tasks as tasks_pkg

    for mod in pkgutil.iter_modules(tasks_pkg.__path__):
        importlib.import_module(f"app.workers.tasks.{mod.name}")


def _queue_of(app, task_name):
    queue = app.amqp.router.route({}, task_name).get("queue")
    return queue.name if hasattr(queue, "name") else queue


# Registered tasks that currently route to the unconsumed "celery" queue. Each is a production bug
# found by the Phase 0 audit (docs/HAIP_Phase0_Failure_Register.md). They are listed so that the
# guard stays strict for everything else; the test also fails when an entry is fixed, so the list
# can only shrink. Do not add to it -- route the new task instead.
_KNOWN_UNROUTED = {
    # Scheduled nightly by beat ("classify-intent-nightly") but unrouted, so it never runs.
    # Routing it starts an LLM job that has never run in production -- needs an owner decision.
    "app.workers.tasks.classify_intent.run",
}


def test_every_registered_task_routes_to_a_consumed_queue(celery_app_instance):
    _import_every_task_module()
    app = celery_app_instance
    unrouted = {}

    for task_name in sorted(app.tasks.keys()):
        if task_name.startswith(_CELERY_INTERNAL_PREFIXES):
            continue
        queue_name = _queue_of(app, task_name)
        if queue_name not in _CONSUMED_QUEUES:
            unrouted[task_name] = queue_name

    new = set(unrouted) - _KNOWN_UNROUTED
    assert not new, (
        f"{len(new)} task(s) route to a queue no worker consumes -- "
        f"they will silently never run: {sorted((n, unrouted[n]) for n in new)}"
    )
    fixed = _KNOWN_UNROUTED - set(unrouted)
    assert not fixed, f"now routed -- remove from _KNOWN_UNROUTED: {sorted(fixed)}"


# Beat entries whose task name is not a registered task. The worker discards these with
# "Received unregistered task", so the job never runs. Each maps to the name it is registered
# under. Fixing the beat entry activates the job in production, which for most of these changes
# data (purges), sends messages (owner digest) or writes PMS rows -- so it needs an explicit
# decision, not a drive-by edit. The test fails if an entry is fixed (shrink this dict) or if a
# new broken entry appears.
_KNOWN_DEAD_BEAT = {
    "app.workers.tasks.lost_reason_cluster.run": "lost_reason_cluster.nightly",
    "app.workers.tasks.dpdp_purge.run": "tasks.dpdp_purge",
    "app.workers.tasks.retention_purge.nightly_purge": "retention.nightly_purge",
    "app.workers.tasks.meta_quality_poll.poll_all_tenants": "meta_quality.poll_all_tenants",
    "app.workers.tasks.sync_all_pms.sync_retalwise_all_tenants": "sync_retalwise_all_tenants",
    "app.workers.tasks.sync_all_pms.sync_hostaway_all_tenants": "sync_hostaway_all_tenants",
    "app.workers.tasks.owner_digest.orchestrate": "owner_digest.orchestrate",
}


def test_beat_schedule_names_are_registered_tasks(celery_app_instance):
    _import_every_task_module()
    app = celery_app_instance
    dead = {entry["task"] for entry in app.conf.beat_schedule.values() if entry["task"] not in app.tasks}

    assert dead - set(_KNOWN_DEAD_BEAT) == set(), (
        f"beat schedules task names that are not registered (they will never run): "
        f"{sorted(dead - set(_KNOWN_DEAD_BEAT))}"
    )
    assert set(_KNOWN_DEAD_BEAT) - dead == set(), (
        f"fixed -- remove from _KNOWN_DEAD_BEAT: {sorted(set(_KNOWN_DEAD_BEAT) - dead)}"
    )
    for beat_name, real_name in _KNOWN_DEAD_BEAT.items():
        assert real_name in app.tasks, f"{beat_name} should be {real_name}, which is not registered either"


def test_scheduled_registered_tasks_land_on_a_consumed_queue(celery_app_instance):
    """Every beat entry that does name a real task must reach a queue the worker consumes."""
    _import_every_task_module()
    app = celery_app_instance
    stuck = sorted(
        (entry["task"], _queue_of(app, entry["task"]))
        for entry in app.conf.beat_schedule.values()
        if entry["task"] in app.tasks and _queue_of(app, entry["task"]) not in _CONSUMED_QUEUES
    )
    assert {name for name, _ in stuck} <= _KNOWN_UNROUTED, f"scheduled but unconsumed: {stuck}"


def test_inbox_rewrite_tasks_land_on_a_consumed_queue(celery_app_instance):
    """The inbox 'rewrite' buttons enqueue these on every click; they sat unconsumed until routed."""
    import app.workers.tasks.composer_rewrite  # noqa: F401
    import app.workers.tasks.rewrite_draft  # noqa: F401

    for name in ("tasks.rewrite_draft", "tasks.composer_rewrite"):
        assert name in celery_app_instance.tasks
        assert _queue_of(celery_app_instance, name) == "whatsapp"


def test_lead_assignment_tick_lands_on_a_consumed_queue(celery_app_instance):
    """The 5-minute automatic-assignment tick shipped with no queue route, so it
    fell through to the unconsumed "celery" queue and never ran in production.
    Unlike the sweep above, this imports the task itself first, so it gives the
    same answer whatever other tests have already loaded."""
    import app.workers.tasks.lead_assignment  # noqa: F401  (registers the task)

    app = celery_app_instance
    assert app.conf.beat_schedule["lead-assignment-5min"]["task"] == "lead_assignment.tick"
    assert "lead_assignment.tick" in app.tasks
    queue = app.amqp.router.route({}, "lead_assignment.tick").get("queue")
    queue_name = queue.name if hasattr(queue, "name") else queue
    assert queue_name in _CONSUMED_QUEUES, f"lead_assignment.tick routes to {queue_name!r}"
