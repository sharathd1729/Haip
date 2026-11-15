"""Yaad shows contact names, not bare numbers: the Yaad app sends the name saved in the phone's contacts with each call
(and once for numbers already sent); a personal workspace puts it on the person. A business workspace ignores it (staff
address books never reach HAIP). Made-up data only."""

from app.models.call import Call
from app.models.guest import Guest
from app.services import identity_service
from tests.test_mobile_devices import _call, _register, _run_ingest, _user, queued  # noqa: F401
from tests.test_personal_calls import _auth, _personal, _tid

NUMBER = "+919811100001"


def _dev(client, db, tid):
    _, staff_h = _user(db, tid)
    return {"Authorization": f"Bearer {_register(client, staff_h)['token']}"}


def _name_of(db, tid, number=NUMBER):
    gid = identity_service.find_person_by_phone(db, tid, number)
    return db.get(Guest, gid).name if gid else None


def test_saved_name_names_the_person_and_their_call(client, db, tenant_and_user, queued, monkeypatch):  # noqa: F811
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    dev = _dev(client, db, tid)
    body = {"calls": [{**_call(number=NUMBER), "contact_name": "Kavya Menon"}]}
    assert client.post("/api/v1/device-calls", json=body, headers=dev).json()["counts"] == {"queued": 1}
    assert _name_of(db, tid) == "Kavya Menon"
    _run_ingest(monkeypatch, db, queued)
    call = db.query(Call).filter_by(tenant_id=tid).one()
    assert db.get(Guest, call.guest_id).name == "Kavya Menon"  # the call landed on the named person, no second guest
    page = client.get("/api/v1/me/calls", headers=_auth(tenant_and_user)).json()
    assert page["calls"][0]["contact"] == "Kavya Menon"


def test_catch_up_renames_and_ignores_placeholders(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    dev = _dev(client, db, tid)
    names = [
        {"number": NUMBER, "name": "Kavya"},
        {"number": "+919811100002", "name": "+91 98111 00002"},
        {"number": "not a number", "name": "Nobody"},
    ]
    r = client.post("/api/v1/device-calls/names", json={"names": names}, headers=dev)
    assert r.status_code == 200 and r.json() == {"renamed": 1}
    assert _name_of(db, tid) == "Kavya" and _name_of(db, tid, "+919811100002") is None
    again = client.post(
        "/api/v1/device-calls/names", json={"names": [{"number": NUMBER, "name": "Kavya Menon"}]}, headers=dev
    )
    assert again.json() == {"renamed": 1} and _name_of(db, tid) == "Kavya Menon"  # the address book wins


def test_business_workspace_never_keeps_staff_contact_names(client, db, tenant_and_user, queued):  # noqa: F811
    tid = _tid(tenant_and_user)
    dev = _dev(client, db, tid)
    body = {"calls": [{**_call(number=NUMBER), "contact_name": "Kavya Menon"}]}
    client.post("/api/v1/device-calls", json=body, headers=dev)
    assert client.post(
        "/api/v1/device-calls/names", json={"names": [{"number": NUMBER, "name": "X Y"}]}, headers=dev
    ).json() == {"renamed": 0}
    assert db.query(Guest).filter_by(tenant_id=tid, name="Kavya Menon").count() == 0


def test_names_stay_in_their_workspace(client, db, tenant_and_user):
    from tests.test_mobile_devices import _other_tenant

    tid = _tid(tenant_and_user)
    _personal(db, tid)
    other = _other_tenant(db)
    _personal(db, other.id)
    theirs = _dev(client, db, other.id)
    client.post("/api/v1/device-calls/names", json={"names": [{"number": NUMBER, "name": "Kavya"}]}, headers=theirs)
    assert _name_of(db, other.id) == "Kavya" and _name_of(db, tid) is None
    assert client.post("/api/v1/device-calls/names", json={"names": []}, headers=theirs).status_code == 422
    assert (
        client.post("/api/v1/device-calls/names", json={"names": [{"number": NUMBER, "name": "K"}]}).status_code == 401
    )
