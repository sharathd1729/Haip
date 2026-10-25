"""Staff WhatsApp photos -> ops file (ops_photo_intake): caption sorting, the ported checks, every path with a scripted model.

No test reaches a vision provider or R2: `describe` and `store` are injected; the photo is a real (tiny) JPEG.
"""
import io
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from PIL import Image

from app.models.guest import Guest
from app.models.conversation import Message
from app.models.ops import OpsItem
from app.models.ops_files import OpsExpense
from app.models.stay_finance import StayAddOn
from app.services import ops_money as money
from app.services import ops_photo_intake as intake
from app.services import ops_trip_service as trips
from app.workers.tasks import whatsapp as wa
from tests.ops_helpers import prop, staff
from tests.test_ops_files import _actor_u1, _green_all_critical, _pay, _ready_file, _stay, _tenant


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 120, 60)).save(out, format="JPEG")
    return out.getvalue()


RAW = _jpeg()


class _Model:
    """A scripted vision model: returns the answer given, records the prompts it was shown."""
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def __call__(self, jpeg, prompt):
        assert jpeg[:3] == b"\xff\xd8\xff"            # always a re-encoded JPEG
        self.prompts.append(prompt)
        return self.answer, {"model": "fake", "secs": 0}


def _store(tenant_id, file_id, message_id, jpeg):
    return f"{tenant_id}/ops/{file_id}/{message_id}.jpg"


def _photo(db, w, who, caption, answer):
    m = _Model(answer)
    out = intake.handle_photo(db, w.t.id, who, raw=RAW, caption=caption, message_id=f"wamid.{uuid.uuid4().hex[:6]}",
                              describe=m, store=_store)
    return out, m


@pytest.fixture()
def w(db):
    t = _tenant(db)
    p = prop(db, t.id, "Ratha 1")
    w = type("W", (), {"t": t, "p": p, "stay": _stay(db, t, p), "driver": staff(db, t.id, "Suresh", "driver"),
                       "helper": staff(db, t.id, "Raju", "driver")})()
    w.f = _ready_file(db, w)
    return w


def _on_trip(db, w):
    _green_all_critical(db, w.f)
    _pay(db, w.stay, "126732")
    trips.refresh(db, w.f)
    trips.dispatch(db, w.f, 87396, "u1")


# ── Pure rules ──────────────────────────────────────────────────────────────

def test_captions_pick_the_kind(db, w):
    items = trips.readiness_items(db, w.f)
    assert intake.classify("odo", items) == ("odometer", None)
    assert intake.classify("Diesel", items) == ("bill", "fuel")
    assert intake.classify("fastag toll", items) == ("bill", "toll")
    assert intake.classify("AC", items) == ("check", "ac")
    assert intake.classify("water tank", items) == ("check", "water")
    assert intake.classify("first aid", items) == ("check", "safety")
    photo_items = [i.key for i in items if i.photo_required]
    assert intake.classify("2", items) == ("check", photo_items[1])
    assert intake.classify("", items) == (None, None)
    assert intake.classify("hello", items) == (None, None)


def test_bill_checks_ported_from_the_prototype():
    fields, problems, warnings = intake.read_bill({"amount_inr": 6240, "litres": 52, "rate_per_litre": 102.5, "confidence": 0.9})
    assert fields["amount"] == Decimal("6240") and not problems and "5330" in warnings[0]
    assert intake.read_bill({"amount_inr": 5330, "litres": 52, "rate_per_litre": 102.5, "confidence": 0.9})[2] == []
    assert intake.read_bill({"amount_inr": 500, "confidence": 0.4})[0] is None
    assert intake.read_bill({"amount_inr": None, "confidence": 0.9})[0] is None
    assert intake.read_odometer({"reading_km": 88792, "confidence": 0.95}) == (88792, [])
    assert intake.read_odometer({"reading_km": 88792.5, "confidence": 0.95})[0] is None
    assert intake.read_odometer({"reading_km": "88,792", "unit": "mi", "confidence": 0.95})[0] is None


def test_a_non_image_is_refused():
    with pytest.raises(ValueError):
        intake.shrink(b"not a photo at all")


# ── Checklist photos ────────────────────────────────────────────────────────

