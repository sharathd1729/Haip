"""The trip's guest ID form (migration 180): the prototype's guestform tests ported (Aadhaar keeps 4 digits, every problem at
once, party size, token lookup), the public link API, the readiness item turning green, the staff endpoints (roles,
cross-tenant) and DPDP erasure."""

import pytest
from fastapi import HTTPException

from app.models.ops_fleet import OpsGuestForm
from app.models.user import UserRole
from app.schemas.ops_fleet import CONSENT_VERSION, GuestFormIn
from app.services import dpdp_erasure_service
from app.services import ops_guest_form as gf
from app.services import ops_trip_service as trips
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop
from tests.test_increment1_defect_specs import _h, _user
from tests.test_ops_files import _actor_u1, _stay, _tenant  # noqa: F401

OK = {
    "guests": [{"name": "Asha Rao", "age": "34", "id_type": "aadhaar", "id_number": "1234 5678 9012"}],
    "emergency_name": "Ravi",
    "emergency_phone": "+91 98000 00000",
    "signed_name": "Asha Rao",
    "agreed": True,
    "consent_version": CONSENT_VERSION,
}


@pytest.fixture()
def w(db):
    t = _tenant(db)
    p = prop(db, t.id, "Ratha 1")
    stay = _stay(db, t, p)
    f = trips.ensure_file(db, t.id, stay)
    db.commit()
    return type("W", (), {"t": t, "p": p, "stay": stay, "f": f})()


def test_aadhaar_keeps_only_the_last_4_digits_others_keep_the_number():
    d = gf.build(GuestFormIn(**OK))
    assert d["guests"][0]["id_number"] == "9012" and gf.mask_id(d["guests"][0]) == "XXXX XXXX 9012"
    p = gf.build(GuestFormIn(**{**OK, "guests": [{"name": "B", "id_type": "passport", "id_number": "k1234567"}]}))
    assert p["guests"][0]["id_number"] == "K1234567" and gf.mask_id(p["guests"][0]) == "••••4567"


def test_every_problem_is_reported_at_once():
    bad = {
        **OK,
        "guests": [{"name": "", "age": "200", "id_type": "aadhaar", "id_number": "123"}],
        "agreed": False,
        "signed_name": "",
        "emergency_phone": "12",
    }
    with pytest.raises(HTTPException) as e:
        gf.build(GuestFormIn(**bad))
    for words in ("name is required", "12 digits", "age looks wrong", "terms", "sign", "Emergency contact phone"):
        assert words in e.value.detail


def test_party_size_and_token_lookup(db, w):
    assert gf.party_count(6, 2) == 8 and gf.party_count(0, 0) == 1 and gf.party_count(20, 0) == 12
    form = gf.ensure_form(db, w.f)
    assert gf.ensure_form(db, w.f).id == form.id
    token = gf.token_for(form)
    assert form.token_hash != token and gf.by_token(db, token).id == form.id
    assert gf.link(form).endswith(f"/r/trip/{token}")
    with pytest.raises(HTTPException):
        gf.by_token(db, "nope")


def test_public_form_fills_and_turns_the_guests_check_green(client, db, w):
    form = gf.ensure_form(db, w.f)
    db.commit()
    token = gf.token_for(form)
    r = client.get(f"/api/v1/public/ops/guest-form/{token}")
    assert r.status_code == 200 and r.json()["party"] == 8 and r.json()["consent"]["version"] == CONSENT_VERSION
    assert "phone" not in str(r.json())
    r = client.post(f"/api/v1/public/ops/guest-form/{token}", json={**OK, "agreed": False})
    assert r.status_code == 422 and "terms" in r.text
    assert client.post(f"/api/v1/public/ops/guest-form/{token}", json=OK).status_code == 200
    db.expire_all()
    item = next(i for i in trips.readiness_items(db, w.f) if i.key == "guests")
    assert item.status == "green"
    saved = db.query(OpsGuestForm).filter_by(id=form.id).one()
    assert saved.data["guests"][0]["id_number"] == "9012" and saved.consent_version == CONSENT_VERSION
    assert client.get("/api/v1/public/ops/guest-form/bad-token").status_code == 404


@pytest.fixture()
def api(db, w):
    seed_capabilities(db, w.t.id)
    return type("A", (), {"foh": _user(db, w.t.id, UserRole.FOH), "mkt": _user(db, w.t.id, UserRole.MARKETING)})()


def test_staff_link_roles_and_tenants(client, db, w, api):
    r = client.post(f"/api/v1/ops/files/{w.f.id}/guest-form/link", headers=_h(api.foh))
    assert r.status_code == 200 and "/r/trip/" in r.json()["url"]
    assert client.post(f"/api/v1/ops/files/{w.f.id}/guest-form/link", headers=_h(api.mkt)).status_code == 403
    other = _tenant(db)
    seed_capabilities(db, other.id)
    om = _user(db, other.id, UserRole.MANAGER)
    assert client.post(f"/api/v1/ops/files/{w.f.id}/guest-form/link", headers=_h(om)).status_code == 404
    # window closed (no WhatsApp from the guest yet): not sent, the reason is said
    r = client.post(f"/api/v1/ops/files/{w.f.id}/guest-form/send", headers=_h(api.foh))
    assert r.status_code == 409 and "Copy the link" in r.json()["detail"]


def test_submitted_form_shows_masked_on_the_trip_file(client, db, w, api):
    form = gf.ensure_form(db, w.f)
    gf.submit(db, form, GuestFormIn(**OK))
    db.commit()
    g = client.get(f"/api/v1/ops/files/{w.f.id}", headers=_h(api.foh)).json()["guest_form"]
    assert g["guests"][0]["id"] == "Aadhaar XXXX XXXX 9012" and g["link"] is None


def test_dpdp_erasure_removes_the_form(db, w):
    gf.submit(db, gf.ensure_form(db, w.f), GuestFormIn(**OK))
    db.commit()
    out = dpdp_erasure_service.erase_guest(db, w.t.id, w.stay.guest_id)
    assert out["rows"]["ops_guest_forms"] == 1
    assert db.query(OpsGuestForm).filter_by(tenant_id=w.t.id).count() == 0
