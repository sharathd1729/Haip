"""Agency M5 (21 Oct 2026): ad drafts from approved content, the money caps, pushing to Meta, pause, the watchdog.

Meta is a fake writer here: no request leaves the test, nothing is spent.
"""
import io
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from PIL import Image

from app.adapters.marketing.meta_ads import MetaAdsError
from app.models.ad_metrics import AdMetric
from app.models.audit_event import AuditEvent
from app.models.integration import Integration
from app.models.marketing_ads import MarketingAdDraft
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_ads_push as pusher
from app.services import marketing_ads_service as ads
from app.services import marketing_agency_service as agency
from app.services import marketing_content_service as svc
from app.services.marketing_content_service import MarketingError
from tests.test_marketing_studio_content import make_user, ws  # noqa: F401  (fixture)

BASE = "/api/v1/marketing/studio/ads"
AUDIENCE = {"label": "Bengaluru", "latitude": 12.97, "longitude": 77.59, "radius_km": 40, "age_min": 25, "age_max": 50}


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1200, 900), (30, 110, 80)).save(out, format="JPEG")
    return out.getvalue()


PHOTO = _jpeg()


class FakeWriter:
    def __init__(self, currency="INR", fail=None):
        self.calls, self.currency, self.fail, self.n = [], currency, fail or {}, 0

    def _id(self, kind):
        if kind in self.fail:
            raise self.fail.pop(kind)
        self.n += 1
        return f"{kind}-{self.n}"

    def account_currency(self):
        return self.currency

    def upload_image(self, jpeg):
        self.calls.append(("image", len(jpeg)))
        return self._id("hash")

    def upload_video(self, url):
        self.calls.append(("video", url))
        return self._id("video")

    def create_campaign(self, name, *, spend_cap_inr):
        self.calls.append(("campaign", spend_cap_inr))
        return self._id("campaign")

    def create_adset(self, name, **kw):
        self.calls.append(("adset", kw["daily_budget_inr"], kw["destination"], kw["starts"], kw["ends"]))
        return self._id("adset")

    def create_creative(self, name, **kw):
        self.calls.append(("creative", kw["message"], kw.get("image_hash"), kw.get("video_id")))
        return self._id("creative")

    def create_ad(self, name, *, adset_id, creative_id):
        self.calls.append(("ad", adset_id, creative_id))
        return self._id("ad")

    def set_status(self, object_id, status):
        self.calls.append(("status", object_id, status))

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _storage(monkeypatch):
    monkeypatch.setattr("app.services.media_storage.upload_marketing_media",
                        lambda t, c, m, e: f"{t}/marketing/{uuid.uuid4().hex}.{e}")
    monkeypatch.setattr("app.services.media_library_service._read_object", lambda key: PHOTO)
    monkeypatch.setattr("app.services.marketing_agency_service.notify_needs_approval", lambda *a, **k: None)


def approved_post(db, ws, kind="post", caption="Coorg, slowly. DM us for dates."):  # noqa: F811
    tid = ws["tenant"].id
    a = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key=f"{tid}/m/{uuid.uuid4().hex}.jpg",
                   mime_type="image/jpeg", bytes=10, sha256=uuid.uuid4().hex * 2, status="active")
    db.add(a)
    db.commit()
    payload = {"caption": caption, "media": {"asset_id": a.id}} if kind == "post" else \
        {"frames": [{"text": "Hi", "media": {"asset_id": a.id}}]}
    item = svc.create_item(db, tid, kind=kind, title="Deck at dawn", actor_id=ws["mkt"].id, payload=payload)
    db.commit()
    svc.submit(db, tid, item.id, item.current_version_id, ws["mkt"])
    svc.approve(db, tid, item.id, item.current_version_id, ws["owner"])
    db.commit()
    return item


