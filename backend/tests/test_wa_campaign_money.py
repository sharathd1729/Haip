"""WhatsApp step 2: campaign cost, tracked clicks, leads/bookings/revenue per campaign, retarget, pause and the
daily messaging limit."""
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.api.v1.endpoints.messaging import (
    CampaignStatus,
    TemplateStatus,
    WACampaign,
    WASubscriber,
    WATemplate,
)
from app.core.security import create_access_token
from app.models.guest import Guest
from app.models.integration import Integration
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient
from app.models.wa_pricing_event import WaPricingEvent
from app.services import wa_campaign_money as money
from app.services import wa_campaign_retarget as retarget
from app.services import wa_costs, wa_send_limits
from app.workers.tasks import run_campaign as runner_mod

NOW = datetime.now(UTC)
TRACKED = [{"type": "BODY", "text": "Hi {{1}}"},
           {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Book", "url": "https://app.example.com/api/v1/c/{{1}}"}]}]


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _role_headers(db, tenant_id, role):
    user = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="U", email=f"u-{uuid.uuid4().hex[:6]}@t.com",
                hashed_password="x", role=role, is_active=True)
    db.add(user)
    db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": user.id, "tenant_id": tenant_id, "role": role.value})}


def _other_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t.id


def _template(db, tid, components=None):
    t = WATemplate(id=str(uuid.uuid4()), tenant_id=tid, name=f"t_{uuid.uuid4().hex[:6]}", language="en",
                   status=TemplateStatus.APPROVED, meta_template_id="m1",
                   components=components or [{"type": "BODY", "text": "Hi"}])
    db.add(t)
    db.commit()
    return t


def _campaign(db, tid, template_id, status=CampaignStatus.COMPLETED, **kw):
    c = WACampaign(id=str(uuid.uuid4()), tenant_id=tid, name="Diwali push", template_id=template_id,
                   audience_filter={}, variable_map={}, status=status, **kw)
    db.add(c)
    db.commit()
    return c


def _recipient(db, c, phone, status="sent", **kw):
    r = Recipient(id=str(uuid.uuid4()), tenant_id=c.tenant_id, campaign_id=c.id, phone=phone, name="Priya",
                  status=status, sent_at=kw.pop("sent_at", NOW - timedelta(days=2)) if status != "failed" else None,
                  wa_message_id=kw.pop("wa_message_id", f"wamid.{uuid.uuid4().hex[:8]}"), **kw)
    db.add(r)
    db.commit()
    return r


def _tenant(db, tid):
    return db.query(Tenant).filter_by(id=tid).first()


# ─── cost ────────────────────────────────────────────────────────────────────

def test_pricing_is_kept_once_per_message_and_costed_at_the_workspace_rates(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    status = {"id": "wamid.A", "timestamp": str(int(NOW.timestamp())),
              "pricing": {"category": "marketing", "billable": True, "pricing_model": "PMP"}}
    assert wa_costs.record(db, tid, status) is True
    assert wa_costs.record(db, tid, {**status, "status": "read"}) is False          # the next status of the same message
    wa_costs.record(db, tid, {"id": "wamid.B", "pricing": {"category": "utility", "billable": True}})
    wa_costs.record(db, tid, {"id": "wamid.C", "pricing": {"category": "service", "billable": False}})
    assert wa_costs.record(db, tid, {"id": "wamid.D"}) is False                     # no pricing object
    db.commit()
    assert db.query(WaPricingEvent).filter_by(tenant_id=tid).count() == 3
    cost = wa_costs.cost_of(db, _tenant(db, tid), ["wamid.A", "wamid.B", "wamid.C"])
    assert cost["messages"] == 2 and cost["amount_inr"] == pytest.approx(0.98)      # 0.86 + 0.12; service is free
    assert cost["by_category"]["marketing"]["messages"] == 1


def test_another_workspaces_pricing_never_counts(db, tenant_and_user):
    tid, other = _tid(tenant_and_user), _other_tenant(db)
    wa_costs.record(db, other, {"id": "wamid.X", "pricing": {"category": "marketing", "billable": True}})
    db.commit()
    assert wa_costs.cost_of(db, _tenant(db, tid), ["wamid.X"])["messages"] == 0


def test_the_status_webhook_records_the_price(db, tenant_and_user):
    from app.workers.tasks import whatsapp as wa
    tid = _tid(tenant_and_user)
    wa._handle_status_update(db, _tenant(db, tid), {"id": "wamid.hook", "status": "sent", "timestamp": str(int(NOW.timestamp())),
                                       "pricing": {"category": "marketing", "billable": True}})
    db.commit()
    assert db.query(WaPricingEvent).filter_by(tenant_id=tid, wamid="wamid.hook").count() == 1


# ─── tracked clicks ──────────────────────────────────────────────────────────

def test_the_tracked_button_is_found_only_by_its_marker():
    assert money.tracked_button_index(TRACKED) == 0
    assert money.tracked_button_index([{"type": "BUTTONS", "buttons": [{"type": "URL", "url": "https://x.com/{{1}}"}]}]) is None


def test_a_tap_is_recorded_once_and_redirects(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid, _template(db, tid, TRACKED).id, link_url="https://ratha.example/book")
    r = _recipient(db, c, "+919800000001")
    code = money.click_code(db, r)
    db.commit()
    assert money.click_code(db, r) == code                                           # stable per recipient
    resp = client.get(f"/api/v1/c/{code}", follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"] == "https://ratha.example/book"
    db.expire_all()
    first = db.query(Recipient).get(r.id).clicked_at
    assert first is not None
    client.get(f"/api/v1/c/{code}", follow_redirects=False)
    db.expire_all()
    assert db.query(Recipient).get(r.id).clicked_at == first                        # the first tap counts


def test_an_unknown_code_is_not_a_redirect(client):
    assert client.get("/api/v1/c/nope123456", follow_redirects=False).status_code == 404


# ─── report ──────────────────────────────────────────────────────────────────

def _money_world(db, tid):
    c = _campaign(db, tid, _template(db, tid, TRACKED).id, link_url="https://ratha.example/book")
    sent_at = NOW - timedelta(days=5)
    prop = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Ratha 1", slug=f"p-{uuid.uuid4().hex[:6]}", type="caravan")
    db.add(prop)
    lead = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Priya", phone="+919800000001", lead_identified_at=NOW - timedelta(days=4))
    old_lead = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Arjun", phone="+919800000002", lead_identified_at=NOW - timedelta(days=60))
    db.add_all([lead, old_lead])
    db.flush()
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=lead.id, property_id=prop.id, check_in=date(2026, 12, 1),
                check_out=date(2026, 12, 3), total_amount=45000, status="confirmed"))
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=old_lead.id, property_id=prop.id, check_in=date(2026, 12, 5),
                check_out=date(2026, 12, 6), total_amount=9000, status="cancelled"))
    db.commit()
    a = _recipient(db, c, "+919800000001", guest_id=lead.id, sent_at=sent_at, clicked_at=NOW - timedelta(days=4),
                   wa_message_id="wamid.r1")
    _recipient(db, c, "+919800000002", guest_id=old_lead.id, sent_at=sent_at, wa_message_id="wamid.r2")
    _recipient(db, c, "+919800000003", status="failed")
    for w in ("wamid.r1", "wamid.r2"):
        wa_costs.record(db, tid, {"id": w, "pricing": {"category": "marketing", "billable": True}})
    db.commit()
    return c, a


