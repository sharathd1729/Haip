"""Ops gap 5 (Nov 2026): the guest ID form for every pack (villa stays too) and guests from abroad (passport + visa,
encrypted numbers, private photos), the Form C helper (one ops item per guest due arrival + 24 h, the copyable sheet, the
audited reveal, the "Submitted on the portal" tick), DPDP erasure, the website hint, roles and tenants."""

import json
from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.audit_event import AuditEvent
from app.models.ops import OpsItem
from app.models.ops_fleet import OpsGuestForm
from app.models.user import UserRole
from app.schemas.ops_files import CheckInIn
from app.schemas.ops_fleet import CONSENT_VERSION, GuestFormIn
from app.services import dpdp_erasure_service, media_storage, website_booking_service
from app.services import ops_form_c as fc
from app.services import ops_guest_form as gf
from app.services import ops_stay_service as stays
from app.services import ops_today_service as today_svc
from app.services import ops_trip_service as trips
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop
from tests.test_increment1_defect_specs import _h, _user
from tests.test_ops_files import TODAY, _actor_u1, _stay, _tenant  # noqa: F401 (_actor_u1 is an autouse fixture)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
PASSPORT, VISA = "K1234567", "VX99887766"
BASE = {
    "emergency_name": "Ravi",
    "emergency_phone": "+91 98000 00000",
    "signed_name": "Sample Guest",
    "agreed": True,
    "consent_version": CONSENT_VERSION,
}
INDIAN = {"name": "Asha Rao", "age": "34", "nationality": "IN", "id_type": "aadhaar", "id_number": "1234 5678 9012"}


def _abroad(**over) -> dict:
    g = {
        "name": "Sam Lee",
        "age": "41",
        "nationality": "GB",
        "passport_number": PASSPORT,
        "passport_expires_on": (TODAY + timedelta(days=900)).isoformat(),
        "visa_type": "e_tourist",
        "visa_number": VISA,
        "visa_expires_on": (TODAY + timedelta(days=60)).isoformat(),
        "arrived_india_on": TODAY.isoformat(),
        "arrived_from": "London, UK",
        "onward_to": "Goa, India",
        "passport_photo_id": "",
        "visa_photo_id": "",
    }
    return {**g, **over}


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """The public tier is 30/min per IP; this file makes many more calls from the test client's one address."""
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)):
        yield


@pytest.fixture()
def store(monkeypatch):
    """Private storage, faked: what was put, and what was deleted."""
    out = {"put": {}, "deleted": []}
    monkeypatch.setattr(media_storage, "_put", lambda key, content, ct: out["put"].__setitem__(key, ct))
    monkeypatch.setattr(media_storage, "get_presigned_media_url", lambda key, expires_in=3600: f"https://signed/{key}")
    monkeypatch.setattr(
        media_storage, "delete_tenant_objects", lambda tid, keys: out["deleted"].extend(keys) or len(keys)
    )
    return out


@pytest.fixture()
def v(db):
    t = _tenant(db, "villa_resort")
    p = prop(db, t.id, "Villa Amara")
    stay = _stay(db, t, p, start=0, nights=3)
    f = trips.ensure_file(db, t.id, stay)
    seed_capabilities(db, t.id)
    db.commit()
    return type(
        "V",
        (),
        {
            "t": t,
            "p": p,
            "stay": stay,
            "f": f,
            "mgr": _user(db, t.id, UserRole.MANAGER),
            "foh": _user(db, t.id, UserRole.FOH),
        },
    )()


def _photos(client, token) -> tuple[str, str]:
    url = f"/api/v1/public/ops/guest-form/{token}/photo"
    ids = []
    for kind in ("passport", "visa"):
        r = client.post(url, data={"kind": kind}, files={"file": (f"{kind}.png", PNG, "image/png")})
        assert r.status_code == 201, r.text
        ids.append(r.json()["photo_id"])
    return ids[0], ids[1]


def _filled(client, db, v) -> OpsGuestForm:
    form = gf.ensure_form(db, v.f)
    db.commit()
    token = gf.token_for(form)
    pid, vid = _photos(client, token)
    body = {**BASE, "guests": [INDIAN, _abroad(passport_photo_id=pid, visa_photo_id=vid)]}
    r = client.post(f"/api/v1/public/ops/guest-form/{token}", json=body)
    assert r.status_code == 200, r.text
    db.expire_all()
    return db.query(OpsGuestForm).filter_by(id=form.id).one()


def _welcome(db, v):
    for i in trips.readiness_items(db, v.f):
        if i.critical and i.source != "system":
            stays.set_item(db, v.f, i.key, "green", None, user_id="u1")
    stays.check_in(db, v.f, CheckInIn(keys_handed=True, deposit_collected=False), "u1")
    db.commit()


