"""Regressions carried over from the old classify / wrap-up tasks into tasks.analyze_call (one model call per call):
guest-name backfill, the is_code_mixed string trap, the Vobiz no-agent-speech attribution check, and the
disposition fallback (a missing/unknown disposition is None, never CALLBACK). The model is scripted, never real."""

import uuid

import pytest

from app.models.call import Call, CallDirection, CallDisposition
from app.models.guest import Guest
from app.models.task import Task
from app.services.call_analysis import coerce_bool
from tests.workers import call_analysis_harness as h


def _setup(db, guest_name="Unknown Guest"):
    t = h.tenant(db)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=t.id, phone="+919876543210", name=guest_name)
    db.add(guest)
    db.commit()
    c = h.call(
        db,
        t.id,
        guest_id=guest.id,
        turns=[{"speaker": "guest", "t0": 0.0, "t1": 2.0, "text": "Hi this is Priya calling"}],
    )
    return t, guest, c


def _analyse(db, t, c, **answer):
    h.run(db, t.id, c.id, h.ScriptedLLM(h.answer(**answer)))
    return db.get(Call, c.id)


# ── guest name (was classify) ───────────────────────────────────────────────────────────────────────────────────────


def test_detected_name_backfills_unnamed_guest(db):
    t, guest, c = _setup(db)
    _analyse(db, t, c, guest_name="Priya")
    assert db.get(Guest, guest.id).name == "Priya"


def test_detected_name_does_not_overwrite_real_name(db):
    t, guest, c = _setup(db, guest_name="Vishwas Rao")
    _analyse(db, t, c, guest_name="SomeoneElse")
    assert db.get(Guest, guest.id).name == "Vishwas Rao"


@pytest.mark.parametrize("bogus", ["", "Unknown", "unknown", "N/A", "None", "Unidentified"])
def test_empty_or_placeholder_names_leave_the_guest_alone(db, bogus):
    """A model echoing 'caller unknown' once produced Guest.name == 'Unknown' in production."""
    t, guest, c = _setup(db)
    _analyse(db, t, c, guest_name=bogus)
    assert db.get(Guest, guest.id).name == "Unknown Guest"


# ── is_code_mixed as a string ───────────────────────────────────────────────────────────────────────────────────────


class TestCoerceBool:
    """SQLAlchemy's Boolean raises on "false" (a string); bool("false") is True. Seen live under a former model."""

    def test_values(self):
        assert coerce_bool(True) is True and coerce_bool(False) is False
        assert coerce_bool("false") is False and coerce_bool("FALSE") is False
        assert coerce_bool("true") is True and coerce_bool("True") is True
        assert coerce_bool(None, default=True) is True and coerce_bool("maybe", default=False) is False


def test_stringified_is_code_mixed_does_not_crash_the_analysis(db):
    t, _, c = _setup(db)
    assert _analyse(db, t, c, is_code_mixed="false").is_code_mixed is False


# ── Vobiz "completed" with no agent speech ──────────────────────────────────────────────────────────────────────────


class TestVobizDialAttributionCorrection:
    """An inbound call attributed via Vobiz's DialStatus "completed" can be only the greeting + hold music; the
    attribution is cleared when the diarized transcript has no agent speech. Outbound is never touched."""

    def _setup(self, db, turns, direction=CallDirection.INBOUND):
        from app.core.security import get_password_hash
        from app.models.user import User, UserRole

        t = h.tenant(db)
        agent = User(
            id=str(uuid.uuid4()),
            tenant_id=t.id,
            name="Agent",
            email=f"a-{uuid.uuid4().hex[:6]}@test.com",
            hashed_password=get_password_hash("testpassword123"),
            role=UserRole.CONCIERGE,
            is_active=True,
        )
        db.add(agent)
        db.commit()
        c = h.call(db, t.id, agent_id=agent.id, ivr_dial_status="completed", direction=direction, turns=turns)
        return t, agent, c

    GREETING = [
        {"speaker": "unknown", "t0": 0.0, "t1": 5.0, "text": "Namaskara and welcome to Ratha Retreats..."},
        {"speaker": "unknown", "t0": 5.0, "t1": 30.0, "text": "Music"},
    ]

    def test_no_agent_speech_clears_bogus_attribution(self, db):
        t, _, c = self._setup(db, self.GREETING)
        assert _analyse(db, t, c).agent_id is None

    def test_real_agent_speech_keeps_attribution(self, db):
        t, agent, c = self._setup(db, h.SPEECH)
        assert _analyse(db, t, c).agent_id == agent.id

    def test_outbound_call_attribution_never_touched(self, db):
        t, agent, c = self._setup(db, self.GREETING[:1], direction=CallDirection.OUTBOUND)
        assert _analyse(db, t, c).agent_id == agent.id


# ── disposition fallback (was wrap-up) ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "given, expected",
    [
        ("no_answer", CallDisposition.NO_ANSWER),
        ("  Quoted  ", CallDisposition.QUOTED),  # case and spaces normalised
        ("missed", None),  # not a real disposition: None, never CALLBACK
        (None, None),  # missing: a nobody-answered call once read as "callback"
    ],
)
def test_disposition_mapping_never_defaults_to_callback(db, given, expected):
    t, _, c = _setup(db)
    assert _analyse(db, t, c, suggested_disposition=given).ai_disposition == expected


def test_an_old_shaped_answer_without_the_actionable_block_still_works(db):
    t, _, c = _setup(db)
    answer = {
        k: v
        for k, v in h.answer(suggested_disposition="callback", next_action="Call back tomorrow").items()
        if k not in ("outcome", "agent_strengths", "agent_growth_areas")
    }
    h.run(db, t.id, c.id, h.ScriptedLLM(answer))
    c = db.get(Call, c.id)
    assert c.ai_insights is None and c.ai_next_action == "Call back tomorrow"


def test_no_callback_task_without_a_guest_or_for_another_disposition(db):
    t = h.tenant(db)
    c1 = h.call(db, t.id)  # no guest
    h.run(db, t.id, c1.id, h.ScriptedLLM(h.answer(suggested_disposition="callback")))
    _, guest, c2 = _setup(db)
    h.run(db, c2.tenant_id, c2.id, h.ScriptedLLM(h.answer(suggested_disposition="booked")))
    assert db.query(Task).filter(Task.tenant_id.in_([t.id, c2.tenant_id])).count() == 0