def test_report_counts_clicks_leads_bookings_revenue_and_cost(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c, _ = _money_world(db, tid)
    with patch("app.services.authz_service.has_capability", return_value=True):   # test tenant has no capability rows
        r = client.get(f"/api/v1/messaging/campaigns/{c.id}/report", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    m = r.json()["money"]
    assert m["tracked_link"] is True and m["clicks"] == 1 and m["click_rate"] == 50.0
    assert m["leads"] == 1                      # Arjun was a lead before the send
    assert m["bookings"] == 1 and m["revenue_inr"] == 45000.0     # cancelled stay left out
    assert m["cost_inr"] == pytest.approx(1.72) and m["cost_per_lead_inr"] == pytest.approx(1.72)
    assert r.json()["campaign"]["link_url"] == "https://ratha.example/book"


def test_revenue_is_hidden_without_revenue_read(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c, _ = _money_world(db, tid)
    with patch("app.services.authz_service.has_capability", return_value=False):
        m = client.get(f"/api/v1/messaging/campaigns/{c.id}/report", headers=_h(tenant_and_user)).json()["money"]
    assert m["revenue_inr"] is None and m["money_restricted"] is True and m["bookings"] == 1


# ─── pause / retarget ────────────────────────────────────────────────────────

def test_pause_a_running_campaign(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid, _template(db, tid).id, status=CampaignStatus.RUNNING)
    r = client.post(f"/api/v1/messaging/campaigns/{c.id}/pause", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    db.expire_all()
    got = db.query(WACampaign).get(c.id)
    assert got.status == CampaignStatus.PAUSED and got.paused_reason.startswith("Paused by")
    assert client.post(f"/api/v1/messaging/campaigns/{c.id}/pause", headers=_h(tenant_and_user)).status_code == 409


def test_pause_needs_a_marketer_and_the_same_workspace(client, db, tenant_and_user):
    tid, other = _tid(tenant_and_user), _other_tenant(db)
    mine = _campaign(db, tid, _template(db, tid).id, status=CampaignStatus.RUNNING)
    theirs = _campaign(db, other, _template(db, other).id, status=CampaignStatus.RUNNING)
    assert client.post(f"/api/v1/messaging/campaigns/{mine.id}/pause",
                       headers=_role_headers(db, tid, UserRole.FOH)).status_code == 403
    assert client.post(f"/api/v1/messaging/campaigns/{theirs.id}/pause", headers=_h(tenant_and_user)).status_code == 404


def test_retarget_segments_leave_out_people_who_opted_out(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid, _template(db, tid).id)
    _recipient(db, c, "+919800000001", status="read", read_at=NOW)
    _recipient(db, c, "+919800000002", status="delivered", clicked_at=NOW)
    _recipient(db, c, "+919800000003", status="delivered")
    db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=tid, phone="+919800000003", name="X", opted_in=False, tags=[]))
    db.commit()
    counts = retarget.count(db, tid, c.id)
    assert counts["not_read"] == 1                      # 0002; 0003 opted out
    assert counts["clicked"] == 1 and counts["not_clicked"] == 1
    assert {m.phone for m in retarget.members(db, tid, {"campaign_id": c.id, "segment": "not_clicked"})} == {"+919800000001"}
    assert retarget.members(db, _other_tenant(db), {"campaign_id": c.id, "segment": "not_clicked"}) == []


def test_retarget_endpoints_make_a_draft(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid, _template(db, tid).id, link_url="https://ratha.example/book")
    _recipient(db, c, "+919800000001", status="delivered")
    opts = client.get(f"/api/v1/messaging/campaigns/{c.id}/retarget", headers=_h(tenant_and_user))
    assert opts.status_code == 200 and {o["segment"]: o["count"] for o in opts.json()}["not_read"] == 1
    r = client.post(f"/api/v1/messaging/campaigns/{c.id}/retarget", json={"segment": "not_read"}, headers=_h(tenant_and_user))
    assert r.status_code == 201, r.text
    new = db.query(WACampaign).get(r.json()["id"])
    assert new.status == CampaignStatus.DRAFT and new.link_url == c.link_url
    assert new.audience_filter == {"type": "retarget", "campaign_id": c.id, "segment": "not_read"}
    assert client.post(f"/api/v1/messaging/campaigns/{c.id}/retarget", json={"segment": "everyone"},
                       headers=_h(tenant_and_user)).status_code == 422
    other = _other_tenant(db)
    assert client.get(f"/api/v1/messaging/campaigns/{c.id}/retarget",
                      headers=_role_headers(db, other, UserRole.OWNER)).status_code == 404


# ─── runner ──────────────────────────────────────────────────────────────────

class FakeAdapter:
    def __init__(self):
        self.calls = []

    async def send_template(self, to, template_name, language_code="en", components=None):
        self.calls.append({"to": to, "components": components})
        return {"messages": [{"id": f"wamid.{len(self.calls)}"}]}


@pytest.fixture()
def world(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=tid, kind="whatsapp_meta", status="active",
                       config={"waba_id": "w", "phone_number_id": "pn"}))
    tmpl = _template(db, tid, TRACKED)
    camp =WACampaign(id=str(uuid.uuid4()), tenant_id=tid, name="c", template_id=tmpl.id, audience_filter={},
                      variable_map={"body": {"1": {"source": "first_name", "fallback": "Guest"}}},
                      status=CampaignStatus.RUNNING, link_url="https://ratha.example/book")
    db.add(camp)
    for i in range(3):
        db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=tid, phone=f"+91980000000{i}", name="Priya", opted_in=True, tags=[]))
    db.commit()
    return SimpleNamespace(tid=tid, camp_id=camp.id)


