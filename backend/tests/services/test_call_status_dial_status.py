"""Tests for the ivr_dial_status priority added to call_status_service
(Vobiz Dial-callback plan): a real answered/no-answer signal from the
provider should override the duration-based guess, which the greeting/
voicemail audio inflates for every call regardless of whether an agent
answered.
"""
from types import SimpleNamespace

from app.models.call import CallDirection
from app.services import call_status_service


def _call(**overrides):
    defaults = dict(
        direction=CallDirection.INBOUND,
        human_disposition=None,
        ai_disposition=None,
        ivr_dial_status=None,
        duration_seconds=45,  # nonzero -- would read "answered" under the old duration-only fallback
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestDialStatusPriority:
    def test_no_answer_dial_status_overrides_nonzero_duration(self):
        call = _call(ivr_dial_status="no-answer", duration_seconds=45)
        assert call_status_service.is_missed_call(call) is True

    def test_timeout_dial_status_is_missed(self):
        assert call_status_service.is_missed_call(_call(ivr_dial_status="timeout")) is True

    def test_completed_dial_status_is_not_missed_even_with_zero_duration(self):
        # A real edge case this fixes: greeting-only duration could be
        # nonzero OR zero depending on exactly when the call dropped --
        # the real provider signal should win either way.
        call = _call(ivr_dial_status="completed", duration_seconds=0)
        assert call_status_service.is_missed_call(call) is False

    def test_human_disposition_still_wins_over_dial_status(self):
        """A human's explicit review of this call is the strongest signal
        that exists -- must not be overridden by the provider's raw
        Dial-leg outcome."""
        call = _call(human_disposition="booked", ivr_dial_status="no-answer")
        assert call_status_service.is_missed_call(call) is False

    def test_no_dial_status_falls_back_to_existing_logic_unchanged(self):
        """NULL ivr_dial_status (every non-Vobiz call, and any Vobiz call
        this signal never reached) must behave exactly as before --
        duration==0 fallback when nothing else is set."""
        assert call_status_service.is_missed_call(_call(duration_seconds=0)) is True
        assert call_status_service.is_missed_call(_call(duration_seconds=45)) is False

    def test_unrecognized_dial_status_value_falls_through_safely(self):
        """An unexpected/future Vobiz DialStatus value must not crash or
        be silently misread as either outcome -- falls through to the
        existing duration logic, same as no signal at all."""
        call = _call(ivr_dial_status="some-new-status-vobiz-adds-later", duration_seconds=0)
        assert call_status_service.is_missed_call(call) is True  # via duration fallback, not a crash


class TestMissedCallSqlFilterMatchesPython:
    """missed_call_sql_filter() must agree with is_missed_call() for the
    same inputs -- the two are required to stay in sync per the module's
    own docstring."""

    def test_dial_status_filter_matches_python_version(self, db):
        import uuid
        from app.models.tenant import Tenant
        from app.models.call import Call

        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant); db.commit()

        answered = Call(
            id=str(uuid.uuid4()), tenant_id=tenant.id, ivr_provider="vobiz",
            ivr_call_id=str(uuid.uuid4()), direction=CallDirection.INBOUND,
            from_number="+919000000001", to_number="+919000000002",
            duration_seconds=0, ivr_dial_status="completed",
        )
        missed = Call(
            id=str(uuid.uuid4()), tenant_id=tenant.id, ivr_provider="vobiz",
            ivr_call_id=str(uuid.uuid4()), direction=CallDirection.INBOUND,
            from_number="+919000000001", to_number="+919000000002",
            duration_seconds=30, ivr_dial_status="no-answer",
        )
        db.add(answered); db.add(missed); db.commit()

        missed_ids = {
            c.id for c in db.query(Call)
            .filter(Call.tenant_id == tenant.id, call_status_service.missed_call_sql_filter())
            .all()
        }
        assert answered.id not in missed_ids
        assert missed.id in missed_ids
        assert call_status_service.is_missed_call(answered) is False
        assert call_status_service.is_missed_call(missed) is True


class TestOutboundCompletedButNoAnswer:
    """Ratha, 20 Oct 2026: Vobiz reported 9 of 20 outbound calls "completed" (voicemail / carrier announcement counts as
    media) while the AI heard nobody, so the "we tried calling" WhatsApp (playbook P2) never went out."""

    def test_ai_no_answer_beats_a_completed_outbound_leg(self):
        call = _call(direction=CallDirection.OUTBOUND, ivr_dial_status="completed", ai_disposition="no_answer", duration_seconds=24)
        assert call_status_service.is_unanswered_outbound(call) is True

    def test_voicemail_counts_too(self):
        call = _call(direction=CallDirection.OUTBOUND, ivr_dial_status="completed", ai_disposition="voicemail")
        assert call_status_service.is_unanswered_outbound(call) is True

    def test_a_person_saying_it_was_answered_still_wins(self):
        call = _call(direction=CallDirection.OUTBOUND, ivr_dial_status="completed", ai_disposition="no_answer",
                     human_disposition="callback")
        assert call_status_service.is_unanswered_outbound(call) is False

    def test_completed_with_a_real_conversation_stays_answered(self):
        call = _call(direction=CallDirection.OUTBOUND, ivr_dial_status="completed", ai_disposition="callback", duration_seconds=58)
        assert call_status_service.is_unanswered_outbound(call) is False

    def test_completed_before_the_ai_has_run_is_answered_for_now(self):
        call = _call(direction=CallDirection.OUTBOUND, ivr_dial_status="completed", ai_disposition=None, duration_seconds=27)
        assert call_status_service.is_unanswered_outbound(call) is False

    def test_inbound_keeps_the_shared_rule(self):
        call = _call(direction=CallDirection.INBOUND, ivr_dial_status="completed", ai_disposition="no_answer")
        assert call_status_service.is_missed_call(call) is False
