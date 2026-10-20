"""lead_priority: the My day order (option B, owner pick 20 Oct 2026). A guest who asked for a call back, a missed call and a
fresh detailed enquiry close to its travel date come first; a lead silent for days, with no details or whose trip is over,
goes to "Chase when free". Severity (the SLA clock behind alerts) is not changed."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import lead_priority as lp

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 20)


def _item(kind, minutes=None, title="Kiran", severity="fresh", attempts=0, inquiry_id="i1"):
    return SimpleNamespace(kind=kind, title=title, severity=severity, attempts=attempts, inquiry_id=inquiry_id,
                           since=NOW - timedelta(minutes=minutes) if minutes is not None else None)


def _inq(check_in=None, check_out=None, adults=None, children=None, route=None, occasion=None, quoted=None):
    return SimpleNamespace(check_in=check_in, check_out=check_out, adults=adults, children=children,
                           route_mentioned=route, occasion=occasion, quoted_amount=quoted)


def _score(item, inq=None, **kw):
    return lp.score_item(item, inq, now=NOW, today=TODAY, **kw)


def test_a_guest_who_asked_for_a_call_back_and_travels_soon_is_top():
    s, lane, why = _score(_item("followup", minutes=-10, title="Callback requested — Ananya"),
                          _inq("2026-10-26", "2026-10-27", adults=8, occasion="Birthday"))
    assert lane == "now" and s >= 80 and why[:2] == ["Asked for a call back", "Travels in 6 days"]


def test_fresh_detailed_lead_beats_an_old_silent_one():
    fresh = _score(_item("new_lead", minutes=4), _inq("2026-11-26", adults=4, route="Goa"))
    silent = _score(_item("no_reply", minutes=60 * 24 * 2), _inq("2026-12-14", "2026-12-16", adults=6), quote_out=True)
    assert fresh[1] == "now" and fresh[0] > silent[0]
    assert "Quote sent" in silent[2] and "Silent 2 days" in silent[2]


def test_a_missed_call_is_always_call_now_even_with_no_details():
    s, lane, why = _score(_item("callback", minutes=22), None)
    assert lane == "now" and why == ["Called us"]


def test_old_lead_with_no_details_goes_to_chase():
    s, lane, why = _score(_item("new_lead", minutes=60 * 24 * 3, severity="critical"), _inq())
    assert lane == "chase" and "No trip details" in why


def test_travel_date_over_caps_the_score_and_chases():
    s, lane, why = _score(_item("reply", minutes=10), _inq("2026-10-01", "2026-10-03", adults=6))
    assert lane == "chase" and s <= 10 and why[-1] == "Travel date is over"


def test_stale_items_are_chase_and_unanswered_calls_cost_points():
    assert _score(_item("reply", minutes=60 * 24 * 4, severity="stale"))[1] == "chase"
    tried = _score(_item("new_lead", minutes=60 * 5, attempts=3), _inq("2026-10-25", adults=2))
    assert "3 calls unanswered" in tried[2]


def test_an_overdue_task_is_reply_today_not_call_now():
    s, lane, why = _score(_item("followup", minutes=60 * 24 * 1, title="Call lead about pricing"), _inq("2026-11-20", adults=4))
    assert lane == "today"


def test_sort_key_is_lane_then_score_then_longest_wait():
    a = SimpleNamespace(kind="new_lead", lane="now", priority=50, since=NOW - timedelta(minutes=5))
    b = SimpleNamespace(kind="new_lead", lane="now", priority=50, since=NOW - timedelta(minutes=50))
    c = SimpleNamespace(kind="no_reply", lane="today", priority=90, since=NOW)
    d = SimpleNamespace(kind="clash", lane="today", priority=0, since=None)
    ordered = sorted([c, d, a, b], key=lambda i: lp.sort_key(i, lambda x: x))
    assert ordered == [b, a, c, d]
