"""Ops metrics (ops gap 10, D-33 .. D-40): each metric on a fixture, empty = None, exclusions, IST day edges, tenants,
the API (owner/manager + ops.read) and the owner brief's lines.

Dates are fixed (November 2026) and ``now`` is passed explicitly, so the machine clock never matters.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.ops import OpsEscalationEvent, OpsItem
from app.models.ops_files import OpsFile, OpsFileEvent, OpsJob, OpsJobItem
from app.models.ops_fleet import OpsGuestForm
from app.models.property import PropertyAddOn, Stay
from app.models.stay_finance import StayAddOn, StayPayment
from app.models.user import UserRole
from app.services import ops_metrics, owner_brief_email, owner_brief_service
from app.services.date_presets import IST
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, tenant
from tests.test_increment1_defect_specs import _h, _user

D = date(2026, 11, 5)                      # the stays' check-in day
NOW = datetime(2026, 11, 8, 6, 0, tzinfo=UTC)  # 11:30 IST on 8 Nov: every check-in above has passed


def _utc_ist(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST).astimezone(UTC)


def _t(db, business_type="villa"):
    t = tenant(db)
    t.business_type = business_type
    db.commit()
    return t


def _stay(db, t, p, *, check_in=D, nights=2, total="20000", status="confirmed", channel=None) -> Stay:
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="G", phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    s = Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, property_id=p.id, check_in=check_in,
             check_out=check_in + timedelta(days=nights), status=status, total_amount=Decimal(total),
             channel_source=channel)
    db.add(s)
    db.flush()
    return s


def _file(db, s, pack="villa") -> OpsFile:
    f = OpsFile(id=str(uuid.uuid4()), tenant_id=s.tenant_id, stay_id=s.id, pack=pack, state="staying", details={})
    db.add(f)
    db.flush()
    return f


def _gate(db, f, at, green=True):
    text = ops_metrics.GATE_GREEN + ": ready" if green else ops_metrics.GATE_LOST + ": back"
    db.add(OpsFileEvent(id=str(uuid.uuid4()), tenant_id=f.tenant_id, file_id=f.id, at=at, text=text, auto=True))
    db.flush()


def _item(db, t, *, created, severity="high", ack_min=None, resolved_min=None, status=None, p=None, stay=None,
          source="staff", guest_id=None, category="maintenance") -> OpsItem:
    i = OpsItem(id=str(uuid.uuid4()), tenant_id=t.id, kind="incident", title="x", severity=severity, duty="ops_manager",
                category=category, source=source, guest_id=guest_id, property_id=p.id if p else None,
                stay_id=stay.id if stay else None, created_at=created,
                acknowledged_at=created + timedelta(minutes=ack_min) if ack_min is not None else None,
                resolved_at=created + timedelta(minutes=resolved_min) if resolved_min is not None else None,
                status=status or ("resolved" if resolved_min is not None else "acknowledged" if ack_min is not None else "open"))
    db.add(i)
    db.flush()
    return i


def _build(db, t, d_from=D, d_to=D, now=NOW):
    return ops_metrics.build(db, t.id, d_from, d_to, now=now)


# ── empty data = None, never 0 ───────────────────────────────────────────────────────────────────────────────

def test_empty_workspace_says_no_data_not_zero(db):
    t = _t(db)
    m = _build(db, t)
    assert m["time_to_acknowledge"]["all"]["median_min"] is None
    assert m["time_to_resolve"]["all"]["p90_min"] is None
    assert m["issues"]["per_10_stays"] is None
    assert m["ready_on_time"]["pct"] is None
    assert m["paperwork_before_arrival"]["pct"] is None
    assert m["addon_revenue"] == {"live": False, "stays": 0, "total": None, "per_stay": None}
    assert m["in_stay_replies"]["pct"] is None
    assert m["reviews"]["available"] is False and m["by_property"] == []


# ── each metric ──────────────────────────────────────────────────────────────────────────────────────────────

def test_time_to_acknowledge_and_resolve_by_severity(db):
    t = _t(db)
    p = prop(db, t.id, "Villa A")
    at = _utc_ist(D, 10)
    for ack in (5, 10, 30):
        _item(db, t, created=at, severity="critical", ack_min=ack, resolved_min=ack + 60, p=p)
    _item(db, t, created=at, severity="low", p=p)                      # never acknowledged
    _item(db, t, created=at, severity="high", ack_min=1, status="cancelled", p=p)  # cancelled: left out
    m = _build(db, t)
    crit = m["time_to_acknowledge"]["by_severity"]["critical"]
    assert crit == {"count": 3, "median_min": 10.0, "p90_min": 26.0}
    assert m["time_to_acknowledge"]["by_severity"]["low"]["count"] == 0
    assert m["time_to_acknowledge"]["not_acknowledged"] == 1
    assert m["time_to_resolve"]["by_severity"]["critical"]["median_min"] == 70.0


def test_ack_clock_starts_after_a_quiet_hours_hold(db):
    t = _t(db)
    at = _utc_ist(D, 23)
    i = _item(db, t, created=at, ack_min=9 * 60 + 15)        # acked 08:15 next morning
    i.dispatch_after = at + timedelta(hours=9)                 # held to 08:00
    db.flush()
    assert _build(db, t)["time_to_acknowledge"]["all"]["median_min"] == 15.0


def test_guest_ticket_resolves_only_when_the_guest_confirms(db):
    t = _t(db)
    p = prop(db, t.id)
    s = _stay(db, t, p)
    at = _utc_ist(D, 10)
    yes = _item(db, t, created=at, ack_min=2, resolved_min=30, status="resolved", stay=s, source="guest_chat",
                guest_id=s.guest_id)
    db.add(OpsEscalationEvent(id=str(uuid.uuid4()), tenant_id=t.id, item_id=yes.id, event="guest_confirmed",
                              created_at=at + timedelta(minutes=90)))
    _item(db, t, created=at, ack_min=2, resolved_min=30, status="resolved", stay=s, source="guest_chat",
          guest_id=s.guest_id)                                   # closed without the guest's answer
    db.flush()
    r = _build(db, t)["time_to_resolve"]
    assert r["all"] == {"count": 1, "median_min": 90.0, "p90_min": 90.0}
    assert r["closed_without_guest_answer"] == 1


def test_issues_per_10_stays_per_unit_and_repeats(db):
    t = _t(db)
    a, b = prop(db, t.id, "Villa A"), prop(db, t.id, "Villa B")
    stays_a = [_stay(db, t, a) for _ in range(4)]
    _stay(db, t, b)
    at = _utc_ist(D, 10)
    _item(db, t, created=at, p=a)
    _item(db, t, created=at, stay=stays_a[1])                  # unit from the stay
    _item(db, t, created=at, p=a, category="deposit")          # a reminder, not an issue
    for s in stays_a[:2]:                                        # pool failed on Villa A twice
        f = _file(db, s)
        job = OpsJob(id=str(uuid.uuid4()), tenant_id=t.id, file_id=f.id, kind="readiness", status="open")
        db.add(job)
        db.flush()
        db.add(OpsJobItem(id=str(uuid.uuid4()), tenant_id=t.id, job_id=job.id, key="pool", label="Pool", status="red"))
    db.flush()
    m = _build(db, t)
    assert m["issues"]["issues"] == 2 and m["issues"]["stays"] == 5 and m["issues"]["per_10_stays"] == 4.0
    by = {r["name"]: r for r in m["by_property"]}
    assert by["Villa A"]["issues_per_10_stays"] == 5.0 and by["Villa B"]["issues_per_10_stays"] == 0.0
    assert m["issues"]["repeats"] == [{"property_id": a.id, "property": "Villa A", "key": "pool", "label": "Pool", "times": 2}]


def test_ready_on_time_reads_the_last_gate_event_before_check_in(db):
    t = _t(db)
    p = prop(db, t.id)
    ok, lost, late, nofile = (_stay(db, t, p) for _ in range(4))
    _gate(db, _file(db, ok), _utc_ist(D, 9))
    f = _file(db, lost)
    _gate(db, f, _utc_ist(D, 8))
    _gate(db, f, _utc_ist(D, 11), green=False)
    _gate(db, _file(db, late), _utc_ist(D, 13))               # green after the 12:00 check-in
    future = _stay(db, t, p, check_in=date(2026, 11, 9))       # check-in not reached: not judged yet
    _gate(db, _file(db, future), _utc_ist(D, 9))
    m = _build(db, t, D, date(2026, 11, 9))["ready_on_time"]
    assert m == {"judged": 3, "on_time": 1, "pct": 33.3}


def test_ready_on_time_honours_the_stays_own_check_in_time(db):
    t = _t(db)
    s = _stay(db, t, prop(db, t.id))
    s.check_in_time = "15:00"
    _gate(db, _file(db, s), _utc_ist(D, 13))
    assert _build(db, t)["ready_on_time"]["on_time"] == 1


def test_paperwork_needs_the_form_and_full_payment_before_arrival(db):
    t = _t(db)
    p = prop(db, t.id)
    done, unpaid, noform = (_stay(db, t, p, total="10000") for _ in range(3))
    for s in (done, unpaid, noform):
        f = _file(db, s)
        if s is not noform:
            db.add(OpsGuestForm(id=str(uuid.uuid4()), tenant_id=t.id, file_id=f.id, stay_id=s.id, nonce="n",
                                token_hash=uuid.uuid4().hex, submitted_at=_utc_ist(D - timedelta(days=1), 10)))
    for s, amt in ((done, "10000"), (unpaid, "5000"), (noform, "10000")):
        db.add(StayPayment(tenant_id=t.id, stay_id=s.id, amount=Decimal(amt), method="upi", paid_on=D - timedelta(days=2)))
    db.add(StayPayment(tenant_id=t.id, stay_id=unpaid.id, amount=Decimal("5000"), method="cash", paid_on=D + timedelta(days=1)))
    db.flush()
    assert _build(db, t)["paperwork_before_arrival"] == {"judged": 3, "complete": 1, "pct": 33.3}


def test_addon_revenue_counts_fully_paid_stays_and_skips_extra_distance(db):
    t = _t(db)
    p = prop(db, t.id)
    db.add(PropertyAddOn(id=str(uuid.uuid4()), tenant_id=t.id, property_id=p.id, name="Dinner", price=Decimal("2000")))
    paid, owing = _stay(db, t, p, total="10000"), _stay(db, t, p, total="10000")
    for s in (paid, owing):
        db.add(StayAddOn(tenant_id=t.id, stay_id=s.id, name="Dinner", quantity=1, unit_price=Decimal("2000")))
    db.add(StayAddOn(tenant_id=t.id, stay_id=paid.id, name="Extra distance", quantity=1, unit_price=Decimal("500")))
    db.add(StayPayment(tenant_id=t.id, stay_id=paid.id, amount=Decimal("12500"), method="upi", paid_on=D))
    db.flush()
    assert _build(db, t)["addon_revenue"] == {"live": True, "stays": 2, "total": 2000.0, "per_stay": 1000.0}


def _msg(db, c, at, inbound=True):
    db.add(Message(id=str(uuid.uuid4()), tenant_id=c.tenant_id, conversation_id=c.id, channel=c.channel, body="x",
                   direction=MessageDirection.INBOUND if inbound else MessageDirection.OUTBOUND, created_at=at,
                   delivery_state=None if inbound else MessageDeliveryState.SENT, is_sample=False))
    db.flush()


def test_in_stay_replies_use_the_work_queue_reply_sla(db):
    t = _t(db)
    s = _stay(db, t, prop(db, t.id))
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=s.guest_id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c)
    db.flush()
    _msg(db, c, _utc_ist(D, 14))
    _msg(db, c, _utc_ist(D, 14, 10), inbound=False)            # 10 min: fresh
    _msg(db, c, _utc_ist(D + timedelta(days=1), 9))
    _msg(db, c, _utc_ist(D + timedelta(days=1), 11), inbound=False)  # 2 h: late
    _msg(db, c, _utc_ist(D - timedelta(days=3), 9))            # before the stay: not counted
    m = _build(db, t, D - timedelta(days=3), D + timedelta(days=1))["in_stay_replies"]
    assert m == {"turns": 2, "on_time": 1, "pct": 50.0}


# ── exclusions, IST edges, tenants ──────────────────────────────────────────────────────────────────────────

def test_cancelled_placeholder_and_comp_stays_are_left_out(db):
    t = _t(db, "caravan")
    real, holder = prop(db, t.id, "Ratha 1"), prop(db, t.id, "Unassigned")
    _stay(db, t, real)
    _stay(db, t, real, status="cancelled")
    _stay(db, t, real, channel="creator", total="0")
    _stay(db, t, holder)
    _item(db, t, created=_utc_ist(D, 10), ack_min=3, p=holder)
    m = _build(db, t)
    assert m["issues"]["stays"] == 1 and m["issues"]["issues"] == 0
    assert m["time_to_acknowledge"]["all"]["count"] == 0
    assert [r["name"] for r in m["by_property"]] == ["Ratha 1"]


@pytest.mark.parametrize("utc_hour, ist_day", [(4, date(2026, 11, 7)), (19, date(2026, 11, 8))])
def test_items_land_on_their_ist_day(db, utc_hour, ist_day):
    """19:45 UTC on 7 Nov is 01:15 IST on 8 Nov; 04:45 UTC is still 7 Nov in IST."""
    t = _t(db)
    _item(db, t, created=datetime(2026, 11, 7, utc_hour, 45, tzinfo=UTC), ack_min=4, p=prop(db, t.id))
    other = date(2026, 11, 8) if ist_day == date(2026, 11, 7) else date(2026, 11, 7)
    assert _build(db, t, ist_day, ist_day)["time_to_acknowledge"]["all"]["count"] == 1
    assert _build(db, t, other, other)["time_to_acknowledge"]["all"]["count"] == 0


def test_last_days_ends_on_the_ist_today_at_1945_utc(db):
    t = _t(db)
    m = ops_metrics.last_days(db, t.id, 7, now=datetime(2026, 11, 7, 19, 45, tzinfo=UTC))
    assert m["period"]["to"] == "2026-11-08" and m["period"]["from"] == "2026-11-02"
    m = ops_metrics.last_days(db, t.id, 7, now=datetime(2026, 11, 7, 10, 0, tzinfo=UTC))
    assert m["period"]["to"] == "2026-11-07"


def test_another_workspaces_rows_never_count(db):
    t, other = _t(db), _t(db)
    p = prop(db, other.id)
    _stay(db, other, p)
    _item(db, other, created=_utc_ist(D, 10), ack_min=3, p=p)
    m = _build(db, t)
    assert m["issues"]["stays"] == 0 and m["time_to_acknowledge"]["all"]["count"] == 0


# ── API ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_metrics_api_owner_ok_concierge_forbidden_and_tenant_scoped(client, db):
    t, other = _t(db), _t(db)
    seed_capabilities(db, t.id)
    seed_capabilities(db, other.id)
    p = prop(db, other.id)
    _stay(db, other, p, check_in=datetime.now(IST).date())
    owner, concierge, other_owner = (_user(db, t.id, UserRole.OWNER), _user(db, t.id, UserRole.CONCIERGE),
                                     _user(db, other.id, UserRole.OWNER))
    r = client.get("/api/v1/ops/files/metrics?days=7", headers=_h(owner))
    assert r.status_code == 200 and r.json()["period"]["days"] == 7
    assert r.json()["issues"]["stays"] == 0                     # the other workspace's stay is not here
    assert client.get("/api/v1/ops/files/metrics", headers=_h(concierge)).status_code == 403
    assert client.get("/api/v1/ops/files/metrics", headers=_h(other_owner)).json()["issues"]["stays"] == 1
    assert client.get("/api/v1/ops/files/metrics?days=400", headers=_h(owner)).status_code == 422


# ── owner brief ─────────────────────────────────────────────────────────────────────────────────────────────

def test_owner_brief_adds_ops_lines_only_when_there_is_something_to_say(db):
    t = _t(db)
    quiet = owner_brief_service._ops_lines(db, t, date(2026, 11, 7))
    assert quiet == []
    p = prop(db, t.id)
    _item(db, t, created=_utc_ist(D, 10), ack_min=12, p=p)
    s = _stay(db, t, p)
    _gate(db, _file(db, s), _utc_ist(D, 14))                   # ready after check-in
    lines = owner_brief_service._ops_lines(db, t, date(2026, 11, 7))
    assert lines[0] == "Operations, last 7 days: 1 issue acknowledged in a median of 12 min."
    assert "1 of 1 stay was not ready before check-in." in lines
    assert len(lines) <= 3
    brief = {"kind": "morning", "period": "Yesterday", "day_label": "Sat, 7 Nov", "sentences": ["No new leads."],
             "ops_lines": lines, "todos": [], "my_day_url": "u", "dashboard_url": "d"}
    assert lines[0] in owner_brief_email.text(brief, "Demo") and "not ready" in owner_brief_email.html(brief, "Demo")


def test_owner_brief_skips_ops_for_businesses_without_an_ops_pack(db):
    t = _t(db, "hotel")
    _item(db, t, created=_utc_ist(D, 10), ack_min=12, p=prop(db, t.id))
    assert owner_brief_service._ops_lines(db, t, date(2026, 11, 7)) == []
