"""Lead autopilot deterministic rules (lead_autopilot_rules.py): what each rule decides from real lead data, and when
it must stay quiet."""
from datetime import timedelta

from app.models.call import CallDisposition
from app.services import lead_autopilot_rules as rules
from app.services.lead_autopilot_rules import StageMap, match_decline
from tests.services._autopilot_fixtures import NOW, booking, call, lead, msg, quote, settings, tenant


def _decide(db, t, inq, **over):
    return rules.evaluate(db, t.id, inq, StageMap.load(db, t.id), settings(**over), now=NOW)


class TestStageMap:
    def test_resolves_the_default_taxonomy_by_flags(self, db):
        t, s = tenant(db)
        m = StageMap.load(db, t.id)
        assert (m.won.key, m.lost.key, m.default_entry.key, m.valid_entry.key, m.rnr.key, m.qualified.key) == \
               ("sold", "lost", "unqualified", "general_enquiry", "rnr", "active")


class TestBookingAndDates:
    def test_a_linked_booking_means_sold(self, db):
        t, s = tenant(db)
        g, inq, _ = lead(db, t.id, s["active"])
        stay = booking(db, t.id, g.id, inq.id)
        d = _decide(db, t, inq)
        assert d.to_stage.key == "sold" and d.rule == "booking_exists" and d.evidence[0]["id"] == stay.id

    def test_a_cancelled_booking_does_not_count(self, db):
        t, s = tenant(db)
        g, inq, _ = lead(db, t.id, s["active"])
        booking(db, t.id, g.id, inq.id, status="cancelled")
        assert _decide(db, t, inq) is None

    def test_dates_passed_without_a_booking_is_lost_dates(self, db):
        t, s = tenant(db)
        _, inq, _ = lead(db, t.id, s["active"], check_in="2026-10-12")
        d = _decide(db, t, inq)
        assert d.to_stage.key == "lost" and d.rule == "dates_passed" and d.lost_reason == "dates"

    def test_future_dates_are_not_lost(self, db):
        t, s = tenant(db)
        _, inq, _ = lead(db, t.id, s["active"], check_in="2026-10-24")
        assert _decide(db, t, inq) is None

    def test_a_plain_dm_without_phone_is_never_lost(self, db):
        t, s = tenant(db)
        _, inq, _ = lead(db, t.id, s["unqualified"], phone=False, check_in="2026-10-01")
        assert _decide(db, t, inq) is None


class TestExplicitDecline:
    def test_guest_says_booked_elsewhere(self, db):
        t, s = tenant(db)
        _, inq, conv = lead(db, t.id, s["active"])
        m = msg(db, t.id, conv, "Thanks, we already booked with another caravan company")
        d = _decide(db, t, inq)
        assert d.rule == "explicit_decline" and d.lost_reason == "booked_elsewhere"
        assert d.evidence == [{"kind": "message", "id": m.id, "quote": "Thanks, we already booked with another caravan company"}]

    def test_a_price_objection_is_not_a_decline(self, db):
        t, s = tenant(db)
        _, inq, conv = lead(db, t.id, s["active"])
        msg(db, t.id, conv, "This is too expensive for us")
        assert _decide(db, t, inq) is None

    def test_a_question_keeps_the_conversation_open(self, db):
        assert match_decline("Not interested in the spa, is the caravan free on 24th?") is None
        assert match_decline("We have cancelled the trip") == "other"
        assert match_decline("not interested") == "other"

    def test_a_decline_older_than_the_current_stage_is_ignored(self, db):
        t, s = tenant(db)
        _, inq, conv = lead(db, t.id, s["active"], entered=NOW - timedelta(hours=1))
        msg(db, t.id, conv, "not interested", ago=timedelta(days=2))
        assert _decide(db, t, inq) is None

    def test_team_marked_the_call_lost(self, db):
        t, s = tenant(db)
        g, inq, _ = lead(db, t.id, s["active"])
        c = call(db, t.id, g.id, duration_seconds=180, human_disposition=CallDisposition.LOST, lost_reason="price",
                 disposition_note="Guest found it above budget")
        d = _decide(db, t, inq)
        assert d.rule == "explicit_decline" and d.lost_reason == "price" and d.evidence[0]["id"] == c.id


