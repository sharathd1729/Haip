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
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
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


def _fake_adapter(extracted: dict, summary="Guest wants a caravan trip.", analysis=None, lead_analysis=None):
    payload = {"summary": summary, "analysis": analysis or {}, "extracted": extracted}
    if lead_analysis is not None:
        payload["lead_analysis"] = lead_analysis

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


class TestExtractionAcceptsStringTypedNumbers:
    """Real bug confirmed live: NVIDIA's nemotron models frequently emit a
    numeric extracted field as a JSON string ("4" instead of 4) despite the
    prompt specifying an integer -- a plain isinstance(x, (int, float))
    check then silently drops a value the model got right. A guest who
    explicitly said "4 guests, Nov 20th" got the correct free-text
    next_action but adults/budget stayed null in the DB and the Trip
    Details card never rendered."""

    def test_string_typed_adults_children_budget_are_still_written(self, db):
        tenant_id, inquiry_id = _setup(db)
        adapter = _fake_adapter({
            "check_in": None, "check_out": None,
            "adults": "4", "children": "0",
            "occasion": None, "budget": "25,000", "special_requests": None,
        })
        updated = _run(db, tenant_id, inquiry_id, adapter)

        assert updated.adults == 4
        assert updated.children == 0
        assert float(updated.budget) == 25000

    def test_boolean_is_never_treated_as_a_count(self, db):
        # bool is a subclass of int in Python -- True/False must never slip
        # through as adults=1/adults=0.
        tenant_id, inquiry_id = _setup(db)
        adapter = _fake_adapter({
            "check_in": None, "check_out": None,
            "adults": True, "children": None,
            "occasion": None, "budget": None, "special_requests": None,
        })
        updated = _run(db, tenant_id, inquiry_id, adapter)

        assert updated.adults is None

    def test_non_numeric_string_is_rejected(self, db):
        tenant_id, inquiry_id = _setup(db)
        adapter = _fake_adapter({
            "check_in": None, "check_out": None,
            "adults": "a few", "children": None,
            "occasion": None, "budget": None, "special_requests": None,
        })
        updated = _run(db, tenant_id, inquiry_id, adapter)

        assert updated.adults is None


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


class TestV4LeadReportFields:
    """Detailed per-lead report (migration 093): route_mentioned,
    quoted_amount (a real write path -- the column existed but nothing
    ever wrote it, confirmed via grep), upsell_offered/accepted, and a
    synthesized ai_lead_analysis paragraph, distinct from ai_summary."""

    def test_route_quoted_amount_and_upsell_are_written(self, db):
        tenant_id, inquiry_id = _setup(db)
        adapter = _fake_adapter(
            {
                "check_in": None, "check_out": None, "adults": None, "children": None,
                "occasion": None, "budget": None, "special_requests": None,
                "route_mentioned": "Shirdi to Mumbai", "quoted_amount": 42000,
                "upsell_offered": "Sunset photography add-on", "upsell_accepted": True,
            },
            lead_analysis="Fast-moving, high-intent guest who accepted the upsell without hesitation.",
        )
        updated = _run(db, tenant_id, inquiry_id, adapter)

        assert updated.route_mentioned == "Shirdi to Mumbai"
        assert float(updated.quoted_amount) == 42000
        assert updated.quoted_at is not None
        assert updated.upsell_offered == "Sunset photography add-on"
        assert updated.upsell_accepted is True
        assert "accepted the upsell" in updated.ai_lead_analysis

    def test_quoted_amount_never_overwrites_an_existing_quote(self, db):
        tenant_id, inquiry_id = _setup(db, quoted_amount=25000, quoted_at="2026-08-01T00:00:00+00:00")
        adapter = _fake_adapter({
            "check_in": None, "check_out": None, "adults": None, "children": None,
            "occasion": None, "budget": None, "special_requests": None,
            "route_mentioned": None, "quoted_amount": 99999,
            "upsell_offered": None, "upsell_accepted": None,
        })
        updated = _run(db, tenant_id, inquiry_id, adapter)

        assert float(updated.quoted_amount) == 25000
        assert updated.quoted_at == "2026-08-01T00:00:00+00:00"

    def test_upsell_accepted_can_fill_in_on_a_later_run_once_offered(self, db):
        """upsell_accepted's empty sentinel is None (not offered / not yet
        answered) -- unlike the write-once fields above, this is allowed to
        go from None to a real False once the guest actually answers an
        offer already on record."""
        tenant_id, inquiry_id = _setup(db, upsell_offered="Sunset photography add-on")
        adapter = _fake_adapter({
            "check_in": None, "check_out": None, "adults": None, "children": None,
            "occasion": None, "budget": None, "special_requests": None,
            "route_mentioned": None, "quoted_amount": None,
            "upsell_offered": "Sunset photography add-on", "upsell_accepted": False,
        })
        updated = _run(db, tenant_id, inquiry_id, adapter)

        assert updated.upsell_accepted is False

