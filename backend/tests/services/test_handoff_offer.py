"""The up-front choice offered on a first reply.

Most leads never say "call me" -- they go quiet instead. Waiting for
explicit intent misses everyone who would have happily phoned, so the first
reply states both routes.
"""
from types import SimpleNamespace

from app.services.handoff_service import append_offer, build_offer_block

PHONE = "+918071581336"
WA = "https://wa.me/message/GJURLNEARL2SE1"


def tenant(phone=PHONE, wa=WA, enabled=True):
    return SimpleNamespace(
        handoff_phone=phone, handoff_whatsapp_url=wa, handoff_enabled=enabled,
    )


def test_offer_names_both_routes():
    block = build_offer_block(tenant())
    assert PHONE in block and WA in block
    # and makes clear chatting on is still fine
    assert "right here" in block.lower() or "here" in block.lower()


def test_offer_is_appended_after_the_answer():
    reply = "Yes, meals are included on every trip."
    out = append_offer(reply, tenant())
    assert out.startswith(reply)
    assert PHONE in out


def test_offer_uses_only_what_is_configured():
    assert WA not in build_offer_block(tenant(wa=None))
    assert PHONE not in build_offer_block(tenant(phone=None))


def test_no_offer_when_nothing_configured():
    assert build_offer_block(tenant(phone=None, wa=None)) == ""
    assert append_offer("Answer.", tenant(phone=None, wa=None)) == "Answer."


def test_no_offer_when_disabled():
    assert build_offer_block(tenant(enabled=False)) == ""


def test_not_duplicated_when_reply_already_has_the_details():
    reply = f"Reach us on {PHONE} any time."
    assert append_offer(reply, tenant()).count(PHONE) == 1


def test_empty_reply_still_yields_the_offer():
    assert PHONE in append_offer("", tenant())
