"""What the concierge searches the knowledge base with (concierge_service.retrieval_query_text)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.concierge_service import _last_question, retrieval_query_text
from tests.test_increment1_defect_specs import _conv, _msg, _tenant

T0 = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)


def _say(db, t, c, minutes, direction, body, **kw):
    _msg(db, t.id, c, direction=direction, body=body, created_at=T0 + timedelta(minutes=minutes), **kw)


def test_a_short_reply_is_searched_with_our_question_in_front(db):
    t = _tenant(db)
    _, c = _conv(db, t.id)
    _say(db, t, c, 0, "inbound", "Hi")
    _say(db, t, c, 1, "outbound", "Hello! Would you like the Coorg route?")
    _say(db, t, c, 2, "inbound", "yes, what's included?")
    q = retrieval_query_text(db, t.id, c.id)
    assert q.startswith("Would you like the Coorg route?") and q.endswith("yes, what's included?")


def test_an_unsent_ai_draft_is_not_our_question(db):
    t = _tenant(db)
    _, c = _conv(db, t.id)
    _say(db, t, c, 0, "outbound", "Want the Coorg route?", is_ai_generated=True, was_approved=None)
    _say(db, t, c, 1, "inbound", "and pets?")
    assert "Coorg" not in retrieval_query_text(db, t.id, c.id)


def test_a_long_question_is_searched_on_its_own(db):
    t = _tenant(db)
    _, c = _conv(db, t.id)
    _say(db, t, c, 0, "outbound", "Would you like the Coorg route?")
    _say(db, t, c, 1, "inbound", "Do you allow pets in the caravan on the Kabini trip")
    assert retrieval_query_text(db, t.id, c.id) == "Do you allow pets in the caravan on the Kabini trip"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Great! Want the Coorg route?", "Want the Coorg route?"),
        ("Sure. How many guests? And which dates?", "And which dates?"),
        ("Our price is fixed. Shall I share the itinerary? Thanks.", "Shall I share the itinerary?"),
        ("Thanks, noted.", ""),
        ("[template] Call back?", ""),
        (None, ""),
    ],
)
def test_last_question(text, expected):
    assert _last_question(text) == expected
