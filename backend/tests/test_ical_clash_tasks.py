"""Calendar clash tasks (ical_clash_tasks): one task per clash (calendar block x vehicle), closed by the next sync once the
clash is gone, and scripts/close_stale_clash_tasks.py (dry run by default) running the same check."""
import importlib.util
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.core.encryption import encrypt_credentials  # noqa: E402
from app.models.audit_event import AuditEvent  # noqa: E402
from app.models.base import gen_uuid  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.ical_feed import ICalFeed  # noqa: E402
from app.models.property import BlockedDate, Property, Stay  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import ical_clash_tasks, ical_sync_service as svc  # noqa: E402

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "close_stale_clash_tasks.py")


def _d(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _ics(*events: str) -> str:
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(events) + "END:VCALENDAR\r\n"


def _ev(uid: str, start: str, end: str) -> str:
    return (f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTART;VALUE=DATE:{start.replace('-', '')}\r\n"
            f"DTEND;VALUE=DATE:{end.replace('-', '')}\r\nEND:VEVENT\r\n")


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"clash-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _world(db, tenant=None):
    t = tenant or _tenant(db)
    p = Property(id=gen_uuid(), tenant_id=t.id, name="Ratha 1", slug=f"p-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True)
    db.add(p)
    db.flush()
    f = ICalFeed(tenant_id=t.id, property_id=p.id, name="Google", export_token=svc.new_export_token(),
                 import_url_enc=encrypt_credentials({"url": "https://example.com/g.ics"}), is_active=True)
    db.add(f)
    db.flush()
    return t, p, f


def _stay(db, tid, prop, start, end, status="confirmed"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Stay Guest")
    db.add(g)
    db.flush()
    s = Stay(id=gen_uuid(), tenant_id=tid, guest_id=g.id, property_id=prop.id, check_in=date.fromisoformat(start),
             check_out=date.fromisoformat(end), status=status)
    db.add(s)
    db.flush()
    return s


def _open(db, tid):
    return db.query(Task).filter(Task.tenant_id == tid, Task.title.like("Double booking%"), Task.is_done.is_(False)).all()


def test_one_task_per_clash_however_many_bookings_it_overlaps(db):
    t, p, f = _world(db)
    _stay(db, t.id, p, _d(5), _d(6))
    _stay(db, t.id, p, _d(6), _d(8))
    fetch = lambda u: _ics(_ev("a@x", _d(5), _d(8)))  # noqa: E731
    assert svc.sync_feed(db, f, fetcher=fetch)["conflicts"] == 1
    svc.sync_feed(db, f, fetcher=fetch)
    tasks = _open(db, t.id)
    assert [x.title for x in tasks] == [f"Double booking on Ratha 1: Google {_d(5)} to {_d(8)}"]


def test_the_task_closes_itself_when_the_calendar_event_goes_away(db):
    t, p, f = _world(db)
    _stay(db, t.id, p, _d(5), _d(7))
    svc.sync_feed(db, f, fetcher=lambda u: _ics(_ev("a@x", _d(6), _d(9))))
    (task,) = _open(db, t.id)
    svc.sync_feed(db, f, fetcher=lambda u: _ics())                     # cancelled upstream: the block is lifted
    db.refresh(task)
    assert task.is_done and task.completed_at is not None
    ev = db.query(AuditEvent).filter_by(tenant_id=t.id, action="task.auto_closed", target_id=task.id).one()
    assert ev.payload["actor"] == "ical_sync" and "block is gone" in ev.payload["reason"]


def test_the_task_closes_when_the_booking_is_cancelled_and_comes_back_if_it_clashes_again(db):
    t, p, f = _world(db)
    stay = _stay(db, t.id, p, _d(5), _d(7))
    fetch = lambda u: _ics(_ev("a@x", _d(6), _d(9)))  # noqa: E731
    svc.sync_feed(db, f, fetcher=fetch)
    stay.status = "cancelled"
    db.flush()
    svc.sync_feed(db, f, fetcher=fetch)
    assert _open(db, t.id) == []
    stay.status = "confirmed"
    db.flush()
    svc.sync_feed(db, f, fetcher=fetch)
    assert len(_open(db, t.id)) == 1


def test_legacy_copies_and_a_gone_placeholder_are_closed_and_other_workspaces_untouched(db):
    t, p, f = _world(db)
    _stay(db, t.id, p, _d(5), _d(7))
    title = f"Double booking on Ratha 1: Google {_d(6)} to {_d(9)}"
    legacy = f"Double booking on Unassigned (legacy bookings -- reassign manually): Google {_d(2)} to {_d(3)}"
    now = datetime.now(timezone.utc)
    copies = [Task(tenant_id=t.id, title=title, priority="high", due_date=now, created_at=now - timedelta(hours=h)) for h in (3, 2)]
    old = Task(tenant_id=t.id, title=legacy, priority="high", due_date=now)
    other_t, _, _ = _world(db)
    theirs = Task(tenant_id=other_t.id, title=legacy, priority="high", due_date=now)
    db.add_all([*copies, old, theirs])
    db.flush()
    svc.sync_feed(db, f, fetcher=lambda u: _ics(_ev("a@x", _d(6), _d(9))))
    for x in (*copies, old, theirs):
        db.refresh(x)
    assert copies[0].is_done is False and copies[1].is_done is True        # the oldest copy is the one kept
    assert old.is_done is True and theirs.is_done is False


def _run_script(db, *argv):
    spec = importlib.util.spec_from_file_location("close_stale_clash_tasks", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with patch.object(mod, "SessionLocal", return_value=db), patch.object(db, "close"), patch.object(sys, "argv", ["x", *argv]):
        return mod.main()


def test_script_dry_run_writes_nothing_and_apply_closes(db, capsys):
    t, p, f = _world(db)
    stale = Task(tenant_id=t.id, title=f"Double booking on Ratha 1: Google {_d(2)} to {_d(3)}", priority="high",
                 due_date=datetime.now(timezone.utc))
    db.add(stale)
    db.commit()
    stale_id = stale.id

    assert _run_script(db, "--tenant-slug", t.slug) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "would close" in out and stale.title in out and "Would close 1 task(s)." in out
    assert db.query(Task).filter_by(id=stale_id).one().is_done is False
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="task.auto_closed").count() == 0

    assert _run_script(db, "--tenant-slug", t.slug, "--apply") == 0
    assert "Closed 1 task(s)." in capsys.readouterr().out
    assert db.query(Task).filter_by(id=stale_id).one().is_done is True
    assert _run_script(db, "--tenant-slug", "no-such-workspace") == 1


def test_describe_reads_the_vehicle_and_dates_back(db):
    props = {"a": "Ratha 1", "b": "Ratha 10"}
    info = ical_clash_tasks.describe("Double booking on Ratha 10: Google 2026-10-21 to 2026-10-22", props)
    assert info == {"start": "2026-10-21", "end": "2026-10-22", "property_id": "b", "vehicle": "Ratha 10"}
    assert ical_clash_tasks.describe("Not enough vehicles from 2026-11-02: more bookings than free vehicles", props)["start"] == "2026-11-02"