class TestReferenceDateAnchoring:
    """v6: a year-less date ("sept 16-18") has no anchor to resolve the year
    against on its own -- confirmed live, the same guest's message came back
    as 2026 on one extraction run and 2023 on the next. The context now
    carries a "Reference date" line so the model has something to resolve
    against, anchored to the most recent INBOUND message's own timestamp --
    never wall-clock "now" (this task can run days after the guest actually
    spoke, e.g. via the debounce catch-up path), which would wrongly roll an
    already-passed date into the following year."""

    def _capturing_adapter(self):
        captured = {}

        class _Capturing:
            async def complete(self, **kwargs):
                captured.update(kwargs)
                return {
                    "content": json.dumps({
                        "summary": "Guest wants a caravan trip.",
                        "analysis": {},
                        "extracted": {
                            "check_in": None, "check_out": None, "adults": None, "children": None,
                            "occasion": None, "budget": None, "special_requests": None,
                        },
                    }),
                    "model": "test-model",
                }
        return _Capturing(), captured

    def _add_message(self, db, tenant_id, conv_id, guest_id, direction, body, created_at):
        db.add(Message(
            id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv_id,
            direction=direction, channel=ChannelType.WHATSAPP,
            body=body, created_at=created_at,
        ))
        db.commit()

    def test_reference_date_anchored_to_latest_inbound_message_not_wall_clock_now(self, db):
        tenant_id, inquiry_id = _setup(db)
        tenant_row = db.query(Tenant).filter_by(id=tenant_id).first()
        guest_id = db.query(Guest).filter_by(tenant_id=tenant_id).first().id

        conv = Conversation(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
            inquiry_id=inquiry_id, channel=ChannelType.WHATSAPP, is_open=True,
        )
        db.add(conv); db.commit()

        # The guest spoke a full year ago (simulates this task running long
        # after the message, e.g. a delayed catch-up run) -- the reference
        # date must reflect when they actually spoke, not today.
        spoken_at = datetime.now(timezone.utc) - timedelta(days=365)
        self._add_message(db, tenant_id, conv.id, guest_id, MessageDirection.INBOUND, "sept 16-18, 5 guests", spoken_at)

        adapter, captured = self._capturing_adapter()
        with patch("app.workers.tasks.generate_ai_summary.get_llm", return_value=adapter), \
             patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db):
            generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=tenant_id)

        assert f"Reference date (when this conversation was last active): {spoken_at.date().isoformat()}" in captured["user_message"]
        # And explicitly NOT today's wall-clock date.
        assert datetime.now(timezone.utc).date().isoformat() not in captured["user_message"].split("\n")[0]

    def test_reference_date_ignores_outbound_only_messages(self, db):
        """An outbound-only message (e.g. staff follow-up with no guest
        reply yet) must not become the anchor -- only what the guest
        themselves said establishes when "sept 16-18" was spoken."""
        tenant_id, inquiry_id = _setup(db)
        guest_id = db.query(Guest).filter_by(tenant_id=tenant_id).first().id

        conv = Conversation(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
            inquiry_id=inquiry_id, channel=ChannelType.WHATSAPP, is_open=True,
        )
        db.add(conv); db.commit()

        inbound_at = datetime.now(timezone.utc) - timedelta(days=10)
        outbound_at = datetime.now(timezone.utc)  # a later staff message
        self._add_message(db, tenant_id, conv.id, guest_id, MessageDirection.INBOUND, "sept 16-18", inbound_at)
        self._add_message(db, tenant_id, conv.id, guest_id, MessageDirection.OUTBOUND, "Calling you shortly", outbound_at)

        adapter, captured = self._capturing_adapter()
        with patch("app.workers.tasks.generate_ai_summary.get_llm", return_value=adapter), \
             patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db):
            generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=tenant_id)

        assert f"Reference date (when this conversation was last active): {inbound_at.date().isoformat()}" in captured["user_message"]

    def test_reference_date_falls_back_to_inquiry_created_at_when_no_messages(self, db):
        tenant_id, inquiry_id = _setup(db)
        # Captured as a plain value before run() -- the task closes `db` in
        # its own finally block, leaving any pre-existing ORM reference
        # detached+expired afterward (see this file's _run() docstring).
        created_at_date = db.query(Inquiry).filter_by(id=inquiry_id).first().created_at.date().isoformat()

        adapter, captured = self._capturing_adapter()
        with patch("app.workers.tasks.generate_ai_summary.get_llm", return_value=adapter), \
             patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db):
            generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=tenant_id)

        assert f"Reference date (when this conversation was last active): {created_at_date}" in captured["user_message"]


class TestV4LeadReportGracefulDegradation:
    def test_missing_lead_analysis_key_does_not_crash(self, db):
        """Older-shaped responses (or a model that omits the new field)
        must still save the rest of the summary."""
        tenant_id, inquiry_id = _setup(db)
        adapter = _fake_adapter({
            "check_in": None, "check_out": None, "adults": None, "children": None,
            "occasion": None, "budget": None, "special_requests": None,
            "route_mentioned": None, "quoted_amount": None,
            "upsell_offered": None, "upsell_accepted": None,
        })
        updated = _run(db, tenant_id, inquiry_id, adapter)

        assert updated.ai_summary == "Guest wants a caravan trip."
        assert updated.ai_lead_analysis is None
