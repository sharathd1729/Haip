"""Mid-stay check (ops gap 9): one WhatsApp on day 2 of a 2+ night stay, 09:30-20:00 workspace time, once per stay; the
guest's "1" is noted on the stay file, anything else is one ops item. No real message is sent (Celery sends patched)."""

from datetime import UTC, datetime, time, timedelta
from unittest.mock import patch

import pytest

from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate
from app.models.audit_event import AuditEvent
from app.models.consent import Consent
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.ops import OpsItem, OpsSettings
from app.models.ops_files import OpsFileEvent
from app.models.ops_fleet import OpsAutoMessage
from app.services import ops_auto_messages as auto
from app.services import ops_midstay_check as mid
from app.services import ops_trip_service as trips
from app.services import wa_booking_pack as pack
from tests.ops_helpers import IST, prop
from tests.test_ops_files import TODAY, _actor_u1, _stay, _tenant  # noqa: F401 (_actor_u1 is an autouse fixture)

DAY2 = datetime.combine(TODAY, time(10, 30), tzinfo=IST).astimezone(UTC)


def _world(db, business_type="villa_resort", nights=3, start=-1):
    t = _tenant(db, business_type)
    p = prop(db, t.id, "Villa Amara")
    stay = _stay(db, t, p, start=start, nights=nights)
    f = trips.ensure_file(db, t.id, stay)
    db.commit()
    return t, stay, f


def _approve(db, tenant_id):
    db.add(
        WATemplate(
            tenant_id=tenant_id,
            name=pack.MIDSTAY_CHECK,
            language="en",
            category=TemplateCategory.UTILITY,
            status=TemplateStatus.APPROVED,
            components=[dict(c) for c in pack.BY_NAME[pack.MIDSTAY_CHECK]["components"]],
        )
    )
    db.commit()


def _switch(db, tenant_id, on: bool):
    db.add(OpsSettings(tenant_id=tenant_id, midstay_check_enabled=on))
    db.commit()


def _run(db, tenant_id, now=DAY2):
    with (
        patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as tpl,
        patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as txt,
    ):
        auto.run_tenant(db, tenant_id, now=now)
    return tpl, txt


def _row(db, f):
    return db.query(OpsAutoMessage).filter_by(file_id=f.id, kind=mid.KIND).one_or_none()


def _sent(db, t, f):
    return db.query(Message).filter_by(tenant_id=t.id, idempotency_key=f"ops:{f.id}:{mid.KIND}").all()


def _events(db, f):
    return [e.text for e in db.query(OpsFileEvent).filter_by(file_id=f.id) if "Mid-stay" in e.text]


