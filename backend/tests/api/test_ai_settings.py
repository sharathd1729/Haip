"""GET / PATCH /api/v1/settings/ai (docs/ai/AI_SWITCHES_SPEC.md step 2): every AI switch with its last-30-day cost and
uses (usage_events), drafts nobody used (ai_draft_outcomes "expired"), owner/manager only, one audit row per change."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.core.security import create_access_token, get_password_hash
from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.usage_event import UsageEvent
from app.models.user import User, UserRole

URL = "/api/v1/settings/ai"


def _tenant(db, **cols):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth", **cols)
    db.add(t)
    db.commit()
    return t


def _headers(db, tid, role=UserRole.OWNER):
    u = User(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        name=role.value,
        email=f"{role.value}-{uuid.uuid4().hex[:6]}@t.com",
        hashed_password=get_password_hash("pw"),
        role=role,
        is_active=True,
    )
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'tenant_id': tid, 'role': role.value})}"}


def _message(db, tid, channel, meta=None, direction="inbound"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=channel, is_open=True)
    db.add(c)
    db.flush()
    m = Message(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        conversation_id=c.id,
        direction=direction,
        channel=channel,
        body="hi",
        channel_metadata=meta,
    )
    db.add(m)
    db.flush()
    return m


def _use(db, tid, task, cost, ref_id=None, days_ago=1, kind="llm_call"):
    row = UsageEvent(
        tenant_id=tid,
        module="test",
        kind=kind,
        units=10,
        meta={"task": task, "cost_usd": cost},
        ref_type="message" if ref_id else None,
        ref_id=ref_id,
    )
    db.add(row)
    db.flush()
    row.created_at = datetime.now(UTC) - timedelta(days=days_ago)


def _world(db):
    t = _tenant(db)
    wa = _message(db, t.id, ChannelType.WHATSAPP)
    comment = _message(db, t.id, ChannelType.INSTAGRAM, {"source": "comment"})
    _use(db, t.id, "call_analysis", 0.10)
    _use(db, t.id, "deep_reason", 0.05)
    _use(db, t.id, "lead_summary", None)  # cost unknown: counted, never estimated
    _use(db, t.id, "lead_summary", 0.02, days_ago=45)  # outside the 30 days
    _use(db, t.id, "concierge_draft", 0.03, ref_id=wa.id)
    _use(db, t.id, "concierge_intent", 0.01, ref_id=comment.id)
    _use(db, t.id, "concierge_draft", 0.04, ref_id=str(uuid.uuid4()))  # the "write a draft" button's fresh id
    _use(db, t.id, "marketing_content", 0.20)
    draft = _message(db, t.id, ChannelType.WHATSAPP, direction="outbound")
    db.add(AIDraftOutcome(tenant_id=t.id, draft_message_id=draft.id, outcome="expired"))
    db.add(AIDraftOutcome(tenant_id=t.id, draft_message_id=draft.id, outcome="sent_verbatim"))
    db.commit()
    return t


def _row(rows, key):
    return next(r for r in rows if r["key"] == key)


def test_owner_sees_every_switch_with_its_30_day_cost_and_unused_drafts(client, db):
    t = _world(db)
    res = client.get(URL, headers=_headers(db, t.id))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["period_days"] == 30
    calls = _row(body["features"], "call_analysis")
    assert calls["enabled"] is True and calls["uses"] == 2 and calls["cost_usd"] == 0.15
    summaries = _row(body["features"], "lead_summaries")
    assert summaries["uses"] == 1 and summaries["cost_unknown_uses"] == 1 and summaries["cost_usd"] == 0
    assert _row(body["features"], "call_transcription")["cost_note"] == "not_metered"
    assert _row(body["features"], "personal_whatsapp_summaries")["enabled"] is False
    wa = _row(body["reply_modes"], "whatsapp_replies")
    assert wa["mode"] == "shadow" and wa["uses"] == 1 and wa["cost_usd"] == 0.03 and wa["unused_drafts"] == 1
    comments = _row(body["reply_modes"], "instagram_comment_replies")
    assert comments["mode"] == "off" and comments["uses"] == 1 and comments["cost_usd"] == 0.01
    assert body["replies_other"]["uses"] == 1 and body["replies_other"]["cost_usd"] == 0.04
    assert _row(body["module_switched"], "marketing")["cost_usd"] == 0.2
    assert body["total_cost_usd"] == 0.43


def test_a_manager_may_read_and_change_switches(client, db):
    t = _tenant(db)
    h = _headers(db, t.id, UserRole.MANAGER)
    assert client.get(URL, headers=h).status_code == 200
    assert client.patch(URL, json={"features": {"briefings": False}}, headers=h).status_code == 200


def test_other_roles_are_refused(client, db):
    t = _tenant(db)
    for role in (UserRole.RESERVATIONS, UserRole.CONCIERGE):
        h = _headers(db, t.id, role)
        assert client.get(URL, headers=h).status_code == 403
        assert client.patch(URL, json={"features": {"call_analysis": False}}, headers=h).status_code == 403
    db.refresh(t)
    assert t.ai_features is None


def test_patch_changes_switches_audits_each_change_and_clears_the_gate_cache(client, db):
    t = _tenant(db)
    h = _headers(db, t.id)
    body = {
        "features": {"call_analysis": False, "lead_summaries": True},
        "reply_modes": {"instagram_comment_replies": "shadow"},
    }
    with patch("app.services.ai_features.forget") as forget:
        res = client.patch(URL, json=body, headers=h)
    assert res.status_code == 200, res.text
    out = res.json()
    # lead_summaries was already on (its default): not a change, not audited
    assert sorted(c["feature"] for c in out["changed"]) == ["call_analysis", "instagram_comment_replies"]
    assert _row(out["features"], "call_analysis")["enabled"] is False
    assert _row(out["reply_modes"], "instagram_comment_replies")["mode"] == "shadow"
    forget.assert_called_once_with(t.id)
    db.refresh(t)
    assert t.ai_features == {"call_analysis": False} and t.ig_comment_ai_mode_default == "shadow"
    audits = db.query(AuditEvent).filter_by(tenant_id=t.id, action="ai.feature_changed").all()
    assert {(a.payload["feature"], a.payload["old"], a.payload["new"]) for a in audits} == {
        ("call_analysis", True, False),
        ("instagram_comment_replies", "off", "shadow"),
    }
    # the same request again changes nothing and writes no new audit row
    with patch("app.services.ai_features.forget") as forget:
        assert client.patch(URL, json=body, headers=h).json()["changed"] == []
    forget.assert_not_called()
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="ai.feature_changed").count() == 2


def test_unknown_switches_and_modes_are_rejected(client, db):
    t = _tenant(db)
    h = _headers(db, t.id)
    assert client.patch(URL, json={"features": {"teleport": False}}, headers=h).status_code == 422
    assert client.patch(URL, json={"reply_modes": {"whatsapp_replies": "always"}}, headers=h).status_code == 422
    assert client.patch(URL, json={"reply_modes": {"email_replies": "off"}}, headers=h).status_code == 422
    assert client.patch(URL, json={"ask_haip": False}, headers=h).status_code == 422  # module-switched, not here
    db.refresh(t)
    assert t.ai_features is None


def test_one_workspace_never_sees_or_changes_another(client, db):
    a = _world(db)
    b = _tenant(db)
    hb = _headers(db, b.id)
    body = client.get(URL, headers=hb).json()
    assert body["total_cost_usd"] == 0 and _row(body["reply_modes"], "whatsapp_replies")["unused_drafts"] == 0
    assert client.patch(URL, json={"features": {"call_analysis": False}}, headers=hb).status_code == 200
    db.refresh(a)
    db.refresh(b)
    assert a.ai_features is None and b.ai_features == {"call_analysis": False}
    assert db.query(AuditEvent).filter_by(tenant_id=a.id, action="ai.feature_changed").count() == 0