# ── The form, every pack ────────────────────────────────────────────────────


def test_villa_stay_gets_a_form_link_worded_for_a_stay(client, db, v):
    r = client.post(f"/api/v1/ops/files/{v.f.id}/guest-form/link", headers=_h(v.foh))
    assert r.status_code == 200 and "/r/stay/" in r.json()["url"]
    token = r.json()["url"].rsplit("/", 1)[-1]
    view = client.get(f"/api/v1/public/ops/guest-form/{token}").json()
    assert view["file_word"] == "stay" and view["unit_word"] == "villa" and view["place"] == "Villa Amara"
    assert "register this stay" in view["consent"]["text"] and "Form C" in view["consent"]["text"]
    assert "IN" in view["countries"] and {"value": "oci", "label": "OCI card (no visa)"} in view["visa_types"]


def test_indian_guest_needs_no_passport_fields_and_none_are_stored():
    d = gf.build(GuestFormIn(**BASE, guests=[{**INDIAN, "passport_number": PASSPORT, "visa_number": VISA}]))
    g = d["guests"][0]
    assert "foreign" not in g and g["id_number"] == "9012" and PASSPORT not in json.dumps(d)


def test_foreign_guest_must_give_passport_visa_travel_and_photos():
    bad = _abroad(
        passport_number="",
        visa_type="",
        visa_number="",
        passport_expires_on="",
        visa_expires_on="",
        arrived_india_on="",
        arrived_from="",
        onward_to="",
    )
    with pytest.raises(HTTPException) as e:
        gf.build(GuestFormIn(**BASE, guests=[bad]), today=TODAY)
    for words in (
        "passport number",
        "passport expiry is required",
        "visa type",
        "visa number",
        "visa expiry",
        "arrival in India",
        "arrived in India from",
        "go after this",
        "photo of the passport",
        "photo of the visa",
    ):
        assert words in e.value.detail, words
    with pytest.raises(HTTPException) as e:  # an expired passport is refused
        gf.build(
            GuestFormIn(**BASE, guests=[_abroad(passport_expires_on=(TODAY - timedelta(days=1)).isoformat())]),
            today=TODAY,
        )
    assert "passport expiry has passed" in e.value.detail
    with pytest.raises(HTTPException) as e:
        gf.build(GuestFormIn(**BASE, guests=[_abroad(nationality="XX")]))
    assert "choose a nationality" in e.value.detail


def test_nepal_and_bhutan_need_no_visa():
    uploads = {"p1": {"key": "t/ops/guest_forms/f/p1.png", "kind": "passport"}}
    d = gf.build(
        GuestFormIn(
            **BASE,
            guests=[
                _abroad(nationality="NP", visa_type="", visa_number="", visa_expires_on="", passport_photo_id="p1")
            ],
        ),
        uploads,
        TODAY,
    )
    fb = d["guests"][0]["foreign"]
    assert fb["visa_type"] is None and fb["visa_last4"] is None and fb["passport_last4"] == "4567"


def test_foreign_guest_numbers_are_encrypted_and_photos_private(client, db, v, store):
    form = _filled(client, db, v)
    raw = json.dumps(form.data)
    assert PASSPORT not in raw and VISA not in raw  # only ciphertext + the last 4 digits
    g = form.data["guests"][1]
    assert g["foreign"]["passport_last4"] == "4567" and gf.numbers(g) == {"passport": PASSPORT, "visa": VISA}
    keys = gf.file_keys(form)
    assert len(keys) == 2 and all(k.startswith(f"{v.t.id}/ops/guest_forms/{form.id}/") for k in keys)
    assert set(keys) <= set(store["put"]) and "uploads" not in form.data
    staff = client.get(f"/api/v1/ops/files/{v.f.id}", headers=_h(v.foh)).json()["guest_form"]
    assert staff["from_abroad"] == 1 and staff["guests"][1]["foreign"]["passport"] == "••••4567"
    assert PASSPORT not in json.dumps(staff) and "signed" not in json.dumps(staff["guests"])


