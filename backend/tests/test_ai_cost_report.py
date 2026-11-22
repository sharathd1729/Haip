"""scripts/ai_cost_report.py (AI_COST_SPEC step 0): per-task cost, reads per phone call, short calls, expired drafts."""

import sys
import uuid
from datetime import UTC, datetime, timedelta

from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.tenant import Tenant
from app.models.usage_event import UsageEvent


class _ReadOnly:
    """The test session for the script's SessionLocal(), without letting its rollback/close touch the test's rows."""

    def __init__(self, db):
        self._db = db

    def rollback(self):
        pass

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._db, name)


def _use(db, tid, task, cost, ref_type=None, ref_id=None, at=None, **meta):
    row = UsageEvent(
        tenant_id=tid,
        module="t",
        kind="llm_call",
        units=100,
        input_units=80,
        meta={"task": task, "cost_usd": cost, "ok": True, **meta},
        ref_type=ref_type,
        ref_id=ref_id,
    )
    db.add(row)
    db.flush()
    if at:
        row.created_at = at


def test_the_report_counts_reads_per_call_short_calls_and_expired_drafts(db, monkeypatch, capsys):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"cost-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="G")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id)
    db.add(inq)
    db.flush()
    call = Call(
        id=str(uuid.uuid4()),
        tenant_id=t.id,
        ivr_provider="vobiz",
        ivr_call_id="x1",
        direction=CallDirection.INBOUND,
        from_number="+919800000001",
        to_number="+912200000000",
        duration_seconds=20,
        inquiry_id=inq.id,
    )
    db.add(call)
    now = datetime.now(UTC) - timedelta(hours=2)
    _use(db, t.id, "call_analysis", 0.10, "call", call.id, now, attempts=2, cache_read_tokens=20)
    _use(db, t.id, "deep_reason", 0.05, "call", call.id, now + timedelta(seconds=30))
    _use(db, t.id, "lead_summary", 0.02, "inquiry", inq.id, now + timedelta(minutes=2))  # call-triggered
    _use(db, t.id, "lead_summary", 0.02, "inquiry", inq.id, now + timedelta(hours=1))  # later: not counted for the call
    _use(db, t.id, "concierge_draft", 0.04)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    draft = Message(
        id=str(uuid.uuid4()),
        tenant_id=t.id,
        conversation_id=conv.id,
        direction="outbound",
        channel=ChannelType.WHATSAPP,
        body="d",
        is_ai_generated=True,
    )
    db.add(draft)
    db.flush()
    db.add(AIDraftOutcome(tenant_id=t.id, draft_message_id=draft.id, outcome="expired"))
    db.commit()

    monkeypatch.setattr("app.core.database.SessionLocal", lambda: _ReadOnly(db))
    monkeypatch.setattr(sys, "argv", ["ai_cost_report.py", "--days", "30", "--tenant", t.slug, "--usd-inr", "88"])
    sys.path.insert(0, "scripts")
    import ai_cost_report

    assert ai_cost_report.main() == 0
    out = capsys.readouterr().out
    assert "Total model cost: $0.23" in out
    assert "Calls analysed: 1; reads per call: avg 3.00" in out  # analysis + re-check + the summary 2 min later
    assert "Under 30 s: 1 calls, reads $0.15" in out
    assert "expired     1 (100%)" in out
    assert "Retried calls' extra cost (upper bound): $0.05" in out
