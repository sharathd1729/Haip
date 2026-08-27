"""
generate_ai_summary v3: structured trip-fact extraction.

Root cause this closes: nothing in the codebase ever parsed a guest's
free-text WhatsApp/Instagram message ("4 guests, Nov 20th, from Shirdi")
into Inquiry.adults/check_in/occasion/etc -- only manual staff entry,
Dograh voice-call events, and Hostaway/RentalWise sync wrote those columns.
So a lead's Trip Details card (Leads360 + Inbox GuestPanel) and profile-
completeness checklist stayed empty/red for organically-arriving chat
leads even when the guest had already stated everything in plain text.

generate_ai_summary already runs an LLM over the full conversation for
every inquiry -- this reuses that same call to also emit a strict,
literal "extracted" object, applied to the Inquiry only where the column
is still empty (manual/Dograh/PMS data always wins over a chat-text guess).
"""
import json
import uuid
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.workers.tasks.generate_ai_summary import generate_ai_summary


def _setup(db, **inquiry_overrides):
    """Returns plain id strings, not ORM objects -- the task under test
    closes `db` (expunging its identity map) partway through every test,
    so any ORM instance handed back here would be left detached+expired
    by the time a test could use it."""
    tenant_id = str(uuid.uuid4())
    tenant = Tenant(id=tenant_id, name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant); db.commit()

    guest_id = str(uuid.uuid4())
    guest = Guest(id=guest_id, tenant_id=tenant_id, name="Chitra", phone="+15308440648")
    db.add(guest); db.commit()

    inquiry_id = str(uuid.uuid4())
    inquiry = Inquiry(
        id=inquiry_id, tenant_id=tenant_id, guest_id=guest_id,
        source=InquirySource.WA_DIRECT,
        **inquiry_overrides,
    )
    db.add(inquiry); db.commit()
    return tenant_id, inquiry_id


def _fake_adapter(extracted: dict, summary="Guest wants a caravan trip.", analysis=None):
    payload = {"summary": summary, "analysis": analysis or {}, "extracted": extracted}

    class _Fake:
        async def complete(self, **kwargs):
            return {"content": json.dumps(payload), "model": "test-model"}
    return _Fake()


def _run(db, tenant_id, inquiry_id, adapter):
    # generate_ai_summary re-queries this same row by id and mutates that
    # (identity-map-shared) instance, then closes `db` in its own finally
    # block -- so any pre-existing Python reference to the row is left
    # detached AND expired afterward. Pass plain id strings in (never an
    # ORM attribute touched post-run) and re-query fresh at the end.
    with patch("app.workers.tasks.generate_ai_summary.get_llm", return_value=adapter), \
         patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db):
        generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=tenant_id)
    return db.query(Inquiry).filter_by(id=inquiry_id).first()


class TestExtractionFillsEmptyFields:
    def test_explicit_trip_facts_get_written_to_empty_columns(self, db):
        tenant_id, inquiry_id = _setup(db)
        adapter = _fake_adapter({
            "check_in": "2026-11-20", "check_out": None,
            "adults": 4, "children": None,
            "occasion": "family trip", "budget": 25000,
            "special_requests": "vegetarian meals only",
        })
        updated = _run(db, tenant_id, inquiry_id, adapter)

        assert updated.check_in == "2026-11-20"
        assert updated.check_out is None
        assert updated.adults == 4
        assert updated.occasion == "family trip"
        assert float(updated.budget) == 25000
        assert updated.special_requests == "vegetarian meals only"


class TestExtractionNeverOverwritesExistingData:
    def test_manually_entered_adults_survives_a_conflicting_extraction(self, db):
        # Staff already corrected the guest count to 6 (e.g. after a phone
        # call) -- a chat-text extraction guessing 4 must not clobber it.
        tenant_id, inquiry_id = _setup(db, adults=6, occasion="anniversary")
        adapter = _fake_adapter({
            "check_in": None, "check_out": None,
            "adults": 4, "children": None,
            "occasion": "family trip", "budget": None,
            "special_requests": None,
        })
        updated = _run(db, tenant_id, inquiry_id, adapter)

        assert updated.adults == 6
        assert updated.occasion == "anniversary"


class TestExtractionRejectsMalformedValues:
    def test_non_iso_date_is_not_written(self, db):
        tenant_id, inquiry_id = _setup(db)
        adapter = _fake_adapter({
            "check_in": "next week", "check_out": None,
            "adults": None, "children": None,
            "occasion": None, "budget": None, "special_requests": None,
        })
        updated = _run(db, tenant_id, inquiry_id, adapter)

        assert updated.check_in is None

    def test_missing_extracted_block_does_not_crash_and_summary_still_saves(self, db):
        tenant_id, inquiry_id = _setup(db)

        class _NoExtractAdapter:
            async def complete(self, **kwargs):
                return {"content": json.dumps({"summary": "Guest asked about pricing.", "analysis": {}}), "model": "test"}

        updated = _run(db, tenant_id, inquiry_id, _NoExtractAdapter())

        assert updated.ai_summary == "Guest asked about pricing."
        assert updated.adults is None


class TestTenantIsolation:
    def test_wrong_tenant_id_is_a_noop(self, db):
        tenant_id, inquiry_id = _setup(db)
        other_tenant_id = str(uuid.uuid4())
        adapter = _fake_adapter({
            "check_in": "2026-11-20", "check_out": None,
            "adults": 4, "children": None,
            "occasion": "family trip", "budget": None, "special_requests": None,
        })
        with patch("app.workers.tasks.generate_ai_summary.get_llm", return_value=adapter), \
             patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db):
            generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=other_tenant_id)
        reloaded = db.query(Inquiry).filter_by(id=inquiry_id).first()

        assert reloaded.adults is None
        assert reloaded.ai_summary is None
