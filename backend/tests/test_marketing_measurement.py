"""Agency M6 (21 Oct 2026): UTMs + link-in-bio, attribution beyond click-to-WhatsApp, "how did you hear about us",
element learning (Thompson sampling), weekly / monthly reports and the health score, the weekly email."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.base import gen_uuid
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.lead_attribution import LeadAttribution
from app.models.marketing import InstagramPostMetricDaily, MarketingPublishAttempt
from app.models.marketing_ads import MarketingAdDraft
from app.models.property import Property, Stay
from app.models.sales_target import SalesTarget
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_attribution as attribution
from app.services import marketing_channels as channels
from app.services import marketing_content_service as svc
from app.services import marketing_learning as learning
from app.services import marketing_links as links
from app.services import marketing_reports as reports
from tests.test_marketing_studio_content import make_user, ws  # noqa: F401  (fixture)

RES = "/api/v1/marketing/studio/results"
TODAY = date(2026, 10, 21)          # a Wednesday; last full week = 12-18 Oct


def _post(db, tid, title="Deck at dawn", caption="6am on the deck. DM us.", kind="post"):
    item = svc.create_item(db, tid, kind=kind, title=title, actor_id=None, payload={"caption": caption})
    db.commit()
    return item


def _published(db, tid, item, *, permalink=None, media_id=None, when=None):
    a = MarketingPublishAttempt(tenant_id=tid, content_id=item.id, version_id=item.current_version_id, sha256="x" * 64,
                                scheduled_for=when or datetime.now(timezone.utc), status="published", channel="instagram",
                                permalink=permalink or f"https://www.instagram.com/p/{uuid.uuid4().hex[:10]}/",
                                media_ids=[media_id or uuid.uuid4().hex], published_at=when or datetime.now(timezone.utc))
    db.add(a)
    db.commit()
    return a


def _lead(db, tid, *, utm=None, created=None, heard=None, first_touch=None):
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Asha", phone=f"+9198450{uuid.uuid4().int % 10**5:05d}",
              first_touch_channel=first_touch, first_touch_at=created)
    db.add(g)
    db.flush()
    inq = Inquiry(id=gen_uuid(), tenant_id=tid, guest_id=g.id, custom_fields={"utm": utm} if utm else {},
                  heard_about=heard)
    if created:
        inq.created_at = created
    db.add(inq)
    db.commit()
    return g, inq


def _stay(db, tid, inq, *, amount=20000, created=None):
    prop = db.query(Property).filter_by(tenant_id=tid).first()
    if prop is None:
        prop = Property(tenant_id=tid, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True)
        db.add(prop)
        db.flush()
    s = Stay(id=gen_uuid(), tenant_id=tid, guest_id=inq.guest_id, property_id=prop.id, inquiry_id=inq.id,
             check_in=TODAY + timedelta(days=20), check_out=TODAY + timedelta(days=22), status="confirmed",
             total_amount=Decimal(amount))
    if created:
        s.created_at = created
    db.add(s)
    db.commit()
    return s


def _referral(db, tid, g, inq, *, source_type, ad_id=None, source_url=None, at=None):
    conv = Conversation(id=gen_uuid(), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, channel=ChannelType.INSTAGRAM,
                        is_open=True)
    db.add(conv)
    db.flush()
    db.add(LeadAttribution(tenant_id=tid, inquiry_id=inq.id, conversation_id=conv.id, guest_id=g.id,
                           destination_channel="instagram", source_type=source_type, ad_id=ad_id, source_url=source_url,
                           first_message_at=at or datetime.now(timezone.utc)))
    db.commit()


# ── Links ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_utm_tags_name_the_post_and_resolve_back_only_in_their_tenant(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    item = _post(db, tid)
    url = links.tag_url("https://stay.example.in/book?x=1", links.utm(source="instagram", medium="bio",
                                                                      campaign=links.campaign_for_content(item.id)))
    assert url.startswith("https://stay.example.in/book?x=1&utm_source=instagram&utm_medium=bio&utm_campaign=c-")
    assert links.resolve_campaign(db, tid, links.campaign_for_content(item.id)) == {"content_id": item.id}
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    assert links.resolve_campaign(db, other.id, links.campaign_for_content(item.id)) == {}
    assert links.resolve_campaign(db, tid, "spring_sale") == {}
    assert links.tag_url("https://a.in/?utm_source=me", {"utm_source": "x"}) == "https://a.in/?utm_source=me"


def test_google_post_button_carries_the_posts_campaign():
    action = channels.google_action("promo", {"socials": {"website": "https://stay.example.in"}}, "abcd1234-0000")
    assert action["actionType"] == "BOOK" and "utm_campaign=c-abcd1234" in action["url"] and "utm_source=google" in action["url"]


def test_bio_items_link_each_published_post_to_the_site(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    a, b = _post(db, tid, "First"), _post(db, tid, "Second")
    _published(db, tid, a, when=datetime.now(timezone.utc) - timedelta(days=2))
    _published(db, tid, b)
    items = links.bio_items(db, tid, "https://stay.example.in/")
    assert [i["title"] for i in items] == ["Second", "First"]
    assert f"utm_campaign={links.campaign_for_content(b.id)}" in items[0]["url"] and "utm_medium=bio" in items[0]["url"]


def test_public_links_page_is_404_for_an_unknown_site(client):
    assert client.get("/api/v1/public/sites/nobody.genhaip.site/links").status_code == 404


# ── Attribution ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_each_booking_names_its_post_or_ad_and_the_rest_is_unknown(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    week = datetime(2026, 10, 14, 6, tzinfo=timezone.utc)
    bio_post, ig_post, ad_post = _post(db, tid, "Bio post"), _post(db, tid, "Referral post"), _post(db, tid, "Ad post")
    attempt = _published(db, tid, ig_post, permalink="https://www.instagram.com/p/AbCdEf123/")
    db.add(MarketingAdDraft(tenant_id=tid, content_id=ad_post.id, version_id="v", content_sha="s", destination="whatsapp",
                            daily_budget_inr=500, days=2, spend_cap_inr=1000, audience={}, status="live",
                            meta={"ad_id": "meta-ad-9"}))
    db.commit()
    _, web = _lead(db, tid, utm={"utm_source": "instagram", "utm_medium": "bio",
                                 "utm_campaign": links.campaign_for_content(bio_post.id)}, created=week)
    _stay(db, tid, web, amount=18000, created=week + timedelta(hours=2))
    g2, ref = _lead(db, tid, created=week, heard="friend")
    _referral(db, tid, g2, ref, source_type="post", source_url="https://instagram.com/p/AbCdEf123", at=week)
    _stay(db, tid, ref, amount=22000, created=week + timedelta(hours=3))
    g3, ad = _lead(db, tid, created=week)
    _referral(db, tid, g3, ad, source_type="ad", ad_id="meta-ad-9", at=week)
    _stay(db, tid, ad, amount=30000, created=week + timedelta(hours=4))
    _, none = _lead(db, tid, created=week, heard="google", first_touch="call")
    _stay(db, tid, none, amount=12000, created=week + timedelta(hours=5))
    out = attribution.bookings(db, tid, date(2026, 10, 12), date(2026, 10, 18))
    assert (out["total"], out["traced"], out["unknown"], out["unknown_share"]) == (4, 3, 1, 0.25)
    titles = [r["credited_title"] for r in out["bookings"]]
    assert titles == ["Bio post", "Referral post", "Ad post", None]
    assert out["bookings"][1]["heard_about"] == "A friend or family"        # what they said, shown apart
    assert out["bookings"][3]["chain"]["first"]["channel"] == "call" and not out["bookings"][3]["chain"]["known"]
    assert {p["title"] for p in out["by_post"]} == {"Bio post", "Referral post", "Ad post"}
    assert attempt.permalink


def test_credit_goes_to_the_last_named_touch_before_the_booking():
    t = lambda h, cid: {"at": datetime(2026, 10, 1, h, tzinfo=timezone.utc), "content_id": cid, "ad_draft_id": None,  # noqa: E731
                        "ad_id": None, "kind": "post", "channel": "instagram", "detail": None}
    ts = [t(1, "early"), t(5, "late"), t(9, "after")]
    c = attribution.chain(ts, datetime(2026, 10, 1, 7, tzinfo=timezone.utc))
    assert c["first"]["content_id"] == "early" and c["credited"]["content_id"] == "late" and c["known"]


def test_heard_about_needs_leads_write_and_is_tenant_scoped(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _, inq = _lead(db, tid)
    r = client.put(f"/api/v1/leads/{inq.id}/heard-about", json={"heard_about": "instagram", "note": "saw the reel"},
                   headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["heard_about"] == "instagram" and r.json()["heard_about_note"] == "saw the reel"
    assert client.put(f"/api/v1/leads/{inq.id}/heard-about", json={"heard_about": "tv"}, headers=ws["owner_h"]).status_code == 422
    _, foh_h = make_user(db, tid, UserRole.FOH)
    assert client.put(f"/api/v1/leads/{inq.id}/heard-about", json={"heard_about": "friend"}, headers=foh_h).status_code == 403
    assert client.get(f"/api/v1/leads/{inq.id}/touches", headers=foh_h).status_code == 200      # reading is fine
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"/api/v1/leads/{inq.id}/touches", headers=other_h).status_code in (403, 404)


# ── Learning ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("line,kind", [("3 mornings in Coorg", "number"), ("Where would you wake up?", "question"),
                                       ("6am on the deck", "moment"), ("Monsoon package for two", "offer"),
                                       ("The road is the stay", "statement"), ("", "none")])
def test_hook_types(line, kind):
    assert learning.hook_type(line) == kind


def _p(fmt, hook, rate):
    return {"rate": rate, "elements": {"format": fmt, "hook": hook, "shot": "view", "pillar": "Routes"}}


def test_thompson_learning_is_deterministic_and_needs_signal():
    assert learning.learn([_p("post", "number", 0.05)])["note"].startswith("Not enough signal")
    posts = [_p("carousel", "number", r) for r in (0.09, 0.08, 0.10, 0.07)] + [_p("post", "statement", r) for r in (0.02, 0.03, 0.01, 0.04)]
    a, b = learning.learn(posts), learning.learn(posts)
    assert a == b
    fmt = {v["value"]: v for v in a["elements"]["format"]}
    assert fmt["carousel"]["wins"] == 4 and fmt["carousel"]["p_best"] > 0.9 and fmt["post"]["p_best"] < 0.1
    shares = learning.thompson({"x": (10, 2), "y": (2, 10)})
    assert abs(sum(shares.values()) - 1) < 0.01 and shares["x"] > shares["y"]


def test_published_posts_get_their_elements_and_latest_rate(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    item = _post(db, tid, caption="Where would you wake up? DM us.")
    _published(db, tid, item, media_id="m1")
    for day, reach, inter in (("2026-10-01", 100, 5), ("2026-10-02", 400, 40)):
        db.add(InstagramPostMetricDaily(tenant_id=tid, media_id="m1", day=day, reach=reach, total_interactions=inter))
    db.commit()
    got = learning.published_posts(db, tid)
    assert got[0]["rate"] == 0.1 and got[0]["elements"] == {"format": "post", "hook": "question", "shot": "unknown",
                                                            "pillar": "unplanned"}


# ── Reports ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_monthly_status_against_the_revenue_target(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    db.add(SalesTarget(tenant_id=tid, scope_type="tenant", scope_id=None, period_month=date(2026, 10, 1),
                       target_amount=Decimal("100000")))
    db.commit()
    _, inq = _lead(db, tid)
    _stay(db, tid, inq, amount=40000, created=datetime(2026, 10, 5, 6, tzinfo=timezone.utc))
    out = reports.monthly(db, ws["tenant"], date(2026, 10, 1), today=date(2026, 10, 15))
    rev = next(m for m in out["metrics"] if m["key"] == "revenue")
    assert rev["this"] == 40000.0 and rev["target"] == 100000.0 and rev["status"] == "off_track"   # 40k by mid-month -> ~83k
    out = reports.monthly(db, ws["tenant"], date(2026, 10, 1), today=date(2026, 10, 12))
    assert next(m for m in out["metrics"] if m["key"] == "revenue")["status"] == "on_track"        # ~103k pace
    assert next(m for m in out["metrics"] if m["key"] == "traced")["status"] is None              # no target, no status


def test_health_score_explains_each_part(db, ws):  # noqa: F811
    h = reports.health(db, ws["tenant"], TODAY)
    assert 0 <= h["score"] <= 100 and [p["key"] for p in h["parts"]] == ["cadence", "engagement", "traceability", "approvals"]
    assert all(p["detail"] for p in h["parts"])


def test_weekly_email_is_off_by_default_then_sent_once_to_owners_and_managers(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    sent = []
    sender = lambda **kw: sent.append(kw) or True  # noqa: E731
    assert reports.send_weekly(db, tenant, today=TODAY, sender=sender) == {"sent": 0, "reason": "off"}
    reports.update_settings(db, tenant, weekly_email=True, monthly_traced_bookings=None, actor_id=ws["owner"].id)
    db.commit()
    _, inq = _lead(db, tenant.id)
    _stay(db, tenant.id, inq, created=datetime(2026, 10, 14, 6, tzinfo=timezone.utc))
    out = reports.send_weekly(db, tenant, today=TODAY, sender=sender)
    assert out["sent"] == len(sent) == 3 and out["week"] == "2026-10-12"         # owner + 2 managers, not marketing
    assert "1 bookings, 0 traced" in sent[0]["subject"] and "unknown" in sent[0]["text"]
    assert ws["mkt"].email not in {s["to"] for s in sent}
    assert reports.send_weekly(db, tenant, today=TODAY, sender=sender)["reason"] == "already sent"


def test_results_api_roles(client, db, ws):  # noqa: F811
    assert client.get(f"{RES}/weekly", headers=ws["mkt_h"]).status_code == 403            # revenue: approvers only
    assert client.get(f"{RES}/weekly", headers=ws["manager_h"]).status_code == 200
    assert client.get(f"{RES}/monthly?month=2026-09", headers=ws["owner_h"]).status_code == 200
    assert client.get(f"{RES}/health", headers=ws["mkt_h"]).status_code == 200
    assert client.get(f"{RES}/learning", headers=ws["mkt_h"]).status_code == 200
    assert client.put(f"{RES}/settings", json={"weekly_email": True}, headers=ws["manager_h"]).status_code == 403
    r = client.put(f"{RES}/settings", json={"weekly_email": True, "monthly_traced_bookings": 6}, headers=ws["owner_h"])
    assert r.json() == {"weekly_email": True, "monthly_traced_bookings": 6}
    assert client.get(f"{RES}/bookings?since=2026-10-20&until=2026-10-01", headers=ws["owner_h"]).status_code == 422
    with patch.object(learning, "ads_split", return_value={"days": 14, "note": "x", "ads": []}):
        assert client.get(f"{RES}/ads-split", headers=ws["mkt_h"]).status_code == 403
