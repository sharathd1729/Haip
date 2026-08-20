"""Price-disclosure policy tests.

The business rule is absolute: the AI concierge never quotes pricing in
chat. These tests are the regression net for that -- a false negative in
detect_price() is a rate reaching a guest unreviewed.
"""
import pytest

from app.services import price_policy as pp


# ─── detect_price: must catch ────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "It is ₹12,000 per night",
    "₹8500",
    "Rs 8500 for two nights",
    "Rs.7500",
    "INR 15000 total",
    "around 12k per night",
    "starts at 8000 per night",
    "the total is 24000",
    "15,000/night for the caravan",
    "costs about 9000",
    "20000/- for the stay",
    "per night 12000",
    "10% discount for you",
    "we can offer a discount of 2000",
    "the price is 5000",
    "$450 a night",
])
def test_detect_price_catches(text):
    assert pp.detect_price(text) is not None, f"LEAK: {text!r} not detected"


# ─── detect_price: must NOT fire ─────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Yes, those dates are available!",
    "We have free WiFi and AC.",
    "Check-in is at 2 PM, check-out by 11 AM.",
    "Could you share your travel dates?",
    "We can host up to 4 guests.",
    "Our team will call you shortly to go through the options.",
    "Bangalore to Coorg is 265 km, about 6 hours.",
    "There are 3 caravans at that location.",
    "Pets are welcome, no extra charge.",
    "How many of you are travelling?",
])
def test_detect_price_allows_legitimate_replies(text):
    assert pp.detect_price(text) is None, f"FALSE POSITIVE: {text!r}"


def test_detect_price_handles_empty():
    assert pp.detect_price("") is None
    assert pp.detect_price(None) is None


# ─── redact_price_facts ──────────────────────────────────────────────────────

def test_redact_strips_money_keeps_availability():
    facts = [{
        "tool": "check_availability",
        "result": [{"property_name": "Caravan A", "available": True,
                    "price_per_night": 12000, "nights": 2}],
    }]
    out = pp.redact_price_facts(facts)
    row = out[0]["result"][0]
    assert row["price_per_night"] == "[withheld]"
    # Availability is the useful half and must survive.
    assert row["available"] is True
    assert row["nights"] == 2
    assert row["property_name"] == "Caravan A"


def test_redact_is_recursive_and_total_free():
    facts = [{"tool": "get_quote", "result": {"subtotal": 100, "gst": 18, "total": 118,
                                              "nested": {"advance_amount": 50}}}]
    out = pp.redact_price_facts(facts)
    import json
    blob = json.dumps(out)
    for leaked in ("100", "118", "50"):
        assert leaked not in blob, f"{leaked} survived redaction"


def test_redact_handles_empty():
    assert pp.redact_price_facts([]) == []
    assert pp.redact_price_facts(None) == []


# ─── lead qualification ──────────────────────────────────────────────────────

class _G:
    def __init__(self, name=None):
        self.name, self.id = name, "g1"


class _I:
    def __init__(self, ci=None, co=None, adults=None, prop=None, occasion=None):
        self.check_in, self.check_out = ci, co
        self.adults, self.property_id, self.occasion = adults, prop, occasion
        self.notes, self.id = None, "i1"


def test_missing_details_lists_everything_when_nothing_known():
    missing = pp.missing_lead_details(_G(), _I())
    assert len(missing) == 5


def test_placeholder_names_count_as_missing():
    """Auto-created guests are often named from a handle, not by the person."""
    for placeholder in ("Instagram User", "guest", "Unknown"):
        assert "their name" in pp.missing_lead_details(_G(placeholder), _I())


def test_real_name_is_not_missing():
    assert "their name" not in pp.missing_lead_details(_G("Arjun Sharma"), _I())


def test_is_qualified_requires_core_fields():
    assert pp.is_qualified(_G("Arjun"), _I()) is False
    full = _I(ci="2026-09-01", co="2026-09-03", adults=2, prop="p1")
    assert pp.is_qualified(_G("Arjun"), full) is True


def test_special_requests_do_not_block_qualification():
    """Waiting for a guest to volunteer an occasion would stall handoffs."""
    full = _I(ci="2026-09-01", co="2026-09-03", adults=2, prop="p1")
    assert pp.is_qualified(_G("Arjun"), full) is True
    assert "any special requests or occasion" in pp.missing_lead_details(_G("Arjun"), full)
