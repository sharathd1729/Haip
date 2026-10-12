"""Reading booking details out of the Ratha team's Google Calendar events (app/services/ical_event_details.py).

The samples are the real event shapes the team uses (names and numbers replaced): a long "Booking confirmation" block with
amounts, a short "BOOKING" block, one with a date range, one with start and return lines, one that spans two calendar days
in the text but sits on one day in the calendar, and bare titles with no description at all.
"""
from datetime import date

import pytest

from app.services import ical_event_details as ed

CONFIRMATION = (
    "🎉 BOOKING CONFIRMATION\\n\\n👤 Guest Details\\n\\nGuest Name: Ms. Manisha\\nContact Number: +91 99000 11111\\n\\n"
    "📍 Trip Details\\n\\nDestination: Wonderland by Treehouse\\nVehicle Requirement: 21st October 2026 from 3 PM onwards\\n"
    "Return: 22nd October 2026 by 3 PM\\nPackage: 1 Day / 1 Night | 250 Kms\\nGuests: 5\\n\\n💳 Payment Details\\n\\n"
    "Package Cost: ₹25,000\\nGST (18%): ₹4,500\\nAdd-on Kits (Adventure + Entertainment, 2 x ₹5,000, no GST): ₹10,000\\n"
    "Total Booking Amount: ₹39,500\\nAdvance Received: ₹19,750\\nBalance Amount: ₹19,750"
)
SHORT_PAID = (
    "BOOKING (details confirmed so far)\\n\\nGuest Name: Vanessa\\nContact Number: +91 98000 22222\\n\\n"
    "Destination: Retreat on the Ridge\\nDates: 3rd - 4th October 2026\\nGuests: 7 pax + 1 toddler\\n"
    "Total ₹35,500, fully paid.\\n\\nBooked on 2 Oct 2026."
)
RANGE = (
    "BOOKING\\n\\nGuest Name: Neha\\nContact Number: +91 98456 00000\\n\\nDestination: Kabini - Discovery Village (Shri pin location)\\n"
    "Dates: 20th - 22nd October 2026, noon to ~6 PM\\nPackage: 3 Days / 2 Nights | 500 Kms\\nGuests: 2 Adults + 1 Child\\n\\n"
    "Package Cost: Rs 50,000 (Rs 25,000/day x 2)\\nGST (18%): Rs 9,000\\nTime extension (no GST, already paid): Rs 11,000\\n"
    "Total Booking Amount: Rs 70,000\\nAdvance Received: Rs 35,000\\nBalance Amount: Rs 35,000\\nExtra km: Rs 90/km"
)
TWO_VEHICLES = (
    "BOOKING (second booking; separate from the 15 Oct one)\\nGuest Name: Krithika (Brandaid Events)\\nContact Number: +91 82774 00000\\n"
    "Destination: KTPO (vanity use)\\nDates: 12th October 2026 from 10 PM to 14th October 2026 (end time not given)\\n"
    "Vehicles: 2 Caravans (White and Black)\\nRate: 50 hrs each at Rs 1,000/hr, 2 hrs complimentary per caravan\\nNet: Rs 96,000\\n"
    "GST (18%): Rs 17,280\\nTotal Booking Amount: Rs 1,13,280\\nAdvance Received: Rs 56,640\\nBalance Amount: Rs 56,640"
)


def test_the_long_confirmation_is_read_field_by_field():
    d = ed.extract("Manisha| Jishanth", CONFIRMATION)
    assert d["guest_name"] == "Manisha"                      # "Ms." is dropped
    assert d["phone"] == "+919900011111"
    assert d["destination"] == "Wonderland by Treehouse" and d["guests"] == "5" and d["package"].startswith("1 Day")
    assert d["amounts"] == {"package_cost": 25000.0, "gst": 4500.0, "total": 39500.0, "advance": 19750.0, "balance": 19750.0}
    assert (d["trip_start"], d["trip_end"]) == ("2026-10-21", "2026-10-22")       # start line + return line


