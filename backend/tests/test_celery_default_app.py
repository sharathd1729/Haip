"""A @shared_task queued from a request handler must use the configured broker.

FastAPI runs sync endpoints in a thread pool and Celery's current app is thread-local, so before celery_app.set_default()
every @shared_task resolved to Celery's fallback app in those threads (broker None -> amqp://localhost) and .delay()
was refused. This checks the binding from a fresh thread, the way a request handler sees it.
"""
import threading

from app.core.config import settings


def _broker_seen_from_a_thread(task) -> str:
    seen = {}
    t = threading.Thread(target=lambda: seen.setdefault("broker", task.app.conf.broker_url))
    t.start()
    t.join()
    return seen["broker"]


def test_shared_tasks_use_the_configured_broker_in_worker_threads():
    import app.workers.celery_app  # noqa: F401  -- what the API imports at startup
    from app.workers.tasks.marketing_studio import generate_content, generate_image
    from app.workers.tasks.module_activation import activate

    for task in (generate_image, generate_content, activate):
        assert _broker_seen_from_a_thread(task) == settings.REDIS_URL, task.name
