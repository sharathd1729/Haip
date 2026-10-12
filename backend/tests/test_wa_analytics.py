"""WhatsApp overview dashboard numbers."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.endpoints.messaging import CampaignStatus, TemplateStatus, WACampaign, WATemplate
from app.core.security import create_access_token
from app.models.consent import Consent
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.wa_campaign_recipient import WACampaignRecipient as R
from app.services import wa_analytics_service as svc

# 25 Sep 2026, 15:30 IST
NOW = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


@pytest.fixture()
def world(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    t = WATemplate(id=str(uuid.uuid4()), tenant_id=tid, name="weekend_offer", language="en", status=TemplateStatus.APPROVED, components=[])
    c = WACampaign(id=str(uuid.uuid4()), tenant_id=tid, name="Diwali push", template_id=t.id, audience_filter={}, variable_map={},
                   status=CampaignStatus.COMPLETED)
    db.add_all([t, c])
    db.commit()
    return type("W", (), {"tid": tid, "camp": c.id, "tmpl": t.id})


def _row(db, w, phone, status, sent=None, delivered=None, read=None, failed=None, created=None, code=None, campaign=None):
    when = sent or failed or created or NOW
    db.add(R(id=str(uuid.uuid4()), tenant_id=w.tid, campaign_id=campaign or w.camp, phone=phone, status=status,
             sent_at=sent, delivered_at=delivered, read_at=read, failed_at=failed, created_at=created or when,
             error_code=code, error_reason="x" if code else None))


def _dash(db, w, days=30):
    db.commit()
    return svc.dashboard(db, w.tid, days, now=NOW)


def test_totals_and_rates(db, world):
    for i in range(4):
        _row(db, world, f"+9198000000{i}", "read", sent=NOW)
    for i in range(4, 6):
        _row(db, world, f"+9198000000{i}", "delivered", sent=NOW)
    _row(db, world, "+919800000006", "sent", sent=NOW)
    _row(db, world, "+919800000007", "failed", failed=NOW, code="131026")
    _row(db, world, "+919800000008", "failed", failed=NOW, code="131026")
    t = _dash(db, world)["totals"]
    assert (t["sent"], t["delivered"], t["read"], t["failed"]) == (7, 6, 4, 2)
    assert (t["delivery_rate"], t["read_rate"], t["failure_rate"]) == (85.7, 66.7, 22.2)
    assert (t["campaigns"], t["contacts"]) == (1, 9)


def test_an_empty_period_has_no_rates_and_a_full_zero_series(db, world):
    d = _dash(db, world, days=7)
    assert d["totals"]["sent"] == 0 and d["totals"]["delivery_rate"] is None and d["totals"]["failure_rate"] is None
    assert len(d["daily"]) == 7 and all(x["sent"] == 0 for x in d["daily"])
    assert (d["range"]["from"], d["range"]["to"]) == ("2026-09-19", "2026-09-25")


def test_days_are_india_days(db, world):
    late = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)        # 00:30 IST on the 25th
    early = datetime(2026, 9, 24, 17, 0, tzinfo=timezone.utc)       # 22:30 IST on the 24th
    _row(db, world, "+919800000001", "read", sent=late)
    _row(db, world, "+919800000002", "delivered", sent=early)
    daily = {x["date"]: x for x in _dash(db, world, 7)["daily"]}
    assert daily["2026-09-25"]["sent"] == 1 and daily["2026-09-25"]["read"] == 1
    assert daily["2026-09-24"]["sent"] == 1 and daily["2026-09-24"]["delivered"] == 1 and daily["2026-09-24"]["read"] == 0
    assert daily["2026-09-25"]["delivery_rate"] == 100.0 and daily["2026-09-25"]["read_rate"] == 100.0


def test_a_failure_is_counted_on_the_day_it_failed(db, world):
    _row(db, world, "+919800000001", "failed", failed=NOW - timedelta(days=2), code="131026")
    daily = {x["date"]: x for x in _dash(db, world, 7)["daily"]}
    assert daily["2026-09-23"]["failed"] == 1


def test_only_the_selected_period_counts_and_the_one_before_is_the_comparison(db, world):
    _row(db, world, "+919800000001", "read", sent=NOW - timedelta(days=2))
    _row(db, world, "+919800000002", "read", sent=NOW - timedelta(days=10))          # previous 7-day window
    _row(db, world, "+919800000003", "sent", sent=NOW - timedelta(days=10))
    _row(db, world, "+919800000004", "read", sent=NOW - timedelta(days=40))          # outside both
    d = _dash(db, world, 7)
    assert d["totals"]["sent"] == 1
    assert (d["previous"]["sent"], d["previous"]["read"]) == (2, 1)


def test_failures_are_grouped_in_plain_words_most_common_first(db, world):
    for i in range(3):
        _row(db, world, f"+9198000001{i}", "failed", failed=NOW, code="131026")
    _row(db, world, "+919800000120", "failed", failed=NOW, code="131050")
    f = _dash(db, world)["failures"]
    assert [(x["group"], x["count"]) for x in f] == [("not_reachable", 3), ("opted_out", 1)]
    assert f[0]["label"] == "Number can't receive it" and f[0]["hint"]


def test_campaigns_and_templates_rows(db, world):
    other = WACampaign(id=str(uuid.uuid4()), tenant_id=world.tid, name="Second", template_id=world.tmpl, audience_filter={},
                       variable_map={}, status=CampaignStatus.RUNNING)
    db.add(other); db.commit()
    _row(db, world, "+919800000001", "read", sent=NOW)
    _row(db, world, "+919800000002", "failed", failed=NOW, code="131026")
    _row(db, world, "+919800000003", "sent", sent=NOW, campaign=other.id)
    d = _dash(db, world)
    by_name = {c["name"]: c for c in d["campaigns"]}
    assert (by_name["Diwali push"]["sent"], by_name["Diwali push"]["failed"], by_name["Diwali push"]["failure_rate"]) == (1, 1, 50.0)
    assert by_name["Second"]["sent"] == 1 and by_name["Second"]["template_name"] == "weekend_offer"
    assert d["templates"] == [{"template_name": "weekend_offer", "campaigns": 2, "sent": 2, "delivered": 1, "read": 1, "failed": 1,
                               "delivery_rate": 50.0, "read_rate": 100.0, "failure_rate": 33.3}]
    assert d["running"] == 1


def test_best_time_needs_enough_messages_to_mean_anything(db, world):
    at_10 = datetime(2026, 9, 24, 4, 30, tzinfo=timezone.utc)        # 10:00 IST
    at_20 = datetime(2026, 9, 24, 14, 30, tzinfo=timezone.utc)       # 20:00 IST
    for i in range(20):
        _row(db, world, f"+91981{i:07d}", "read" if i < 15 else "sent", sent=at_10)
    for i in range(20, 40):
        _row(db, world, f"+91981{i:07d}", "read" if i < 25 else "sent", sent=at_20)
    for i in range(40, 43):
        _row(db, world, f"+91981{i:07d}", "read", sent=NOW)          # 100% read but only 3 sent: ignored
    d = _dash(db, world)
    assert d["best_hour"] == 10
    ten = next(h for h in d["hours"] if h["hour"] == 10)
    assert (ten["sent"], ten["read"], ten["read_rate"]) == (20, 15, 75.0)


def test_upcoming_scheduled_campaigns_and_opt_outs_and_health(db, world):
    db.add(WACampaign(id=str(uuid.uuid4()), tenant_id=world.tid, name="Later", audience_filter={}, variable_map={},
                      status=CampaignStatus.SCHEDULED, scheduled_at="2026-09-28T04:30:00+00:00"))
    from app.models.guest import Guest
    # consents.guest_id is a foreign key to guests: both opted-out guests have to exist
    g, g_old = str(uuid.uuid4()), str(uuid.uuid4())
    db.add_all([Guest(id=g, tenant_id=world.tid, name="Opted out"), Guest(id=g_old, tenant_id=world.tid, name="Opted out long ago")])
    db.flush()
    db.add(Consent(id=str(uuid.uuid4()), tenant_id=world.tid, guest_id=g, channel="whatsapp", scope="marketing", granted=False,
                   recorded_at=NOW.isoformat(), withdrawn_at=(NOW - timedelta(days=1)).isoformat()))
    db.add(Consent(id=str(uuid.uuid4()), tenant_id=world.tid, guest_id=g_old, channel="whatsapp", scope="marketing", granted=False,
                   recorded_at=NOW.isoformat(), withdrawn_at=(NOW - timedelta(days=90)).isoformat()))
    db.add(WATemplate(id=str(uuid.uuid4()), tenant_id=world.tid, name="d", language="en", status=TemplateStatus.REJECTED, components=[]))
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=world.tid, kind="whatsapp_meta", status="active", config={}))
    d = _dash(db, world)
    assert [u["name"] for u in d["upcoming"]] == ["Later"]
    assert d["totals"]["opt_outs"] == 1
    assert d["health"]["connected"] is True
    assert (d["health"]["templates"]["approved"], d["health"]["templates"]["rejected"]) == (1, 1)


def test_other_workspaces_are_invisible(db, world):
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.flush()
    db.add(R(id=str(uuid.uuid4()), tenant_id=other.id, campaign_id="x", phone="+919899999999", status="read", sent_at=NOW, created_at=NOW))
    _row(db, world, "+919800000001", "sent", sent=NOW)
    d = _dash(db, world)
    assert d["totals"]["sent"] == 1 and d["totals"]["contacts"] == 1


# ─── endpoint ────────────────────────────────────────────────────────────────

def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def test_endpoint_returns_the_dashboard(client, db, tenant_and_user):
    r = client.get("/api/v1/messaging/analytics", params={"days": 14}, headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["range"]["days"] == 14 and len(b["daily"]) == 14 and "totals" in b and "health" in b


def test_endpoint_validates_days_and_roles(client, db, tenant_and_user):
    assert client.get("/api/v1/messaging/analytics", params={"days": 0}, headers=_h(tenant_and_user)).status_code == 422
    assert client.get("/api/v1/messaging/analytics", params={"days": 999}, headers=_h(tenant_and_user)).status_code == 422
    user = User(id=str(uuid.uuid4()), tenant_id=_tid(tenant_and_user), name="A", email=f"a-{uuid.uuid4().hex[:6]}@t.com",
                hashed_password="x", role=UserRole.CONCIERGE, is_active=True)
    db.add(user); db.commit()
    token = create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": "concierge"})
    assert client.get("/api/v1/messaging/analytics", headers={"Authorization": f"Bearer {token}"}).status_code == 403
