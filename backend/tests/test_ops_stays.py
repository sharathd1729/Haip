"""Ops files, villa pack (phase 4): the stay state machine end to end, deposit refund / deduct, meal plan, villa staff
photos (zones, chlorine reading, check-out vs arrival), Ops Today for villas, the report, and the API (happy, wrong role,
cross-tenant). Caravan behaviour is covered by test_ops_files / test_ops_today (unchanged).
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.audit_event import AuditEvent
from app.models.ops import OpsItem
from app.models.ops_files import OpsExpense, OpsJob
from app.models.stay_finance import StayDeposit
from app.models.user import UserRole
from app.schemas.ops_files import CheckInIn, DepositDecisionIn, ExpenseIn, Meal, MealIn, PeopleIn
from app.services import ops_money as money
from app.services import ops_pack_catalog as packs
from app.services import ops_photo_intake as intake
from app.services import ops_stay_meals as meals
from app.services import ops_stay_photos as photos
from app.services import ops_stay_report, ops_trip_report
from app.services import ops_stay_service as stays
from app.services import ops_today_service as today_svc
from app.services import ops_trip_service as trips
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, staff
from tests.test_increment1_defect_specs import _h, _user
from tests.test_ops_files import TODAY, _actor_u1, _pay, _stay, _tenant  # noqa: F401 (_actor_u1 is an autouse fixture)
from tests.test_ops_photo_intake import RAW, _Model, _store


@pytest.fixture()
def v(db):
    t = _tenant(db, "villa_resort")
    p = prop(db, t.id, "Villa Amara")
    return type(
        "V",
        (),
        {
            "t": t,
            "p": p,
            "stay": _stay(db, t, p, start=1, nights=6, total="60000"),
            "caretaker": staff(db, t.id, "Manju", "caretaker", property_id=p.id),
            "cook": staff(db, t.id, "Lakshmi", "fnb"),
            "cleaner": staff(db, t.id, "Ravi", "housekeeping", property_id=p.id),
        },
    )()


def _ready(db, f):
    for i in trips.readiness_items(db, f):
        if i.critical and i.source != "system":
            stays.set_item(db, f, i.key, "green", None, user_id="u1")


def _deposit(db, stay, amount="10000"):
    db.add(StayDeposit(tenant_id=stay.tenant_id, stay_id=stay.id, amount=Decimal(amount), status="pending"))
    db.flush()


def _welcomed(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    _ready(db, f)
    _deposit(db, v.stay)
    stays.check_in(db, f, CheckInIn(keys_handed=True, deposit_collected=True), "u1")
    return f


# ── Pack and file ───────────────────────────────────────────────────────────


def test_villa_business_types_map_to_the_villa_pack_and_caravan_is_unchanged():
    assert packs.pack_for_business_type("villa_resort") == "villa"
    assert packs.pack_for_business_type("Villa") == "villa"
    assert packs.pack_for_business_type("caravan") == "caravan_rv"
    v = packs.get("villa")
    assert (v["unit_word"], v["file_word"]) == ("villa", "stay")
    assert v["step_names"] == ("Get ready", "Welcome", "Staying", "Check-out", "Settle", "Done")
    assert {i["key"] for i in v["checklists"]["inspection"]["items"]} >= {"damage", "missing", "pool"}
    assert "dispatch_ready" in packs.CANCELLABLE and "preparing" in packs.CANCELLABLE


def test_file_is_created_with_people_suggested_and_the_welcome_checklist(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    assert (f.pack, f.state) == ("villa", "preparing")
    d = money.details(f)
    assert (d.caretaker_staff_id, d.cook_staff_id, d.cleaner_staff_id) == (v.caretaker.id, v.cook.id, v.cleaner.id)
    keys = [i.key for i in trips.readiness_items(db, f)]
    assert keys[:2] == ["pool", "chlorine"] and "payment" in keys and "guests" in keys
    assert trips.ensure_file(db, v.t.id, v.stay).id == f.id
    a = money.account(db, f)
    assert a["distance_km"] is None and a["extra_km_charge"] == Decimal("0.00")


# ── State machine end to end ────────────────────────────────────────────────


def test_stay_end_to_end_with_full_refund(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    with pytest.raises(HTTPException) as e:
        stays.check_in(db, f, CheckInIn(keys_handed=True, deposit_collected=False), "u1")
    assert e.value.status_code == 409
    _ready(db, f)
    assert f.state == "ready"
    assert stays.stage(db, f)["next_key"] == "checkin"
    _deposit(db, v.stay)
    stays.check_in(db, f, CheckInIn(keys_handed=True, deposit_collected=True, note="early arrival"), "u1")
    assert f.state == "staying" and f.dispatched_at is not None
    assert db.query(StayDeposit).filter_by(stay_id=v.stay.id).one().status == "held"
    # 6 nights: cleans on day 3 only (every 3rd day, before check-out)
    jobs = db.query(OpsJob).filter_by(file_id=f.id, kind="cleaning").all()
    assert len(jobs) == 1 and jobs[0].staff_id == v.cleaner.id
    stays.check_out(db, f, "u1")
    assert f.state == "checked_out" and jobs[0].status == "cancelled"
    with pytest.raises(HTTPException):
        stays.settle(db, f, "return_checked", "u1")  # inspection not finished
    for i in trips.readiness_items(db, f, "inspection"):
        stays.set_item(db, f, i.key, "green", None, user_id="u1")
    stays.settle(db, f, "return_checked", "u1")
    assert f.state == "settling"
    with pytest.raises(HTTPException) as e:
        stays.close(db, f, "u1")
    assert "deposit not decided" in e.value.detail and "balance" in e.value.detail
    _pay(db, v.stay, "60000")
    stays.decide_deposit(db, f, DepositDecisionIn(decision="refund"), "u1")
    dep = db.query(StayDeposit).filter_by(stay_id=v.stay.id).one()
    assert (dep.status, dep.deducted) == ("released", Decimal(0))
    stays.settle(db, f, "report_approved", "u1")
    assert stays.stage(db, f)["next_key"] == "close"
    stays.close(db, f, "u1")
    db.commit()
    assert f.state == "closed"
    actions = {a for (a,) in db.query(AuditEvent.action).filter(AuditEvent.tenant_id == v.t.id)}
    assert {"ops.stay.checked_in", "ops.stay.deposit_decided", "ops.stay.closed"} <= actions


def test_deposit_deduction_needs_a_reason_and_keeps_the_inspection_photos(db, v):
    f = _welcomed(db, v)
    stays.check_out(db, f, "u1")
    for i in trips.readiness_items(db, f, "inspection"):
        stays.set_item(db, f, i.key, "red" if i.key == "damage" else "green", None, user_id="u1")
    dmg = next(i for i in trips.readiness_items(db, f, "inspection") if i.key == "damage")
    dmg.photo_key = "t/ops/x/broken-lamp.jpg"
    stays.settle(db, f, "return_checked", "u1")
    with pytest.raises(HTTPException) as e:
        stays.decide_deposit(db, f, DepositDecisionIn(decision="deduct", amount=Decimal(2500)), "u1")
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        stays.decide_deposit(db, f, DepositDecisionIn(decision="deduct", amount=Decimal(20000), reason="x"), "u1")
    stays.decide_deposit(db, f, DepositDecisionIn(decision="deduct", amount=Decimal(2500), reason="Broken lamp"), "u1")
    dep = db.query(StayDeposit).filter_by(stay_id=v.stay.id).one()
    assert (dep.status, dep.deducted, dep.notes) == ("released", Decimal(2500), "Broken lamp")
    d = money.details(f)
    assert (d.deposit_decision, d.deposit_evidence) == ("deduct", ["damage"])
    with pytest.raises(HTTPException):  # decided once
        stays.decide_deposit(db, f, DepositDecisionIn(decision="refund"), "u1")


def test_keeping_the_whole_deposit_forfeits_it(db, v):
    f = _welcomed(db, v)
    stays.check_out(db, f, "u1")
    for i in trips.readiness_items(db, f, "inspection"):
        stays.set_item(db, f, i.key, "green", None, user_id="u1")
    stays.settle(db, f, "return_checked", "u1")
    stays.decide_deposit(db, f, DepositDecisionIn(decision="deduct", amount=Decimal(10000), reason="Pool pump"), "u1")
    assert db.query(StayDeposit).filter_by(stay_id=v.stay.id).one().status == "forfeited"


def test_check_in_without_a_booked_deposit_records_the_amount(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    _ready(db, f)
    with pytest.raises(HTTPException) as e:
        stays.check_in(db, f, CheckInIn(keys_handed=True, deposit_collected=True), "u1")
    assert e.value.status_code == 422
    stays.check_in(db, f, CheckInIn(keys_handed=False, deposit_collected=True, deposit_amount=Decimal(5000)), "u1")
    dep = db.query(StayDeposit).filter_by(stay_id=v.stay.id).one()
    assert (dep.amount, dep.status) == (Decimal(5000), "held")
    assert money.details(f).keys_handed is False


def test_cancelled_booking_before_check_in_cancels_the_file(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    v.stay.status = "cancelled"
    db.flush()
    assert trips.sync_files(db, v.t.id, TODAY)["cancelled"] == 1
    assert f.state == "cancelled"


def test_cleaning_job_is_done_by_a_person(db, v):
    f = _welcomed(db, v)
    job = db.query(OpsJob).filter_by(file_id=f.id, kind="cleaning").one()
    stays.finish_cleaning(db, f, job.id, actor_id="u1")
    assert job.status == "done"
    with pytest.raises(HTTPException):
        stays.finish_cleaning(db, f, job.id, actor_id="u1")


def test_people_must_be_active_staff(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    with pytest.raises(HTTPException):
        stays.set_people(db, f, PeopleIn(caretaker_staff_id=str(uuid.uuid4())), "u1")
    stays.set_people(
        db, f, PeopleIn(caretaker_staff_id=v.caretaker.id, cook_staff_id=None, cleaner_staff_id=None), "u1"
    )
    assert stays.names(db, f) == {"caretaker": "Manju", "cook": None, "cleaner": None}


# ── Meal plan ───────────────────────────────────────────────────────────────


def test_meal_plan_cook_confirms_by_whatsapp(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    day = v.stay.check_in.isoformat()
    m = meals.add_meal(db, f, MealIn(date=day, meal="dinner", guests=8, food="non_veg", notes="no peanuts"), "u1")
    meals.add_meal(db, f, MealIn(date=day, meal="breakfast", guests=8), "u1")
    with pytest.raises(HTTPException):  # one dinner per day
        meals.add_meal(db, f, MealIn(date=day, meal="dinner", guests=2), "u1")
    with pytest.raises(HTTPException):  # outside the stay
        meals.add_meal(db, f, MealIn(date=(TODAY - timedelta(days=9)).isoformat(), meal="lunch", guests=2), "u1")
    assert [x.meal for x in money.details(f).meals] == ["breakfast", "dinner"]
    sent = []
    assert meals.send_meals(db, f, "u1", send=lambda db, t, phone, text: sent.append((phone, text))) == 2
    assert sent[0][0] == v.cook.phone_e164 and "Reply OK" in sent[0][1] and "no peanuts" in sent[0][1]
    assert meals.cook_reply(db, v.t.id, v.caretaker, "ok") is None  # not the cook
    out = intake.handle_text(db, v.t.id, v.cook, "OK")
    assert out is not None and "2 meals confirmed" in out.reply
    d = money.details(f)
    assert all(x.confirmed_by == "cook" for x in d.meals)
    assert meals.cook_reply(db, v.t.id, v.cook, "ok") is None  # nothing left to confirm
    meals.remove_meal(db, f, m.id, "u1")
    assert len(money.details(f).meals) == 1


def test_a_person_can_mark_meals_confirmed(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    m = meals.add_meal(db, f, MealIn(date=v.stay.check_in.isoformat(), meal="lunch", guests=4), "u1")
    meals.confirm_meals(db, f, [m.id], "u1")
    assert money.details(f).meals[0].confirmed_by == "u1"
    with pytest.raises(HTTPException):
        meals.confirm_meals(db, f, [m.id], "u1")


# ── Staff photos ────────────────────────────────────────────────────────────


def _photo(db, v, who, caption, answer, fetch=None):
    m = _Model(answer)
    out = photos.handle(
        db,
        v.t.id,
        who,
        raw=RAW,
        caption=caption,
        message_id=f"wamid.{uuid.uuid4().hex[:6]}",
        describe=m,
        store=_store,
        fetch=fetch,
    )
    return out, m


def test_villa_captions():
    keys = [i["key"] for i in packs.get("villa")["checklists"]["readiness"]["items"]]
    assert photos.classify("Pool", keys) == ("check", "pool")
    assert photos.classify("pool test kit", keys) == ("check", "chlorine")
    assert photos.classify("pH", keys) == ("check", "chlorine")
    assert photos.classify("master bedroom", keys) == ("check", "bedrooms")
    assert photos.classify("gas cylinder", keys) == ("check", "kitchen")
    assert photos.classify("groceries", keys) == ("bill", "groceries")
    assert photos.classify("photo", keys) == (None, None)
    assert photos.classify("cleaned", keys) == ("clean", None)


def test_chlorine_reading_in_and_out_of_range(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    out, _ = _photo(db, v, v.caretaker, "chlorine", {"chlorine_ppm": 2, "ph": 7.4, "confidence": 0.9})
    item = next(i for i in trips.readiness_items(db, f) if i.key == "chlorine")
    assert item.status == "green" and "Chlorine 2 ppm" in out.reply
    out, _ = _photo(db, v, v.caretaker, "chlorine", {"chlorine_ppm": 0.4, "ph": 8.1, "confidence": 0.9})
    assert item.status == "red" and "chlorine 0.4 ppm" in item.note and "pH 8.1" in item.note
    assert db.query(OpsItem).filter_by(tenant_id=v.t.id).count() == 1
    out, _ = _photo(db, v, v.caretaker, "chlorine", {"chlorine_ppm": None, "ph": 7.4, "confidence": 0.9})
    assert "Could not read" in out.reply and item.status == "red"


def test_inspection_photo_is_compared_with_the_arrival_photo(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    _photo(db, v, v.caretaker, "pool", {"shows_item": True, "ok": True, "problems": [], "confidence": 0.9})
    arrival = next(i for i in trips.readiness_items(db, f) if i.key == "pool")
    assert arrival.status == "green" and arrival.photo_key
    _ready(db, f)
    _deposit(db, v.stay)
    stays.check_in(db, f, CheckInIn(keys_handed=True, deposit_collected=True), "u1")
    stays.check_out(db, f, "u1")
    fetched = []
    out, m = _photo(
        db,
        v,
        v.caretaker,
        "pool",
        {"shows_item": True, "ok": False, "problems": ["pool light cover broken"], "confidence": 0.9},
        fetch=lambda key: fetched.append(key) or RAW,
    )
    insp = next(i for i in trips.readiness_items(db, f, "inspection") if i.key == "pool")
    assert fetched == [arrival.photo_key] and "HANDOVER" in m.prompts[0]
    assert insp.status == "red" and insp.ai_verdict["compared_with"] == arrival.photo_key
    assert "manager has been told" in out.reply
    assert stays.stage(db, f)["next_key"] == "inspect"


def test_groceries_bill_and_cleaning_photo(db, v):
    f = _welcomed(db, v)
    out, _ = _photo(
        db,
        v,
        v.cook,
        "groceries",
        {"category": "groceries", "amount_inr": 1840, "vendor": "More", "date": TODAY.isoformat(), "confidence": 0.9},
    )
    assert "Stay expenses so far Rs 1,840" in out.reply
    assert db.query(OpsExpense).filter_by(file_id=f.id).one().category == "groceries"
    job = db.query(OpsJob).filter_by(file_id=f.id, kind="cleaning").one()
    out, _ = _photo(db, v, v.cleaner, "cleaned", {})
    assert "No cleaning is due" in out.reply and job.status == "open"
    job.due_at = datetime.now(UTC) - timedelta(hours=1)
    out, _ = _photo(db, v, v.cleaner, "cleaned", {})
    assert "marked done" in out.reply and job.status == "done"


def test_handle_photo_routes_villa_staff_to_the_villa_rules(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    out = intake.handle_photo(
        db,
        v.t.id,
        v.caretaker,
        raw=RAW,
        caption="bedroom",
        message_id="wamid.v1",
        describe=_Model({"shows_item": True, "ok": True, "problems": [], "confidence": 0.95}),
        store=_store,
    )
    assert out.file_id == f.id and "looks fine" in out.reply


# ── Today ───────────────────────────────────────────────────────────────────


def test_today_for_villas(db, v):
    f = trips.ensure_file(db, v.t.id, v.stay)
    out = today_svc.build(db, v.t.id)
    assert (out["pack"], out["unit_word"], out["file_word"]) == ("villa", "villa", "stay")
    assert out["units"][0]["name"] == "Villa Amara" and out["units"][0]["status"] == "Getting ready"
    titles = [n["title"] for n in out["needs"]]
    assert any("checks still open" in t for t in titles)
    _ready(db, f)
    _deposit(db, v.stay)
    stays.check_in(db, f, CheckInIn(keys_handed=True, deposit_collected=True), "u1")
    d = money.details(f)  # a lunch today the cook has not confirmed (check-in is tomorrow in the fixture)
    d.meals = [Meal(id="m1", date=TODAY.isoformat(), meal="lunch", guests=4)]
    money.save_details(f, d)
    out = today_svc.build(db, v.t.id)
    assert out["units"][0]["status"] == "Guests staying"
    assert any(n["title"] == "Cook has not confirmed lunch" for n in out["needs"])
    stays.check_out(db, f, "u1")
    stays.set_item(db, f, "damage", "red", "cracked tile", user_id="u1")
    out = today_svc.build(db, v.t.id)
    assert out["needs"][0]["level"] == "red" and out["needs"][0]["title"] == "Inspection found a problem"
    for i in trips.readiness_items(db, f, "inspection"):
        if i.status == "pending":
            stays.set_item(db, f, i.key, "green", None, user_id="u1")
    stays.settle(db, f, "return_checked", "u1")
    f.returned_at = datetime.now(UTC) - timedelta(hours=60)
    out = today_svc.build(db, v.t.id)
    dep = next(n for n in out["needs"] if n["title"].startswith("Decide the deposit"))
    assert dep["level"] == "red"
    assert any(n["title"].startswith("Collect Rs") for n in out["needs"])


# ── Report ──────────────────────────────────────────────────────────────────


def test_stay_report_has_no_kilometre_section_and_renders(db, v):
    f = _welcomed(db, v)
    _pay(db, v.stay, "20000")
    money.add_expense(db, f, ExpenseIn(category="groceries", amount=Decimal(1840)))
    r = ops_stay_report.build(db, f)
    titles = [s["title"] for s in r["sections"]]
    assert r["title"] == "Stay Account Report" and r["draft"] is True
    assert not any("ilometre" in t for t in titles) and len(titles) == 7
    rows = {label: value for s in r["sections"] for label, value, _ in s["rows"]}
    assert "1,840" in rows["Groceries"] and "10,000" in rows["Security deposit (not revenue)"]
    assert ops_trip_report.render(r)[:4] == b"%PDF"


# ── API ─────────────────────────────────────────────────────────────────────


@pytest.fixture()
def api(db, v):
    seed_capabilities(db, v.t.id)
    return type(
        "A",
        (),
        {
            "mgr": _user(db, v.t.id, UserRole.MANAGER),
            "foh": _user(db, v.t.id, UserRole.FOH),
            "mkt": _user(db, v.t.id, UserRole.MARKETING),
        },
    )()


def test_api_villa_flow(client, db, v, api):
    r = client.get(f"/api/v1/ops/files/by-stay/{v.stay.id}", headers=_h(api.mgr))
    assert r.status_code == 200, r.text
    body = r.json()
    fid = body["id"]
    assert body["pack"] == "villa" and body["people"]["caretaker"] == "Manju" and body["crew"] == {}
    assert body["stage"]["step_name"] == "Get ready" and len(body["inspection"]) == 0
    for i in body["checklist"]:
        if i["critical"] and i["source"] != "system":
            assert (
                client.put(
                    f"/api/v1/ops/files/{fid}/checklist/{i['key']}", json={"status": "green"}, headers=_h(api.foh)
                ).status_code
                == 200
            )
    r = client.post(
        f"/api/v1/ops/files/{fid}/meals",
        json={"date": v.stay.check_in.isoformat(), "meal": "dinner", "guests": 6},
        headers=_h(api.foh),
    )
    assert r.status_code == 201 and r.json()["details"]["meals"][0]["meal"] == "dinner"
    mid = r.json()["details"]["meals"][0]["id"]
    assert (
        client.post(f"/api/v1/ops/files/{fid}/meals/confirm", json={"meal_ids": [mid]}, headers=_h(api.foh)).status_code
        == 200
    )
    r = client.post(
        f"/api/v1/ops/files/{fid}/check-in",
        json={"keys_handed": True, "deposit_collected": True, "deposit_amount": 5000},
        headers=_h(api.mgr),
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "staying" and r.json()["stage"]["step_name"] == "Staying"
    assert client.post(f"/api/v1/ops/files/{fid}/check-out", headers=_h(api.foh)).json()["state"] == "checked_out"
    assert client.post(f"/api/v1/ops/files/{fid}/accept", json={"route": "x"}, headers=_h(api.mgr)).status_code == 409
    r = client.get(f"/api/v1/ops/files/{fid}/report.pdf", headers=_h(api.mgr))
    assert r.status_code == 200 and "stay-account" in r.headers["content-disposition"]


def test_api_villa_roles(client, db, v, api):
    fid = client.get(f"/api/v1/ops/files/by-stay/{v.stay.id}", headers=_h(api.mgr)).json()["id"]
    assert (
        client.post(
            f"/api/v1/ops/files/{fid}/check-in",
            json={"keys_handed": True, "deposit_collected": False},
            headers=_h(api.foh),
        ).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/ops/files/{fid}/deposit", json={"decision": "refund"}, headers=_h(api.foh)).status_code
        == 403
    )
    assert client.post(f"/api/v1/ops/files/{fid}/people", json={}, headers=_h(api.mkt)).status_code == 403
    assert client.post(f"/api/v1/ops/files/{fid}/meals/send", headers=_h(api.mkt)).status_code == 403


def test_api_villa_cross_tenant(client, db, v, api):
    fid = client.get(f"/api/v1/ops/files/by-stay/{v.stay.id}", headers=_h(api.mgr)).json()["id"]
    other = _tenant(db, "villa_resort")
    seed_capabilities(db, other.id)
    om = _user(db, other.id, UserRole.MANAGER)
    assert client.post(f"/api/v1/ops/files/{fid}/people", json={}, headers=_h(om)).status_code == 404
    assert client.post(f"/api/v1/ops/files/{fid}/check-out", headers=_h(om)).status_code == 404
    assert client.get(f"/api/v1/ops/files/{fid}", headers=_h(om)).status_code == 404
