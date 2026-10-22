"""A Razorpay payment whose webhook never reached HAIP is picked up by asking Razorpay (payment_reconcile_service), and the
Razorpay settings never hand out a webhook URL that cannot work (API_BASE_URL unset). 22 Oct 2026: a guest paid, Razorpay
captured it, the booking stayed "Unpaid" and no confirmation went out."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.stay_finance import StayPayment, StayPaymentLink
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import payment_reconcile_service as recon
from tests.test_marketing_studio_content import make_user
from tests.test_payment_events import _h, _setup, q  # noqa: F401  (q is a fixture)

pytestmark = pytest.mark.usefixtures("capabilities_seeded")


def _link(db, stay, ext="plink_A1", status="created", age_days=0):
    link = StayPaymentLink(tenant_id=stay.tenant_id, stay_id=stay.id, external_id=ext, short_url=f"https://rzp.io/{ext}", amount=5,
                           status=status, created_at=datetime.now(timezone.utc) - timedelta(days=age_days))
    db.add(link)
    db.commit()
    return link


def _remote(status="paid", pay_id="pay_X1", paise=500):
    payments = [{"payment_id": pay_id, "amount": paise, "method": "upi", "status": "captured", "created_at": 1792676460}] if status == "paid" else []
    return lambda key_id, key_secret, link_id: {"id": link_id, "status": status, "amount_paid": paise if payments else 0, "payments": payments}


def test_a_paid_link_without_a_webhook_is_recorded_once_and_confirms(db, tenant_and_user, q):  # noqa: F811
    stay = _setup(db, tenant_and_user, total=10)
    link = _link(db, stay)
    tenant = tenant_and_user["tenant"]
    out = recon.reconcile_tenant(db, tenant, fetch=_remote())
    assert out == {"checked": 1, "recorded": 1}
    pays = db.query(StayPayment).filter_by(tenant_id=tenant.id, stay_id=stay.id).all()
    assert len(pays) == 1 and float(pays[0].amount) == 5.0 and pays[0].external_id == "pay_X1"
    db.refresh(link)
    assert link.status == "paid" and q.after.call_count == 1              # invoice + guest WhatsApp confirmation queued
    again = recon.reconcile_tenant(db, tenant, fetch=_remote())             # the link is paid now: not asked again
    assert again == {"checked": 0} and q.after.call_count == 1
    # A webhook arriving late for the same payment is a harmless duplicate (unique index on the Razorpay payment id).
    from app.services.payment_events_service import on_payment_link_paid
    assert on_payment_link_paid(db, tenant, link, {"id": "pay_X1", "amount": 500, "method": "upi"}) == "duplicate"


def test_expired_and_unpaid_links(db, tenant_and_user, q):  # noqa: F811
    stay = _setup(db, tenant_and_user, total=10)
    gone = _link(db, stay, ext="plink_old")
    open_ = _link(db, stay, ext="plink_open")
    fetches = {"plink_old": _remote("expired"), "plink_open": _remote("created")}
    out = recon.reconcile_tenant(db, tenant_and_user["tenant"], fetch=lambda k, s, link_id: fetches[link_id](k, s, link_id))
    assert out["checked"] == 2 and out.get("expired") == 1 and out.get("open") == 1
    db.refresh(gone)
    db.refresh(open_)
    assert gone.status == "expired" and open_.status == "created" and q.after.call_count == 0


def test_old_links_and_razorpay_errors_are_left_alone(db, tenant_and_user, q):  # noqa: F811
    from app.adapters.payments.razorpay import RazorpayError
    stay = _setup(db, tenant_and_user, total=10)
    _link(db, stay, ext="plink_ancient", age_days=recon.LOOKBACK_DAYS + 2)
    _link(db, stay, ext="plink_err")

    def boom(*_a):
        raise RazorpayError("down")
    assert recon.reconcile_tenant(db, tenant_and_user["tenant"], fetch=boom) == {"checked": 1, "error": 1}


def test_not_connected_and_other_workspaces_untouched(db, tenant_and_user, q):  # noqa: F811
    stay = _setup(db, tenant_and_user, total=10, razorpay=False)
    _link(db, stay)
    assert recon.reconcile_tenant(db, tenant_and_user["tenant"], fetch=_remote()) == {"skipped": "Razorpay is not connected"}
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    assert recon.reconcile_tenant(db, other, fetch=_remote()) == {"skipped": "Razorpay is not connected"}
    assert db.query(StayPayment).count() == 0


def test_reconcile_endpoint_is_for_owners_and_managers(client, db, tenant_and_user, q):  # noqa: F811
    stay = _setup(db, tenant_and_user, total=10)
    _link(db, stay)
    _, concierge_h = make_user(db, tenant_and_user["tenant"].id, UserRole.CONCIERGE)
    assert client.post("/api/v1/payments/razorpay/reconcile", headers=concierge_h).status_code == 403
    with patch("app.services.payment_reconcile_service.rzp.fetch_payment_link", _remote()):
        r = client.post("/api/v1/payments/razorpay/reconcile", headers=_h(tenant_and_user))
    assert r.status_code == 200 and r.json() == {"checked": 1, "recorded": 1}


def test_no_webhook_url_without_a_public_api_address(client, db, tenant_and_user, monkeypatch):
    monkeypatch.setattr("app.api.v1.endpoints.payments_razorpay.settings.API_BASE_URL", "")
    with patch("app.api.v1.endpoints.payments_razorpay.rzp.check_credentials"):
        r = client.post("/api/v1/payments/razorpay/connect", json={"key_id": "rzp_test_abc12345", "key_secret": "s3cretvalue"},
                        headers=_h(tenant_and_user))
    body = r.json()
    assert r.status_code == 200 and body["webhook_url"] is None and "API_BASE_URL" in body["warning"]
    st = client.get("/api/v1/payments/razorpay", headers=_h(tenant_and_user)).json()
    assert st["webhook_url"] is None and st["warning"]
    monkeypatch.setattr("app.api.v1.endpoints.payments_razorpay.settings.API_BASE_URL", "https://genhaip.example")
    st = client.get("/api/v1/payments/razorpay", headers=_h(tenant_and_user)).json()
    assert st["webhook_url"] == f"https://genhaip.example/api/v1/webhooks/razorpay/{tenant_and_user['tenant'].slug}" and "warning" not in st
