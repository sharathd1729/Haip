"""A Google Calendar feed carries every event ever; fetch_ics drops long-past ones before parsing (Jade, 7 Nov 2026)."""
from datetime import date
from zoneinfo import ZoneInfo

from app.services.ical_sync_service import _drop_old_events, parse_ics

TODAY = date(2026, 11, 7)


def _event(uid, start, end, extra=""):
    return f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTART;VALUE=DATE:{start}\r\nDTEND;VALUE=DATE:{end}\r\n{extra}SUMMARY:{uid}\r\nEND:VEVENT\r\n"


def _calendar(*events):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(events) + "END:VCALENDAR\r\n"


def test_old_events_dropped_recent_and_repeating_kept():
    text = _calendar(
        _event("old-2023", "20230105", "20230107"),
        _event("recent", "20261101", "20261103"),
        _event("upcoming", "20261220", "20261222"),
        _event("weekly-since-2022", "20220101", "20220102", "RRULE:FREQ=WEEKLY\r\n"),
        _event("old-last", "20240301", "20240302"),            # last event old: the calendar must still close
    )
    out = _drop_old_events(text, TODAY)
    uids = {e["uid"] for e in parse_ics(out, ZoneInfo("Asia/Kolkata"))}
    assert {"recent", "upcoming", "weekly-since-2022"} <= uids
    assert "old-2023" not in uids and "old-last" not in uids
    assert out.rstrip().endswith("END:VCALENDAR")


def test_events_inside_the_import_window_are_never_dropped():
    # ended 45 days ago: older than the 30-day import window but inside the 90-day prefilter margin
    text = _calendar(_event("ended-45-days-ago", "20260920", "20260923"))
    assert "ended-45-days-ago" in _drop_old_events(text, TODAY)


def test_thousands_of_old_events_shrink_to_the_live_window():
    old = "".join(_event(f"old-{i}", "20210101", "20210102") for i in range(20_000))
    text = _calendar(old, _event("recent", "20261101", "20261103"))
    out = _drop_old_events(text, TODAY)
    assert len(out) < len(text) // 100
    assert [e["uid"] for e in parse_ics(out, ZoneInfo("Asia/Kolkata"))] == ["recent"]