def ready(db, ws, cap=10_000, level="suggest"):  # noqa: F811
    """Owner sets a budget + audience, turns the performance marketer on, connects the Page."""
    tenant = ws["tenant"]
    ads.put_settings(db, tenant, {"monthly_cap_inr": cap, "audience": AUDIENCE}, ws["owner"].id)
    agency.update_agency(db, tenant, ws["owner"].id, roles={"ads": level})
    if not db.query(Integration).filter_by(tenant_id=tenant.id, kind="facebook_page").first():   # unique per kind
        db.add(Integration(tenant_id=tenant.id, kind="facebook_page", status="active", config={"page_id": "page-1"}))
    db.commit()


def run_push(db, ws, draft, writer, **kw):  # noqa: F811
    return pusher.push(db, ws["tenant"].id, draft.id, writer_factory=lambda d, t: writer,
                       media_url=lambda a: f"https://cdn/{a.id}", read_bytes=lambda k: PHOTO, **kw)


# ── Settings ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_nothing_is_spent_until_the_owner_sets_a_budget(client, db, ws):  # noqa: F811
    assert ads.get_settings(ws["tenant"])["monthly_cap_inr"] == 0
    assert agency.get_agency(ws["tenant"])["roles"]["ads"] == "off"
    r = client.put(f"{BASE}/settings", json={"monthly_cap_inr": 5000}, headers=ws["manager_h"])
    assert r.status_code == 403                                                  # money limits are the owner's
    assert client.put(f"{BASE}/settings", json={"monthly_cap_inr": -1}, headers=ws["owner_h"]).status_code == 422
    r = client.put(f"{BASE}/settings", json={"monthly_cap_inr": 5000, "audience": AUDIENCE}, headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["budget_left_inr"] == 5000
    assert db.query(AuditEvent).filter_by(tenant_id=ws["tenant"].id, action="marketing.ads.settings_updated").count() == 1


# ── Drafts + approval ───────────────────────────────────────────────────────────────────────────────────────────────

def test_a_draft_needs_approved_content_and_an_audience(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    draft_item = svc.create_item(db, tenant.id, kind="post", title="x", actor_id=None, payload={"caption": "x"})
    db.commit()
    with pytest.raises(MarketingError) as e:
        ads.create_draft(db, tenant, {"content_id": draft_item.id, "daily_budget_inr": 500, "days": 3}, ws["mkt"].id)
    assert e.value.code == "not_approved"
    item = approved_post(db, ws)
    with pytest.raises(MarketingError) as e:
        ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 500, "days": 3}, ws["mkt"].id)
    assert e.value.code == "no_audience"
    story = approved_post(db, ws, kind="story")
    ready(db, ws)
    with pytest.raises(MarketingError) as e:
        ads.create_draft(db, tenant, {"content_id": story.id, "daily_budget_inr": 500, "days": 3}, ws["mkt"].id)
    assert e.value.code == "kind_not_supported"
    with pytest.raises(MarketingError):
        ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 50, "days": 3}, ws["mkt"].id)
    d = ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 500, "days": 3}, ws["mkt"].id)
    assert (d.status, d.spend_cap_inr, d.version_id, d.destination) == ("draft", 1500, item.approved_version_id, "whatsapp")


def test_approval_checks_the_budget_the_role_and_who_made_it(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    item = approved_post(db, ws)
    ads.put_settings(db, tenant, {"monthly_cap_inr": 0, "audience": AUDIENCE}, ws["owner"].id)
    d = ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 1000, "days": 3}, ws["mkt"].id)
    db.commit()
    with pytest.raises(MarketingError) as e:
        ads.approve(db, tenant, d.id, ws["owner"])
    assert e.value.code == "cannot_spend" and "monthly ads budget" in e.value.message
    ads.put_settings(db, tenant, {"monthly_cap_inr": 4000, "audience": AUDIENCE}, ws["owner"].id)
    with pytest.raises(MarketingError) as e:
        ads.approve(db, tenant, d.id, ws["owner"])
    assert "switched off" in e.value.message                                     # the ads role is off by default
    agency.update_agency(db, tenant, ws["owner"].id, roles={"ads": "suggest"})
    mine = ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 100, "days": 1}, ws["manager"].id)
    with pytest.raises(MarketingError) as e:
        ads.approve(db, tenant, mine.id, ws["manager"])
    assert e.value.code == "self_approval"
    assert ads.approve(db, tenant, d.id, ws["manager"]).status == "approved"
    assert ads.committed_this_month(db, tenant.id) == 3000 and ads.budget_left(db, tenant) == 1000
    big = ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 1000, "days": 2}, ws["mkt"].id)
    with pytest.raises(MarketingError) as e:
        ads.approve(db, tenant, big.id, ws["owner"])
    assert "more than is left" in e.value.message
    d.status, d.spent_inr = "ended", Decimal("1200")                               # a finished ad counts what it spent
    db.commit()
    assert ads.committed_this_month(db, tenant.id) == 1200


