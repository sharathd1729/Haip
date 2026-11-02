"""Automatic trip messages (Ops phase 2): crew brief at T-72 h, photo reminder and guest pre-trip at T-24 h, deposit reminder
24 h after return. Text inside the 24-hour window else the template; once per (file, kind, recipient); a message that could
not go is a Today need and is retried, never dropped. The prototype's messages tests (first-name greeting) are ported."""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.ops import OpsItem
from app.models.ops_fleet import OpsAutoMessage
from app.models.stay_finance import StayDeposit
from app.services import ops_auto_messages as auto
from app.services import ops_today_service
from app.services import ops_trip_service as trips
from tests.ops_helpers import IST, prop, staff
from tests.test_ops_files import _actor_u1, _green_all_critical, _pay, _ready_file, _stay, _tenant  # noqa: F401


class _Adapter:
    def __init__(self):
        self.sent = []

    async def send_text(self, to, body):
        self.sent.append(("text", to, body))
        return {"messages": [{"id": "wamid.t"}]}

    async def send_template(self, to, template_name, language_code="en", components=None):
        self.sent.append(("template", to, template_name, components))
        return {"messages": [{"id": "wamid.p"}]}


@pytest.fixture()
def w(db):
    t = _tenant(db)
    p = prop(db, t.id, "Ratha 1")
    w = type(
        "W",
        (),
        {
            "t": t,
            "p": p,
            "stay": _stay(db, t, p),
            "driver": staff(db, t.id, "Suresh", "driver"),
            "helper": staff(db, t.id, "Raju", "driver"),
        },
    )()
    w.f = _ready_file(db, w)
    w.pickup = datetime.combine(w.stay.check_in, time(12, 0), tzinfo=IST).astimezone(UTC)
    w.adapter = _Adapter()
    db.commit()
    return w


def _run(db, w, hours_before):
    with (
        patch("app.services.lead_alert_sender.wa_credentials", return_value=("pn", "tok")),
        patch("app.services.lead_alert_sender._adapter", return_value=w.adapter),
    ):
        return auto.run_tenant(db, w.t.id, now=w.pickup - timedelta(hours=hours_before))


def _rows(db, w, kind):
    return db.query(OpsAutoMessage).filter_by(file_id=w.f.id, kind=kind).all()


def test_first_name_keeps_the_title_and_strips_brackets():
    assert auto.first_name("Mr. Saleem") == "Mr. Saleem"
    assert auto.first_name("Krithika(Brandaid Events)") == "Krithika"
    assert auto.first_name("Neha Sharma") == "Neha" and auto.first_name(None) == "there"


def test_nothing_before_72_hours(db, w):
    _run(db, w, 80)
    assert w.adapter.sent == [] and db.query(OpsAutoMessage).count() == 0


def test_crew_brief_goes_once_as_text_inside_the_window_else_template(db, w):
    w.driver.last_inbound_at = datetime.now(UTC) - timedelta(hours=2)
    db.commit()
    with patch("app.services.lead_alert_sender.template_approved", return_value="en"):
        _run(db, w, 48)
    kinds = sorted(s[0] for s in w.adapter.sent)
    assert kinds == ["template", "text"]
    text = next(s for s in w.adapter.sent if s[0] == "text")[2]
    assert "Bangalore -> Hyderabad" in text and "Kurnool" in text and "Sample" in text and "driver" in text
    tpl = next(s for s in w.adapter.sent if s[0] == "template")
    assert tpl[2] == "ops_crew_brief_v1" and len(tpl[3][0]["parameters"]) == 6
    assert {r.status for r in _rows(db, w, "crew_brief")} == {"sent"}
    _run(db, w, 47)
    assert len(w.adapter.sent) == 2  # never twice


def test_a_message_that_cannot_go_is_a_today_need_and_is_retried(db, w):
    _run(db, w, 48)  # no window, no approved template
    rows = _rows(db, w, "crew_brief")
    assert len(rows) == 2 and all(r.status == "failed" and "not approved" in r.reason for r in rows)
    needs = ops_today_service.build(db, w.t.id, now=w.pickup - timedelta(hours=48))["needs"]
    assert any(n["title"] == "Crew brief not sent to Suresh" and n["file_id"] == w.f.id for n in needs)
    with patch("app.services.lead_alert_sender.template_approved", return_value="en"):
        _run(db, w, 47)
    assert {r.status for r in _rows(db, w, "crew_brief")} == {"sent"} and all(
        r.attempts == 2 for r in _rows(db, w, "crew_brief")
    )


def test_staff_who_did_not_agree_get_nothing_and_it_says_why(db, w):
    w.helper.whatsapp_opt_in_at = None
    db.commit()
    _run(db, w, 48)
    row = next(r for r in _rows(db, w, "crew_brief") if r.recipient == f"staff:{w.helper.id}")
    assert row.status == "failed" and "has not agreed" in row.reason


def test_t24_photo_reminder_lists_missing_photos_and_guest_pretrip_needs_a_template(db, w):
    w.helper.last_inbound_at = datetime.now(UTC)
    db.commit()
    _run(db, w, 20)
    chase = next(s for s in w.adapter.sent if "still needed" in s[2])
    assert "Tyres" in chase[2] and "AC and cooling" in chase[2]
    guest = _rows(db, w, "guest_pretrip")[0]
    assert guest.status == "failed" and guest.via == "template" and "template not approved" in guest.reason


def test_no_reminder_when_every_photo_is_in(db, w):
    _green_all_critical(db, w.f)
    for i in trips.readiness_items(db, w.f):
        if i.photo_required:
            trips.set_item(db, w.f, i.key, "green", None, user_id="u1")
    db.commit()
    _run(db, w, 20)
    assert _rows(db, w, "helper_chase") == []


def test_deposit_reminder_24h_after_return_once_and_resolved_when_settled(db, w):
    _green_all_critical(db, w.f)
    _pay(db, w.stay, "126732")
    db.add(StayDeposit(tenant_id=w.t.id, stay_id=w.stay.id, amount=Decimal(20000), status="held"))
    trips.refresh(db, w.f)
    trips.dispatch(db, w.f, 1000, "u1")
    trips.end_trip(db, w.f, 1500, actor_id="u1")
    w.f.returned_at = datetime.now(UTC) - timedelta(hours=30)
    db.commit()
    with patch("app.services.lead_alert_sender.wa_credentials", return_value=("pn", "tok")):
        auto.run_tenant(db, w.t.id)
        auto.run_tenant(db, w.t.id)
    item = db.query(OpsItem).filter_by(tenant_id=w.t.id, category="deposit").one()
    assert "refund deposit Rs 20,000" in item.title and item.duty == "ops_manager"
    needs = ops_today_service.build(db, w.t.id)["needs"]
    assert not any(n["item_id"] == item.id for n in needs)  # shown once, as the trip's own "Refund deposit" need
    db.query(StayDeposit).filter_by(stay_id=w.stay.id).update({StayDeposit.status: "released"})
    db.commit()
    auto.run_tenant(db, w.t.id)
    db.refresh(item)
    assert item.status == "resolved"


def test_another_tenants_files_are_left_alone(db, w):
    other = _tenant(db)
    with (
        patch("app.services.lead_alert_sender.wa_credentials", return_value=("pn", "tok")),
        patch("app.services.lead_alert_sender._adapter", return_value=w.adapter),
    ):
        auto.run_tenant(db, other.id, now=w.pickup - timedelta(hours=48))
    assert w.adapter.sent == [] and db.query(OpsAutoMessage).count() == 0
