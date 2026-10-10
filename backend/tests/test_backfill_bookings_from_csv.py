"""scripts/backfill_bookings_from_csv.py: dry run changes nothing; apply fixes booked-on dates for the Pick-Up Report."""
import importlib.util
import os
import sys
import uuid
from datetime import date, timedelta
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.models.base import gen_uuid
from app.models.guest import Guest
from app.models.integration import Integration  # noqa: F401  (keeps the model registry complete)
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.models.webhook import WebhookDelivery
from app.services import sales_performance_service, webhook_service

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "backfill_bookings_from_csv.py")


def _run(db, *argv):
    spec = importlib.util.spec_from_file_location("backfill_bookings_from_csv", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with patch.object(mod, "SessionLocal", return_value=db), patch.object(db, "close"), patch.object(sys, "argv", ["x", *argv]):
        return mod.main()


def _csv(tmp_path, *lines):
    p = tmp_path / "b.csv"
    p.write_text("guest,booked_on,travel_from,travel_to,amount,guest_id\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def _world(db, n_props=1):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"rathaa-{uuid.uuid4().hex[:5]}", plan="growth")
    db.add(t)
    db.flush()
    props = [Property(id=gen_uuid(), tenant_id=t.id, name=f"Caravan {i + 1}", slug=f"c{i}-{uuid.uuid4().hex[:4]}", type="villa", is_active=True)
             for i in range(n_props)]
    db.add_all(props)
    db.flush()
    return t, props


def _guest(db, t, name, phone):
    g = Guest(id=gen_uuid(), tenant_id=t.id, name=name, phone=phone)
    db.add(g)
    db.flush()
    return g


def test_dry_run_changes_nothing_then_apply_creates_and_updates(db, tmp_path, capsys):
    t, (prop,) = _world(db)
    deepti = _guest(db, t, "Deepti Sharma", "+919800000001")
    vividh = _guest(db, t, "Vividh Singh", "+919800000002")
    existing = Stay(id=gen_uuid(), tenant_id=t.id, guest_id=vividh.id, property_id=prop.id, check_in=date(2026, 8, 7),
                    check_out=date(2026, 8, 8), status="checked_out", total_amount=None)
    db.add(existing)
    db.commit()
    path = _csv(tmp_path, "Deepti,2026-07-24,2026-07-25,2026-07-29,,", "Vividh Singh,2026-07-18,2026-08-07,2026-08-08,30000,")

    assert _run(db, "--tenant-slug", t.slug, "--csv", path) == 0
    out = capsys.readouterr().out
    assert "Would create 1 booking(s) (0 with a new guest), update 1, skip 0" in out and "Dry run only" in out and "******0001" in out and "9800000001" not in out
    assert db.query(Stay).filter_by(tenant_id=t.id).count() == 1

    assert _run(db, "--tenant-slug", t.slug, "--csv", path, "--apply") == 0
    new = db.query(Stay).filter_by(tenant_id=t.id, guest_id=deepti.id).one()
    assert (float(new.total_amount), new.status, new.channel_source) == (100000.0, "checked_out", "direct")   # 4 days x 25,000
    assert new.created_at.date() == date(2026, 7, 24) and "estimated" in new.internal_notes
    db.refresh(existing)
    assert existing.created_at.date() == date(2026, 7, 18) and float(existing.total_amount) == 30000.0


def test_pickup_report_buckets_backfilled_bookings_by_booked_on_date(db, tmp_path):
    t, (prop,) = _world(db)
    _guest(db, t, "Deepti", "+919800000003")
    _guest(db, t, "Sita", "+919800000004")
    db.commit()
    path = _csv(tmp_path, "Deepti,2026-07-24,2026-07-25,2026-07-29,100000,", "Sita,2026-07-29,2026-08-06,2026-08-06,25000,")
    _run(db, "--tenant-slug", t.slug, "--csv", path, "--apply")
    rep = sales_performance_service.pickup_report(db, t.id, date(2026, 7, 1), as_of=date(2026, 7, 31))
    by_day = {r["date"]: r for r in rep["rows"]}
    assert by_day["2026-07-24"]["pickup_of_day"] == 100000.0 and by_day["2026-07-24"]["this_month"] == 100000.0
    assert by_day["2026-07-29"]["pickup_of_day"] == 25000.0 and by_day["2026-07-29"]["next_month"] == 25000.0
    assert rep["picked_up"] == 125000.0


def test_ambiguous_and_missing_guests_are_skipped_and_reported(db, tmp_path, capsys):
    t, _ = _world(db)
    _guest(db, t, "Neha Rao", "+919800000005")
    _guest(db, t, "Neha Kumar", "+919800000006")
    db.commit()
    path = _csv(tmp_path, "Neha,2026-10-02,2026-10-20,2026-10-22,,", "Nobody,2026-10-02,2026-10-21,2026-10-22,,")
    assert _run(db, "--tenant-slug", t.slug, "--csv", path, "--apply") == 2
    out = capsys.readouterr().out
    assert "2 guests match" in out and "no guest with that name" in out and "Created 0 booking(s) (0 with a new guest), updated 0, skipped 2" in out
    assert db.query(Stay).filter_by(tenant_id=t.id).count() == 0
    # pinning the guest id resolves the ambiguity
    neha = db.query(Guest).filter_by(tenant_id=t.id, name="Neha Rao").one()
    path2 = _csv(tmp_path, f"Neha,2026-10-02,2026-10-20,2026-10-22,,{neha.id}")
    assert _run(db, "--tenant-slug", t.slug, "--csv", path2, "--apply") == 0
    assert db.query(Stay).filter_by(tenant_id=t.id, guest_id=neha.id).count() == 1


def test_property_required_when_several_and_future_bookings_stay_confirmed(db, tmp_path, capsys):
    t, props = _world(db, n_props=2)
    g = _guest(db, t, "Krithika", "+919800000007")
    db.commit()
    future = (date.today() + timedelta(days=20)).isoformat()
    path = _csv(tmp_path, f"Krithika,{date.today().isoformat()},{future},{future},25000,")
    assert _run(db, "--tenant-slug", t.slug, "--csv", path, "--apply") == 2
    assert "needs --property" in capsys.readouterr().out and db.query(Stay).filter_by(tenant_id=t.id).count() == 0
    assert _run(db, "--tenant-slug", t.slug, "--csv", path, "--property", "Caravan 2", "--apply") == 0
    s = db.query(Stay).filter_by(tenant_id=t.id, guest_id=g.id).one()
    assert s.status == "confirmed" and s.property_id == props[1].id and s.check_in == s.check_out


def test_no_webhook_for_backfilled_bookings(db, tmp_path):
    t, _ = _world(db)
    _guest(db, t, "Ravi", "+919800000008")
    ep, _ = webhook_service.create_endpoint(db, t.id, "https://hooks.example.com/x", ["booking.created", "booking.updated"], None, None)
    db.commit()
    with patch("app.workers.tasks.webhook_delivery.deliver_webhook.delay") as delay:
        _run(db, "--tenant-slug", t.slug, "--csv", _csv(tmp_path, "Ravi,2026-08-29,2026-08-30,2026-08-30,25000,"), "--apply")
    assert db.query(WebhookDelivery).filter_by(tenant_id=t.id).count() == 0 and delay.call_count == 0
    assert db.query(Stay).filter_by(tenant_id=t.id).count() == 1


def test_monthly_target_is_set_for_each_booking_month_and_feeds_the_report(db, tmp_path, capsys):
    from app.models.sales_target import SCOPE_TENANT
    from app.services import targets_service
    t, _ = _world(db)
    _guest(db, t, "Deepti", "+919800000009")
    _guest(db, t, "Sakshi", "+919800000010")
    db.commit()
    path = _csv(tmp_path, "Deepti,2026-07-24,2026-07-25,2026-07-29,100000,", "Sakshi,2026-09-17,2026-09-22,2026-09-23,25000,")

    _run(db, "--tenant-slug", t.slug, "--csv", path, "--monthly-target", "600000")            # dry run
    assert "TARGET: Rs 600,000 a month for Jul 2026, Sep 2026" in capsys.readouterr().out
    assert targets_service.get_target(db, t.id, SCOPE_TENANT, None, date(2026, 7, 1)) is None

    _run(db, "--tenant-slug", t.slug, "--csv", path, "--monthly-target", "600000", "--apply")
    assert float(targets_service.get_target(db, t.id, SCOPE_TENANT, None, date(2026, 7, 1)).target_amount) == 600000.0
    assert float(targets_service.get_target(db, t.id, SCOPE_TENANT, None, date(2026, 9, 1)).target_amount) == 600000.0
    assert targets_service.get_target(db, t.id, SCOPE_TENANT, None, date(2026, 8, 1)) is None   # no booking made in August

    rep = sales_performance_service.pickup_report(db, t.id, date(2026, 7, 1), as_of=date(2026, 7, 31))
    assert rep["has_target"] and round(rep["target_per_day"]) == round(600000 / 31)
    assert rep["rows"][-1]["variance"] == 100000.0 - 600000.0


def test_existing_booking_on_the_travel_date_settles_an_ambiguous_name(db, tmp_path, capsys):
    """'Neha' matches many guests, but only one has a booking starting 20 Oct: that booking is the one."""
    t, (prop,) = _world(db)
    nehas = [_guest(db, t, f"Neha {surname}", f"+91980000{i:04d}") for i, surname in enumerate(["Jain", "Singh", "Mathur"], start=20)]
    stay = Stay(id=gen_uuid(), tenant_id=t.id, guest_id=nehas[1].id, property_id=prop.id, check_in=date(2026, 10, 20),
                check_out=date(2026, 10, 22), status="confirmed", total_amount=48000)
    db.add(stay)
    db.commit()
    path = _csv(tmp_path, "Neha,2026-10-02,2026-10-20,2026-10-22,,")
    assert _run(db, "--tenant-slug", t.slug, "--csv", path, "--apply") == 0
    out = capsys.readouterr().out
    assert "UPDATE" in out and "Neha Singh" in out and "keeps amount 48,000" in out
    db.refresh(stay)
    assert stay.created_at.date() == date(2026, 10, 2) and float(stay.total_amount) == 48000.0     # real amount untouched


def test_two_bookings_the_same_day_for_one_name_are_reported(db, tmp_path, capsys):
    t, (prop,) = _world(db)
    for i, surname in enumerate(["Jain", "Rao"], start=30):
        g = _guest(db, t, f"Neha {surname}", f"+91980000{i:04d}")
        db.add(Stay(id=gen_uuid(), tenant_id=t.id, guest_id=g.id, property_id=prop.id, check_in=date(2026, 10, 20), check_out=date(2026, 10, 21)))
    db.commit()
    assert _run(db, "--tenant-slug", t.slug, "--csv", _csv(tmp_path, "Neha,2026-10-02,2026-10-20,2026-10-21,,"), "--apply") == 2
    assert "2 bookings start that day" in capsys.readouterr().out


def test_create_missing_makes_one_name_only_guest_and_is_safe_to_rerun(db, tmp_path, capsys):
    t, (prop,) = _world(db)
    db.commit()
    path = _csv(tmp_path, "Vanessa,2026-10-02,2026-10-03,2026-10-04,25000,")

    assert _run(db, "--tenant-slug", t.slug, "--csv", path, "--apply") == 2                    # no flag: reported, nothing made
    assert "use --create-missing" in capsys.readouterr().out and db.query(Guest).filter_by(tenant_id=t.id).count() == 0

    assert _run(db, "--tenant-slug", t.slug, "--csv", path, "--create-missing", "--apply") == 0
    guest = db.query(Guest).filter_by(tenant_id=t.id, name="Vanessa").one()
    assert guest.phone == ""                                                                    # name only: valid, phone can be added later
    stay = db.query(Stay).filter_by(tenant_id=t.id, guest_id=guest.id).one()
    assert stay.created_at.date() == date(2026, 10, 2) and float(stay.total_amount) == 25000.0

    assert _run(db, "--tenant-slug", t.slug, "--csv", path, "--create-missing", "--apply") == 0   # rerun: updates, no duplicates
    assert db.query(Guest).filter_by(tenant_id=t.id).count() == 1 and db.query(Stay).filter_by(tenant_id=t.id).count() == 1