def test_a_later_reapproval_of_the_post_stops_an_old_ad(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    item = approved_post(db, ws)
    ready(db, ws)
    d = ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 500, "days": 2}, ws["mkt"].id)
    ads.approve(db, tenant, d.id, ws["owner"])
    db.commit()
    svc.add_version(db, tenant.id, item.id, {"caption": "New words", "media": svc.get_version(
        db, tenant.id, item.current_version_id).payload["media"]}, origin="human", actor_id=ws["mkt"].id)
    db.commit()
    svc.submit(db, tenant.id, item.id, item.current_version_id, ws["mkt"])
    svc.approve(db, tenant.id, item.id, item.current_version_id, ws["owner"])
    db.commit()
    writer = FakeWriter()
    run_push(db, ws, d, writer)
    assert d.status == "failed" and "approved again" in d.error and writer.calls == []


# ── Push ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_push_builds_everything_paused_then_switches_it_on_inside_out(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    item = approved_post(db, ws)
    ready(db, ws)
    d = ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 800, "days": 3}, ws["mkt"].id)
    ads.approve(db, tenant, d.id, ws["owner"])
    db.commit()
    writer = FakeWriter()
    now = datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc)
    run_push(db, ws, d, writer, now=now)
    kinds = [c[0] for c in writer.calls]
    assert kinds == ["image", "campaign", "adset", "creative", "ad", "status", "status", "status"]
    assert ("campaign", 2400) in writer.calls
    adset = next(c for c in writer.calls if c[0] == "adset")
    assert adset[1] == 800 and adset[2] == "whatsapp" and adset[4] - adset[3] == timedelta(days=3)
    assert next(c for c in writer.calls if c[0] == "creative")[1] == "Coorg, slowly. DM us for dates."
    assert [c[1] for c in writer.calls if c[0] == "status"] == ["ad-5", "adset-3", "campaign-2"]
    assert d.status == "live" and d.meta["campaign_id"] == "campaign-2" and d.meta["ad_id"] == "ad-5"
    again = FakeWriter()
    run_push(db, ws, d, again)                                                   # re-delivered job: nothing new
    assert again.calls == []


def test_a_meta_outage_resumes_without_a_second_campaign(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    item = approved_post(db, ws)
    ready(db, ws)
    d = ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 500, "days": 2}, ws["mkt"].id)
    ads.approve(db, tenant, d.id, ws["owner"])
    db.commit()
    writer = FakeWriter(fail={"adset": MetaAdsError("Service unavailable", status=503)})
    with pytest.raises(pusher.TransientPushError):
        run_push(db, ws, d, writer)
    assert d.status == "approved" and d.meta["campaign_id"] == "campaign-2"
    run_push(db, ws, d, writer)
    assert d.status == "live" and [c[0] for c in writer.calls].count("campaign") == 1


@pytest.mark.parametrize("writer,setup,expect", [
    (FakeWriter(currency="USD"), None, "not in rupees"),
    (FakeWriter(fail={"campaign": MetaAdsError("Permissions error", status=403, code=200)}), None, "ads_management"),
    (FakeWriter(), "no_page", "Facebook Page"),
])
def test_push_fails_visibly(db, ws, writer, setup, expect):  # noqa: F811
    tenant = ws["tenant"]
    item = approved_post(db, ws)
    ready(db, ws)
    if setup == "no_page":
        db.query(Integration).filter_by(tenant_id=tenant.id, kind="facebook_page").delete()
        db.commit()
    d = ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 500, "days": 2}, ws["mkt"].id)
    ads.approve(db, tenant, d.id, ws["owner"])
    db.commit()
    run_push(db, ws, d, writer)
    assert d.status == "failed" and expect in d.error
    assert db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="marketing.ad.failed").count() == 1


