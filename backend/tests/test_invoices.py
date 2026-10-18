"""Invoices: GSTIN rules, numbering, GST split, immutability, reissue, PDF, settings and invoice endpoints."""
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

from app.core.security import create_access_token  # noqa: E402
from app.models.base import gen_uuid  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.invoice import Invoice  # noqa: E402
from app.models.property import Property, Stay  # noqa: E402
from app.models.stay_finance import StayAddOn, StayPayment  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.schemas.invoice import InvoiceProfile, gstin_problem  # noqa: E402
from app.services import invoice_pdf, invoice_service  # noqa: E402

GSTIN_KA = "29AAGCB7383J1Z4"      # valid check character, Karnataka
GSTIN_MH = "27AAPFU0939F1ZV"      # valid check character, Maharashtra
PROFILE = {"legal_name": "Ratha Journeys LLP", "gstin": GSTIN_KA, "address": "Jakkur, Bengaluru", "state_code": "29",
           "sac_code": "9966", "gst_rate": 12, "invoice_prefix": "INV", "receipt_prefix": "RCPT"}


@pytest.fixture(autouse=True)
def _no_broker():
    with patch("app.workers.tasks.invoice_tasks.render_pdf.delay") as rp, \
         patch("app.workers.tasks.invoice_tasks.after_payment.delay"), \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay"):
        yield rp


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _user(db, tenant_id, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name=role.value, email=f"{role.value}-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": tenant_id, "role": role.value})}


