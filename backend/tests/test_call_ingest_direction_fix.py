"""Regression tests for the outbound-call identity bug: call_ingest.py's
_dedup_guest always resolved on normalized.from_number, which for an
outbound click-to-call is the tenant's own IVR/DID number (Vobiz dials FROM
the DID TO the guest), not the lead. That corrupted guest identity (a
"guest" whose phone was literally the tenant's IVR number) and was also
directly why the Calls page showed the IVR number instead of the lead's."""
import uuid

import pytest
from sqlalchemy.orm import Session as SASession

from app.adapters.ivr.base import CallWebhookPayload
from app.models.call import Call
from app.models.guest import Guest
from app.workers.tasks import call_ingest
from app.workers.tasks.call_ingest import ingest_call


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
    dispatched = {}
    monkeypatch.setattr(
        call_ingest.fetch_and_store_recording, "delay",
        lambda **kw: dispatched.update(kw),
    )
    # ingest_call.run() opens its own SessionLocal() -- a brand new engine
    # connection to the same SQLite file the test's `db` fixture already
    # holds an open transaction on, which deadlocks ("database is locked").
    # Bind a throwaway Session to the SAME underlying connection instead, so
    # it joins the fixture's transaction rather than fighting it for a
    # write lock. ingest_call.run() closes this session in its `finally` --
    # that's fine, it's not the fixture's own `db` object.
    monkeypatch.setattr(call_ingest, "SessionLocal", lambda: SASession(bind=db.connection()))
    result = ingest_call.run(payload={}, tenant_id=tenant_id, ivr_provider="vobiz")
    return result, dispatched


class TestOutboundGuestResolution:
    def test_outbound_call_resolves_guest_by_to_number_not_from_number(self, db, tenant_and_user, monkeypatch):
        tenant_id = _tenant_id(tenant_and_user)
        payload = CallWebhookPayload(
            ivr_call_id=f"call-{uuid.uuid4().hex[:8]}",
            direction="outbound",
            from_number="+912271264296",  # tenant's own IVR/DID
            to_number="+917249066854",    # the real lead
            duration_seconds=42,
            recording_url="https://media.vobiz.ai/rec.mp3",
            agent_number="+919000000000",
            started_at="2026-08-05T10:00:00+00:00",
            ended_at="2026-08-05T10:00:42+00:00",
            provider="vobiz",
            raw={},
        )

        result, _ = _run_ingest(monkeypatch, db, tenant_id, payload)

        call = db.query(Call).filter_by(id=result["call_id"]).one()
        guest = db.query(Guest).filter_by(id=call.guest_id).one()
        assert guest.phone == "+917249066854"
        assert guest.phone != "+912271264296"

    def test_inbound_call_still_resolves_guest_by_from_number(self, db, tenant_and_user, monkeypatch):
        tenant_id = _tenant_id(tenant_and_user)
        payload = CallWebhookPayload(
            ivr_call_id=f"call-{uuid.uuid4().hex[:8]}",
            direction="inbound",
            from_number="+917249066854",  # the real lead, calling in
            to_number="+912271264296",    # tenant's own DID
            duration_seconds=15,
            recording_url="https://media.vobiz.ai/rec2.mp3",
            agent_number="+919000000000",
            started_at="2026-08-05T10:00:00+00:00",
            ended_at="2026-08-05T10:00:15+00:00",
            provider="vobiz",
            raw={},
        )

        result, _ = _run_ingest(monkeypatch, db, tenant_id, payload)

        call = db.query(Call).filter_by(id=result["call_id"]).one()
        guest = db.query(Guest).filter_by(id=call.guest_id).one()
        assert guest.phone == "+917249066854"

    def test_outbound_call_below_ai_threshold_skips_transcription(self, db, tenant_and_user, monkeypatch):
        """Sanity check that Call rows get created with the right guest even
        for very short calls -- the AI-skip logic (tested separately) only
        gates the recording-fetch step, not guest resolution."""
        tenant_id = _tenant_id(tenant_and_user)
        payload = CallWebhookPayload(
            ivr_call_id=f"call-{uuid.uuid4().hex[:8]}",
            direction="outbound",
            from_number="+912271264296",
            to_number="+919812345678",
            duration_seconds=2,
            recording_url="https://media.vobiz.ai/rec3.mp3",
            agent_number="+919000000000",
            started_at="2026-08-05T10:00:00+00:00",
            ended_at="2026-08-05T10:00:02+00:00",
            provider="vobiz",
            raw={},
        )

        result, dispatched = _run_ingest(monkeypatch, db, tenant_id, payload)

        call = db.query(Call).filter_by(id=result["call_id"]).one()
        guest = db.query(Guest).filter_by(id=call.guest_id).one()
        assert guest.phone == "+919812345678"
        # fetch_and_store_recording is still queued regardless of duration --
        # the short-call skip happens inside that task, after the recording
        # is already stored (see test_call_short_duration_skips_ai.py).
        assert dispatched.get("call_id") == call.id
