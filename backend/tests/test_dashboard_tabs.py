"""Home dashboard tabs (workspace redesign Phase 2): Bookings & payments and Ops (services/dashboard_tabs.py)."""
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.core.security import create_access_token, get_password_hash  # noqa: E402
from app.models.base import gen_uuid  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.ops_files import OpsFile  # noqa: E402
from app.models.ops_fleet import OpsAutoMessage, OpsGuestForm  # noqa: E402
from app.models.property import Property, Stay  # noqa: E402
from app.models.stay_finance import StayDeposit, StayInstalment, StayPayment, StayPaymentLink  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services import dashboard_tabs  # noqa: E402

pytestmark = pytest.mark.usefixtures("capabilities_seeded")
T = datetime.now(ZoneInfo("Asia/Kolkata")).date()


def _d(n):
    return T + timedelta(days=n)


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _role(db, tid, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name=role, email=f"{role}-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password=get_password_hash("pw"), role=UserRole(role), is_active=True)
    db.add(u)
    db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": tid, "role": role})}


def _world(db, tid):
    p = Property(id=gen_uuid(), tenant_id=tid, name="Cedar Cottage", slug=f"p-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    db.add(p)
    db.flush()

    def stay(name, a, b, total, paid=0, status="confirmed"):
        g = Guest(id=gen_uuid(), tenant_id=tid, name=name, phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
        db.add(g)
        db.flush()
        s = Stay(id=gen_uuid(), tenant_id=tid, guest_id=g.id, property_id=p.id, check_in=_d(a), check_out=_d(b),
                 status=status, total_amount=total, channel_source="direct")
        db.add(s)
        db.flush()
        if paid:
            db.add(StayPayment(tenant_id=tid, stay_id=s.id, kind="payment", amount=paid, method="upi", paid_on=T))
        return s

    late = stay("Ananya Rao", 5, 8, 40000, paid=10000)
    db.add(StayInstalment(tenant_id=tid, stay_id=late.id, label="Balance", amount=30000, due_date=_d(-2)))
    soon = stay("Vikram Kulkarni", 3, 5, 20000, paid=5000)
    db.add(StayInstalment(tenant_id=tid, stay_id=soon.id, label="Balance", amount=15000, due_date=_d(4)))
    stay("Meera Pillai", 10, 12, 18000, paid=18000)                       # paid in full: not listed
    gone = stay("Fatima Shaikh", -4, -1, 12000, paid=12000, status="checked_out")
    db.add(StayDeposit(tenant_id=tid, stay_id=gone.id, amount=5000, status="held"))
    db.add(StayPaymentLink(tenant_id=tid, stay_id=soon.id, external_id="plink_1", short_url="https://rzp.io/x",
                           amount=15000, status="created"))
    db.commit()
    return p, late, soon


def test_payments_lists_what_is_owed_overdue_first(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _, late, soon = _world(db, tid)
    out = dashboard_tabs.payments(db, tid, T, money=True)
    b = out["balances"]
    assert b["count"] == 2 and b["amount"] == 45000.0
    assert b["overdue"] == {"count": 1, "amount": 30000.0}
    assert b["this_week"] == {"count": 1, "amount": 15000.0}
    assert [i["guest"] for i in b["items"]] == ["Ananya Rao", "Vikram Kulkarni"] and b["items"][0]["overdue"] is True
    assert b["items"][0]["href"] == f"/dashboard/bookings/{late.id}"
    assert out["links_unpaid"]["count"] == 1 and out["links_unpaid"]["amount"] == 15000.0
    assert out["deposits"]["held"]["count"] == 1 and out["deposits"]["to_give_back"]["amount"] == 5000.0


def test_payments_hides_amounts_without_revenue_access(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _world(db, tid)
    out = dashboard_tabs.payments(db, tid, T, money=False)
    assert out["money_restricted"] is True and out["balances"]["amount"] is None and out["balances"]["count"] == 2
    assert all(i["amount"] is None for i in out["balances"]["items"])


def test_payments_never_shows_another_workspace(db, tenant_and_user):
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _world(db, other.id)
    out = dashboard_tabs.payments(db, _tid(tenant_and_user), T, money=True)
    assert out["balances"]["count"] == 0 and out["links_unpaid"]["count"] == 0 and out["deposits"]["held"]["count"] == 0


def test_payments_endpoint_roles(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _world(db, tid)
    r = client.get("/api/v1/dashboard/payments", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    assert r.json()["balances"]["count"] == 2
    assert client.get("/api/v1/dashboard/payments", headers=_role(db, tid, "foh")).status_code == 403


def test_ops_board_id_forms_and_reviews(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    p = Property(id=gen_uuid(), tenant_id=tid, name="Hilltop Villa", slug=f"p-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    db.add(p)
    db.flush()
    stays = []
    for name, day in (("Rahul Iyer", 1), ("Sneha Menon", 2), ("Arjun Shetty", 5)):
        g = Guest(id=gen_uuid(), tenant_id=tid, name=name, phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
        db.add(g)
        db.flush()
        s = Stay(id=gen_uuid(), tenant_id=tid, guest_id=g.id, property_id=p.id, check_in=_d(day), check_out=_d(day + 2),
                 status="confirmed", total_amount=10000, channel_source="direct")
        db.add(s)
        db.flush()
        stays.append(s)
    files = []
    for s in stays:
        f = OpsFile(id=str(uuid.uuid4()), tenant_id=tid, stay_id=s.id, pack="villa", state="accepted", details={})
        db.add(f)
        db.flush()
        files.append(f)
    db.add(OpsGuestForm(id=str(uuid.uuid4()), tenant_id=tid, file_id=files[0].id, stay_id=stays[0].id, nonce="n",
                        token_hash=uuid.uuid4().hex, submitted_at=datetime.now(UTC)))
    db.add(OpsGuestForm(id=str(uuid.uuid4()), tenant_id=tid, file_id=files[1].id, stay_id=stays[1].id, nonce="n",
                        token_hash=uuid.uuid4().hex))
    for f, resp in zip(files, ("5", "2", None), strict=True):          # one ask per stay file
        db.add(OpsAutoMessage(tenant_id=tid, file_id=f.id, kind="review_request", recipient="guest", status="sent",
                              sent_at=datetime.now(UTC) - timedelta(days=3), response=resp))
    db.commit()
    with patch("app.services.vehicle_pool.placeholder_ids", return_value=[]):
        r = client.get("/api/v1/dashboard/ops-board", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    a = r.json()["arrivals"]
    assert a["count"] == 3 and a["id_forms"] == {"submitted": 1, "waiting": 1, "not_sent": 1}
    assert a["missing_within_48h"] == 1                                    # Sneha (day 2) has a form she has not filled
    assert a["items"][0]["href"] == f"/dashboard/ops/files/{files[0].id}"
    rv = r.json()["reviews"]
    assert (rv["asked"], rv["answered"], rv["rated"], rv["average"], rv["low"]) == (3, 2, 2, 3.5, 1)
