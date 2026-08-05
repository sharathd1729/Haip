"""Regression test for HAIP Inbox full-parity pass, ticket 1: Mcube's
_normalize_phone double-prefixed a number that was already
country-code-prefixed but missing "+" (e.g. "917816999444" -> the old code
produced "+91917816999444" instead of "+917816999444"), which never matched
the guest's correctly-formatted signal from other channels -- every call
from such a number created a fresh Guest instead of merging into the real
thread."""
from app.adapters.ivr.mcube import McubeAdapter


class TestNormalizePhone:
    def setup_method(self):
        self.adapter = McubeAdapter()

    def test_already_e164_passes_through(self):
        assert self.adapter._normalize_phone("+917816999444") == "+917816999444"

    def test_local_ten_digit_gets_country_code_prefixed(self):
        assert self.adapter._normalize_phone("7816999444") == "+917816999444"

    def test_country_code_prefixed_without_plus_is_not_double_prefixed(self):
        assert self.adapter._normalize_phone("917816999444") == "+917816999444"

    def test_leading_zero_stripped_before_prefixing(self):
        assert self.adapter._normalize_phone("07816999444") == "+917816999444"

    def test_empty_string_returns_empty(self):
        assert self.adapter._normalize_phone("") == ""

    def test_strips_spaces_and_dashes(self):
        assert self.adapter._normalize_phone("78169-99444") == "+917816999444"