def test_sent_once_on_day_two_of_a_three_night_stay_as_the_template(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    tpl, _ = _run(db, t.id)
    tpl.assert_called_once()
    assert tpl.call_args.kwargs["template_name"] == pack.MIDSTAY_CHECK
    assert tpl.call_args.kwargs["variables"][1] == "stay at Villa Amara"
    msgs = _sent(db, t, f)
    assert len(msgs) == 1 and "Reply 1 if all good" in msgs[0].body and msgs[0].sender_kind == "system"
    assert _row(db, f).status == "sent" and _events(db, f) == ["Mid-stay check sent to the guest (template)."]
    tpl2, txt2 = _run(db, t.id, DAY2 + timedelta(hours=3))  # the next hourly runs: never twice
    tpl2.assert_not_called()
    txt2.assert_not_called()
    assert len(_sent(db, t, f)) == 1


def test_caravan_words_say_trip_in_the_vehicle(db):
    t, stay, f = _world(db, business_type="caravan")
    _approve(db, t.id)
    tpl, _ = _run(db, t.id)
    assert tpl.call_args.kwargs["variables"][1] == "trip in Villa Amara"


def test_text_inside_the_window_even_without_the_template_when_switched_on(db):
    t, stay, f = _world(db)
    _switch(db, t.id, True)
    conv = Conversation(tenant_id=t.id, guest_id=stay.guest_id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    db.add(
        Message(
            tenant_id=t.id,
            conversation_id=conv.id,
            direction=MessageDirection.INBOUND,
            channel=ChannelType.WHATSAPP,
            body="hi",
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    db.commit()
    tpl, txt = _run(db, t.id)
    txt.assert_called_once()
    tpl.assert_not_called()
    assert _row(db, f).via == "text" and "stay at Villa Amara" in _sent(db, t, f)[0].body


def test_not_for_a_one_night_stay(db):
    t, stay, f = _world(db, nights=1)
    _approve(db, t.id)
    tpl, _ = _run(db, t.id)
    tpl.assert_not_called()
    assert _row(db, f) is None


def test_only_on_day_two(db):
    t, stay, f = _world(db, start=-2)
    _approve(db, t.id)
    tpl, _ = _run(db, t.id)
    tpl.assert_not_called()
    assert _row(db, f) is None


@pytest.mark.parametrize("hour,minute", [(9, 0), (20, 30), (23, 0)])
def test_quiet_hours_respected(db, hour, minute):
    t, stay, f = _world(db)
    _approve(db, t.id)
    tpl, _ = _run(db, t.id, datetime.combine(TODAY, time(hour, minute), tzinfo=IST).astimezone(UTC))
    tpl.assert_not_called()
    assert _row(db, f) is None


def test_not_after_cancellation(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    stay.status = "cancelled"
    db.commit()
    tpl, _ = _run(db, t.id)
    tpl.assert_not_called()
    assert _sent(db, t, f) == []


def test_not_after_stop(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    db.add(
        Consent(
            tenant_id=t.id,
            guest_id=stay.guest_id,
            channel="whatsapp",
            scope="marketing",
            granted=False,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    )
    db.commit()
    tpl, _ = _run(db, t.id)
    tpl.assert_not_called()
    row = _row(db, f)
    assert row.status == "skipped" and "stop" in row.reason and _sent(db, t, f) == []


def test_template_not_approved_outside_the_window_is_skipped_without_spam(db):
    t, stay, f = _world(db)
    tpl, _ = _run(db, t.id)  # default: off until the template is approved
    tpl.assert_not_called()
    assert _row(db, f) is None
    _switch(db, t.id, True)
    _run(db, t.id)
    _run(db, t.id, DAY2 + timedelta(hours=1))
    row = _row(db, f)
    assert row.status == "skipped" and "not approved" in row.reason and row.attempts == 2
    assert _sent(db, t, f) == []
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="ops_file.message_not_sent").count() == 0
    assert db.query(OpsItem).filter_by(tenant_id=t.id).count() == 0  # no task, no ops item


def test_owner_switched_it_off(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    _switch(db, t.id, False)
    tpl, _ = _run(db, t.id)
    tpl.assert_not_called()
    assert not mid.enabled(db, t.id) and _row(db, f) is None


def _sent_check(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    _run(db, t.id)
    return t, stay, f


@pytest.mark.parametrize("reply", ["1", "All good", "ok thanks!", "👍"])
def test_a_positive_reply_is_noted_and_raises_no_ticket(db, reply):
    t, stay, f = _sent_check(db)
    assert mid.on_guest_message(db, t.id, stay.guest_id, None, reply, now=DAY2 + timedelta(hours=1)) == "positive"
    assert _row(db, f).response == "positive"
    assert "Mid-stay check: the guest says all is good." in _events(db, f)
    assert db.query(OpsItem).filter_by(tenant_id=t.id).count() == 0
    assert mid.on_guest_message(db, t.id, stay.guest_id, None, "1", now=DAY2 + timedelta(hours=2)) is None


def test_a_problem_reply_raises_one_ops_item(db):
    t, stay, f = _sent_check(db)
    with patch("app.workers.tasks.ops_escalation.queue_delivery"):
        out = mid.on_guest_message(
            db, t.id, stay.guest_id, "conv-1", "1 but the AC is not cooling", now=DAY2 + timedelta(hours=1)
        )
        again = mid.on_guest_message(db, t.id, stay.guest_id, "conv-1", "still hot", now=DAY2 + timedelta(hours=2))
    assert out == "problem" and again is None
    item = db.query(OpsItem).filter_by(tenant_id=t.id).one()
    assert item.category == "complaint" and item.duty == "ops_manager" and item.stay_id == stay.id
    assert item.source == "guest_chat" and "AC is not cooling" in item.summary and item.conversation_id == "conv-1"
    assert _row(db, f).response == "problem" and any("reported a problem" in e for e in _events(db, f))


def test_a_reply_after_24_hours_or_without_a_check_is_ignored(db):
    t, stay, f = _sent_check(db)
    assert mid.on_guest_message(db, t.id, stay.guest_id, None, "noisy", now=DAY2 + timedelta(hours=25)) is None
    other_t, other_stay, _ = _world(db)
    assert mid.on_guest_message(db, other_t.id, other_stay.guest_id, None, "noisy", now=DAY2) is None


def test_positive_phrases():
    assert mid.is_positive("1.") and mid.is_positive("Everything is fine, thank you")
    assert not mid.is_positive("1 but the wifi is down") and not mid.is_positive("no")


def test_tenant_isolation(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    other = _tenant(db, "villa_resort")
    tpl, _ = _run(db, other.id)
    tpl.assert_not_called()
    assert _row(db, f) is None
    _run(db, t.id)
    assert mid.on_guest_message(db, other.id, stay.guest_id, None, "broken tap", now=DAY2) is None
    assert _row(db, f).response is None and db.query(OpsItem).count() == 0
