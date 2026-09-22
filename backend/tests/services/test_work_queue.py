"""The one work queue (work_queue_service).

The point of this service is that every screen agrees, so these tests pin
both halves: each kind counts what its own screen counts, and the dashboard
cards read the same numbers as the queue.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import dashboard_service, work_queue_service as wq

NOW = datetime.now(timezone.utc)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"wq-{uuid.uuid4().hex[:6]}", plan="growth",
               ivr_provider="vobiz")
    db.add(t); db.flush(); return t


def _user(db, tid):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name="Agent", email=f"a-{uuid.uuid4().hex[:6]}@t.com",
             role=UserRole.CONCIERGE, is_active=True)
    db.add(u); db.flush(); return u


def _guest(db, tid, name="Guest"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name, phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g); db.flush(); return g


def _waiting(db, tid, assigned_to=None, minutes=30, name="Waiting Guest"):
    g = _guest(db, tid, name)
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.INSTAGRAM,
                     is_open=True, assigned_to=assigned_to)
    db.add(c); db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=c.id, direction="inbound",
                   channel=ChannelType.INSTAGRAM, body="hello?", created_at=NOW - timedelta(minutes=minutes)))
    db.flush()
    return c


def _missed(db, tid, minutes=20):
    g = _guest(db, tid, "Caller")
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, ivr_provider="vobiz",
                ivr_call_id=f"c-{uuid.uuid4().hex[:8]}", direction=CallDirection.INBOUND,
                from_number=g.phone, to_number="+918000000000", duration_seconds=0,
                created_at=NOW - timedelta(minutes=minutes)))
    db.flush()


def test_queue_collects_every_kind(db):
    t = _tenant(db)
    me = _user(db, t.id)
    _waiting(db, t.id, assigned_to=me.id)
    _missed(db, t.id)
    db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title="Call Anand back", is_done=False,
                assigned_to=me.id, due_date=NOW - timedelta(hours=3)))
    g = _guest(db, t.id, "Unowned Lead")
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, stage=InquiryStage.NEW,
                   source=InquirySource.WA_DIRECT, created_at=NOW - timedelta(hours=2)))
    db.commit()

    res = wq.build(db, t, scope_user_id=None)
    assert res["counts"]["reply"] == 1
    assert res["counts"]["callback"] == 1
    assert res["counts"]["followup"] == 1
    assert res["counts"]["unassigned"] == 1
    assert res["total"] == sum(res["counts"].values())
    kinds = [i["kind"] for i in res["items"]]
    assert kinds[0] == "followup"          # overdue sorts first
    assert set(kinds) == {"reply", "callback", "followup", "unassigned"}
    assert all(i["action"] and i["href"] for i in res["items"])


def test_dashboard_cards_read_the_same_numbers(db):
    t = _tenant(db)
    _waiting(db, t.id)
    _waiting(db, t.id, minutes=90)
    _missed(db, t.id)
    db.commit()

    q = wq.counts(db, t, None)
    cards = dashboard_service.needs_you_now(db, t, scope_user_id=None)
    assert cards["waiting_reply"] == q["counts"]["reply"] == 2
    assert cards["missed_not_called_back"] == q["counts"]["callback"] == 1
    assert cards["waiting_oldest_at"] == q["oldest"]["reply"]


def test_an_agent_sees_only_their_own_work(db):
    t = _tenant(db)
    me, peer = _user(db, t.id), _user(db, t.id)
    _waiting(db, t.id, assigned_to=me.id)
    _waiting(db, t.id, assigned_to=peer.id)
    db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title="peer task", is_done=False,
                assigned_to=peer.id, due_date=NOW - timedelta(hours=1)))
    db.commit()

    mine = wq.build(db, t, scope_user_id=me.id)
    assert mine["counts"]["reply"] == 1
    assert mine["counts"]["followup"] == 0
    assert mine["scope"] == "mine"
    assert wq.build(db, t, scope_user_id=None)["counts"]["reply"] == 2


def test_future_tasks_and_old_calls_stay_out(db):
    t = _tenant(db)
    me = _user(db, t.id)
    db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title="next week", is_done=False,
                assigned_to=me.id, due_date=NOW + timedelta(days=5)))
    db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title="done already", is_done=True,
                assigned_to=me.id, due_date=NOW - timedelta(hours=2)))
    _missed(db, t.id, minutes=60 * 24 * 10)   # older than the call-back window
    db.commit()
    res = wq.build(db, t, scope_user_id=me.id)
    assert res["counts"]["followup"] == 0 and res["counts"]["callback"] == 0


def test_kinds_filter_and_other_tenants(db):
    t, other = _tenant(db), _tenant(db)
    _waiting(db, t.id)
    _missed(db, t.id)
    _waiting(db, other.id)
    _missed(db, other.id)
    db.commit()

    only_calls = wq.build(db, t, scope_user_id=None, kinds=["callback"])
    assert only_calls["counts"]["callback"] == 1
    assert {i["kind"] for i in only_calls["items"]} == {"callback"}
    assert wq.build(db, t, scope_user_id=None)["counts"]["reply"] == 1   # not the other tenant's


def test_endpoint_returns_the_queue(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _waiting(db, tid)
    db.commit()
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    r = client.get("/api/v1/work-queue", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["reply"] == 1 and body["scope"] == "team"
    assert client.get("/api/v1/work-queue?mine_only=true", headers=h).json()["scope"] == "mine"
    assert client.get("/api/v1/work-queue/counts", headers=h).json()["counts"]["reply"] == 1
    assert client.get("/api/v1/work-queue?kinds=nonsense", headers=h).status_code == 422