def _run(db, w, adapter):
    with patch.object(runner_mod, "SessionLocal", return_value=db), \
         patch("app.adapters.whatsapp.meta_cloud.get_wa_adapter", return_value=adapter), \
         patch("app.workers.tasks.whatsapp._get_wa_access_token", return_value="tok"):
        runner_mod.run_campaign.apply(kwargs={"campaign_id": w.camp_id, "tenant_id": w.tid}).get()
    db.expire_all()


def test_each_recipient_gets_their_own_tracked_code(db, world):
    adapter = FakeAdapter()
    _run(db, world, adapter)
    rows = db.query(Recipient).filter_by(campaign_id=world.camp_id).all()
    codes = {r.click_code for r in rows}
    assert len(rows) == 3 and None not in codes and len(codes) == 3
    sent_codes = {c["components"][-1]["parameters"][0]["text"] for c in adapter.calls}
    assert sent_codes == codes


def test_a_tracked_template_without_a_target_pauses(db, world):
    db.query(WACampaign).filter_by(id=world.camp_id).update({"link_url": None})
    db.commit()
    adapter = FakeAdapter()
    _run(db, world, adapter)
    camp = db.query(WACampaign).get(world.camp_id)
    assert camp.status == CampaignStatus.PAUSED and "tracked link" in camp.paused_reason and adapter.calls == []


