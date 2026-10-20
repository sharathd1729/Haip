"""scripts/ratha_vehicles.py: rename the caravans Ratha 1 / Ratha 2, keep the colour in each booking's notes, move bookings off the
"Unassigned" placeholder. A dry run (rollback) writes nothing; another workspace is never touched."""
import importlib.util
import os
import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

from app.models.base import gen_uuid  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.ical_feed import ICalFeedVehicle  # noqa: E402
from app.models.property import Property, Stay  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from tests.test_ical_feeds import _feed  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("ratha_vehicles", os.path.join(os.path.dirname(__file__), "..", "scripts", "ratha_vehicles.py"))
rv = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rv)


def _d(n):
    return date.today() + timedelta(days=n)


def _prop(db, tid, name):
    p = Property(id=gen_uuid(), tenant_id=tid, name=name, slug=f"{uuid.uuid4().hex[:8]}", type="caravan", is_active=True)
    db.add(p)
    db.commit()
    return p


def _stay(db, tid, prop, a, b, notes=None):
    g = Guest(id=gen_uuid(), tenant_id=tid, name="G", phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    s = Stay(id=gen_uuid(), tenant_id=tid, guest_id=g.id, property_id=prop.id, check_in=_d(a), check_out=_d(b), adults=2, status="confirmed",
             channel_source="direct", internal_notes=notes)
    db.add(s)
    db.commit()
    return s


@pytest.fixture()
def world(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    ph = _prop(db, tid, "Unassigned (vehicle not chosen yet)")
    white, black = _prop(db, tid, "Ratha White"), _prop(db, tid, "Ratha Black")
    feed = _feed(db, tid, ph.id, name="Google")
    db.add(ICalFeedVehicle(tenant_id=tid, feed_id=feed.id, property_id=white.id, keywords=["white"]))
    db.add(ICalFeedVehicle(tenant_id=tid, feed_id=feed.id, property_id=black.id, keywords=["black"]))
    db.commit()
    return {"tid": tid, "ph": ph, "white": white, "black": black}


def test_vehicles_are_renamed_alphabetically_and_the_colour_goes_into_the_notes(db, world):
    old = _stay(db, world["tid"], world["white"], 5, 7, notes="Cake at arrival")
    rv.run(db, world["tid"], None)
    db.commit()
    names = {p.id: p.name for p in db.query(Property).filter_by(tenant_id=world["tid"]).all()}
    assert names[world["black"].id] == "Ratha 1" and names[world["white"].id] == "Ratha 2"
    db.refresh(old)
    assert old.internal_notes == "Cake at arrival\nCaravan: Ratha White"


def test_first_chooses_which_caravan_becomes_ratha_1(db, world):
    rv.run(db, world["tid"], "white")
    db.commit()
    db.refresh(world["white"])
    assert world["white"].name == "Ratha 1"


def test_unassigned_bookings_move_to_the_first_free_vehicle_oldest_first(db, world):
    a = _stay(db, world["tid"], world["ph"], 10, 12)
    b = _stay(db, world["tid"], world["ph"], 11, 13)
    c = _stay(db, world["tid"], world["ph"], 11, 14)
    out = rv.run(db, world["tid"], None)
    db.commit()
    for s in (a, b, c):
        db.refresh(s)
    assert a.property_id == world["black"].id and b.property_id == world["white"].id        # Ratha 1, then Ratha 2
    assert c.property_id == world["ph"].id and [m["stay_id"] for m in out["stuck"]] == [c.id]  # nothing free: left, and listed


def test_a_dry_run_rolls_back_and_apply_commits(db, world, monkeypatch, capsys):
    from unittest.mock import MagicMock

    _stay(db, world["tid"], world["ph"], 10, 12)
    slug = db.query(Tenant).filter_by(id=world["tid"]).one().slug
    spy = MagicMock(wraps=db)
    spy.commit, spy.rollback, spy.close = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(rv, "SessionLocal", lambda: spy)
    monkeypatch.setattr("sys.argv", ["ratha_vehicles.py", "--tenant-slug", slug])
    assert rv.main() == 0
    assert spy.rollback.called and not spy.commit.called and "DRY RUN" in capsys.readouterr().out
    spy.rollback.reset_mock()
    monkeypatch.setattr("sys.argv", ["ratha_vehicles.py", "--tenant-slug", slug, "--apply"])
    assert rv.main() == 0
    assert spy.commit.called and not spy.rollback.called and "APPLIED" in capsys.readouterr().out


def test_running_twice_changes_nothing_more(db, world):
    _stay(db, world["tid"], world["white"], 5, 7)
    rv.run(db, world["tid"], None)
    db.commit()
    again = rv.run(db, world["tid"], None)
    assert again["renames"] == [] and again["stays_noted"] == 0 and again["moved"] == []


def test_past_bookings_on_the_placeholder_are_left_alone_by_default(db, world):
    s = _stay(db, world["tid"], world["ph"], -10, -8)
    out = rv.run(db, world["tid"], None)
    db.commit()
    db.refresh(s)
    assert s.property_id == world["ph"].id and out["moved"] == [] and out["stuck"] == []


def test_include_past_assigns_oldest_first_ratha_1_then_ratha_2_for_overlaps(db, world):
    a = _stay(db, world["tid"], world["ph"], -40, -37)
    b = _stay(db, world["tid"], world["ph"], -39, -36)       # overlaps a: takes the other vehicle
    c = _stay(db, world["tid"], world["ph"], -20, -18)       # later, free again: back to Ratha 1
    out = rv.run(db, world["tid"], None, include_past=True)
    db.commit()
    for s in (a, b, c):
        db.refresh(s)
    names = {p.id: p.name for p in db.query(Property).filter_by(tenant_id=world["tid"]).all()}
    assert [names[s.property_id] for s in (a, b, c)] == ["Ratha 1", "Ratha 2", "Ratha 1"] and out["stuck"] == []


def test_include_past_puts_a_cancelled_booking_on_ratha_1_even_when_both_are_busy(db, world):
    _stay(db, world["tid"], world["black"], -30, -28)
    _stay(db, world["tid"], world["white"], -30, -28)
    dead = _stay(db, world["tid"], world["ph"], -29, -27)
    dead.status = "cancelled"
    db.commit()
    rv.run(db, world["tid"], None, include_past=True)
    db.commit()
    db.refresh(dead)
    assert db.query(Property).filter_by(id=dead.property_id).one().name == "Ratha 1"


def test_include_past_splits_checked_out_trips_on_the_same_dates_across_the_caravans(db, world):
    # Production, 20 Oct 2026: checked-out trips never blocked a vehicle, so two trips on the same day both got Ratha 1.
    a = _stay(db, world["tid"], world["ph"], -30, -29)
    b = _stay(db, world["tid"], world["ph"], -30, -29)
    day = _stay(db, world["tid"], world["ph"], -20, -20)      # two day trips on one day
    day2 = _stay(db, world["tid"], world["ph"], -20, -20)
    third = _stay(db, world["tid"], world["ph"], -30, -28)    # both caravans already out: Ratha 1, flagged
    for s in (a, b, day, third):
        s.status = "checked_out"
    db.commit()                                                 # day2 stays "confirmed" though its date passed: same rule
    out = rv.run(db, world["tid"], None, include_past=True)
    db.commit()
    names = {p.id: p.name for p in db.query(Property).filter_by(tenant_id=world["tid"]).all()}
    for s in (a, b, day, day2, third):
        db.refresh(s)
    assert [names[s.property_id] for s in (a, b, day, day2, third)] == ["Ratha 1", "Ratha 2", "Ratha 1", "Ratha 2", "Ratha 1"]
    assert [m["stay_id"] for m in out["moved"] if m.get("overlap")] == [third.id]
