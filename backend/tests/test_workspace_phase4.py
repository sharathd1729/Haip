"""Workspace redesign Phase 4: the workspace's own guest details form (guest_form_config), one stay's money ledger and
Ops › Money (ops_money_board), and a booking's thread across modules (record_thread)."""

import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.models.audit_event import AuditEvent
from app.models.ops_files import OpsExpense
from app.models.stay_finance import StayAddOn, StayInstalment, StayPayment, StayPaymentLink
from app.models.tenant import Tenant
from app.schemas.guest_form_config import GuestFormConfig
from app.schemas.ops_fleet import GuestFormIn
from app.services import guest_form_config, ops_money_board, record_thread
from app.services import ops_guest_form as gf
from app.services import ops_trip_service as trips
from app.services.booking_agenda_service import tenant_today
from tests.ops_helpers import prop
from tests.test_dashboard_tabs import _role, _world
from tests.test_ops_files import _stay, _tenant
from tests.test_ops_guest_form import OK

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

Q_PET = {"id": "pet00001", "label": "Bringing a pet?", "kind": "yesno", "required": True}
Q_TIME = {
    "id": "time0001",
    "label": "What time will you reach?",
    "kind": "choice",
    "options": ["Before 2 pm", "2 to 6 pm"],
}


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


# ── guest form config ────────────────────────────────────────────────────────


def test_defaults_ask_what_the_form_always_asked():
    d = gf.build(GuestFormIn(**OK), cfg=GuestFormConfig())
    assert d["emergency_name"] == "Ravi" and d["answers"] == []
    with pytest.raises(HTTPException) as e:
        gf.build(GuestFormIn(**{**OK, "emergency_name": ""}))
    assert "Emergency contact name is required" in e.value.detail


def test_switched_off_questions_are_not_checked_or_kept_and_own_questions_are():
    cfg = GuestFormConfig(emergency="off", food="off", age="req", questions=[Q_PET, Q_TIME])
    body = {
        **OK,
        "emergency_name": "",
        "emergency_phone": "",
        "food": "veg",
        "answers": {"pet00001": "YES", "time0001": "2 to 6 pm", "zzz": "ignored"},
    }
    d = gf.build(GuestFormIn(**body), cfg=cfg)
    assert d["emergency_name"] == "" and d["food"] == ""
    assert d["answers"] == [
        {"id": "pet00001", "label": "Bringing a pet?", "kind": "yesno", "value": "Yes"},
        {"id": "time0001", "label": "What time will you reach?", "kind": "choice", "value": "2 to 6 pm"},
    ]
    with pytest.raises(HTTPException) as e:
        gf.build(
            GuestFormIn(**{**body, "guests": [{**OK["guests"][0], "age": ""}], "answers": {"time0001": "Midnight"}}),
            cfg=cfg,
        )
    assert "age is required" in e.value.detail and "Please answer: Bringing a pet?" in e.value.detail
    assert "choose one of the options" in e.value.detail


def test_config_schema_refuses_bad_questions_and_links():
    with pytest.raises(ValueError):
        GuestFormConfig(questions=[{**Q_TIME, "options": ["Only one"]}])
    with pytest.raises(ValueError):
        GuestFormConfig(rules_url="http://plain.example.com/rules")
    with pytest.raises(ValueError):
        GuestFormConfig(questions=[Q_PET, Q_PET])


