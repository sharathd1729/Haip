"""A lead's AI summary is prose, never the model's raw field dump.

Bug (Oct 2026, live, Instagram lead): ai_summary was stored as a markdown rendering of the JSON fields
("_accepted`: null ... Requirements:\n`requirements`: [...]") because _parse_summary_response kept any non-JSON reply
verbatim. The task now rejects it, keeps the previous summary, logs the reason and hands the run to the retry path;
scripts/repair_broken_summaries.py finds summaries already stored that fail the same check.
"""
import importlib.util
import json
import os
import uuid
from unittest.mock import patch

import pytest

from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.tenant import Tenant
from app.workers.tasks import generate_ai_summary as gas
from app.workers.tasks.generate_ai_summary import generate_ai_summary

# The shape stored live (guest details replaced), cut where the model stopped.
RAFAUL_STYLE = (
    "_accepted`: null\n\nRequirements:\n`requirements`: [\"Wi-Fi\", \"private lakeside view\"]\n\n"
    "Inferences:\n`inferences`: [\"likely a couple\"]\n\nUnanswered questions:\n`unanswered_questions`: []\n\n"
    "Next best action:\n- `"
)
CLEAN = "Asha wants a lakeside caravan stay for two in November. No budget stated yet. Call her today to confirm dates."

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "repair_broken_summaries.py")
_spec = importlib.util.spec_from_file_location("repair_broken_summaries", _SCRIPT)
repair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repair)


def _setup(db, **inquiry_kw):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Asha", phone="+919800000021")
    db.add(guest)
    db.flush()
    inquiry = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, source=InquirySource.META_IG, **inquiry_kw)
    db.add(inquiry)
    db.commit()
    return tenant.id, inquiry.id


class _Fake:
    def __init__(self, content):
        self.content = content
        self.user_message = None

    def __call__(self, task):
        outer = self

        class _LLM:
            async def complete(self, **kwargs):
                outer.user_message = kwargs["user_message"]
                return {"content": outer.content, "model": "fake"}
        return _LLM()


def _run(db, tenant_id, inquiry_id, fake, expect_retry=False):
    with patch("app.workers.tasks.generate_ai_summary.get_llm", fake), \
         patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db), \
         patch.object(db, "close"), patch.object(db, "rollback"), \
         patch.object(generate_ai_summary, "retry", side_effect=RuntimeError("retry scheduled")) as retry:
        if expect_retry:
            with pytest.raises(RuntimeError, match="retry scheduled"):
                generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=tenant_id)
        else:
            generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=tenant_id)
    db.expire_all()
    return db.query(Inquiry).filter_by(id=inquiry_id).first(), retry


# ─── the check ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,reason", [
    (RAFAUL_STYLE, "backticks"),
    ('{"summary": "x"}', "json"),
    ("Requirements:\nWi-Fi and a lake view for the couple.", "field_labels"),
    ("Guest wants Coorg; upsell_accepted is null for now.", "field_names"),
    ("Guest wants Coorg. Budget: null.", "literal_values"),
    ("Guest wants a lakeside caravan stay for two in November and asked abo", "truncated"),
    ("", "empty"),
    ("   ", "empty"),
])
def test_non_prose_is_rejected(text, reason):
    assert gas.summary_rejection_reason(text) == reason


@pytest.mark.parametrize("text", [
    CLEAN,
    "Kiran wants Coorg 24-25 Oct for 4 adults; price feels high (₹18,000). Follow up tomorrow!",
    'Guest asked "is the caravan pet friendly?"',
])
def test_prose_is_accepted(text):
    assert gas.summary_rejection_reason(text) is None


def test_parser_never_returns_raw_text_as_the_summary():
    assert gas._parse_summary_response(RAFAUL_STYLE)[0] == ""
    assert gas._parse_summary_response(json.dumps({"summary": "", "analysis": {}}))[0] == ""       # was: the raw JSON
    assert gas._parse_summary_response(json.dumps({"summary": RAFAUL_STYLE}))[0] == ""
    assert gas._parse_summary_response(CLEAN)[0] == CLEAN                                          # plain prose still kept


