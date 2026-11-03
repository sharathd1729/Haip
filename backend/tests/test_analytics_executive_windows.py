"""GET /analytics/executive: each card's previous window is [prev_start, period_start), not prev_start..now.

The previous period used to run to now, so it also counted the current period (QA prev averaged both windows).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_analytics_executive import _auth, _entitle_analytics_modules, _guest  # noqa: F401

pytestmark = pytest.mark.usefixtures("capabilities_seeded")


def _iso(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _get(client, tenant_and_user, **params):
    res = client.get("/api/v1/analytics/executive", params=params, headers=_auth(tenant_and_user["access_token"]))
    assert res.status_code == 200, res.text
    return res.json()


def test_qa_current_and_previous_windows_do_not_overlap(client, tenant_and_user, db):
    from app.models.call import Call, CallDirection

    tid = tenant_and_user["tenant"].id
    for score, days_ago in ((80, 3), (90, 10), (60, 40)):
        db.add(
            Call(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                ivr_provider="vobiz",
                ivr_call_id=str(uuid.uuid4()),
                direction=CallDirection.INBOUND,
                from_number="+919876543210",
                to_number="+912271264296",
                ai_score=score,
                started_at=_iso(days_ago),
            )
        )
    db.commit()
    data = _get(client, tenant_and_user, range_days=30)
    assert data["qa_avg_score"] == 85.0
    assert data["qa_prev"] == 60.0  # was 76.7: the 3 calls averaged together


def test_ai_draft_rate_previous_window_is_bounded(client, tenant_and_user, db):
    from app.models.conversation import ChannelType, Conversation, Message, MessageDirection

    tid = tenant_and_user["tenant"].id
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=_guest(db, tid), channel=ChannelType.WHATSAPP)
    db.add(conv)
    now = datetime.now(UTC)
    # current window: 1 of 2 outbound is AI; previous window: 0 of 1
    for ai, days_ago in ((True, 2), (False, 2), (False, 12)):
        db.add(
            Message(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                conversation_id=conv.id,
                direction=MessageDirection.OUTBOUND,
                channel=ChannelType.WHATSAPP,
                body="hi",
                is_ai_generated=ai,
                created_at=now - timedelta(days=days_ago),
            )
        )
    db.commit()
    data = _get(client, tenant_and_user, range_days=7)
    assert data["ai_draft_rate_pct"] == 50.0
    assert data["ai_draft_prev"] == 0.0  # was 33.3


def _journey(db, tid, received_days_ago, contact_after_min=None):
    from app.models.inquiry import Inquiry, InquirySource
    from app.models.lead_workflow import LeadJourney

    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=_guest(db, tid), source=InquirySource.WA_DIRECT)
    db.add(inq)
    received = datetime.now(UTC) - timedelta(days=received_days_ago)
    db.add(
        LeadJourney(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            inquiry_id=inq.id,
            received_at=received,
            first_human_contact_at=(
                received + timedelta(minutes=contact_after_min) if contact_after_min is not None else None
            ),
        )
    )


def test_sla_uses_first_human_contact_and_the_work_queue_new_lead_sla(client, tenant_and_user, db):
    tid = tenant_and_user["tenant"].id
    _journey(db, tid, 2, contact_after_min=5)  # on time (new_lead SLA: 15 min)
    _journey(db, tid, 2, contact_after_min=90)  # late
    _journey(db, tid, 3)  # never contacted, long past the SLA: breached
    _journey(db, tid, 1, contact_after_min=10)  # on time
    _journey(db, tid, 0.001)  # 1.4 min old, not contacted: not due yet, left out
    _journey(db, tid, 10, contact_after_min=120)  # previous window: late
    db.commit()
    data = _get(client, tenant_and_user, range_days=7)
    assert data["sla_compliance_pct"] == 50.0
    assert data["sla_prev"] == 0.0


def test_sla_no_data_is_none_not_100(client, tenant_and_user, db):
    _journey(db, tenant_and_user["tenant"].id, 0.001)
    db.commit()
    data = _get(client, tenant_and_user, range_days=7)
    assert data["sla_compliance_pct"] is None and data["sla_prev"] is None


def test_revenue_chart_is_zero_filled_by_ist_day_and_ignores_cancelled_stays(client, tenant_and_user, db):
    from app.models.inquiry import Inquiry, InquirySource
    from app.models.inquiry_360 import InquiryQuote
    from app.models.property import Property, Stay
    from app.services.date_presets import IST

    tid = tenant_and_user["tenant"].id
    today = datetime.now(IST).date()
    prop = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Ratha 1", slug="r1", type="caravan", is_active=True)
    db.add(prop)
    gid = _guest(db, tid)
    for status, amount, days_ago in (("confirmed", 40000, 1), ("cancelled", 10, 2), ("blocked", 0, 3)):
        db.add(
            Stay(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                guest_id=gid,
                property_id=prop.id,
                status=status,
                total_amount=amount,
                check_in=today - timedelta(days=days_ago),
                check_out=today,
            )
        )
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=gid, source=InquirySource.WA_DIRECT)
    db.add(inq)
    group = str(uuid.uuid4())
    # 2 options of one quote 2 days ago: only the primary counts; a quote awaiting approval is not issued
    issued = datetime.now(UTC) - timedelta(days=2)
    for rank, amount, status in ((1, 30000, "issued"), (2, 25000, "issued")):
        db.add(
            InquiryQuote(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                inquiry_id=inq.id,
                amount=amount,
                status=status,
                option_rank=rank,
                option_group_id=group,
                created_at=issued,
            )
        )
    db.add(
        InquiryQuote(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            inquiry_id=inq.id,
            amount=99000,
            status="pending_approval",
            created_at=issued,
        )
    )
    db.commit()

    chart = _get(client, tenant_and_user, range_days=7)["revenue_chart"]
    assert [p["date"] for p in chart] == [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    by_day = {p["date"]: p for p in chart}
    assert by_day[(today - timedelta(days=1)).isoformat()]["confirmed"] == 40000.0
    assert sum(p["confirmed"] for p in chart) == 40000.0  # cancelled / blocked stays add nothing
    assert by_day[issued.astimezone(IST).date().isoformat()]["quoted"] == 30000.0
    assert sum(p["quoted"] for p in chart) == 30000.0
