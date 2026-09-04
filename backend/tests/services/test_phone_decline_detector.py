"""Tests for phone_decline_detector.py -- the deterministic keyword match
used to alert an agent when a guest explicitly refuses to share a phone
number, mirroring escalation_policy.py's own test shape."""
from app.services.phone_decline_detector import detect_phone_decline


class TestDetectPhoneDecline:
    def test_matches_the_real_live_message(self):
        # Confirmed live: Neil Moses's exact real Instagram message.
        assert detect_phone_decline("No phone number kindly give me the details") == "no phone number"

    def test_matches_common_variants(self):
        assert detect_phone_decline("Sorry, I don't have a number to share right now") is not None
        assert detect_phone_decline("I would rather not share my number here") is not None
        assert detect_phone_decline("Can't share my number, sorry") is not None

    def test_no_match_on_ordinary_messages(self):
        assert detect_phone_decline("Is the caravan available this weekend?") is None
        assert detect_phone_decline("How much do your services cost?") is None

    def test_no_match_on_generic_phrases_without_phone_context(self):
        """Confirmed live in the same real message as 'no phone number', but
        neither phrase implies a decline on its own -- must not fire alone."""
        assert detect_phone_decline("Kindly give me the details") is None
        assert detect_phone_decline("Can you reply here itself") is None

    def test_empty_and_none_return_none(self):
        assert detect_phone_decline("") is None
        assert detect_phone_decline(None) is None
