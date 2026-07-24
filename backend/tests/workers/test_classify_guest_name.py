"""
Tests for classify.py's guest-name detection: extracting a spoken name
from the call transcript (via the same classify LLM call, no new task)
and backfilling it onto the Guest record -- replacing the "Unknown Guest"
placeholder left by calls whose only signal is a phone number.
"""
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.call import Call, CallDirection
from app.models.transcript import Transcript
from app.workers.tasks.classify import classify


def _base_classification(**overrides):
    base = {
        "sentiment": "positive", "intent": "booking_inquiry", "language": "en",
        "is_code_mixed": False, "themes": [], "confidence": 0.9,
        "occasion": "", "budget_signal": "", "decision_stage": "", "competitor_mentioned": "",
        "conversion_probability": 50, "lost_reason": "", "guest_name": "",
    }
    base.update(overrides)
    return base


def _setup(db, guest_name="Unknown Guest"):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant); db.commit()

    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone="+919876543210", name=guest_name)
    db.add(guest); db.commit()

    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
        ivr_provider="mcube", ivr_call_id=str(uuid.uuid4()),
        direction=CallDirection.INBOUND, from_number="+919876543210", to_number="+911234567890",
    )
    db.add(call); db.commit()

    transcript = Transcript(
        id=str(uuid.uuid4()), tenant_id=tenant.id, call_id=call.id,
        provider="sarvam", language="en",
        turns=json.dumps([{"speaker": "guest", "t0": 0.0, "t1": 2.0, "text": "Hi this is Priya calling"}]),
        raw_text="Hi this is Priya calling",
    )
    db.add(transcript); db.commit()

    return tenant, guest, call


def test_detected_name_backfills_unnamed_guest(db, monkeypatch):
    tenant, guest, call = _setup(db, guest_name="Unknown Guest")
    guest_id, tenant_id, call_id = guest.id, tenant.id, call.id

    class _FakeLLM:
        async def complete(self, **kwargs):
            return {"tool_use": _base_classification(guest_name="Priya")}

    monkeypatch.setattr("app.workers.tasks.classify.get_llm", lambda task: _FakeLLM())
    monkeypatch.setattr("app.workers.tasks.judge.judge.delay", MagicMock())

    with patch("app.workers.tasks.classify.SessionLocal", return_value=db):
        classify(call_id=call_id, tenant_id=tenant_id)

    refreshed = db.query(Guest).filter_by(id=guest_id).first()
    assert refreshed.name == "Priya"


def test_detected_name_does_not_overwrite_real_name(db, monkeypatch):
    tenant, guest, call = _setup(db, guest_name="Vishwas Rao")
    guest_id, tenant_id, call_id = guest.id, tenant.id, call.id

    class _FakeLLM:
        async def complete(self, **kwargs):
            return {"tool_use": _base_classification(guest_name="SomeoneElse")}

    monkeypatch.setattr("app.workers.tasks.classify.get_llm", lambda task: _FakeLLM())
    monkeypatch.setattr("app.workers.tasks.judge.judge.delay", MagicMock())

    with patch("app.workers.tasks.classify.SessionLocal", return_value=db):
        classify(call_id=call_id, tenant_id=tenant_id)

    refreshed = db.query(Guest).filter_by(id=guest_id).first()
    assert refreshed.name == "Vishwas Rao"


def test_empty_guest_name_leaves_placeholder_untouched(db, monkeypatch):
    tenant, guest, call = _setup(db, guest_name="Unknown Guest")
    guest_id, tenant_id, call_id = guest.id, tenant.id, call.id

    class _FakeLLM:
        async def complete(self, **kwargs):
            return {"tool_use": _base_classification(guest_name="")}

    monkeypatch.setattr("app.workers.tasks.classify.get_llm", lambda task: _FakeLLM())
    monkeypatch.setattr("app.workers.tasks.judge.judge.delay", MagicMock())

    with patch("app.workers.tasks.classify.SessionLocal", return_value=db):
        classify(call_id=call_id, tenant_id=tenant_id)

    refreshed = db.query(Guest).filter_by(id=guest_id).first()
    assert refreshed.name == "Unknown Guest"


@pytest.mark.parametrize("bogus", ["Unknown", "unknown", "N/A", "None", "Unidentified"])
def test_non_name_placeholder_values_are_rejected(db, monkeypatch, bogus):
    """Regression: the model echoing a transcript phrase like 'caller
    unknown' produced Guest.name == 'Unknown' in production -- distinct
    from our own 'Unknown Guest' placeholder, so the basic guard didn't
    catch it."""
    tenant, guest, call = _setup(db, guest_name="Unknown Guest")
    guest_id, tenant_id, call_id = guest.id, tenant.id, call.id

    class _FakeLLM:
        async def complete(self, **kwargs):
            return {"tool_use": _base_classification(guest_name=bogus)}

    monkeypatch.setattr("app.workers.tasks.classify.get_llm", lambda task: _FakeLLM())
    monkeypatch.setattr("app.workers.tasks.judge.judge.delay", MagicMock())

    with patch("app.workers.tasks.classify.SessionLocal", return_value=db):
        classify(call_id=call_id, tenant_id=tenant_id)

    refreshed = db.query(Guest).filter_by(id=guest_id).first()
    assert refreshed.name == "Unknown Guest"