def test_the_kill_switch_stops_a_push_at_the_last_moment(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    item = approved_post(db, ws)
    ready(db, ws)
    d = ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 500, "days": 2}, ws["mkt"].id)
    ads.approve(db, tenant, d.id, ws["owner"])
    agency.update_agency(db, tenant, ws["owner"].id, paused=True)
    db.commit()
    writer = FakeWriter()
    run_push(db, ws, d, writer)
    assert d.status == "failed" and "paused" in d.error and writer.calls == []


# ── Pause + watchdog ────────────────────────────────────────────────────────────────────────────────────────────────

def _live(db, ws, writer, cap_days=2):  # noqa: F811
    tenant = ws["tenant"]
    item = approved_post(db, ws)
    ready(db, ws)
    d = ads.create_draft(db, tenant, {"content_id": item.id, "daily_budget_inr": 500, "days": cap_days}, ws["mkt"].id)
    ads.approve(db, tenant, d.id, ws["owner"])
    db.commit()
    run_push(db, ws, d, writer)
    return d


def test_watchdog_pauses_at_the_cap_and_ends_finished_ads(db, ws):  # noqa: F811
    writer = FakeWriter()
    d = _live(db, ws, writer)
    tid = ws["tenant"].id
    db.add(AdMetric(tenant_id=tid, ad_account_id="act_1", date=date.today(), ad_id=d.meta["ad_id"], spend=Decimal("1000")))
    db.commit()
    out = pusher.watch(db, ws["tenant"], writer_factory=lambda dd, t: writer)
    assert out["paused"] == 1 and d.status == "paused" and float(d.spent_inr) == 1000.0
    assert ("status", d.meta["campaign_id"], "PAUSED") in writer.calls
    other = _live(db, ws, FakeWriter())
    other.ends_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert pusher.watch(db, ws["tenant"])["ended"] == 1 and other.status == "ended"


def test_pause_api_needs_an_approver_and_is_tenant_scoped(client, db, ws, monkeypatch):  # noqa: F811
    writer = FakeWriter()
    d = _live(db, ws, writer)
    monkeypatch.setattr(pusher, "_writer", lambda dd, t: writer)
    assert client.post(f"{BASE}/drafts/{d.id}/pause", headers=ws["mkt_h"]).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.post(f"{BASE}/drafts/{d.id}/pause", headers=other_h).status_code in (403, 404)
    r = client.post(f"{BASE}/drafts/{d.id}/pause", headers=ws["manager_h"])
    assert r.status_code == 200 and r.json()["status"] == "paused"


def test_approve_api_queues_the_push(client, db, ws, monkeypatch):  # noqa: F811
    item = approved_post(db, ws)
    ready(db, ws)
    queued = []
    monkeypatch.setattr("app.workers.tasks.marketing_ads._queue_push", lambda t, d: queued.append((t, d)))
    r = client.post(f"{BASE}/drafts", json={"content_id": item.id, "daily_budget_inr": 500, "days": 2}, headers=ws["mkt_h"])
    assert r.status_code == 201, r.text
    draft_id = r.json()["id"]
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.post(f"{BASE}/drafts/{draft_id}/approve", headers=foh_h).status_code == 403
    r = client.post(f"{BASE}/drafts/{draft_id}/approve", headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["status"] == "approved" and queued == [(ws["tenant"].id, draft_id)]
    body = client.get(BASE, headers=ws["mkt_h"]).json()
    assert body["budget_left_inr"] == 9000 and body["drafts"][0]["id"] == draft_id
    assert db.query(MarketingAdDraft).filter_by(tenant_id=ws["tenant"].id).count() == 1
