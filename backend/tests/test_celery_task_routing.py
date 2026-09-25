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


def test_every_registered_task_routes_to_a_consumed_queue(celery_app_instance):
    app = celery_app_instance
    unrouted = []

    for task_name in sorted(app.tasks.keys()):
        if task_name.startswith(_CELERY_INTERNAL_PREFIXES):
            continue
        route = app.amqp.router.route({}, task_name)
        queue = route.get("queue")
        queue_name = queue.name if hasattr(queue, "name") else queue
        if queue_name not in _CONSUMED_QUEUES:
            unrouted.append((task_name, queue_name))

    assert not unrouted, (
        f"{len(unrouted)} task(s) route to a queue no worker consumes -- "
        f"they will silently never run: {unrouted}"
    )


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
