"""scripts/clean_calendar_guest_names.py: removes Google's bold markers from names read before the sync cleaned them.

Pinned: a dry run counts and changes nothing; --apply cleans calendar-booking guests and calendar-hold names of ONE tenant
only, leaves other guests alone, writes one audit row, and prints counts, never names.
"""

import importlib.util
import os
import sys
import uuid
from datetime import date, timedelta
from unittest.mock import patch

from app.models.audit_event import AuditEvent
from app.models.base import gen_uuid
from app.models.guest import Guest
from app.models.ical_feed import ICalEventDetail
from app.models.property import Property, Stay
from app.models.tenant import Tenant

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "clean_calendar_guest_names.py")


def _run(db, *argv):
    spec = importlib.util.spec_from_file_location("clean_calendar_guest_names", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with (
        patch.object(mod, "SessionLocal", return_value=db),
        patch.object(db, "close"),
        patch.object(sys, "argv", ["x", *argv]),
    ):
        return mod.main()


def _world(db, name="*Mr.Saksham*"):
    t = Tenant(id=str(uuid.uuid4()), name="Villas", slug=f"villas-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    p = Property(
        id=gen_uuid(),
        tenant_id=t.id,
        name="Villa Aster",
        slug=f"p-{uuid.uuid4().hex[:6]}",
        type="villa",
        is_active=True,
    )
    cal = Guest(id=gen_uuid(), tenant_id=t.id, name=name, phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    crm = Guest(id=gen_uuid(), tenant_id=t.id, name="*Starred in CRM*", phone=f"+9197{uuid.uuid4().int % 10**8:08d}")
    db.add_all([p, cal, crm])
    db.flush()
    start = date.today() + timedelta(days=5)
    db.add_all(
        [
            Stay(
                tenant_id=t.id,
                guest_id=cal.id,
                property_id=p.id,
                check_in=start,
                check_out=start + timedelta(days=2),
                status="confirmed",
                channel_source="google_calendar",
                currency="INR",
                special_requests=[],
            ),
            Stay(
                tenant_id=t.id,
                guest_id=crm.id,
                property_id=p.id,
                check_in=start + timedelta(days=4),
                check_out=start + timedelta(days=6),
                status="confirmed",
                channel_source="direct",
                currency="INR",
                special_requests=[],
            ),
            ICalEventDetail(
                tenant_id=t.id,
                blocked_date_id=gen_uuid(),
                feed_id=gen_uuid(),
                event_uid="e1@g",
                title="*Ms. Ritika / Mr. Rahul*",
                details={"guest_name": "*Ms. Ritika* / _Mr. Rahul_", "phone": "+919800000000"},
            ),
        ]
    )
    db.commit()
    return t, cal, crm


def test_dry_run_counts_and_changes_nothing(db, capsys):
    t, cal, _ = _world(db)
    assert _run(db, "--tenant-slug", t.slug) == 0
    out = capsys.readouterr().out
    assert "would clean 1 guest name(s) and 1 calendar hold name(s)" in out
    assert "Saksham" not in out and "Ritika" not in out  # counts only, never names
    db.expire_all()
    assert db.get(Guest, cal.id).name == "*Mr.Saksham*"


def test_apply_cleans_one_tenant_only(db, capsys):
    t, cal, crm = _world(db)
    other, other_cal, _ = _world(db, name="*Other Guest*")
    assert _run(db, "--tenant-slug", t.slug, "--apply") == 0
    assert "cleaned 1 guest name(s) and 1 calendar hold name(s)" in capsys.readouterr().out
    db.expire_all()
    assert db.get(Guest, cal.id).name == "Mr.Saksham"
    assert db.get(Guest, crm.id).name == "*Starred in CRM*"  # not a calendar booking's guest: untouched
    detail = db.query(ICalEventDetail).filter_by(tenant_id=t.id).one()
    assert detail.details == {"guest_name": "Ms. Ritika / Mr. Rahul", "phone": "+919800000000"}
    assert db.get(Guest, other_cal.id).name == "*Other Guest*"  # the other tenant is untouched
    assert (
        db.query(ICalEventDetail).filter_by(tenant_id=other.id).one().details["guest_name"]
        == "*Ms. Ritika* / _Mr. Rahul_"
    )
    (audit,) = db.query(AuditEvent).filter_by(tenant_id=t.id, action="guest.names_cleaned").all()
    assert audit.payload["guests"] == 1 and audit.payload["calendar_holds"] == 1


def test_unknown_tenant_is_an_error(db, capsys):
    assert _run(db, "--tenant-slug", "no-such-tenant") == 1
