"""CSV import of WhatsApp subscribers, and campaign scheduling times."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.endpoints.messaging import WASubscriber
from app.models.guest import Guest
from app.services import wa_campaign_schedule as sched
from app.services import wa_subscriber_import as imp


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


# ─── parsing ─────────────────────────────────────────────────────────────────

def test_parse_with_a_header_and_any_column_order():
    rows = imp.parse_csv(b"Tags,Name,Mobile\nvip|goa,Priya,98765 43210\n,Arjun,+91 98220 11111\n")
    assert [(r.raw_phone, r.name, r.tags, r.row) for r in rows] == [
        ("98765 43210", "Priya", ["vip", "goa"], 2), ("+91 98220 11111", "Arjun", [], 3)]


def test_parse_without_a_header_uses_phone_name_tags():
    rows = imp.parse_csv(b"9876543210,Priya,vip\n9822011111,Arjun,\n")
    assert rows[0].raw_phone == "9876543210" and rows[0].name == "Priya" and rows[0].tags == ["vip"] and rows[0].row == 1


def test_parse_semicolon_bom_and_blank_lines():
    rows = imp.parse_csv("﻿phone;name\n\n9876543210;Priya\n".encode("utf-8"))
    assert len(rows) == 1 and rows[0].name == "Priya"


def test_parse_latin1_file():
    rows = imp.parse_csv("phone,name\n9876543210,Jos\xe9\n".encode("latin-1"))
    assert rows[0].name == "Jos\xe9"


@pytest.mark.parametrize("content,expected", [
    (b"", "empty"),
    (b"   \n \n", "empty"),
    (b"name,email\nPriya,p@x.com\n", "phone column"),
    (b"phone,name\n", "no contacts"),
])
def test_parse_rejects_unusable_files(content, expected):
    with pytest.raises(imp.ImportError_, match=expected):
        imp.parse_csv(content)


def test_parse_row_and_size_limits():
    many = "phone\n" + "\n".join(f"98765{i:05d}" for i in range(imp.MAX_ROWS + 1))
    with pytest.raises(imp.ImportError_, match="limit"):
        imp.parse_csv(many.encode())
    with pytest.raises(imp.ImportError_, match="larger"):
        imp.parse_csv(b"phone\n" + b"9" * (imp.MAX_BYTES + 1))


# ─── phone validation ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("98765 43210", "+919876543210"), ("+91 98765-43210", "+919876543210"), ("09876543210", "+919876543210"),
    ("+14155552671", "+14155552671"),
])
def test_valid_numbers_become_e164(raw, expected):
    assert imp.validate_phone(raw) == (expected, None)


@pytest.mark.parametrize("raw,fragment", [
    ("", "No phone"), ("abc", "Not a phone"), ("12345", "valid"), ("9.87E+11", "spreadsheet"),
])
def test_bad_numbers_say_why(raw, fragment):
    phone, reason = imp.validate_phone(raw)
    assert phone is None and fragment in reason


# ─── importing ───────────────────────────────────────────────────────────────

def test_import_adds_dedupes_and_reports_bad_rows(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    rows = imp.parse_csv(b"phone,name,tags\n9876543210,Priya,vip\n+91 98765 43210,Priya again,goa\n123,Bad,\n9822011111,Arjun,\n")
    res = imp.import_rows(db, tid, rows, batch_tag="diwali")
    db.commit()
    assert (res.total_rows, res.added, res.duplicates_in_file) == (4, 2, 1)
    assert res.invalid == [{"row": 4, "value": "123", "reason": "Not a valid phone number."}]
    priya = db.query(WASubscriber).filter_by(tenant_id=tid, phone="+919876543210").one()
    assert priya.opted_in is True and priya.source == "import" and priya.opt_in_at
    assert set(priya.tags) == {"vip", "goa", "diwali"}


def test_import_never_opts_someone_back_in(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=tid, phone="+919876543210", opted_in=False, tags=[]))
    db.commit()
    res = imp.import_rows(db, tid, imp.parse_csv(b"phone\n9876543210\n"), batch_tag="x")
    db.commit()
    assert (res.added, res.updated, res.opted_out_skipped) == (0, 0, 1)
    assert res.opted_out == [{"row": 2, "value": "+919876543210"}]
    sub = db.query(WASubscriber).filter_by(tenant_id=tid, phone="+919876543210").one()
    assert sub.opted_in is False and "x" not in (sub.tags or [])


def test_import_merges_into_existing_subscribers(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=tid, phone="+919876543210", opted_in=True, tags=["vip"]))
    db.commit()
    res = imp.import_rows(db, tid, imp.parse_csv(b"phone,name,tags\n9876543210,Priya,goa\n"), batch_tag="diwali")
    db.commit()
    assert (res.added, res.updated) == (0, 1)
    sub = db.query(WASubscriber).filter_by(tenant_id=tid, phone="+919876543210").one()
    assert sub.name == "Priya" and set(sub.tags) == {"vip", "goa", "diwali"}
    again = imp.import_rows(db, tid, imp.parse_csv(b"phone,name,tags\n9876543210,Priya,goa\n"), batch_tag="diwali")
    assert again.updated == 0                                   # nothing new -> not counted as an update


def test_import_links_the_guest_by_phone(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Priya", phone="+919876543210")
    db.add(g)
    db.commit()
    imp.import_rows(db, tid, imp.parse_csv(b"phone\n9876543210\n"))
    db.commit()
    assert db.query(WASubscriber).filter_by(tenant_id=tid, phone="+919876543210").one().guest_id == g.id


def test_import_is_scoped_to_the_workspace(db, tenant_and_user):
    from app.models.tenant import Tenant
    tid = _tid(tenant_and_user)
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.flush()
    db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=other.id, phone="+919876543210", opted_in=False, tags=[]))
    db.commit()
    res = imp.import_rows(db, tid, imp.parse_csv(b"phone\n9876543210\n"))
    db.commit()
    assert res.added == 1 and res.opted_out_skipped == 0        # the other workspace's opt-out is not ours
    assert db.query(WASubscriber).filter_by(phone="+919876543210").count() == 2


# ─── scheduling ──────────────────────────────────────────────────────────────

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def test_a_time_without_a_timezone_is_india_time():
    assert sched.normalize_schedule("2026-09-26T10:00", NOW) == "2026-09-26T04:30:00+00:00"


def test_utc_and_offset_times_are_kept_as_utc():
    assert sched.normalize_schedule("2026-09-26T10:00:00Z", NOW) == "2026-09-26T10:00:00+00:00"
    assert sched.normalize_schedule("2026-09-26T10:00:00+05:30", NOW) == "2026-09-26T04:30:00+00:00"


def test_empty_means_no_schedule():
    assert sched.normalize_schedule(None, NOW) is None and sched.normalize_schedule("  ", NOW) is None


def test_bad_schedules_are_refused_in_words():
    with pytest.raises(sched.ScheduleError, match="already passed"):
        sched.normalize_schedule("2026-09-24T10:00:00Z", NOW)
    with pytest.raises(sched.ScheduleError, match="6 months"):
        sched.normalize_schedule("2027-09-25T10:00:00Z", NOW)
    with pytest.raises(sched.ScheduleError, match="read"):
        sched.normalize_schedule("next tuesday", NOW)
    assert sched.normalize_schedule((NOW - timedelta(seconds=30)).isoformat(), NOW)   # "now" typed a moment ago is fine


def test_is_due():
    assert sched.is_due("2026-09-25T11:59:00+00:00", NOW) is True
    assert sched.is_due("2026-09-25T12:01:00+00:00", NOW) is False
    assert sched.is_due("2026-09-25T17:30", NOW) is True          # naive = IST = 12:00 UTC
    assert sched.is_due(None, NOW) is False and sched.is_due("garbage", NOW) is False
