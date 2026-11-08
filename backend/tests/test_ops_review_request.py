"""Review request (ops gap 2): "How was your stay?" the day after check-out, once per stay, 09:30-20:00 workspace time.
Every answer gets the Google review link (no review gating); a 1-3 also opens a guest ticket. No real message is sent
(Celery sends patched)."""

from datetime import UTC, datetime, time, timedelta
from unittest.mock import patch

import pytest

from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate
from app.models.consent import Consent
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.integration import Integration
from app.models.marketing import MarketingGuestReview
from app.models.ops import OpsItem, OpsSettings
from app.models.ops_files import OpsFileEvent
from app.models.ops_fleet import OpsAutoMessage
from app.services import kpi_metrics
from app.services import ops_auto_messages as auto
from app.services import ops_review_request as rev
from app.services import ops_trip_service as trips
from app.services import wa_booking_pack as pack
from tests.ops_helpers import IST, prop
from tests.test_ops_files import TODAY, _actor_u1, _stay, _tenant  # noqa: F401 (_actor_u1 is an autouse fixture)

DAY_AFTER = datetime.combine(TODAY, time(10, 30), tzinfo=IST).astimezone(UTC)  # check-out was yesterday
LINK = "https://g.page/r/sample-place/review"


def _world(db, business_type="villa_resort", checked_out_days_ago=1, **kw):
    t = _tenant(db, business_type)
    p = prop(db, t.id, "Villa Amara")
    stay = _stay(db, t, p, start=-(3 + checked_out_days_ago), nights=3, **kw)
    f = trips.ensure_file(db, t.id, stay)
    db.commit()
    return t, stay, f


def _approve(db, tenant_id):
    db.add(
        WATemplate(
            tenant_id=tenant_id,
            name=pack.REVIEW_REQUEST,
            language="en",
            category=TemplateCategory.UTILITY,
            status=TemplateStatus.APPROVED,
            components=[dict(c) for c in pack.BY_NAME[pack.REVIEW_REQUEST]["components"]],
        )
    )
    db.commit()


def _google(db, tenant_id, url=LINK):
    db.add(Integration(tenant_id=tenant_id, kind="google_business", status="active", config={"review_url": url}))
    db.commit()


def _run(db, tenant_id, now=DAY_AFTER):
    with (
        patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as tpl,
        patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as txt,
    ):
        auto.run_tenant(db, tenant_id, now=now)
    return tpl, txt


def _row(db, f):
    return db.query(OpsAutoMessage).filter_by(file_id=f.id, kind=rev.KIND).one_or_none()


def _asks(db, t, f):
    return db.query(Message).filter_by(tenant_id=t.id, idempotency_key=f"ops:{f.id}:{rev.KIND}").all()


def _thanks(db, t, f):
    return db.query(Message).filter_by(tenant_id=t.id, idempotency_key=f"ops:{f.id}:review_thanks").all()


def _events(db, f):
    return [e.text for e in db.query(OpsFileEvent).filter_by(file_id=f.id)]


def _asked(db, **kw):
    t, stay, f = _world(db, **kw)
    _approve(db, t.id)
    _run(db, t.id)
    assert _row(db, f).status == "sent"
    return t, stay, f