def _setup(db, tenant, total=11200, profile=PROFILE):
    tenant.brand_config = {**(tenant.brand_config or {}), "invoice_profile": dict(profile)} if profile else (tenant.brand_config or {})
    prop = Property(id=gen_uuid(), tenant_id=tenant.id, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    guest = Guest(id=gen_uuid(), tenant_id=tenant.id, name="Kiran Rao", phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add_all([prop, guest])
    db.flush()
    stay = Stay(id=gen_uuid(), tenant_id=tenant.id, guest_id=guest.id, property_id=prop.id, check_in=date.today() + timedelta(days=10),
                check_out=date.today() + timedelta(days=12), adults=2, status="confirmed", total_amount=total, channel_source="direct")
    db.add(stay)
    db.commit()
    return stay


# ── GSTIN ────────────────────────────────────────────────────────────────────

def test_gstin_validation():
    assert gstin_problem(GSTIN_KA) is None and gstin_problem(GSTIN_MH) is None
    assert "15 characters" in gstin_problem("29AAGCB7383J1Z")
    assert "format" in gstin_problem("29AAGCB738XJ1Z4")
    assert "not a GST state code" in gstin_problem("98AAGCB7383J1Z4")
    assert "does not match" in gstin_problem("29AAGCB7383J1Z5")          # one character off
    with pytest.raises(ValueError):
        InvoiceProfile(gstin=GSTIN_KA, state_code="27")                  # GSTIN registered in another state
    p = InvoiceProfile(gstin=GSTIN_KA.lower())
    assert p.gstin == GSTIN_KA and p.state_code == "29"                    # state filled from the GSTIN
    with pytest.raises(ValueError):
        InvoiceProfile(invoice_prefix="INV", receipt_prefix="INV")


# ── Numbers and GST ──────────────────────────────────────────────────────────

def test_financial_year():
    assert invoice_service.financial_year(date(2026, 10, 18)) == "2026-27"
    assert invoice_service.financial_year(date(2027, 3, 31)) == "2026-27"
    assert invoice_service.financial_year(date(2027, 4, 1)) == "2027-28"


def test_numbers_are_sequential_per_series_and_tenant(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    nums = [invoice_service.next_number(db, tid, "2026-27", "INV") for _ in range(3)]
    assert nums == ["INV/2026-27/0001", "INV/2026-27/0002", "INV/2026-27/0003"]
    assert invoice_service.next_number(db, tid, "2027-28", "INV") == "INV/2027-28/0001"     # new financial year restarts
    assert invoice_service.next_number(db, tid, "2026-27", "RCPT") == "RCPT/2026-27/0001"   # receipts are their own series
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.flush()
    assert invoice_service.next_number(db, other.id, "2026-27", "INV") == "INV/2026-27/0001"  # tenant isolation


def test_gst_split_intra_and_inter_state():
    lines = [{"description": "Stay", "amount": 11200}]
    intra = invoice_service.compute(lines, 12, "29", None)
    assert intra["taxable_value"] == Decimal("10000.00") and intra["cgst"] == Decimal("600.00") and intra["sgst"] == Decimal("600.00")
    assert intra["igst"] == 0 and intra["total"] == Decimal("11200.00") and intra["place_of_supply"] == "29"
    inter = invoice_service.compute(lines, 12, "29", "27")
    assert inter["igst"] == Decimal("1200.00") and inter["cgst"] == 0 and inter["sgst"] == 0
    odd = invoice_service.compute([{"description": "a", "amount": 999.99}, {"description": "b", "amount": 0.01}], 18, "29", None)
    assert odd["taxable_value"] + odd["cgst"] + odd["sgst"] == odd["total"]        # always reconciles to the paisa


def test_issue_invoice_snapshot_and_no_gst_without_gstin(db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    stay = _setup(db, tenant)
    db.add(StayAddOn(tenant_id=tenant.id, stay_id=stay.id, name="Experience kit", quantity=2, unit_price=2240))
    db.commit()
    inv = invoice_service.issue_invoice(db, tenant, stay)
    db.commit()
    assert inv.number.startswith("INV/") and inv.total == Decimal("15680.00") and len(inv.lines) == 2
    assert inv.seller["gstin"] == GSTIN_KA and inv.buyer["name"] == "Kiran Rao" and inv.cgst == inv.sgst == Decimal("840.00")

    tenant.brand_config = {"invoice_profile": {**PROFILE, "gstin": None}}
    db.commit()
    stay2 = _setup(db, tenant, profile=None)
    plain = invoice_service.issue_invoice(db, tenant, stay2)
    assert float(plain.gst_rate) == 0 and plain.cgst == 0 and plain.taxable_value == plain.total


def test_incomplete_profile_refuses(db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    stay = _setup(db, tenant, profile={"gstin": GSTIN_KA})
    with pytest.raises(invoice_service.InvoiceError, match="legal name"):
        invoice_service.issue_invoice(db, tenant, stay)


def test_issued_invoice_is_immutable(db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    inv = invoice_service.issue_invoice(db, tenant, _setup(db, tenant))
    db.commit()
    inv.pdf_media_key = f"{tenant.id}/invoices/{inv.id}.pdf"          # allowed
    db.commit()
    inv.total = 1
    with pytest.raises(invoice_service.InvoiceError, match="cannot be edited"):
        db.flush()


# ── PDF ──────────────────────────────────────────────────────────────────────

def test_pdf_renders_invoice_and_receipt(db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    stay = _setup(db, tenant)
    inv = invoice_service.issue_invoice(db, tenant, stay, place_of_supply="27")
    pay = StayPayment(tenant_id=tenant.id, stay_id=stay.id, amount=5000, method="razorpay", reference="pay_1", paid_on=date.today())
    db.add(pay)
    db.flush()
    rec = invoice_service.issue_receipt(db, tenant, stay, pay, inv)
    from PIL import Image
    import io
    logo = io.BytesIO()
    Image.new("RGB", (300, 100), (30, 122, 90)).save(logo, format="PNG")
    for doc in (inv, rec):
        pdf = invoice_pdf.render(doc, logo=logo.getvalue())
        assert pdf.startswith(b"%PDF-") and len(pdf) > 1500
    assert invoice_pdf.render(inv, logo=b"not an image").startswith(b"%PDF-")      # a bad logo never stops the invoice
    assert rec.kind == "receipt" and rec.invoice_id == inv.id and rec.number.startswith("RCPT/")
    assert invoice_pdf.inr_text(125000) == "Rs. 1,25,000" and invoice_pdf.inr_text(45.5) == "Rs. 45.50"


# ── Endpoints ────────────────────────────────────────────────────────────────

def test_reissue_supersedes_and_numbers_move_on(client, db, tenant_and_user, _no_broker):
    tenant = tenant_and_user["tenant"]
    stay = _setup(db, tenant)
    h = _h(tenant_and_user)
    url = f"/api/v1/bookings/{stay.id}/invoices"
    assert client.get(url, headers=h).json()["invoices"] == []

    first = client.post(f"{url}/reissue", json={}, headers=h)          # no invoice yet: issues the first one
    assert first.status_code == 201, first.text
    assert [i["status"] for i in first.json()["invoices"]] == ["issued"]
    old_number = first.json()["invoices"][0]["number"]

    second = client.post(f"{url}/reissue", json={"place_of_supply": "27", "reason": "Guest is from Mumbai"}, headers=h).json()
    statuses = {i["number"]: i for i in second["invoices"]}
    assert statuses[old_number]["status"] == "superseded"
    new = next(i for i in second["invoices"] if i["status"] == "issued")
    assert new["number"] != old_number and new["supersedes_id"] == statuses[old_number]["id"] and new["igst"] > 0
    assert _no_broker.call_count == 2                                  # PDF rendered by the task, never inline
    actions = [e["action"] for e in client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()["activity"]]
    assert "booking.invoice_reissued" in actions and "booking.invoice_issued" in actions


def test_reissue_without_profile_says_what_is_missing(client, db, tenant_and_user):
    stay = _setup(db, tenant_and_user["tenant"], profile=None)
    r = client.post(f"/api/v1/bookings/{stay.id}/invoices/reissue", json={}, headers=_h(tenant_and_user))
    assert r.status_code == 422 and "Invoice details" in r.json()["detail"]


def test_invoice_endpoints_forbidden_and_cross_tenant(client, db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    stay = _setup(db, tenant)
    inv = invoice_service.issue_invoice(db, tenant, stay)
    db.commit()
    res = _user(db, tenant.id, UserRole.RESERVATIONS)
    assert client.get(f"/api/v1/bookings/{stay.id}/invoices", headers=res).status_code == 200       # bookings.read
    assert client.post(f"/api/v1/bookings/{stay.id}/invoices/reissue", json={}, headers=res).status_code == 403
    mk = _user(db, tenant.id, UserRole.MARKETING)                    # no bookings.read
    assert client.get(f"/api/v1/invoices/{inv.id}/pdf", headers=mk).status_code == 403
    assert client.get(f"/api/v1/bookings/{stay.id}/invoices", headers=mk).status_code == 403

    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    from tests.conftest import seed_capabilities
    seed_capabilities(db, other.id)
    oh = _user(db, other.id, UserRole.OWNER)
    assert client.get(f"/api/v1/bookings/{stay.id}/invoices", headers=oh).status_code == 404
    assert client.post(f"/api/v1/bookings/{stay.id}/invoices/reissue", json={}, headers=oh).status_code == 404
    assert client.get(f"/api/v1/invoices/{inv.id}/pdf", headers=oh).status_code == 404


def test_pdf_link_waits_for_render_then_signs(client, db, tenant_and_user, _no_broker):
    tenant = tenant_and_user["tenant"]
    inv = invoice_service.issue_invoice(db, tenant, _setup(db, tenant))
    db.commit()
    h = _h(tenant_and_user)
    assert client.get(f"/api/v1/invoices/{inv.id}/pdf", headers=h).status_code == 409
    assert _no_broker.called
    inv.pdf_media_key = f"{tenant.id}/invoices/{inv.id}.pdf"
    db.commit()
    with patch("app.services.media_storage.get_presigned_download_url", return_value="https://files.example/x.pdf") as sign:
        r = client.get(f"/api/v1/invoices/{inv.id}/pdf", headers=h).json()
    assert r["url"] == "https://files.example/x.pdf" and r["filename"].startswith("Invoice INV-")
    assert sign.call_args.args[0] == inv.pdf_media_key


def test_settings_roundtrip_audited_and_role_gated(client, db, tenant_and_user):
    h = _h(tenant_and_user)
    r = client.get("/api/v1/settings/invoice-profile", headers=h).json()
    assert r["profile"]["invoice_prefix"] == "INV" and r["payments"]["auto_balance_reminder"] is False
    assert "legal name" in r["missing"] and r["states"]["29"] == "Karnataka"

    bad = client.put("/api/v1/settings/invoice-profile", json={"profile": {**PROFILE, "gstin": "29AAGCB7383J1Z5"}}, headers=h)
    assert bad.status_code == 422
    ok = client.put("/api/v1/settings/invoice-profile",
                    json={"profile": PROFILE, "payments": {"auto_balance_reminder": True}}, headers=h)
    assert ok.status_code == 200 and ok.json()["missing"] == [] and ok.json()["payments"]["auto_balance_reminder"] is True
    db.refresh(tenant_and_user["tenant"])
    assert tenant_and_user["tenant"].brand_config["invoice_profile"]["gstin"] == GSTIN_KA
    from app.models.audit_event import AuditEvent
    assert db.query(AuditEvent).filter_by(tenant_id=tenant_and_user["tenant"].id, action="settings.invoice_profile_updated").count() == 1

    res = _user(db, tenant_and_user["tenant"].id, UserRole.RESERVATIONS)
    assert client.get("/api/v1/settings/invoice-profile", headers=res).status_code == 403
    assert client.put("/api/v1/settings/invoice-profile", json={"profile": PROFILE}, headers=res).status_code == 403

    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    oh = _user(db, other.id, UserRole.OWNER)
    assert client.get("/api/v1/settings/invoice-profile", headers=oh).json()["profile"]["gstin"] is None   # own tenant only


def test_logo_upload_reencodes_and_branding_fallback(client, db, tenant_and_user):
    import base64
    import io
    from PIL import Image
    tenant = tenant_and_user["tenant"]
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (200, 10, 10)).save(buf, format="JPEG")
    tenant.brand_config = {"branding_theme": {"logoUrl": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}
    db.commit()
    h = _h(tenant_and_user)
    assert client.get("/api/v1/settings/invoice-profile", headers=h).json()["logo_source"] == "branding"

    upload = MagicMock(return_value=f"{tenant.id}/invoice_logo/abc.png")
    with patch("app.services.media_storage.upload_invoice_logo", upload), \
         patch("app.services.media_storage.get_presigned_media_url", return_value="https://files.example/logo.png"):
        bad = client.post("/api/v1/settings/invoice-profile/logo", files={"file": ("x.png", b"not an image", "image/png")}, headers=h)
        assert bad.status_code == 422
        r = client.post("/api/v1/settings/invoice-profile/logo", files={"file": ("l.jpg", buf.getvalue(), "image/jpeg")}, headers=h)
    assert r.status_code == 200 and r.json()["logo_source"] == "uploaded"
    assert upload.call_args.args[1].startswith(b"\x89PNG")                 # stored re-encoded as PNG
    assert client.delete("/api/v1/settings/invoice-profile/logo", headers=h).json()["logo_source"] == "branding"
    res = _user(db, tenant.id, UserRole.RESERVATIONS)
    assert client.post("/api/v1/settings/invoice-profile/logo", files={"file": ("l.jpg", buf.getvalue(), "image/jpeg")},
                       headers=res).status_code == 403
    assert client.delete("/api/v1/settings/invoice-profile/logo", headers=res).status_code == 403


def test_dpdp_erasure_keeps_invoices_detached(db, tenant_and_user):
    from app.services.guest_service import dpdp_delete as purge
    tenant = tenant_and_user["tenant"]
    stay = _setup(db, tenant)
    inv = invoice_service.issue_invoice(db, tenant, stay)
    db.commit()
    purge(db, tenant.id, stay.guest_id)
    db.commit()
    kept = db.query(Invoice).filter_by(id=inv.id).first()
    assert kept is not None and kept.stay_id is None and kept.number == inv.number