class TestUnansweredCalls:
    def test_three_unanswered_across_two_days_is_rnr(self, db):
        t, s = tenant(db)
        g, inq, _ = lead(db, t.id, s["general_enquiry"])
        for h in (30, 26, 2):
            call(db, t.id, g.id, ivr_dial_status="no-answer", ago=timedelta(hours=h))
        d = _decide(db, t, inq)
        assert d.to_stage.key == "rnr" and d.rule == "unanswered_calls" and len(d.evidence) == 3

    def test_three_unanswered_on_one_day_is_not_enough(self, db):
        t, s = tenant(db)
        g, inq, _ = lead(db, t.id, s["general_enquiry"])
        for h in (3, 2, 1):
            call(db, t.id, g.id, ivr_dial_status="no-answer", ago=timedelta(hours=h))
        assert _decide(db, t, inq) is None

    def test_a_reply_since_resets_the_streak(self, db):
        t, s = tenant(db)
        g, inq, conv = lead(db, t.id, s["general_enquiry"])
        for h in (30, 26, 3):
            call(db, t.id, g.id, ivr_dial_status="no-answer", ago=timedelta(hours=h))
        msg(db, t.id, conv, "busy now, will call you", ago=timedelta(hours=1))
        assert _decide(db, t, inq) is None

    def test_never_moves_an_active_lead_back_to_rnr(self, db):
        t, s = tenant(db)
        g, inq, _ = lead(db, t.id, s["active"])
        for h in (30, 26, 2):
            call(db, t.id, g.id, ivr_dial_status="no-answer", ago=timedelta(hours=h))
        assert _decide(db, t, inq) is None


class TestSilence:
    def test_quote_sent_and_no_reply(self, db):
        t, s = tenant(db)
        _, inq, conv = lead(db, t.id, s["active"])
        msg(db, t.id, conv, "Please send the price for 4 adults", ago=timedelta(days=10))
        q = quote(db, t.id, inq.id, ago=timedelta(days=8))
        d = _decide(db, t, inq)
        assert d.rule == "quote_no_reply" and d.lost_reason == "no_response" and d.evidence[0]["id"] == q.id

    def test_reply_after_the_quote_keeps_it_open(self, db):
        t, s = tenant(db)
        _, inq, conv = lead(db, t.id, s["active"])
        quote(db, t.id, inq.id, ago=timedelta(days=8))
        msg(db, t.id, conv, "Let me check with family", ago=timedelta(days=1))
        assert _decide(db, t, inq) is None

    def test_no_reply_after_our_follow_ups(self, db):
        t, s = tenant(db)
        _, inq, conv = lead(db, t.id, s["active"])
        msg(db, t.id, conv, "Hi, caravan for Coorg?", ago=timedelta(days=16))
        msg(db, t.id, conv, "Hi Kiran, following up on Coorg", inbound=False, ago=timedelta(days=5))
        d = _decide(db, t, inq)
        assert d.rule == "no_reply" and d.lost_reason == "no_response"

    def test_a_follow_up_sent_yesterday_gets_its_chance(self, db):
        t, s = tenant(db)
        _, inq, conv = lead(db, t.id, s["active"])
        msg(db, t.id, conv, "Hi, caravan for Coorg?", ago=timedelta(days=16))
        msg(db, t.id, conv, "Hi Kiran, following up", inbound=False, ago=timedelta(hours=20))
        assert _decide(db, t, inq) is None


class TestQualified:
    def test_unqualified_with_a_phone_moves_to_the_valid_entry(self, db):
        t, s = tenant(db)
        _, inq, _ = lead(db, t.id, s["unqualified"])
        assert _decide(db, t, inq).to_stage.key == "general_enquiry"

    def test_general_enquiry_with_a_requirement_moves_to_active(self, db):
        t, s = tenant(db)
        _, inq, _ = lead(db, t.id, s["general_enquiry"], check_in="2026-10-24", adults=4, route_mentioned="Bangalore to Coorg")
        d = _decide(db, t, inq)
        assert d.to_stage.key == "active" and d.rule == "qualified" and "dates" in d.reason

    def test_general_enquiry_without_a_requirement_stays(self, db):
        t, s = tenant(db)
        _, inq, _ = lead(db, t.id, s["general_enquiry"])
        assert _decide(db, t, inq) is None


def test_rules_only_read_their_own_tenant(db):
    """A booking/decline in tenant B never moves tenant A's lead, even for the same guest phone."""
    ta, sa = tenant(db)
    tb, sb = tenant(db)
    _, inq_a, _ = lead(db, ta.id, sa["active"])
    gb, inq_b, conv_b = lead(db, tb.id, sb["active"])
    booking(db, tb.id, gb.id, inq_b.id)
    msg(db, tb.id, conv_b, "not interested")
    assert _decide(db, ta, inq_a) is None
