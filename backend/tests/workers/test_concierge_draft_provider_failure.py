"""A provider error while drafting must never crash the task silently.

Real incident (Ratha, Sep 2026): guests on WhatsApp and Instagram got no
reply at all for hours. The completion loop only caught asyncio.TimeoutError
-- any other error from the LLM adapter (auth, quota, an outage) escaped it
uncaught, hit the task's outer except, retried the identical failing call 3
times, then crashed on MaxRetriesExceededError with nothing caught around
it. No draft, no holding reply, no notification -- total silence, for every
guest, on every channel, until whatever broke the provider was fixed.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.workers.tasks.concierge_draft import concierge_draft


def _setup(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant); db.commit()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone="+919876500099", name="Suma")
    db.add(guest); db.commit()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
                        channel=ChannelType.INSTAGRAM, is_open=True, ai_mode="shadow")
    db.add(conv); db.commit()
    inbound = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction="inbound", channel=ChannelType.INSTAGRAM.value,
        body="What are the rates for a luxury caravan stay?",
        channel_message_id=f"ig.{uuid.uuid4().hex}",
    )
    db.add(inbound); db.commit()
    return tenant, guest, conv, inbound


class _BoomLLM:
    """Every call raises a real provider error -- never a timeout."""
    provider = "gemini"

    async def complete(self, **kwargs):
        raise RuntimeError("401 Unauthorized: API key expired")


def _run(db, tenant, conv, inbound):
    with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.workers.tasks.concierge_draft.get_llm", return_value=_BoomLLM()), \
         patch("app.services.push_service.send_to_tenant"), \
         patch("app.workers.tasks.concierge_draft._emit_sse"):
        concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)


def test_a_provider_error_still_produces_a_safe_holding_draft(db):
    tenant, guest, conv, inbound = _setup(db)
    _run(db, tenant, conv, inbound)
    db.expire_all()
    draft = db.query(Message).filter_by(conversation_id=conv.id, direction="outbound").first()
    assert draft is not None, "guest was left with total silence instead of a holding reply"
    assert draft.is_ai_generated and draft.ai_needs_human_reason
    assert "401 Unauthorized" in draft.ai_needs_human_reason or "RuntimeError" in draft.ai_needs_human_reason
    assert "Thanks for your message" in draft.body


def test_the_task_completes_without_raising(db):
    tenant, guest, conv, inbound = _setup(db)
    _run(db, tenant, conv, inbound)   # must not raise MaxRetriesExceededError or anything else


def test_retries_exhausted_on_a_non_llm_error_is_caught_not_crashed(db, caplog):
    """Defense in depth: any other exception that survives to the outer
    handler and exhausts retries must be logged, never left to crash the
    worker process unhandled (same class of bug already fixed once in
    sync_wa_templates.py)."""
    tenant, guest, conv, inbound = _setup(db)
    with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.workers.tasks.concierge_draft.build_concierge_context", side_effect=RuntimeError("db hiccup")):
        concierge_draft.push_request(retries=concierge_draft.max_retries)
        try:
            with patch.object(concierge_draft, "retry", side_effect=__import__(
                "celery.exceptions", fromlist=["MaxRetriesExceededError"]).MaxRetriesExceededError("boom")):
                concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)
        finally:
            concierge_draft.pop_request()