def _guest_writes(db, t, stay, body, at):
    """The guest's message lands in their open WhatsApp thread (opens the 24 h window); returns its id."""
    conv = db.query(Conversation).filter_by(tenant_id=t.id, guest_id=stay.guest_id, is_open=True).first()
    if conv is None:
        conv = Conversation(tenant_id=t.id, guest_id=stay.guest_id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(conv)
        db.flush()
    m = Message(
        tenant_id=t.id,
        conversation_id=conv.id,
        direction=MessageDirection.INBOUND,
        channel=ChannelType.WHATSAPP,
        body=body,
        created_at=datetime.now(UTC),
    )
    db.add(m)
    db.commit()
    return conv.id, m.id


def _answer(db, t, stay, body, hours=2):
    conv_id, msg_id = _guest_writes(db, t, stay, body, DAY_AFTER + timedelta(hours=hours))
    with (
        patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"),
        patch("app.workers.tasks.ops_escalation.queue_delivery"),
    ):
        return rev.on_guest_message(
            db, t.id, stay.guest_id, conv_id, body, now=DAY_AFTER + timedelta(hours=hours), message_id=msg_id
        )


# ── asking ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_sent_once_the_day_after_check_out_as_the_template(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    tpl, _ = _run(db, t.id)
    tpl.assert_called_once()
    assert tpl.call_args.kwargs["template_name"] == pack.REVIEW_REQUEST
    assert tpl.call_args.kwargs["variables"][1] == "stay at Villa Amara"
    msgs = _asks(db, t, f)
    assert len(msgs) == 1 and "1 (poor) to 5 (excellent)" in msgs[0].body and msgs[0].sender_kind == "system"
    tpl2, txt2 = _run(db, t.id, DAY_AFTER + timedelta(hours=3))  # later hourly runs, and the next day: never twice
    tpl3, _ = _run(db, t.id, DAY_AFTER + timedelta(days=1))
    tpl2.assert_not_called(), txt2.assert_not_called(), tpl3.assert_not_called()
    assert len(_asks(db, t, f)) == 1


def test_caravan_words_say_trip(db):
    t, stay, f = _world(db, business_type="caravan")
    _approve(db, t.id)
    tpl, _ = _run(db, t.id)
    assert tpl.call_args.kwargs["variables"][1] == "trip in Villa Amara"


def test_not_before_or_long_after_the_day_after(db):
    t, stay, f = _world(db, checked_out_days_ago=0)
    _approve(db, t.id)
    tpl, _ = _run(db, t.id)
    tpl.assert_not_called()
    t2, stay2, f2 = _world(db, checked_out_days_ago=2)  # missed its day (not a ticket hold): not asked late
    _approve(db, t2.id)
    tpl, _ = _run(db, t2.id)
    tpl.assert_not_called()
    assert _row(db, f) is None and _row(db, f2) is None


@pytest.mark.parametrize("hour,minute", [(9, 0), (20, 30), (23, 0)])
def test_quiet_hours_respected(db, hour, minute):
    t, stay, f = _world(db)
    _approve(db, t.id)
    tpl, _ = _run(db, t.id, datetime.combine(TODAY, time(hour, minute), tzinfo=IST).astimezone(UTC))
    tpl.assert_not_called()
    assert _row(db, f) is None


def test_not_for_a_cancelled_stay(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    stay.status = "cancelled"
    db.commit()
    tpl, _ = _run(db, t.id)
    tpl.assert_not_called()
    assert _row(db, f).status == "skipped" and _asks(db, t, f) == []


def test_not_for_a_comped_creator_stay(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    stay.channel_source = "creator"
    db.commit()
    tpl, _ = _run(db, t.id)
    tpl.assert_not_called()
    assert "creator" in _row(db, f).reason


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
    assert "stop" in _row(db, f).reason and _asks(db, t, f) == []


def test_template_not_approved_outside_the_window_is_skipped(db):
    t, stay, f = _world(db)
    tpl, _ = _run(db, t.id)  # default: off until the template is approved
    tpl.assert_not_called()
    assert _row(db, f) is None and not rev.enabled(db, t.id)
    db.add(OpsSettings(tenant_id=t.id, review_request_enabled=True))
    db.commit()
    _run(db, t.id)
    row = _row(db, f)
    assert row.status == "skipped" and "not approved" in row.reason and _asks(db, t, f) == []


def test_owner_switched_it_off(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    db.add(OpsSettings(tenant_id=t.id, review_request_enabled=False))
    db.commit()
    tpl, _ = _run(db, t.id)
    tpl.assert_not_called()
    assert _row(db, f) is None


def test_an_open_ticket_holds_the_ask_until_closed_at_most_three_days(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    ticket = OpsItem(
        tenant_id=t.id,
        title="Guest reports a complaint",
        kind="incident",
        category="complaint",
        severity="high",
        duty="ops_manager",
        stay_id=stay.id,
        source="guest_chat",
        status="open",
    )
    db.add(ticket)
    db.commit()
    tpl, _ = _run(db, t.id)
    tpl.assert_not_called()
    assert _row(db, f).reason == rev.TICKET_HOLD
    ticket.status = "closed"
    db.commit()
    tpl, _ = _run(db, t.id, DAY_AFTER + timedelta(days=2))
    tpl.assert_called_once()
    assert _row(db, f).status == "sent"


def test_a_ticket_open_past_three_days_means_no_ask(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    db.add(
        OpsItem(
            tenant_id=t.id,
            title="t",
            kind="incident",
            category="complaint",
            severity="high",
            duty="ops_manager",
            stay_id=stay.id,
            source="guest_chat",
            status="open",
        )
    )
    db.commit()
    _run(db, t.id)
    db.query(OpsItem).filter_by(stay_id=stay.id).update({"status": "closed"})
    db.commit()
    tpl, _ = _run(db, t.id, DAY_AFTER + timedelta(days=4))
    tpl.assert_not_called()
    assert _row(db, f).status == "skipped"


# ── the answer ──────────────────────────────────────────────────────────────────────────────────────────────


def test_rating_5_gets_thanks_and_the_link_and_no_ticket(db):
    t, stay, f = _asked(db)
    _google(db, t.id)
    assert _answer(db, t, stay, "5") == "rated"
    assert _row(db, f).response == "5"
    assert "The guest rated the stay 5/5." in _events(db, f)
    assert stay.guest.preferences["stay_rating"]["stars"] == 5
    thanks = _thanks(db, t, f)
    assert len(thanks) == 1 and LINK in thanks[0].body and "sorry" not in thanks[0].body
    assert db.query(OpsItem).filter_by(tenant_id=t.id).count() == 0


def test_rating_2_gets_the_same_link_and_a_ticket(db):
    t, stay, f = _asked(db)
    _google(db, t.id)
    assert _answer(db, t, stay, "2") == "rated"
    body = _thanks(db, t, f)[0].body
    assert LINK in body and "our team will contact you" in body  # never withheld for a low rating
    item = db.query(OpsItem).filter_by(tenant_id=t.id).one()
    assert item.category == "complaint" and item.stay_id == stay.id and item.source == "guest_chat"
    assert item.source_ref.startswith("msg:") and "2/5" in item.summary


def test_words_instead_of_a_number_still_get_the_link(db):
    t, stay, f = _asked(db)
    _google(db, t.id)
    assert _answer(db, t, stay, "Lovely place, the staff were great") == "feedback"
    assert _row(db, f).response == "feedback" and LINK in _thanks(db, t, f)[0].body
    assert db.query(OpsItem).filter_by(tenant_id=t.id).count() == 0


def test_negative_words_open_a_ticket_by_the_escalation_keywords(db):
    t, stay, f = _asked(db)
    _google(db, t.id)
    assert _answer(db, t, stay, "Worst experience ever, I want to complain") == "feedback"
    assert LINK in _thanks(db, t, f)[0].body
    assert db.query(OpsItem).filter_by(tenant_id=t.id, category="complaint").count() == 1


def test_no_google_link_means_thanks_only(db):
    t, stay, f = _asked(db)
    assert _answer(db, t, stay, "4") == "rated"
    body = _thanks(db, t, f)[0].body
    assert body.startswith("Thank you for rating") and "http" not in body


def test_only_the_first_answer_counts_and_late_answers_are_ignored(db):
    t, stay, f = _asked(db)
    assert _answer(db, t, stay, "5") == "rated"
    assert _answer(db, t, stay, "actually 3", hours=3) is None
    t2, stay2, f2 = _asked(db)
    assert _answer(db, t2, stay2, "5", hours=24 * 3 + 1) is None


def test_tenant_isolation(db):
    t, stay, f = _world(db)
    _approve(db, t.id)
    other = _tenant(db, "villa_resort")
    tpl, _ = _run(db, other.id)
    tpl.assert_not_called()
    assert _row(db, f) is None
    _run(db, t.id)
    assert rev.on_guest_message(db, other.id, stay.guest_id, None, "1", now=DAY_AFTER) is None
    assert _row(db, f).response is None and db.query(OpsItem).count() == 0


@pytest.mark.parametrize(
    "text,stars",
    [
        ("5", 5),
        ("5!", 5),
        ("4/5", 4),
        ("4 out of 5", 4),
        ("4 stars - lovely", 4),
        ("I would give it a 4", 4),
        ("⭐⭐⭐⭐⭐", 5),
        ("5 loved it", 5),
        ("Rating: 3", 3),
        ("We loved the 2 nights", None),
        ("2 nights was great", None),
        ("3pm checkout was late", None),
        ("10/10", None),
        ("great stay", None),
    ],
)
def test_parse_rating(text, stars):
    assert rev.parse_rating(text) == stars


# ── the metric (D-33) ───────────────────────────────────────────────────────────────────────────────────────


def test_review_request_results(db):
    t, stay, f = _asked(db)
    lo, hi = DAY_AFTER - timedelta(days=1), DAY_AFTER + timedelta(days=5)
    assert kpi_metrics.review_request_results(db, t.id, lo, hi)["rating_rate"] == 0.0
    _answer(db, t, stay, "4")
    db.add(
        MarketingGuestReview(
            tenant_id=t.id,
            source="google",
            external_id="r1",
            rating=5,
            reviewed_at=DAY_AFTER.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    )
    db.commit()
    out = kpi_metrics.review_request_results(db, t.id, lo, hi)
    assert out == {
        "asked": 1,
        "rated": 1,
        "feedback": 0,
        "rating_rate": 1.0,
        "average_stars": 4.0,
        "google_reviews": 1,
        "google_reviews_per_stay_asked": 1.0,
    }
    empty = kpi_metrics.review_request_results(db, _tenant(db, "villa_resort").id, lo, hi)
    assert empty["asked"] == 0 and empty["rating_rate"] is None and empty["average_stars"] is None


def test_google_review_url_from_location_metadata():
    from app.adapters.google_business import review_url

    assert review_url({"newReviewUri": LINK, "placeId": "x"}) == LINK
    assert review_url({"placeId": "ChIJ_abc-1"}) == "https://search.google.com/local/writereview?placeid=ChIJ_abc-1"
    assert review_url({"newReviewUri": "http://evil.example", "placeId": "a b"}) is None and review_url(None) is None
