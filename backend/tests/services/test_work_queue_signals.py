"""The owner dashboard's additions to the one work queue (work_queue_signals): the ``no_reply`` kind (D-23) and the
not_called / open_lead / at_risk flags. Each rule is pinned with the case that must count and the case that must not, and
every test builds two workspaces so nothing from one appears in the other's queue.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.pipeline_stage import PipelineStage
from app.models.task import Task
from app.models.tenant import Tenant
from app.services import work_queue_service as wq
from app.services.date_presets import IST

NOW = datetime.now(timezone.utc)
TODAY = datetime.now(IST).date()


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"wqs-{uuid.uuid4().hex[:6]}", plan="growth", ivr_provider="vobiz")
    db.add(t); db.flush()
    return t


def _stage(db, tid, key, category, won=False, lost=False):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key=key, label=key.title(), category=category, order=1,
                      is_closed_won=won, is_closed_lost=lost)
    db.add(s); db.flush()
    return s


def _lead(db, tid, name, *, stage=None, hours_ago=200, **inq):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name, phone=f"+9198{uuid.uuid4().int % 10**8:08d}",
              first_touch_channel="whatsapp", lead_identified_at=NOW - timedelta(hours=hours_ago))
    db.add(g); db.flush()
    i = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage=InquiryStage.NEW, stage_id=stage.id if stage else None,
                source=InquirySource.WA_DIRECT, created_at=NOW - timedelta(hours=hours_ago), **inq)
    db.add(i)
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel="whatsapp", is_open=True)
    db.add(c); db.flush()
    return g, i, c


def _msg(db, tid, conv, direction, hours_ago, **kw):
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=direction, channel=conv.channel,
                   body=kw.pop("body", "hello"), created_at=NOW - timedelta(hours=hours_ago), **kw))
    db.flush()


def _call(db, tid, guest, direction, hours_ago, status="completed", duration=60):
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, ivr_provider="vobiz", ivr_call_id=uuid.uuid4().hex[:10],
                direction=direction, from_number=guest.phone, to_number="+918000000000", duration_seconds=duration,
                ivr_dial_status=status, created_at=NOW - timedelta(hours=hours_ago)))
    db.flush()


def _contacted(db, tid, conv, hours_ago=100):
    """A person already spoke to them (so they are not a new lead any more)."""
    _msg(db, tid, conv, "outbound", hours_ago, body="Hi, this is Krisha from Ratha")


def _by_title(res):
    return {i["title"]: i for i in res["items"]}


# ── no_reply (D-23) ──────────────────────────────────────────────────────────────────────────────────────────

def test_a_lead_silent_for_a_day_after_our_message_is_not_replying(db):
    t, other = _tenant(db), _tenant(db)
    g, _, c = _lead(db, t.id, "Pooja")
    _msg(db, t.id, c, "inbound", 60)
    _contacted(db, t.id, c, hours_ago=30)                       # our message 30 h ago, nothing since
    g2, _, c2 = _lead(db, t.id, "Fresh")
    _msg(db, t.id, c2, "inbound", 60)
    _contacted(db, t.id, c2, hours_ago=5)                       # only 5 h: not yet
    _lead(db, other.id, "Elsewhere")
    db.commit()
    res = wq.build(db, t, scope_user_id=None)
    items = _by_title(res)
    assert items["Pooja"]["kind"] == "no_reply" and "Krisha" in items["Pooja"]["detail"]
    assert "Fresh" not in items and res["counts"]["no_reply"] == 1
    assert items["Pooja"]["severity"] == "fresh"                # 30 h: inside its 48 h first threshold
    assert wq.build(db, other, scope_user_id=None)["counts"]["no_reply"] == 0


def test_an_auto_sent_or_approved_ai_reply_counts_as_ours_but_an_unsent_draft_does_not(db):
    t = _tenant(db)
    _, _, c1 = _lead(db, t.id, "Auto")
    _msg(db, t.id, c1, "inbound", 50)
    _contacted(db, t.id, c1, hours_ago=49)
    _msg(db, t.id, c1, "outbound", 30, is_ai_generated=True, sent_autonomously=True)
    _, _, c2 = _lead(db, t.id, "Draft")
    _msg(db, t.id, c2, "inbound", 40)
    _contacted(db, t.id, c2, hours_ago=39)
    _msg(db, t.id, c2, "inbound", 30)                           # the guest spoke last...
    _msg(db, t.id, c2, "outbound", 29, is_ai_generated=True, was_approved=None)   # ...an unsent draft is not a reply
    db.commit()
    items = _by_title(wq.build(db, t, scope_user_id=None))
    assert items["Auto"]["kind"] == "no_reply"
    assert items.get("Draft", {}).get("kind") != "no_reply"


def test_a_guest_reply_or_a_call_clears_it(db):
    t = _tenant(db)
    g1, _, c1 = _lead(db, t.id, "Replied")
    _contacted(db, t.id, c1, hours_ago=40)
    _msg(db, t.id, c1, "inbound", 2)
    g2, _, c2 = _lead(db, t.id, "Called")
    _contacted(db, t.id, c2, hours_ago=40)
    _call(db, t.id, g2, CallDirection.OUTBOUND, 10)
    db.commit()
    items = _by_title(wq.build(db, t, scope_user_id=None))
    assert items.get("Replied", {}).get("kind") != "no_reply"
    assert "Called" not in items


def test_closed_leads_and_old_messages_are_left_out(db):
    t = _tenant(db)
    sold = _stage(db, t.id, "sold", "valid", won=True)
    lost = _stage(db, t.id, "lost", "valid", lost=True)
    for name, kw in (("Sold", {"stage": sold}), ("Lost", {"stage": lost}), ("Spam", {"qualification_status": "unqualified"})):
        _, _, c = _lead(db, t.id, name, **kw)
        _contacted(db, t.id, c, hours_ago=40)
    _, _, old = _lead(db, t.id, "Old", hours_ago=900)
    _contacted(db, t.id, old, hours_ago=24 * 20)               # outside the 14-day look-back
    db.commit()
    res = wq.build(db, t, scope_user_id=None)
    assert res["counts"]["no_reply"] == 0


# ── flags ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_lead_nobody_ever_called_is_flagged_not_called(db):
    t, other = _tenant(db), _tenant(db)
    g1, _, c1 = _lead(db, t.id, "Kavya", hours_ago=2)
    _msg(db, t.id, c1, "inbound", 2)
    g2, _, c2 = _lead(db, t.id, "Rohan", hours_ago=2)
    _msg(db, t.id, c2, "inbound", 2)
    _call(db, t.id, g2, CallDirection.OUTBOUND, 1, status="no-answer", duration=0)   # an attempt counts as called
    db.commit()
    res = wq.build(db, t, scope_user_id=None)
    items = _by_title(res)
    assert "not_called" in items["Kavya"]["flags"] and "not_called" not in items["Rohan"]["flags"]
    assert res["flags"]["not_called"] == 1
    assert wq.build(db, other, scope_user_id=None)["flags"]["not_called"] == 0


def test_only_follow_ups_on_open_valid_stage_leads_are_flagged(db):
    t = _tenant(db)
    active = _stage(db, t.id, "active", "valid")
    general = _stage(db, t.id, "general_enquiry", "invalid")
    lost = _stage(db, t.id, "lost", "valid", lost=True)
    for name, stage in (("On active", active), ("On general", general), ("On lost", lost)):
        g, i, _ = _lead(db, t.id, name, stage=stage)
        db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title=f"Call {name}", inquiry_id=i.id, guest_id=g.id,
                    due_date=NOW - timedelta(hours=3), is_done=False))
    db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title="Fix the awning", due_date=NOW - timedelta(hours=3), is_done=False))
    db.commit()
    res = wq.build(db, t, scope_user_id=None)
    flagged = {i["title"] for i in res["items"] if i["kind"] == "followup" and "open_lead" in i["flags"]}
    assert flagged == {"Call On active"}
    assert res["flags"]["followup_open_lead"] == 1
    assert res["counts"]["followup"] == 4                       # My day still lists every task


def test_a_warm_lead_travelling_soon_and_quiet_for_two_days_is_at_risk(db):
    t, other = _tenant(db), _tenant(db)
    soon = (TODAY + timedelta(days=10)).isoformat()
    late = (TODAY + timedelta(days=60)).isoformat()
    warm = {"temperature": {"value": "warm"}}
    cases = (("Nikhil", soon, warm, 60), ("Cold", soon, {"sentiment": "negative"}, 60), ("Far", late, warm, 60),
             ("Busy", soon, warm, 30))           # on the no_reply list (30 h) but not quiet for 48 h
    for name, check_in, analysis, quiet_hours in cases:
        _, _, c = _lead(db, t.id, name, check_in=check_in, ai_analysis=analysis)
        _msg(db, t.id, c, "inbound", quiet_hours + 30)
        _contacted(db, t.id, c, hours_ago=quiet_hours)          # we wrote last: they are on the no_reply list
    db.commit()
    res = wq.build(db, t, scope_user_id=None)
    at_risk = {i["title"] for i in res["items"] if "at_risk" in i["flags"]}
    assert {"Nikhil", "Cold", "Far", "Busy"} <= set(_by_title(res))       # all four are on the queue...
    assert at_risk == {"Nikhil"} and res["flags"]["at_risk"] == 1
    assert wq.build(db, other, scope_user_id=None)["flags"]["at_risk"] == 0


def test_counts_endpoint_shape_carries_the_flags(db):
    t = _tenant(db)
    db.commit()
    res = wq.counts(db, t, scope_user_id=None)
    assert set(res["flags"]) == {"not_called", "at_risk", "followup_open_lead"}
    assert "no_reply" in res["counts"] and res["counts"]["no_reply"] == 0
