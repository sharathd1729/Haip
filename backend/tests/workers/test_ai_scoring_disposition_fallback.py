"""Regression: ai_scoring.py's _map_disposition() used to default any
missing/unrecognized disposition to CallDisposition.CALLBACK -- an
ANSWERED value (call_status_service.py's ANSWERED set). Confirmed live: a
call whose transcript was pure IVR greeting audio with nobody ever
answering got ai_disposition=CALLBACK, so it read as answered rather than
missed. None is the correct default -- it lets is_missed_call() fall
through to the real dial_status/duration signals instead of a wrong,
answered-implying guess."""
from app.models.call import CallDisposition
from app.workers.tasks.ai_scoring import _map_disposition


class TestMapDisposition:
    def test_known_values_map_correctly(self):
        assert _map_disposition("hot") == CallDisposition.HOT
        assert _map_disposition("quoted") == CallDisposition.QUOTED
        assert _map_disposition("booked") == CallDisposition.BOOKED
        assert _map_disposition("lost") == CallDisposition.LOST
        assert _map_disposition("callback") == CallDisposition.CALLBACK
        assert _map_disposition("no_answer") == CallDisposition.NO_ANSWER
        assert _map_disposition("voicemail") == CallDisposition.VOICEMAIL

    def test_case_and_whitespace_insensitive(self):
        assert _map_disposition("  No_Answer  ") == CallDisposition.NO_ANSWER
        assert _map_disposition("CALLBACK") == CallDisposition.CALLBACK

    def test_unrecognized_value_returns_none_not_callback(self):
        assert _map_disposition("unclear") is None
        assert _map_disposition("missed") is None

    def test_empty_string_returns_none_not_callback(self):
        assert _map_disposition("") is None

    def test_none_input_returns_none_not_callback(self):
        assert _map_disposition(None) is None
