"""
Tests for leads_service.get_needs_action and GET /api/v1/leads/needs-action --
the Leads default view that groups open leads by the agent's next step.

Bucket rules (most urgent first, each lead in exactly one bucket):
  draft_ready -- guest waiting AND a pending AI draft exists
  waiting     -- guest's last message unanswered (<= 7 days)
  call        -- shared a phone, no real call since the enquiry
  followup    -- AI flagged the lead for a human
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.core.security import create_access_token
from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity, IdentityType
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import leads_service

NOW = datetime.now(timezone.utc)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"na-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _lead(db, tenant_id, name="Guest", phone=False, assigned_to=None, stage=InquiryStage.NEW):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone="")
    db.add(g); db.flush()
    if phone:
        db.add(GuestIdentity(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id,
            identity_type=IdentityType.PHONE, identity_value=f"+9198{uuid.uuid4().int % 10**8:08d}",
            source="test", confidence=0.9,
        ))
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, stage=stage,
        source=InquirySource.META_IG, assigned_to=assigned_to,
        created_at=NOW - timedelta(hours=6), updated_at=NOW - timedelta(hours=1),
    )
    db.add(inq); db.flush()
    return inq


def _conv(db, inq):
    c = Conversation(
        id=str(uuid.uuid4()), tenant_id=inq.tenant_id, guest_id=inq.guest_id,
        inquiry_id=inq.id, channel="instagram",
    )
    db.add(c); db.flush(); return c


def _msg(db, conv, direction, at, **kw):
    db.add(Message(
        id=str(uuid.uuid4()), tenant_id=conv.tenant_id, conversation_id=conv.id,
        direction=direction, channel="instagram", body="hi", created_at=at, **kw,
    ))
    db.flush()


def _buckets(resp):
    return {b.key: [c.inquiry_id for c in b.leads] for b in resp.buckets}


def test_leads_land_in_exactly_one_most_urgent_bucket(db):
    t = _tenant(db)

    drafted = _lead(db, t.id, "Drafted")
    c = _conv(db, drafted)
    _msg(db, c, "inbound", NOW - timedelta(minutes=30))
    _msg(db, c, "outbound", NOW - timedelta(minutes=29), is_ai_generated=True, was_approved=None)

    waiting = _lead(db, t.id, "Waiting", phone=True)  # phone too, but waiting wins
    _msg(db, _conv(db, waiting), "inbound", NOW - timedelta(hours=2))

    to_call = _lead(db, t.id, "Call me", phone=True)
    c = _conv(db, to_call)
    _msg(db, c, "inbound", NOW - timedelta(hours=3))
    _msg(db, c, "outbound", NOW - timedelta(hours=3) + timedelta(seconds=20))

    flagged = _lead(db, t.id, "Flagged")
    c = _conv(db, flagged)
    _msg(db, c, "inbound", NOW - timedelta(hours=4))
    _msg(db, c, "outbound", NOW - timedelta(hours=4) + timedelta(seconds=20),
         sent_autonomously=True, ai_needs_human_reason="Custom quote")

    nothing = _lead(db, t.id, "Handled")
    c = _conv(db, nothing)
    _msg(db, c, "inbound", NOW - timedelta(hours=5))
    _msg(db, c, "outbound", NOW - timedelta(hours=5) + timedelta(seconds=20))
    db.commit()

    resp = leads_service.get_needs_action(db, t.id)
    b = _buckets(resp)
    assert b["draft_ready"] == [drafted.id]
    assert b["waiting"] == [waiting.id]
    assert b["call"] == [to_call.id]
    assert b["followup"] == [flagged.id]
    every = [i for ids in b.values() for i in ids]
    assert nothing.id not in every
    assert len(every) == len(set(every))
    assert resp.kpis.waiting == 2 and resp.kpis.drafts_ready == 1 and resp.kpis.phone_not_called == 1


def test_superseded_draft_is_not_ready_to_send(db):
    """A pending draft left over after the guest already got a reply."""
    t = _tenant(db)
    inq = _lead(db, t.id)
    c = _conv(db, inq)
    _msg(db, c, "inbound", NOW - timedelta(hours=2))
    _msg(db, c, "outbound", NOW - timedelta(hours=2) + timedelta(seconds=5), is_ai_generated=True, was_approved=None)
    _msg(db, c, "outbound", NOW - timedelta(hours=2) + timedelta(seconds=30))
    db.commit()
    assert _buckets(leads_service.get_needs_action(db, t.id))["draft_ready"] == []


def test_stale_wait_beyond_messaging_window_is_dropped(db):
    t = _tenant(db)
    inq = _lead(db, t.id)
    _msg(db, _conv(db, inq), "inbound", NOW - timedelta(days=9))
    db.commit()
    assert _buckets(leads_service.get_needs_action(db, t.id))["waiting"] == []


def test_phone_lead_already_called_is_not_in_call_bucket(db):
    t = _tenant(db)
    inq = _lead(db, t.id, phone=True)
    db.add(Call(
        id=str(uuid.uuid4()), tenant_id=t.id, guest_id=inq.guest_id, ivr_provider="vobiz",
        ivr_call_id=f"c-{uuid.uuid4().hex[:8]}", direction=CallDirection.OUTBOUND,
        from_number="+918000000000", to_number="+919800000000", duration_seconds=60,
        created_at=NOW - timedelta(hours=1),
    ))
    db.commit()
    assert _buckets(leads_service.get_needs_action(db, t.id))["call"] == []


def test_tenant_isolation(db):
    a, b = _tenant(db), _tenant(db)
    inq_b = _lead(db, b.id, phone=True)
    db.commit()
    every = [i for ids in _buckets(leads_service.get_needs_action(db, a.id)).values() for i in ids]
    assert inq_b.id not in every


def test_scope_hides_peer_agents_leads(db):
    t = _tenant(db)
    me = str(uuid.uuid4())
    peer = str(uuid.uuid4())
    for uid in (me, peer):
        db.add(User(id=uid, tenant_id=t.id, name=uid[:4], email=f"{uid[:8]}@t.com",
                    role=UserRole.CONCIERGE, is_active=True))
    db.flush()
    mine = _lead(db, t.id, phone=True, assigned_to=me)
    unclaimed = _lead(db, t.id, phone=True)
    peers = _lead(db, t.id, phone=True, assigned_to=peer)
    db.commit()
    ids = _buckets(leads_service.get_needs_action(db, t.id, scope_user_id=me))["call"]
    assert set(ids) == {mine.id, unclaimed.id}
    assert peers.id not in ids


# ── endpoint ──────────────────────────────────────────────────────────────────

def _auth(user):
    tok = create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})
    return {"Authorization": f"Bearer {tok}"}


def test_endpoint_happy_path_and_cross_tenant(client, db, tenant_and_user):
    owner = tenant_and_user["user"]
    mine = _lead(db, owner.tenant_id, phone=True)
    other = _tenant(db)
    theirs = _lead(db, other.id, phone=True)
    db.commit()

    res = client.get("/api/v1/leads/needs-action", headers=_auth(owner))
    assert res.status_code == 200
    body = res.json()
    assert [b["key"] for b in body["buckets"]] == ["draft_ready", "waiting", "call", "followup"]
    ids = [c["inquiry_id"] for b in body["buckets"] for c in b["leads"]]
    assert mine.id in ids and theirs.id not in ids


def test_endpoint_requires_auth(client):
    assert client.get("/api/v1/leads/needs-action").status_code in (401, 403)


def test_endpoint_rejects_out_of_range_window(client, tenant_and_user):
    res = client.get("/api/v1/leads/needs-action?window_days=365", headers=_auth(tenant_and_user["user"]))
    assert res.status_code == 422
