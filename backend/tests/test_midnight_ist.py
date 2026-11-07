"""Midnight guard: "today" is the workspace's day (IST), never the machine's date.

From 00:00 to 05:30 IST (18:30-24:00 UTC) the UTC date is still yesterday. These tests once failed only when CI ran in
that window (7 Nov 2026, 19:45 UTC). Each instant re-runs them in a child pytest with the clock frozen (time-machine,
via HAIP_FREEZE_AT in conftest.py) on a UTC machine, so a test or product "today" taken from the machine clock fails
here at any hour. The child uses its own throwaway SQLite file, so it never touches this session's database.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
GUARDED = [
    "tests/test_booking_agenda.py::test_overdue_means_trip_started_or_an_instalment_past_due",
    "tests/test_ical_calendar_bookings.py::test_with_no_creation_stamp_a_future_trip_advance_is_dated_today",
    "tests/test_marketing_partners.py::test_bookings_through_the_creators_link_are_credited_and_the_free_stay_is_not_counted",
    "tests/test_ops_stays.py::test_today_for_villas",
    "tests/test_ops_today.py::test_tomorrows_trip_with_open_checks_is_red_and_on_its_unit",
]


@pytest.mark.skipif(bool(os.environ.get("HAIP_FREEZE_AT")), reason="already inside a frozen child run")
@pytest.mark.parametrize("instant", ["2026-11-07T10:00:00Z",    # 15:30 IST: same date in UTC and IST
                                     "2026-11-07T19:45:00Z"])   # 01:15 IST on the 8th: UTC still says the 7th
def test_today_is_the_workspace_day_at_any_hour(instant, tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "REQUIRE_POSTGRES_TESTS"}
    env.update(HAIP_FREEZE_AT=instant, TZ="UTC0",   # UTC0: a UTC machine on Linux (glibc) and Windows (MSVC) alike
               DATABASE_URL=f"sqlite:///{(tmp_path / 'midnight.db').as_posix()}")
    run = subprocess.run([sys.executable, "-m", "pytest", *GUARDED, "-q", "-p", "no:cacheprovider", "-W", "ignore"],
                         cwd=BACKEND, env=env, capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, f"at {instant}:\n{run.stdout[-6000:]}\n{run.stderr[-2000:]}"