def test_a_date_range_gives_the_nights():
    d = ed.extract("Neha| Jishanth", RANGE)
    assert (d["trip_start"], d["trip_end"]) == ("2026-10-20", "2026-10-22")
    assert d["amounts"]["total"] == 70000.0 and d["amounts"]["balance"] == 35000.0 and d["amounts"]["package_cost"] == 50000.0
    assert d["guests"] == "2 Adults + 1 Child"


def test_free_text_totals_and_fully_paid_are_understood():
    d = ed.extract("Vanessa| Jishanth", SHORT_PAID)
    assert d["amounts"] == {"total": 35500.0, "advance": 35500.0, "balance": 0.0}
    assert (d["trip_start"], d["trip_end"]) == ("2026-10-03", "2026-10-04")
    assert "booked_on" not in d                       # "Booked on 2 Oct 2026." has no label to read; left out, not guessed


def test_indian_grouping_and_two_dates_in_one_line():
    d = ed.extract("Krithika| Jishanth", TWO_VEHICLES)
    assert d["amounts"]["total"] == 113280.0 and d["amounts"]["advance"] == 56640.0
    assert (d["trip_start"], d["trip_end"]) == ("2026-10-12", "2026-10-14")
    assert d["vehicles"] == "2 Caravans (White and Black)"


def test_a_bare_title_has_no_details_and_does_not_break():
    d = ed.extract("Shri personal/black Ratha", "")
    assert d == {"title": "Shri personal/black Ratha"}
    assert ed.extract("", "no labels at all, just words") == {"title": "", "notes": "no labels at all, just words"}


@pytest.mark.parametrize("text,expected", [("₹1,13,280", 113280.0), ("Rs 9,000", 9000.0), ("Rs. 90/km", 90.0), ("5000", 5000.0), ("n/a", None), (None, None)])
def test_amounts(text, expected):
    assert ed.parse_amount(text) == expected


def test_the_window_uses_the_trip_dates_when_the_event_sits_on_one_day():
    d = ed.extract("Neha| Jishanth", RANGE)
    # the calendar event is the single day 20 Oct (end exclusive 21 Oct); the trip runs 20 -> 22
    assert ed.block_window("2026-10-20", "2026-10-21", d) == ("2026-10-20", "2026-10-22", "description")
    k = ed.extract("Krithika| Jishanth", TWO_VEHICLES)
    # event on 13 Oct, trip 12 -> 14: the block covers the whole trip and still contains the event
    assert ed.block_window("2026-10-13", "2026-10-14", k) == ("2026-10-12", "2026-10-14", "description")


def test_a_trip_date_far_from_the_event_is_not_trusted():
    d = {"trip_start": "2027-01-05", "trip_end": "2027-01-07"}
    assert ed.block_window("2026-10-20", "2026-10-21", d) == ("2026-10-20", "2026-10-21", "event")
    long = {"trip_start": "2026-10-20", "trip_end": "2026-12-20"}                 # two months: a typo, not a trip
    assert ed.block_window("2026-10-20", "2026-10-21", long)[2] == "event"
    assert ed.block_window("2026-10-20", "2026-10-21", {})[2] == "event"


RULES = {"white-id": ["white", "white ratha"], "black-id": ["black", "black ratha"]}


@pytest.mark.parametrize("text,expected", [
    ("Poornima| white ratha| Jishanth", ["white-id"]),
    ("Shri personal/black Ratha", ["black-id"]),
    ("Krithika| Jishanth\nVehicles: 2 Caravans (White and Black)", ["white-id", "black-id"]),
    ("Manisha| Jishanth\nVehicle Requirement: 21st October 2026", []),                 # no colour: ambiguous
    ("Whiteboard training| Jishanth", []),                                              # whole words only
])
def test_vehicle_matching_is_by_whole_word_and_empty_means_ambiguous(text, expected):
    assert ed.match_vehicles(text, RULES) == expected


def test_unescape_handles_ical_text():
    assert ed.unescape("a\\nb\\, c\\; d\\\\e") == "a\nb, c; d\\e"
    assert date.fromisoformat("2026-10-20")