def test_config_endpoint_saves_audits_and_needs_ops_manage(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    r = client.get("/api/v1/ops/guest-form/config", headers=_h(tenant_and_user))
    assert r.status_code == 200 and r.json()["config"]["emergency"] == "req" and len(r.json()["always"]) == 4
    body = {**GuestFormConfig().model_dump(), "food": "off", "questions": [Q_PET], "welcome": "Help us  get ready"}
    r = client.put("/api/v1/ops/guest-form/config", json=body, headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    assert r.json()["config"]["welcome"] == "Help us get ready" and r.json()["changed"] == [
        "food",
        "questions",
        "welcome",
    ]
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="ops.guest_form_changed").count() == 1
    assert client.put("/api/v1/ops/guest-form/config", json=body, headers=_role(db, tid, "foh")).status_code == 403
    assert client.patch(
        "/api/v1/tenants/me", json={"brand_config": {"guest_form": {}}}, headers=_h(tenant_and_user)
    ).status_code in (400, 403, 422)


def test_config_is_per_workspace(db, tenant_and_user):
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    guest_form_config.update(db, other, None, GuestFormConfig(emergency="off"))
    db.commit()
    mine = db.get(Tenant, _tid(tenant_and_user))
    assert guest_form_config.get(mine).emergency == "req" and guest_form_config.get(other).emergency == "off"


def test_guest_page_shows_the_form_and_submit_keeps_answers(client, db):
    t = _tenant(db)
    stay = _stay(db, t, prop(db, t.id, "Ratha 1"))
    f = trips.ensure_file(db, t.id, stay)
    guest_form_config.update(db, t, None, GuestFormConfig(questions=[Q_PET], welcome="Hello"))
    form = gf.ensure_form(db, f)
    db.commit()
    view = gf.public_view(db, form)
    assert view["form"]["welcome"] == "Hello" and view["form"]["questions"][0]["id"] == "pet00001"
    gf.submit(db, form, GuestFormIn(**{**OK, "answers": {"pet00001": "no"}}))
    db.commit()
    staff = gf.staff_view(db, f, with_link=False)
    assert staff["answers"] == [{"id": "pet00001", "label": "Bringing a pet?", "kind": "yesno", "value": "No"}]


# ── money ───────────────────────────────────────────────────────────────────


def test_stay_ledger_lists_every_dated_line(db):
    t = _tenant(db)
    stay = _stay(db, t, prop(db, t.id, "Ratha 1"))
    f = trips.ensure_file(db, t.id, stay)
    today = tenant_today(db, t.id)
    db.add(
        StayPayment(
            tenant_id=t.id,
            stay_id=stay.id,
            kind="payment",
            amount=12000,
            method="upi",
            reference="UTR431892",
            paid_on=today - timedelta(days=3),
        )
    )
    db.add(
        StayPaymentLink(
            tenant_id=t.id,
            stay_id=stay.id,
            external_id="plink_9",
            short_url="https://rzp.io/a",
            amount=5000,
            status="created",
        )
    )
    db.add(StayAddOn(tenant_id=t.id, stay_id=stay.id, name="Bonfire", quantity=2, unit_price=1250))
    db.add(
        OpsExpense(tenant_id=t.id, file_id=f.id, category="groceries", amount=3150, bill_date=today - timedelta(days=1))
    )
    db.add(
        StayInstalment(
            tenant_id=t.id, stay_id=stay.id, label="Advance", amount=12000, due_date=today - timedelta(days=5)
        )
    )
    db.commit()
    out = ops_money_board.stay_ledger(db, f)
    kinds = {line["kind"]: line for line in out["lines"]}
    assert set(kinds) == {"payment", "link", "extra", "expense"}
    assert kinds["payment"]["detail"] == "…1892" and kinds["payment"]["sign"] == 1
    assert kinds["extra"]["amount"] == 2500.0 and kinds["expense"]["sign"] == -1
    assert out["schedule"][0]["status"] == "paid" and out["booking_id"] == stay.id


def test_board_numbers_and_rows(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _, late, soon = _world(db, tid)
    today = tenant_today(db, tid)
    out = ops_money_board.board(db, tid, today, None, money=True)
    tot = out["totals"]
    assert tot["overdue"] == {"count": 1, "amount": 30000.0}
    assert tot["due_week"]["count"] == 1 and tot["deposits"]["held"] == 1 and tot["deposits"]["to_give_back"] == 1
    assert out["rows"][0]["booking_id"] == late.id and out["rows"][0]["overdue"] is True
    hidden = ops_money_board.board(db, tid, today, None, money=False)
    assert hidden["money_restricted"] is True and hidden["totals"]["overdue"]["amount"] is None
    assert all(r["balance"] is None for r in hidden["rows"])


def test_board_never_shows_another_workspace(client, db, tenant_and_user):
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _world(db, other.id)
    r = client.get("/api/v1/ops/money", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [] and r.json()["totals"]["collected"]["count"] == 0
    assert client.get("/api/v1/ops/money", headers=_role(db, _tid(tenant_and_user), "marketing")).status_code == 403


# ── a booking's thread ──────────────────────────────────────────────────────


def test_booking_thread_steps_and_cross_tenant(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _, late, _ = _world(db, tid)
    r = client.get(f"/api/v1/bookings/{late.id}/thread", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    steps = {s["key"]: s for s in r.json()["steps"]}
    assert list(steps) == ["enquiry", "chats", "quote", "booking", "money", "form", "ops", "review"]
    assert steps["money"]["state"] == "due" and "overdue" in steps["money"]["value"]
    assert steps["booking"]["state"] == "current" and r.json()["linked"][0]["href"].startswith("/dashboard/guests/")
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _, theirs, _ = _world(db, other.id)
    assert client.get(f"/api/v1/bookings/{theirs.id}/thread", headers=_h(tenant_and_user)).status_code == 404


def test_thread_hides_amounts_when_told(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _, late, _ = _world(db, tid)
    out = record_thread.for_booking(db, tid, late, money=False)
    money = next(s for s in out["steps"] if s["key"] == "money")
    assert "₹" not in money["value"] and out["money_restricted"] is True
