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
from app.workers.tasks.classify import classify, _coerce_bool


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


class TestCoerceBool:
    """Regression: classify.py's Call.is_code_mixed is a SQLAlchemy
    Boolean column, but meta/llama-3.1-8b-instruct (quick_classify's
    model -- CLAUDE.md's own routing table already documents its weak
    tool-calling) frequently returns the JSON string "true"/"false"
    instead of a real boolean. SQLAlchemy's Boolean type raises TypeError
    on any non-bool value rather than guessing -- confirmed live in
    production: every classify run that hit this crashed, retried 3x,
    then died, meaning judge/wrap_up (and the call's disposition) never
    ran at all. Plain bool(value) is NOT a safe fix -- bool("false") is
    True in Python, the same trap SQLAlchemy itself refuses to take."""

    def test_real_bool_passes_through(self):
        assert _coerce_bool(True) is True
        assert _coerce_bool(False) is False

    def test_string_false_coerces_to_false_not_true(self):
        assert _coerce_bool("false") is False
        assert _coerce_bool("False") is False
        assert _coerce_bool("FALSE") is False

    def test_string_true_coerces_to_true(self):
        assert _coerce_bool("true") is True
        assert _coerce_bool("True") is True

    def test_missing_value_uses_default(self):
        assert _coerce_bool(None, default=False) is False
        assert _coerce_bool(None, default=True) is True

    def test_garbage_string_uses_default(self):
        assert _coerce_bool("maybe", default=False) is False


def test_stringified_is_code_mixed_does_not_crash_classify(db, monkeypatch):
    """End-to-end: the exact live failure mode -- is_code_mixed comes back
    as the string "false", classify() must not raise, and the column must
    end up with the real boolean, not the raw string."""
    tenant, guest, call = _setup(db, guest_name="Unknown Guest")
    guest_id, tenant_id, call_id = guest.id, tenant.id, call.id

    class _FakeLLM:
        async def complete(self, **kwargs):
            return {"tool_use": _base_classification(is_code_mixed="false")}

    monkeypatch.setattr("app.workers.tasks.classify.get_llm", lambda task: _FakeLLM())
    monkeypatch.setattr("app.workers.tasks.judge.judge.delay", MagicMock())

    with patch("app.workers.tasks.classify.SessionLocal", return_value=db):
        classify(call_id=call_id, tenant_id=tenant_id)  # must not raise

    refreshed = db.query(Call).filter_by(id=call_id).first()
    assert refreshed.is_code_mixed is False


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
