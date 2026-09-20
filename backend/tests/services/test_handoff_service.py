"""Handing a guest over to a phone call or WhatsApp.

The Instagram quick-reply rule covered this for a fixed keyword list, but it
replaced the AI reply instead of adding to it, and the AI itself had no
knowledge of the tenant's number -- so any phrasing the keywords missed
produced an answer with no way to reach anyone.
"""
from types import SimpleNamespace

import pytest

from app.services.handoff_service import (
    append_handoff, build_handoff_block, detect_handoff_intent,
)

PHONE = "+918071581336"
WA = "https://wa.me/message/GJURLNEARL2SE1"


def tenant(phone=PHONE, wa=WA, enabled=True):
    return SimpleNamespace(
        handoff_phone=phone, handoff_whatsapp_url=wa, handoff_enabled=enabled,
    )


# ── detection ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "can you call me",
    "Call me please",
    "can someone ring me",
    "share your contact number",
    "what is your mobile",
    "I want to talk to someone",
    "can we connect on a quick call",
    "please call back",
])
def test_call_requests_are_detected(text):
    """Phrasings the keyword rule missed -- 'ring me', 'connect', 'talk'."""
    assert detect_handoff_intent(text).wants_call


@pytest.mark.parametrize("text", [
    "whatsapp me",
    "can we chat on WhatsApp?",
    "send it on wtsp",
    "lets talk on wa",
])
def test_whatsapp_requests_are_detected(text):
    assert detect_handoff_intent(text).wants_whatsapp


@pytest.mark.parametrize("text", [
    "is food provided?",
    "what amenities are included",
    "Dandeli",
    "how do I book?",
    "",
    None,
])
def test_ordinary_questions_are_not_handoffs(text):
    assert not detect_handoff_intent(text).wanted


@pytest.mark.parametrize("text", [
    "what do you call this caravan",
    "this calls for a celebration",
    "what is it called",
])
def test_incidental_use_of_call_is_not_a_handoff(text):
    """'call' is common in hospitality copy; a false positive staples a phone
    number onto an unrelated reply."""
    assert not detect_handoff_intent(text).wanted


# ── what gets offered ────────────────────────────────────────────────────────

def test_call_request_offers_the_phone_number():
    block = build_handoff_block(tenant(), detect_handoff_intent("please call me"))
    assert PHONE in block
    assert WA not in block  # they asked to be called, not to chat


def test_whatsapp_request_offers_only_the_link():
    block = build_handoff_block(tenant(), detect_handoff_intent("whatsapp me"))
    assert WA in block
    assert PHONE not in block


def test_ambiguous_request_offers_both():
    """'connect with someone' does not say which channel -- guessing wrong
    costs the lead."""
    block = build_handoff_block(tenant(), detect_handoff_intent("can I connect with someone"))
    assert PHONE in block and WA in block


def test_asking_for_an_unconfigured_channel_still_offers_the_other():
    block = build_handoff_block(tenant(wa=None), detect_handoff_intent("whatsapp me"))
    assert PHONE in block


def test_nothing_configured_offers_nothing():
    assert build_handoff_block(tenant(phone=None, wa=None),
                               detect_handoff_intent("call me")) == ""


def test_disabled_tenant_offers_nothing():
    """Details can be staged before the bot is allowed to volunteer them."""
    assert build_handoff_block(tenant(enabled=False),
                               detect_handoff_intent("call me")) == ""


# ── appending to the AI reply ────────────────────────────────────────────────

def test_the_ai_answer_is_kept_and_contact_appended():
    """The whole point: the question still gets answered."""
    reply = "Yes, meals are included on every trip."
    out, intent = append_handoff(reply, tenant(), "is food provided? also can you call me")
    assert reply in out
    assert PHONE in out
    assert intent.wants_call


def test_no_handoff_leaves_the_reply_untouched():
    reply = "Yes, meals are included."
    out, intent = append_handoff(reply, tenant(), "is food provided?")
    assert out == reply
    assert not intent.wanted


def test_details_are_not_duplicated_when_the_model_already_gave_them():
    reply = f"Sure -- reach us on {PHONE}."
    out, _ = append_handoff(reply, tenant(), "call me")
    assert out.count(PHONE) == 1


def test_empty_ai_reply_still_returns_the_contact_block():
    """A blank draft must not swallow the one thing the guest asked for."""
    out, _ = append_handoff("", tenant(), "call me")
    assert PHONE in out
