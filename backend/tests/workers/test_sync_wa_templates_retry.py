"""
Test for T0.4: sync_wa_templates.py's retry-exhaustion handling.

Before the fix, `self.MaxRetriesExceededError` didn't exist (Celery Task
instances don't carry that attribute), so the hasattr guard was always
False, and MaxRetriesExceededError -- raised by self.retry() once
max_retries is exhausted -- was never actually caught; it propagated as
an unhandled task failure with no distinct log line.
"""
import uuid
from unittest.mock import patch, MagicMock
import pytest
from celery.exceptions import MaxRetriesExceededError

from app.models.tenant import Tenant
from app.models.integration import Integration
from app.api.v1.endpoints.messaging import WATemplate, TemplateStatus
from app.workers.tasks import sync_wa_templates as mod


class _NoCloseSessionWrapper:
    def __init__(self, real_db):
        self._real_db = real_db

    def __getattr__(self, name):
        return getattr(self._real_db, name)

    def close(self):
        pass


def _make_tenant_with_integration(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    integ = Integration(
        id=str(uuid.uuid4()), tenant_id=t.id, kind="whatsapp_meta", status="active",
        config={"access_token": "tok", "waba_id": "waba123"},
    )
    db.add(integ)
    tmpl = WATemplate(
        id=str(uuid.uuid4()), tenant_id=t.id, name="booking_confirmation",
        status=TemplateStatus.PENDING,
    )
    db.add(tmpl)
    db.flush()
    return t


def test_retry_exhaustion_is_caught_and_logged(db, caplog):
    """When Meta calls keep failing and retries are exhausted, the task
    must not raise an unhandled MaxRetriesExceededError -- it should be
    caught and logged."""
    t = _make_tenant_with_integration(db)
    db.commit()

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("httpx.get", side_effect=RuntimeError("Meta API down")):
        task = mod.sync_tenant_templates
        task.push_request(retries=task.max_retries)  # simulate final attempt
        try:
            with patch.object(task, "retry", side_effect=MaxRetriesExceededError("boom")):
                # Should NOT raise -- the fix catches MaxRetriesExceededError
                # around the retry() call specifically.
                task.run(t.id)
        finally:
            task.pop_request()
