"""GET /analytics/executive: each card's previous window is [prev_start, period_start), not prev_start..now.

The previous period used to run to now, so it also counted the current period (QA prev averaged both windows).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_analytics_executive import _auth, _entitle_analytics_modules, _guest  # noqa: F401

pytestmark = pytest.mark.usefixtures("capabilities_seeded")


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _get(client, tenant_and_user, **params):
    res = client.get("/api/v1/analytics/executive", params=params, headers=_auth(tenant_and_user["access_token"]))
    assert res.status_code == 200, res.text
    return res.json()


def test_qa_current_and_previous_windows_do_not_overlap(client, tenant_and_user, db):
    from app.models.call import Call, CallDirection
    tid = tenant_and_user["tenant"].id
    for score, days_ago in ((80, 3), (90, 10), (60, 40)):
        db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
                    direction=CallDirection.INBOUND, from_number="+919876543210", to_number="+912271264296",
                    ai_score=score, started_at=_iso(days_ago)))
    db.commit()
    data = _get(client, tenant_and_user, range_days=30)
    assert data["qa_avg_score"] == 85.0
    assert data["qa_prev"] == 60.0  # was 76.7: the 3 calls averaged together


def test_ai_draft_rate_previous_window_is_bounded(client, tenant_and_user, db):
    from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
    tid = tenant_and_user["tenant"].id
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=_guest(db, tid), channel=ChannelType.WHATSAPP)
    db.add(conv)
    now = datetime.now(timezone.utc)
    # current window: 1 of 2 outbound is AI; previous window: 0 of 1
    for ai, days_ago in ((True, 2), (False, 2), (False, 12)):
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                       channel=ChannelType.WHATSAPP, body="hi", is_ai_generated=ai,
                       created_at=now - timedelta(days=days_ago)))
    db.commit()
    data = _get(client, tenant_and_user, range_days=7)
    assert data["ai_draft_rate_pct"] == 50.0
    assert data["ai_draft_prev"] == 0.0  # was 33.3
