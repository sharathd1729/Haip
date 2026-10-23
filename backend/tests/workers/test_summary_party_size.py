"""A stated group total lands in adults when no children make up the difference (leads360-summary-v9).

Bug (Oct 2026, live WhatsApp lead): the guest said they were a group of 4 including her 84-year-old father; the AI summary
said 4 guests but Inquiry.adults stayed 1. The model filled "adults" with the one person it could name (or the speaker, or
the "Adults: 1" context line) and nothing checked it against the headcount. v9 asks for the total as
extracted.party_size and generate_ai_summary._adults_with_party_size raises adults to it.
"""
import json
import uuid
from unittest.mock import patch

import pytest

from app.core.prompt_versions import get_version
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.tenant import Tenant
from app.workers.tasks import generate_ai_summary as gas
from app.workers.tasks.generate_ai_summary import generate_ai_summary


@pytest.mark.parametrize("adults,children,party,stored_children,expected", [
    (1, None, 4, None, 4),       # the live bug: "4 of us incl. my father" read as adults=1
    (None, None, 4, None, 4),    # "4 of us", no adult figure at all
    (None, 1, 4, None, 3),       # "4 of us, one is a child"
    (3, 1, 4, None, 3),          # already consistent: unchanged
    (2, None, 4, 2, 2),          # children on file from an earlier message make up the rest
    (5, None, 4, None, 5),       # more adults than the total: the specific figure is kept
    (2, None, None, None, 2),    # no total stated: unchanged
    (None, None, None, None, None),
    (1, None, True, None, 1),    # a boolean is never a count
    (1, None, 400, None, 1),     # absurd total ignored
    (None, 4, 4, None, None),    # all children: no adults to imply
])
def test_adults_with_party_size(adults, children, party, stored_children, expected):
    assert gas._adults_with_party_size(adults, children, party, stored_children) == expected


def test_prompt_asks_for_the_total_and_is_versioned():
    assert '"party_size"' in gas.SYSTEM_PROMPT and "party_size" in gas._EXTRACTED_KEYS
    assert "never put 1 in \"adults\" for the person writing" in gas.SYSTEM_PROMPT
    assert get_version("leads360_summary") == "leads360-summary-v10"


def _setup(db, **inquiry_kw):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Monika", phone="+919800000031")
    db.add(guest)
    db.flush()
    inquiry = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, source=InquirySource.WA_DIRECT, **inquiry_kw)
    db.add(inquiry)
    db.commit()
    return tenant.id, inquiry.id


def _run(db, tenant_id, inquiry_id, extracted):
    payload = {"summary": "A group of 4 incl. an elderly parent wants a caravan trip. No budget yet. Call to confirm dates.",
               "analysis": {}, "extracted": extracted}
    calls = []

    class _LLM:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            return {"content": json.dumps(payload), "model": "fake"}

    with patch("app.workers.tasks.generate_ai_summary.get_llm", lambda task: _LLM()), \
         patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db), patch.object(db, "close"):
        generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=tenant_id)
    db.expire_all()
    return db.query(Inquiry).filter_by(id=inquiry_id).first(), calls


def test_four_of_us_sets_adults_to_four(db):
    tid, iid = _setup(db)
    inq, _ = _run(db, tid, iid, {"adults": 1, "children": None, "party_size": 4})
    assert inq.adults == 4 and inq.children is None


def test_a_stored_adults_1_is_corrected_by_the_stated_total(db):
    tid, iid = _setup(db, adults=1)
    inq, _ = _run(db, tid, iid, {"adults": None, "children": None, "party_size": 4})
    assert inq.adults == 4


def test_a_stated_child_is_kept_out_of_adults(db):
    tid, iid = _setup(db)
    inq, _ = _run(db, tid, iid, {"adults": None, "children": 1, "party_size": 4})
    assert (inq.adults, inq.children) == (3, 1)


def test_without_a_total_the_old_behaviour_is_unchanged(db):
    tid, iid = _setup(db)
    inq, _ = _run(db, tid, iid, {"adults": 2, "children": None})
    assert inq.adults == 2


def test_wrong_tenant_is_a_noop(db):
    tid, iid = _setup(db, adults=1)
    other, _ = _setup(db)
    inq, calls = _run(db, other, iid, {"adults": None, "party_size": 4})
    assert calls == [] and inq.adults == 1
