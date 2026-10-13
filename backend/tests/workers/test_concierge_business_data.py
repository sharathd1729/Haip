"""The real concierge task, with Ratha's structured business data published: what the model is shown, and what it may say.

Only the language model is scripted (so the exact prompt can be read); records, pricing, availability, guards and the draft are real.
Pinned here (docs/ai/RATHA_KB_EVOLUTION.md acceptance list):
  * published package / route / itinerary data reaches the reply; drafts and rejected versions never do;
  * a published price change reaches the next reply with no knowledge re-index, and the old figure is then blocked;
  * handoff mode never shows the model a price; grounded mode shows only the quote for this stay;
  * a quote that cannot be given (over capacity, no rate, unavailable) leaves the model with no figure to repeat.
"""
from decimal import Decimal
from unittest.mock import patch

from app.services import business_data_service as bds
from tests.test_business_data import coorg, package
from tests.workers.test_concierge_operational_data import (
    CHECK_IN, CHECK_OUT, TODAY, Scripted, _avail, _conversation, _property, _run, _tenant,
)

# Everything is dated relative to today (tenant calendar) so the rate window always covers the test stay.
WINDOW = {"label": "Standard", "valid_from": TODAY.isoformat(), "valid_to": f"{TODAY.year + 2}-12-31", "unit": "night"}


def _publish(db, t, kind, key, data):
    d = bds.create_draft(db, t.id, kind, key, data, None)
    return bds.publish(db, t.id, d.id, None)


def _setup(db, mode="grounded", amount="18000"):
    t = _tenant(db, mode="autonomous", price_disclosure=mode if mode == "grounded" else None)
    prop = _property(db, t, name="Caravan A", max_adults=4)
    _publish(db, t, "destination", "coorg", coorg())
    _publish(db, t, "package", "coorg-signature", package(destination_keys=["coorg"], rates=[{**WINDOW, "amount": amount}]))
    return t, prop


def _ask(db, t, text="What would a Coorg trip cost for 2 nights?", reply="Our team will confirm.", **extra):
    _, conv, (msg,) = _conversation(db, t, text)
    llm = Scripted(_avail({"intent": "price_quote", "destination": "Coorg", **extra}),
                   reply={"reply": reply, "confidence": 0.95, "citations": [], "needs_human": False})
    drafts, _ = _run(db, t, conv, msg, llm)
    return llm, drafts


def test_published_package_and_route_reach_the_model_but_no_price_in_handoff_mode(db):
    t, _ = _setup(db, mode="handoff")
    llm, drafts = _ask(db, t, text="What is included in the Coorg trip and how long is the drive?")
    p = llm.system_prompt
    assert "PACKAGES, ROUTES AND POLICIES" in p and 'Package "Signature Caravan - Coorg"' in p and "Caravan with driver" in p
    assert "Madikeri (overnight)" in p and "250" in p
    assert "40320" not in p and "36000" not in p and "18000" not in p and "PRICING RULE" in p
    assert float(drafts[0].ai_confidence) == 0.95


def test_grounded_mode_shows_the_quote_for_this_stay_and_a_price_change_reaches_the_next_reply_without_reindexing(db):
    t, _ = _setup(db)
    ok = "For those 2 nights the total comes to Rs 40,320 including GST."
    llm, drafts = _ask(db, t, reply=ok)
    assert 'Package quote "Signature Caravan - Coorg"' in llm.system_prompt and "total 40320.00 INR" in llm.system_prompt
    assert float(drafts[0].ai_confidence) == 0.95 and not drafts[0].ai_needs_human_reason

    with patch("app.workers.tasks.embed_knowledge.embed_entry.delay", side_effect=AssertionError("no re-index")):
        _publish(db, t, "package", "coorg-signature", package(destination_keys=["coorg"], rates=[{**WINDOW, "amount": "21000"}]))
        llm2, drafts2 = _ask(db, t, reply="For those 2 nights the total comes to Rs 47,040 including GST.")
    assert "total 47040.00 INR" in llm2.system_prompt and "40320" not in llm2.system_prompt
    assert float(drafts2[0].ai_confidence) == 0.95

    _, stale = _ask(db, t, reply=ok)                                       # the replaced figure is no longer supported by any fact
    assert float(stale[0].ai_confidence) == 0.0 and "not present in grounded_facts" in stale[0].ai_needs_human_reason


def test_a_draft_or_rejected_change_never_reaches_the_model(db):
    t, _ = _setup(db)
    bds.create_draft(db, t.id, "package", "coorg-signature", package(name="Unreviewed Name", destination_keys=["coorg"], rates=[{**WINDOW, "amount": "99999"}]), None)
    rej = bds.create_draft(db, t.id, "destination", "goa", coorg() | {"name": "Gokarna"}, None)
    bds.reject(db, t.id, rej.id, None, "no")
    llm, _ = _ask(db, t)
    p = llm.system_prompt
    for needle in ("Unreviewed Name", "99999", "Gokarna"):
        assert needle not in p, p[max(0, p.index(needle) - 150): p.index(needle) + 100]
    assert "total 40320.00 INR" in llm.system_prompt


def test_a_quote_that_cannot_be_given_leaves_the_model_no_figure_to_repeat(db):
    t, _ = _setup(db)
    llm, drafts = _ask(db, t, text="Price for 9 of us?", reply="It will be Rs 40,320.", adults=9)
    p = llm.system_prompt
    assert "Package quote not possible" in p and "40320" not in p and "do NOT state any price" in p
    assert float(drafts[0].ai_confidence) == 0.0                           # the invented figure is blocked


def test_nothing_published_means_the_prompt_is_unchanged_and_the_team_confirms(db):
    t = _tenant(db, mode="autonomous", price_disclosure="grounded")
    _property(db, t)
    llm, _ = _ask(db, t)
    assert "PACKAGES, ROUTES AND POLICIES" not in llm.system_prompt and "Package quote" not in llm.system_prompt
