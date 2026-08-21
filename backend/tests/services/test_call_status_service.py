"""Missed-call classification tests.

The bug this replaces: duration_seconds is populated from Vobiz's
RecordingDuration (recording length), not talk time. A caller who reaches
voicemail and leaves a 53-second message produced duration=53 and read as
"answered" -- the exact call in the bug report, confirmed against the live
transcript ("this person is not available... leave a message after the
tone"). agent_id is NULL on every production call, so it isn't usable as a
signal either.
"""
import pytest

from app.services import call_status_service as css


class _C:
    def __init__(self, direction="inbound", duration=0, human=None, ai=None):
        self.direction = direction
        self.duration_seconds = duration
        self.human_disposition = human
        self.ai_disposition = ai


class _E:
    """Stand-in for a SQLAlchemy enum member, exposing .value like the ORM does."""
    def __init__(self, value):
        self.value = value


# ─── the bug report itself ───────────────────────────────────────────────────

def test_voicemail_with_recording_but_no_disposition_falls_back_to_duration(css_state=None):
    """This is the exact unresolved case: duration=53 (voicemail recording
    length), no disposition (classify/judge chain never completed). Without a
    disposition to lean on there is no reliable signal, so it currently reads
    as answered -- documented as the known limit, not silently "fixed" by
    guessing. The real fix is judge() actually running (call_recovery.py)."""
    call = _C(direction="inbound", duration=53, human=None, ai=None)
    assert css.is_missed_call(call) is False


def test_same_call_becomes_missed_once_disposition_is_known():
    """Once the classify/judge chain actually completes -- which is the real
    fix, call_recovery.py -- the same 53-second voicemail is correctly
    reclassified via its disposition rather than its duration."""
    call = _C(direction="inbound", duration=53, human=None, ai=_E("voicemail"))
    assert css.is_missed_call(call) is True


# ─── disposition wins over duration ──────────────────────────────────────────

def test_no_answer_disposition_is_missed_even_with_nonzero_duration():
    call = _C(direction="inbound", duration=1, ai=_E("no_answer"))
    assert css.is_missed_call(call) is True


def test_answered_disposition_is_not_missed_even_with_zero_duration():
    """A callback logged with duration=0 (recording glitch, short handoff)
    must not be miscounted as missed once we know it was answered."""
    call = _C(direction="inbound", duration=0, ai=_E("callback"))
    assert css.is_missed_call(call) is False


def test_human_disposition_overrides_ai_disposition():
    """An agent's own correction is the ground truth."""
    call = _C(direction="inbound", duration=0, ai=_E("no_answer"), human=_E("quoted"))
    assert css.is_missed_call(call) is False


@pytest.mark.parametrize("disp", ["hot", "quoted", "booked", "lost", "callback"])
def test_every_answered_disposition_is_not_missed(disp):
    assert css.is_missed_call(_C(direction="inbound", duration=0, ai=_E(disp))) is False


@pytest.mark.parametrize("disp", ["no_answer", "voicemail"])
def test_every_not_answered_disposition_is_missed(disp):
    assert css.is_missed_call(_C(direction="inbound", duration=5, ai=_E(disp))) is True


# ─── duration fallback (no disposition at all) ───────────────────────────────

def test_zero_duration_with_no_disposition_is_missed():
    assert css.is_missed_call(_C(direction="inbound", duration=0)) is True


def test_nonzero_duration_with_no_disposition_reads_as_answered():
    """The honest limit: without a disposition, a short-but-real answered
    call and an un-analysed voicemail are indistinguishable from duration
    alone."""
    assert css.is_missed_call(_C(direction="inbound", duration=8)) is False


# ─── outbound is never "missed" ──────────────────────────────────────────────

def test_outbound_is_never_missed_regardless_of_duration_or_disposition():
    assert css.is_missed_call(_C(direction="outbound", duration=0)) is False
    assert css.is_missed_call(_C(direction="outbound", duration=0, ai=_E("no_answer"))) is False


def test_is_answered_call_is_the_inverse_for_inbound():
    inbound_answered = _C(direction="inbound", duration=0, ai=_E("callback"))
    inbound_missed = _C(direction="inbound", duration=0)
    assert css.is_answered_call(inbound_answered) is True
    assert css.is_answered_call(inbound_missed) is False


def test_is_answered_call_is_false_for_outbound():
    """Outbound is never "answered" in the missed-call sense either -- it's
    simply not part of this classification."""
    assert css.is_answered_call(_C(direction="outbound", duration=30)) is False


# ─── enum-vs-string tolerance (direction/disposition may arrive either way) ──

def test_handles_plain_string_direction_and_disposition():
    call = _C(direction="inbound", duration=1)
    call.ai_disposition = "NO_ANSWER"  # some callers store the raw string
    assert css.is_missed_call(call) is True


def test_handles_none_direction_gracefully():
    call = _C(direction=None, duration=0)
    assert css.is_missed_call(call) is False