# ─── the task ─────────────────────────────────────────────────────────────────

def test_happy_path_clean_summary_is_saved(db):
    tid, iid = _setup(db)
    inq, retry = _run(db, tid, iid, _Fake(json.dumps({"summary": CLEAN, "analysis": {}, "extracted": {}})))
    assert inq.ai_summary == CLEAN and retry.call_count == 0


def test_rafaul_style_reply_keeps_the_previous_summary_and_retries(db):
    tid, iid = _setup(db, ai_summary=CLEAN, ai_analysis={"intent": "kept"})
    with patch.object(gas.log, "error") as err:
        inq, retry = _run(db, tid, iid, _Fake(RAFAUL_STYLE), expect_retry=True)
    assert inq.ai_summary == CLEAN and inq.ai_analysis == {"intent": "kept"}
    assert retry.call_count == 1 and isinstance(retry.call_args.kwargs["exc"], gas.SummaryRejected)
    event, kw = err.call_args.args[0], err.call_args.kwargs
    assert event == "generate_ai_summary_rejected" and kw["reason"] == "backticks"
    assert "Wi-Fi" not in json.dumps(kw, default=str)                       # never the model's (guest's) text


def test_rafaul_style_reply_on_a_new_lead_leaves_the_summary_empty(db):
    tid, iid = _setup(db)
    inq, _ = _run(db, tid, iid, _Fake(RAFAUL_STYLE), expect_retry=True)
    assert inq.ai_summary is None and inq.ai_analysis is None


def test_a_broken_stored_summary_is_not_fed_back_as_the_previous_summary(db):
    tid, iid = _setup(db, ai_summary=RAFAUL_STYLE)
    fake = _Fake(json.dumps({"summary": CLEAN, "analysis": {}, "extracted": {}}))
    inq, _ = _run(db, tid, iid, fake)
    assert "PREVIOUS SUMMARY" not in fake.user_message and inq.ai_summary == CLEAN


def test_wrong_tenant_is_a_noop(db):
    tid, iid = _setup(db, ai_summary=RAFAUL_STYLE)
    other, _ = _setup(db)
    fake = _Fake(json.dumps({"summary": CLEAN}))
    inq, _ = _run(db, other, iid, fake)
    assert fake.user_message is None and inq.ai_summary == RAFAUL_STYLE


# ─── the repair script ────────────────────────────────────────────────────────

def test_repair_finds_broken_summaries_happy_path(db):
    tid, broken = _setup(db, ai_summary=RAFAUL_STYLE)
    guest_id = db.query(Inquiry).filter_by(id=broken).first().guest_id
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest_id, source=InquirySource.META_IG, ai_summary=CLEAN))
    db.commit()
    assert repair.broken_summaries(db, tid) == [(broken, "backticks")]


def test_repair_is_tenant_scoped(db):
    tid, _ = _setup(db, ai_summary=RAFAUL_STYLE)
    other, _ = _setup(db)
    assert repair.broken_summaries(db, other) == []


def test_repair_requeues_only_on_apply(db):
    tid, broken = _setup(db, ai_summary=RAFAUL_STYLE)
    slug = db.query(Tenant).filter_by(id=tid).first().slug
    with patch.object(repair, "SessionLocal", return_value=db), patch.object(db, "close"), \
         patch("app.workers.tasks.generate_ai_summary.generate_ai_summary.delay") as delay, \
         patch("sys.argv", ["x", "--tenant-slug", slug]):
        assert repair.main() == 0
        assert delay.call_count == 0                                         # dry run by default
        with patch("sys.argv", ["x", "--tenant-slug", slug, "--apply"]):
            assert repair.main() == 0
    delay.assert_called_once_with(inquiry_id=broken, tenant_id=tid)
    assert db.query(Inquiry).filter_by(id=broken).first().ai_summary == RAFAUL_STYLE   # the script writes nothing
