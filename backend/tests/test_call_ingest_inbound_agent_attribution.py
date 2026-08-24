"""Regression tests for the Vobiz Dial-callback plan's call_ingest.py change:
agent_id lookup via the click-to-call-agent cache is no longer gated to
outbound-only -- webhooks_vobiz.py's new dial-status webhook now writes to
that same cache for inbound calls too (agent resolved via DialBLegTo), so
ingest_call must attempt the lookup regardless of direction. A miss (no
cache entry -- non-Vobiz provider, or DialBLegTo matched no known agent)
must still resolve to None, unchanged from before."""
import uuid

from sqlalchemy.orm import Session as SASession

from app.adapters.ivr.base import CallWebhookPayload
from app.models.call import Call
from app.workers.tasks import call_ingest
from app.workers.tasks.call_ingest import ingest_call, cache_click_to_call_agent


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


class _FakeAdapter:
    def __init__(self, payload: CallWebhookPayload):
        self._payload = payload

    def parse_call_webhook(self, raw):
        return self._payload


def _run_ingest(monkeypatch, db, tenant_id, payload: CallWebhookPayload):
    monkeypatch.setattr(call_ingest, "get_ivr_adapter", lambda provider: _FakeAdapter(payload))
    monkeypatch.setattr(
        call_ingest.fetch_and_store_recording, "delay",
        lambda **kw: None,
    )
    monkeypatch.setattr(call_ingest, "SessionLocal", lambda: SASession(bind=db.connection()))
    result = ingest_call.run(payload={}, tenant_id=tenant_id, ivr_provider="vobiz")
    return result


def _inbound_payload(ivr_call_id: str, **overrides) -> CallWebhookPayload:
    defaults = dict(
        ivr_call_id=ivr_call_id,
        direction="inbound",
        from_number="+917249066854",
        to_number="+912271264296",
        duration_seconds=42,
        recording_url="https://media.vobiz.ai/rec.mp3",
        agent_number="+919000000000",
        started_at="2026-08-24T10:00:00+00:00",
        ended_at="2026-08-24T10:00:42+00:00",
        provider="vobiz",
        raw={},
        ivr_dial_status="completed",
    )
    defaults.update(overrides)
    return CallWebhookPayload(**defaults)


class TestInboundAgentAttribution:
    def test_inbound_call_sets_agent_id_on_click_to_call_agent_cache_hit(self, db, tenant_and_user, monkeypatch):
        tenant_id = _tenant_id(tenant_and_user)
        call_uuid = f"call-{uuid.uuid4().hex[:8]}"
        agent_id = tenant_and_user["user"]["id"] if isinstance(tenant_and_user["user"], dict) else tenant_and_user["user"].id
        cache_click_to_call_agent(tenant_id, call_uuid, agent_id)

        payload = _inbound_payload(call_uuid)
        result = _run_ingest(monkeypatch, db, tenant_id, payload)

        call = db.query(Call).filter_by(id=result["call_id"]).one()
        assert call.agent_id == agent_id

    def test_inbound_call_agent_id_stays_none_on_cache_miss(self, db, tenant_and_user, monkeypatch):
        tenant_id = _tenant_id(tenant_and_user)
        call_uuid = f"call-{uuid.uuid4().hex[:8]}"  # never cached

        payload = _inbound_payload(call_uuid)
        result = _run_ingest(monkeypatch, db, tenant_id, payload)

        call = db.query(Call).filter_by(id=result["call_id"]).one()
        assert call.agent_id is None

    def test_inbound_call_persists_ivr_dial_status(self, db, tenant_and_user, monkeypatch):
        tenant_id = _tenant_id(tenant_and_user)
        call_uuid = f"call-{uuid.uuid4().hex[:8]}"

        payload = _inbound_payload(call_uuid, ivr_dial_status="no-answer")
        result = _run_ingest(monkeypatch, db, tenant_id, payload)

        call = db.query(Call).filter_by(id=result["call_id"]).one()
        assert call.ivr_dial_status == "no-answer"

    def test_inbound_call_ivr_dial_status_none_when_absent(self, db, tenant_and_user, monkeypatch):
        tenant_id = _tenant_id(tenant_and_user)
        call_uuid = f"call-{uuid.uuid4().hex[:8]}"

        payload = _inbound_payload(call_uuid, ivr_dial_status="")
        result = _run_ingest(monkeypatch, db, tenant_id, payload)

        call = db.query(Call).filter_by(id=result["call_id"]).one()
        assert call.ivr_dial_status is None
