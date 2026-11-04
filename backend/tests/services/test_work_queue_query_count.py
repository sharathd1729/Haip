"""GET /work-queue took ~40 s on Rathaa-size data. The number of SQL statements build() runs must not grow with the
number of people on the list (no N+1), and a mid-size workspace must build quickly."""

import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import event

from app.models.conversation import Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.task import Task
from app.models.tenant import Tenant
from app.services import work_queue_service as wq

NOW = datetime.now(UTC)


def _seed(db, tid, n):
    for k in range(n):
        g = Guest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            name=f"Guest {k}",
            phone=f"+9198{uuid.uuid4().int % 10**8:08d}",
            first_touch_channel="whatsapp",
            lead_identified_at=NOW - timedelta(hours=5 + k),
        )
        db.add(g)
        db.flush()
        i = Inquiry(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            guest_id=g.id,
            stage=InquiryStage.NEW,
            source=InquirySource.WA_DIRECT,
            created_at=NOW - timedelta(hours=5 + k),
        )
        c = Conversation(
            id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, inquiry_id=i.id, channel="whatsapp", is_open=True
        )
        db.add_all([i, c])
        db.flush()
        for m in range(3):
            db.add(
                Message(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    conversation_id=c.id,
                    direction="inbound" if m % 2 == 0 else "outbound",
                    channel="whatsapp",
                    body="hi",
                    created_at=NOW - timedelta(hours=4 + k, minutes=m),
                )
            )
        if k % 3 == 0:
            db.add(
                Task(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    title=f"Call Guest {k}",
                    guest_id=g.id,
                    inquiry_id=i.id,
                    due_date=NOW - timedelta(hours=1),
                    is_done=False,
                )
            )
    db.commit()


def _statements(db, tenant):
    n = [0]

    def count(*_a, **_k):
        n[0] += 1

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", count)
    try:
        started = time.perf_counter()
        res = wq.build(db, tenant, scope_user_id=None)
        return n[0], time.perf_counter() - started, res
    finally:
        event.remove(engine, "before_cursor_execute", count)


def test_build_runs_the_same_number_of_queries_for_10_or_60_people(db):
    small, big = (
        Tenant(id=str(uuid.uuid4()), name=x, slug=f"wqc-{uuid.uuid4().hex[:6]}", plan="growth", ivr_provider="vobiz")
        for x in ("S", "B")
    )
    db.add_all([small, big])
    db.flush()
    _seed(db, small.id, 10)
    _seed(db, big.id, 60)
    q_small, _, r_small = _statements(db, small)
    q_big, secs, r_big = _statements(db, big)
    assert r_small["people"] >= 10 and r_big["people"] >= 60
    print(f"work_queue.build: {q_small} statements for 10 people, {q_big} for 60, {secs:.2f}s")
    assert q_big <= q_small + 5, f"N+1: {q_small} statements for 10 people, {q_big} for 60"
    assert secs < 5, f"build() took {secs:.1f}s for 60 people"
