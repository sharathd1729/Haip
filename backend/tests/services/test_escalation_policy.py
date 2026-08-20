"""Escalation policy tests.

This is the backstop that has to hold when the model misjudges tone, so
the bar is: no misses on genuine escalations, and no firing on ordinary
pre-booking questions (which would bury agents in false alarms and train
them to ignore the alert).
"""
import pytest

from app.services import escalation_policy as ep


class _T:
    def __init__(self, extra=None):
        self.ai_escalation_keywords = extra


# ─── must escalate ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,category", [
    ("I want a refund now", "refund_billing"),
    ("you double charged me", "refund_billing"),
    ("I will take legal action", "legal"),
    ("my lawyer will contact you", "legal"),
    ("I need to cancel my booking", "cancellation"),
    ("this is unacceptable", "complaint"),
    ("worst experience ever", "complaint"),
    ("this is a scam", "complaint"),
    ("can I speak to a human", "human_request"),
    ("put me through to a manager", "human_request"),
    ("let me talk to your manager", "human_request"),
    ("connect me to a supervisor", "human_request"),
    ("my friend was injured", "safety_medical"),
    ("there was a theft at the property", "safety_medical"),
    ("I will post this on google review", "review_threat"),
])
def test_escalates(text, category):
    hit = ep.detect_escalation(text)
    assert hit is not None, f"MISSED: {text!r}"
    assert hit["category"] == category


# ─── must NOT escalate ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "What is your cancellation policy?",
    "Do you offer free cancellation?",
    "Do you have a manager on site 24/7 for assistance?",
    "Who is the owner of this property?",
    "Is there a first aid kit?",
    "I have an issue understanding the route",
    "What's the check-in time?",
    "Can we get a bonfire?",
    "Is parking free?",
    "We had a great experience last time",
    "Do you have a first floor room?",
])
def test_does_not_escalate_ordinary_questions(text):
    assert ep.detect_escalation(text) is None, f"FALSE POSITIVE: {text!r}"


def test_word_boundaries_prevent_substring_matches():
    """'sue' inside 'issue' and 'fir' inside 'first' must not fire."""
    assert ep.detect_escalation("I have an issue with the wifi") is None
    assert ep.detect_escalation("the first night was lovely") is None


def test_empty_input():
    assert ep.detect_escalation("") is None
    assert ep.detect_escalation(None) is None


# ─── tenant custom keywords ──────────────────────────────────────────────────

def test_tenant_custom_keyword_escalates():
    hit = ep.detect_escalation("the generator is broken again", ["generator"])
    assert hit == {"category": "tenant_custom", "keyword": "generator"}


def test_tenant_keywords_are_additive_not_replacing():
    """Custom keywords must never disable the built-in safety list."""
    tenant = _T(extra=["generator"])
    assert ep.should_escalate("I want a refund", None, tenant) is not None


def test_tenant_keywords_handles_garbage():
    assert ep.tenant_keywords(_T(extra=None)) == []
    assert ep.tenant_keywords(_T(extra="not-a-list")) == []
    assert ep.tenant_keywords(_T(extra=["  ", "ok"])) == ["ok"]


# ─── intent-based escalation ─────────────────────────────────────────────────

def test_complaint_intent_always_escalates_even_with_neutral_words():
    """`complaint` previously fell through to the ordinary reply path with
    no special routing whatsoever."""
    hit = ep.should_escalate("the room was not what we expected", "complaint", _T())
    assert hit == {"category": "intent", "keyword": "complaint"}


def test_benign_intent_does_not_escalate():
    assert ep.should_escalate("what time is check-in", "faq_answer", _T()) is None
