"""Inbound WhatsApp messages that aren't plain text used to show as blank bubbles."""
import pytest

from app.workers.tasks.whatsapp import _NO_AI_TYPES, _describe_other_message as d


def test_template_quick_reply_button_is_read():
    assert d("button", {"button": {"text": "Book now", "payload": "x"}}) == "Book now"
    assert d("button", {"button": {"payload": "SEE_DATES"}}) == "SEE_DATES"


def test_interactive_button_and_list_replies():
    assert d("interactive", {"interactive": {"button_reply": {"title": "Yes"}}}) == "Yes"
    assert d("interactive", {"interactive": {"list_reply": {"title": "Coorg"}}}) == "Coorg"


def test_reaction_sticker_location_contact():
    assert d("reaction", {"reaction": {"emoji": "👍"}}) == "👍 Reacted to a message"
    assert d("reaction", {"reaction": {}}) == "Removed a reaction"
    assert d("sticker", {}) == "[Sticker]"
    loc = d("location", {"location": {"name": "Home", "latitude": 12.9, "longitude": 77.5}})
    assert "Shared a location: Home" in loc and "12.9" in loc
    assert d("contacts", {"contacts": [{"name": {"formatted_name": "Priya"}}]}) == "👤 Shared a contact: Priya"


def test_unknown_types_are_never_blank():
    assert d("weird", {}).strip() and d("", {}).strip()


@pytest.mark.parametrize("t", ["reaction", "sticker", "unsupported"])
def test_these_do_not_wake_the_ai(t):
    assert t in _NO_AI_TYPES


def test_buttons_do_wake_the_ai():
    assert "button" not in _NO_AI_TYPES and "interactive" not in _NO_AI_TYPES