def test_a_good_checklist_photo_ticks_the_item(db, w):
    out, m = _photo(db, w, w.helper, "AC", {"shows_item": True, "ok": True, "problems": [], "confidence": 0.9})
    item = next(i for i in trips.readiness_items(db, w.f) if i.key == "ac")
    assert item.status == "green" and item.photo_key and item.ai_verdict["ok"] and item.set_by_staff_id == w.helper.id
    assert "AC and cooling" in m.prompts[0] and "Still needed" in out.reply and out.send_ids == []


def test_a_problem_turns_the_item_red_and_flags_the_manager(db, w):
    out, _ = _photo(db, w, w.helper, "first aid", {"shows_item": True, "ok": False, "problems": ["box half empty"],
                                                   "confidence": 0.85})
    item = next(i for i in trips.readiness_items(db, w.f) if i.key == "safety")
    assert item.status == "red" and "box half empty" in item.note
    flag = db.query(OpsItem).filter_by(tenant_id=w.t.id, stay_id=w.stay.id).one()
    assert flag.severity == "high" and flag.duty == "ops_manager" and "Ratha 1" in flag.title
    assert "manager has been told" in out.reply


def test_a_photo_of_something_else_changes_nothing(db, w):
    out, _ = _photo(db, w, w.helper, "ac", {"shows_item": False, "ok": False, "confidence": 0.9})
    assert next(i for i in trips.readiness_items(db, w.f) if i.key == "ac").status == "pending"
    assert "send it again" in out.reply


def test_no_caption_asks_what_it_is_without_calling_the_model(db, w):
    out, m = _photo(db, w, w.helper, None, {})
    assert m.prompts == [] and "one word" in out.reply


def test_checklist_is_closed_once_the_trip_left(db, w):
    _on_trip(db, w)
    out, m = _photo(db, w, w.helper, "ac", {"shows_item": True, "ok": True, "confidence": 0.9})
    assert m.prompts == [] and "closed" in out.reply


# ── Odometer ────────────────────────────────────────────────────────────────

def test_start_odometer_photo_only_prefills_dispatch(db, w):
    out, _ = _photo(db, w, w.driver, "odo", {"reading_km": 87396, "unit": "km", "confidence": 0.95})
    d = money.details(w.f)
    assert d.start_odometer_photo_km == 87396 and d.start_odometer is None and w.f.state != "on_trip"
    assert "manager will start the trip" in out.reply


def test_end_odometer_photo_returns_the_trip_and_bills_extra_km(db, w):
    _on_trip(db, w)
    out, _ = _photo(db, w, w.driver, "odo", {"reading_km": 88792, "unit": "km", "confidence": 0.95})
    assert w.f.state == "returned" and money.details(w.f).end_odometer == 88792
    assert db.query(StayAddOn).filter_by(stay_id=w.stay.id, name=money.EXTRA_KM_ADDON).one().unit_price == Decimal("12740.00")
    assert "1,396 km" in out.reply


def test_unclear_or_backwards_odometer_changes_nothing(db, w):
    _on_trip(db, w)
    out, _ = _photo(db, w, w.driver, "odo", {"reading_km": 88792, "confidence": 0.3})
    assert w.f.state == "on_trip" and "clearer photo" in out.reply
    out, _ = _photo(db, w, w.driver, "odo", {"reading_km": 80000, "confidence": 0.95})
    assert w.f.state == "on_trip" and "below the start" in out.reply


# ── Bills ───────────────────────────────────────────────────────────────────

def test_fuel_bill_becomes_an_expense_and_a_mismatch_is_flagged(db, w):
    _on_trip(db, w)
    ans = {"category": "other", "vendor": "HP Hassan", "date": "2026-10-26", "amount_inr": 6240, "litres": 52,
           "rate_per_litre": 102.5, "confidence": 0.9}
    out, _ = _photo(db, w, w.driver, "diesel", ans)
    e = db.query(OpsExpense).filter_by(file_id=w.f.id).one()
    assert (e.category, e.amount, e.source, e.staff_id) == ("fuel", Decimal("6240.00"), "photo", w.driver.id) and e.photo_key
    assert db.query(OpsItem).filter_by(tenant_id=w.t.id, category="bill").count() == 1
    assert "Rs 6,240" in out.reply
    out, _ = _photo(db, w, w.driver, "diesel", ans)
    assert "already added" in out.reply and db.query(OpsExpense).filter_by(file_id=w.f.id).count() == 1