def test_a_replaced_photo_is_deleted_and_a_sent_form_takes_no_more(client, db, v, store):
    form = gf.ensure_form(db, v.f)
    db.commit()
    token = gf.token_for(form)
    _photos(client, token)  # these two are replaced before sending
    pid, vid = _photos(client, token)
    body = {**BASE, "guests": [_abroad(passport_photo_id=pid, visa_photo_id=vid)]}
    assert client.post(f"/api/v1/public/ops/guest-form/{token}", json=body).status_code == 200
    assert len(store["deleted"]) == 2
    r = client.post(
        f"/api/v1/public/ops/guest-form/{token}/photo",
        data={"kind": "passport"},
        files={"file": ("p.png", PNG, "image/png")},
    )
    assert r.status_code == 409
    assert client.post(f"/api/v1/public/ops/guest-form/{token}", json=body).status_code == 409
    r = client.post(
        f"/api/v1/public/ops/guest-form/{gf.token_for(form)}x/photo",
        data={"kind": "passport"},
        files={"file": ("p.png", PNG, "image/png")},
    )
    assert r.status_code == 404


def test_photo_upload_keeps_the_paper_limits(client, db, v, store):
    form = gf.ensure_form(db, v.f)
    db.commit()
    url = f"/api/v1/public/ops/guest-form/{gf.token_for(form)}/photo"
    r = client.post(url, data={"kind": "passport"}, files={"file": ("p.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 422 and "JPG, PNG, WebP or PDF" in r.text
    r = client.post(url, data={"kind": "passport"}, files={"file": ("p.png", b"not a png", "image/png")})
    assert r.status_code == 422
    r = client.post(url, data={"kind": "selfie"}, files={"file": ("p.png", PNG, "image/png")})
    assert r.status_code == 422 and not store["put"]


# ── Form C ──────────────────────────────────────────────────────────────────


def test_form_c_item_is_due_24_hours_after_check_in(client, db, v, store):
    _filled(client, db, v)
    v.stay.check_in = TODAY + timedelta(days=1)  # not arrived yet: nothing raised on submit
    db.commit()
    assert fc.sync(db, v.f) == [] and db.query(OpsItem).filter_by(tenant_id=v.t.id, category="form_c").count() == 0
    v.stay.check_in = TODAY
    _welcome(db, v)
    items = db.query(OpsItem).filter_by(tenant_id=v.t.id, category="form_c").all()
    assert len(items) == 1  # the Indian guest needs none
    it = items[0]
    arrived = v.f.dispatched_at if v.f.dispatched_at.tzinfo else v.f.dispatched_at.replace(tzinfo=UTC)
    due = it.resolve_due_at if it.resolve_due_at.tzinfo else it.resolve_due_at.replace(tzinfo=UTC)
    assert due == arrived + timedelta(hours=24) and it.severity == "high" and it.duty == "ops_manager"
    assert "FRRO" in it.summary and "Sam" not in (it.summary + it.title) and PASSPORT not in it.summary
    fc.sync(db, v.f)
    db.commit()
    assert db.query(OpsItem).filter_by(tenant_id=v.t.id, category="form_c").count() == 1  # idempotent
    need = next(n for n in today_svc.build(db, v.t.id)["needs"] if n.get("item_id") == it.id)
    assert need["action"] == "open_file" and need["file_id"] == v.f.id


def test_the_check_in_date_arriving_raises_it_hourly(client, db, v, store):
    _filled(client, db, v)
    v.stay.check_in_time = "10:00"
    db.commit()
    from app.core.tenant_tz import get_tz

    tz = get_tz(v.t)
    assert fc.run_tenant(db, v.t.id, now=datetime.combine(TODAY, time(9, 0), tzinfo=tz)) == 0
    other = _tenant(db, "villa_resort")  # another workspace's file is never touched
    fc.run_tenant(db, other.id, now=datetime.combine(TODAY, time(11, 0), tzinfo=tz))
    assert db.query(OpsItem).filter_by(category="form_c").count() == 0
    fc.run_tenant(db, v.t.id, now=datetime.combine(TODAY, time(11, 0), tzinfo=tz))
    it = db.query(OpsItem).filter_by(tenant_id=v.t.id, category="form_c").one()
    due = it.resolve_due_at if it.resolve_due_at.tzinfo else it.resolve_due_at.replace(tzinfo=UTC)
    assert due == datetime.combine(TODAY, time(10, 0), tzinfo=tz) + timedelta(hours=24)


def test_ticking_submitted_closes_the_item(client, db, v, store):
    _filled(client, db, v)
    _welcome(db, v)
    url = f"/api/v1/ops/files/{v.f.id}/guest-form/guests/2/form-c/submitted"
    assert client.post(url, json={}, headers=_h(v.foh)).status_code == 403  # a manager ticks it
    r = client.post(url, json={"note": "ack 123"}, headers=_h(v.mgr))
    assert r.status_code == 200 and r.json()["submitted_at"]
    db.expire_all()
    it = db.query(OpsItem).filter_by(tenant_id=v.t.id, category="form_c").one()
    assert it.status == "resolved" and it.resolved_by_user_id == v.mgr.id
    assert db.query(AuditEvent).filter_by(tenant_id=v.t.id, action="ops.form_c.submitted").count() == 1
    assert client.post(url, json={}, headers=_h(v.mgr)).status_code == 409
    bad = f"/api/v1/ops/files/{v.f.id}/guest-form/guests/1/form-c/submitted"  # guest 1 is Indian
    assert client.post(bad, json={}, headers=_h(v.mgr)).status_code == 404


def test_sheet_is_masked_and_the_reveal_needs_pii_rights_and_is_audited(client, db, v, store):
    _filled(client, db, v)
    base = f"/api/v1/ops/files/{v.f.id}/guest-form/guests/2/form-c"
    s = client.get(base, headers=_h(v.foh)).json()
    rows = {r["key"]: r for r in s["fields"]}
    assert (
        s["can_reveal"] is False
        and rows["passport_number"]["value"] == "••••4567"
        and rows["passport_number"]["masked"]
    )
    assert rows["surname"]["value"] == "Lee" and rows["nationality"]["value"] == "GB" and "FRRO" in s["note"]
    assert s["photos"] == [] and PASSPORT not in json.dumps(s)
    assert client.post(f"{base}/reveal", headers=_h(v.foh)).status_code == 403
    assert db.query(AuditEvent).filter_by(tenant_id=v.t.id, action="guest.passport.reveal").count() == 0
    assert client.get(base, headers=_h(v.mgr)).json()["can_reveal"] is True
    r = client.post(f"{base}/reveal", headers=_h(v.mgr)).json()
    rows = {x["key"]: x for x in r["fields"]}
    assert rows["passport_number"]["value"] == PASSPORT and rows["visa_number"]["value"] == VISA
    assert [p["kind"] for p in r["photos"]] == ["passport", "visa"] and r["photos"][0]["url"].startswith(
        "https://signed/"
    )
    audit = db.query(AuditEvent).filter_by(tenant_id=v.t.id, action="guest.passport.reveal").one()
    assert audit.actor_user_id == v.mgr.id and PASSPORT not in json.dumps(audit.payload)


def test_form_c_endpoints_refuse_other_workspaces_and_other_roles(client, db, v, store):
    _filled(client, db, v)
    other = _tenant(db, "villa_resort")
    seed_capabilities(db, other.id)
    om = _user(db, other.id, UserRole.MANAGER)
    base = f"/api/v1/ops/files/{v.f.id}/guest-form/guests/2/form-c"
    assert client.get(base, headers=_h(om)).status_code == 404
    assert client.post(f"{base}/reveal", headers=_h(om)).status_code == 404
    assert client.post(f"{base}/submitted", json={}, headers=_h(om)).status_code == 404
    mkt = _user(db, v.t.id, UserRole.MARKETING)  # no ops rights at all
    assert client.get(base, headers=_h(mkt)).status_code == 403


def test_website_hint_raises_form_c_even_without_the_form(db, v, store):
    assert website_booking_service._form_c_covers(db, v.t.id, v.stay) is True
    form = db.query(OpsGuestForm).filter_by(file_id=v.f.id).one()
    assert form.data["hint_foreign"] is True and gf.public_view(db, form)["guest_from_abroad"] is True
    _welcome(db, v)
    it = db.query(OpsItem).filter_by(tenant_id=v.t.id, category="form_c").one()
    assert "not filled" in it.summary
    other = _tenant(db, "travel_agency")  # no ops pack: the caller keeps its own reminder task
    assert (
        website_booking_service._form_c_covers(db, other.id, _stay(db, other, prop(db, other.id, "H")))
        is False
    )


# ── DPDP ────────────────────────────────────────────────────────────────────


def test_dpdp_erasure_removes_passport_data_and_photos(client, db, v, store):
    form = _filled(client, db, v)
    _welcome(db, v)
    keys = gf.file_keys(form)
    out = dpdp_erasure_service.erase_guest(db, v.t.id, v.stay.guest_id)
    assert out["rows"]["ops_guest_forms"] == 1 and set(keys) <= set(out["files"])
    assert out["rows"]["ops_items_detached"] >= 1
    assert db.query(OpsGuestForm).filter_by(tenant_id=v.t.id).count() == 0
    it = db.query(OpsItem).filter_by(tenant_id=v.t.id, category="form_c").one()
    assert it.stay_id is None and it.guest_id is None and it.summary is None


def test_arrival_is_none_before_the_check_in_date(db, v):
    v.stay.check_in = date.today() + timedelta(days=5)
    assert fc.arrival_at(db, v.f, v.stay) is None