def test_the_daily_limit_holds_the_rest_for_the_next_window(db, world):
    with patch.object(wa_send_limits, "remaining_today", return_value=2):
        adapter = FakeAdapter()
        _run(db, world, adapter)
    camp = db.query(WACampaign).get(world.camp_id)
    assert len(adapter.calls) == 2
    assert camp.status == CampaignStatus.SCHEDULED and camp.scheduled_at and "limit" in camp.paused_reason


def test_a_paused_campaign_stops_before_the_next_batch(db, world):
    db.query(WACampaign).filter_by(id=world.camp_id).update({"status": CampaignStatus.PAUSED})
    db.commit()
    with patch.object(runner_mod, "_set_status"):        # the runner must not flip it back
        adapter = FakeAdapter()
        _run(db, world, adapter)
    assert adapter.calls == [] and db.query(WACampaign).get(world.camp_id).status == CampaignStatus.PAUSED


def test_tier_limit_reads_the_latest_quality_snapshot(db, tenant_and_user):
    from app.workers.tasks.meta_quality_poll import MetaQualitySnapshot
    tid = _tid(tenant_and_user)
    assert wa_send_limits.remaining_today(db, tid) is None
    db.add(MetaQualitySnapshot(id=str(uuid.uuid4()), tenant_id=tid, waba_id="w", messaging_limit_tier="TIER_250"))
    db.commit()
    assert wa_send_limits.tier_limit(db, tid) == 250
    c = _campaign(db, tid, _template(db, tid).id)
    _recipient(db, c, "+919800000001", sent_at=NOW - timedelta(hours=1))
    _recipient(db, c, "+919800000002", sent_at=NOW - timedelta(hours=30))      # outside the window
    assert wa_send_limits.remaining_today(db, tid) == 249