def test_unreadable_bill_adds_nothing(db, w):
    _on_trip(db, w)
    out, _ = _photo(db, w, w.driver, "bill", {"amount_inr": None, "confidence": 0.9})
    assert db.query(OpsExpense).filter_by(file_id=w.f.id).count() == 0 and "clearer photo" in out.reply


# ── Who may send ────────────────────────────────────────────────────────────

def test_someone_not_on_a_trip_or_in_another_business_gets_nothing(db, w):
    other_t = _tenant(db)
    stranger = staff(db, other_t.id, "Other")
    out = intake.handle_photo(db, other_t.id, stranger, raw=RAW, caption="ac", message_id="x",
                              describe=_Model({}), store=_store)
    assert "No trip found" in out.reply
    idle = staff(db, w.t.id, "Anil")
    out, m = _photo(db, w, idle, "ac", {})
    assert "No trip found" in out.reply and m.prompts == []


def test_issue_text_opens_a_critical_incident_on_the_road(db, w):
    _on_trip(db, w)
    out = intake.handle_text(db, w.t.id, w.driver, "Issue: flat tyre near Hassan")
    flag = db.query(OpsItem).filter_by(tenant_id=w.t.id, category="incident").one()
    assert flag.severity == "critical" and "flat tyre" in flag.summary and "alerted" in out.reply
    assert intake.handle_text(db, w.t.id, w.driver, "on my way") is None


# ── Webhook path ────────────────────────────────────────────────────────────

def test_a_staff_photo_is_queued_and_never_becomes_a_guest(db, w):
    msg = {"from": w.helper.phone_e164.lstrip("+"), "id": f"wamid.in.{uuid.uuid4().hex[:8]}", "type": "image",
           "image": {"id": "media-1", "mime_type": "image/jpeg", "caption": "AC"}}
    with patch("app.workers.tasks.ops_intake.process_staff_photo.delay") as delay, \
         patch("app.workers.tasks.ops_escalation.queue_delivery"):
        wa._handle_inbound_message(db, w.t, msg, contacts=[])
    delay.assert_called_once_with(w.t.id, w.helper.id, "media-1", "AC", msg["id"])
    assert db.query(Guest).filter_by(tenant_id=w.t.id).filter(Guest.name != "Sample Guest").count() == 0
    assert db.query(Message).filter_by(tenant_id=w.t.id).count() == 0


def test_an_issue_text_through_the_webhook_alerts_and_replies(db, w):
    _on_trip(db, w)
    msg = {"from": w.driver.phone_e164.lstrip("+"), "id": f"wamid.in.{uuid.uuid4().hex[:8]}", "type": "text",
           "text": {"body": "issue engine warning light"}}
    with patch("app.workers.tasks.ops_escalation.queue_delivery"), \
         patch("app.services.lead_alert_sender.send_text") as reply:
        wa._handle_inbound_message(db, w.t, msg, contacts=[])
    assert db.query(OpsItem).filter_by(tenant_id=w.t.id, category="incident").count() == 1
    assert "alerted" in reply.call_args.args[3]


def test_the_task_reads_replies_and_is_idempotent(db, w):
    from app.workers.tasks import ops_intake
    cache: dict = {}
    model = _Model({"shows_item": True, "ok": True, "problems": [], "confidence": 0.9})
    with patch.object(ops_intake, "SessionLocal", return_value=_NoClose(db)), \
         patch.object(ops_intake, "_fetch", return_value=(RAW, "image/jpeg")), \
         patch("app.services.lead_alert_sender.wa_credentials", return_value=("pn", "tok")), \
         patch("app.services.lead_alert_sender.send_text") as reply, \
         patch("app.workers.tasks.ops_escalation.queue_delivery"), \
         patch("app.core.cache.get_cached", side_effect=cache.get), \
         patch("app.core.cache.set_cached", side_effect=lambda k, v, ttl=None: cache.__setitem__(k, v)), \
         patch.object(intake, "_default_describe", model), patch.object(intake, "_store", _store):
        ops_intake.process_staff_photo.run(w.t.id, w.helper.id, "media-1", "AC", "wamid.same")
        ops_intake.process_staff_photo.run(w.t.id, w.helper.id, "media-1", "AC", "wamid.same")
    assert len(model.prompts) == 1 and reply.call_count == 1 and "looks fine" in reply.call_args.args[3]


class _NoClose:
    """SessionLocal() stand-in: the task's `with` block must not close the test's session."""
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        return False
