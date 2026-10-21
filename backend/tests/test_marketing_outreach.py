"""Agency M3c-e (21 Oct 2026): WhatsApp campaign drafts with a cost, email newsletters, comment-to-DM."""
import uuid
from datetime import datetime, timezone

import pytest

from app.api.v1.endpoints.messaging import (CampaignStatus, TemplateCategory, TemplateStatus, WACampaign, WASubscriber,
                                            WATemplate)
from app.models.audit_event import AuditEvent
from app.models.automation import AutomationRule
from app.models.consent import Consent
from app.models.guest import Guest
from app.models.integration import Integration
from app.models.marketing import MarketingNewsletterRecipient
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_comment_dm as comment_dm
from app.services import marketing_content_service as svc
from app.services import marketing_lint as lint
from app.services import marketing_newsletter as newsletter
from app.services import marketing_whatsapp as wa
from app.services.ig_keyword_match import find_matching_rule
from tests.test_marketing_studio_content import BASE, make_user, ws  # noqa: F401  (fixture)


def _photo(db, tid):
    a = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key=f"{tid}/m/{uuid.uuid4().hex}.jpg", mime_type="image/jpeg",
                   bytes=10, sha256=uuid.uuid4().hex * 2, status="active")
    db.add(a)
    db.commit()
    return a


def _approved(db, ws, kind="promo", payload=None, approver="owner"):  # noqa: F811
    tid = ws["tenant"].id
    payload = payload or {"caption": "A Diwali long weekend in Coorg. Message us for dates.", "headline": "Diwali in the hills",
                          "body": "Three slow days by caravan.", "cta": "Message us", "media": {"asset_id": _photo(db, tid).id}}
    item = svc.create_item(db, tid, kind=kind, title="Diwali weekend", actor_id=ws["mkt"].id, payload=payload)
    db.commit()
    svc.submit(db, tid, item.id, item.current_version_id, ws["mkt"])
    svc.approve(db, tid, item.id, item.current_version_id, ws[approver])
    db.commit()
    return item


def _template(db, tid, status=TemplateStatus.APPROVED, body="Hi {{1}}, Diwali dates are open."):
    t = WATemplate(tenant_id=tid, name=f"diwali_{uuid.uuid4().hex[:4]}", category=TemplateCategory.MARKETING, status=status,
                   components=[{"type": "BODY", "text": body}])
    db.add(t)
    db.commit()
    return t


def _subscribers(db, tid, n=3, tag="past_guests"):
    for i in range(n):
        db.add(WASubscriber(tenant_id=tid, phone=f"+91900000{i:04d}", name=f"G{i}", opted_in=True, tags=[tag]))
    db.add(WASubscriber(tenant_id=tid, phone="+919999999999", name="Out", opted_in=False, tags=[tag]))
    db.commit()


VMAP = {"body": {"1": {"source": "first_name"}}}


# ── WhatsApp ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_estimate_counts_opted_in_people_at_the_workspace_rate(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _subscribers(db, tid)
    t = _template(db, tid)
    est = wa.estimate(db, ws["tenant"], t.id, {"tags": ["past_guests"]})
    assert est["recipients"] == 3 and est["rate_inr"] == 0.86 and est["total_inr"] == 2.58 and est["category"] == "MARKETING"
    wa.update_settings(db, ws["tenant"], ws["owner"].id, rates={"MARKETING": 1.1})
    assert wa.estimate(db, ws["tenant"], t.id, {"tags": ["past_guests"]})["total_inr"] == 3.3
    with pytest.raises(svc.MarketingError) as exc:
        wa.estimate(db, ws["tenant"], t.id, {"type": "leads", "past_guests": True})
    assert exc.value.code == "consent_required"                                  # leads need a confirmation every time


def test_draft_campaign_from_an_approved_promo_is_never_launched(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _subscribers(db, tid)
    t = _template(db, tid)
    item = _approved(db, ws)
    body = {"template_id": t.id, "audience_filter": {"tags": ["past_guests"]}, "variable_map": VMAP}
    r = client.post(f"{BASE}/content/{item.id}/whatsapp", json=body, headers=ws["mkt_h"])
    assert r.status_code == 201 and r.json()["recipients"] == 3 and r.json()["status"] == "draft"
    camp = db.get(WACampaign, r.json()["campaign_id"])
    assert camp.status == CampaignStatus.DRAFT and camp.name.startswith("Studio: ")
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="marketing.whatsapp.drafted").count() == 1
    assert client.post(f"{BASE}/content/{item.id}/whatsapp", json={**body, "variable_map": {}}, headers=ws["mkt_h"]).json()["detail"]["code"] == "variables_unmapped"
    pending = _template(db, tid, status=TemplateStatus.PENDING)
    assert client.post(f"{BASE}/content/{item.id}/whatsapp", json={**body, "template_id": pending.id},
                       headers=ws["mkt_h"]).json()["detail"]["code"] == "template_not_approved"
    post = _approved(db, ws, kind="post", payload={"caption": "x", "media": {"asset_id": _photo(db, tid).id}})
    assert client.post(f"{BASE}/content/{post.id}/whatsapp", json=body, headers=ws["mkt_h"]).json()["detail"]["code"] == "not_a_promo"
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = _template(db, other.id)
    assert client.post(f"{BASE}/content/{item.id}/whatsapp", json={**body, "template_id": theirs.id},
                       headers=ws["mkt_h"]).json()["detail"]["code"] == "template_not_found"


def test_approving_a_promo_that_targets_whatsapp_drafts_a_campaign_with_the_defaults(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _subscribers(db, tid)
    t = _template(db, tid)
    db.add(Integration(tenant_id=tid, kind="whatsapp_meta", status="active"))
    db.commit()
    assert client.put(f"{BASE}/whatsapp", json={"template_id": t.id, "tags": ["past_guests"], "variable_map": VMAP},
                      headers=ws["manager_h"]).status_code == 403
    assert client.put(f"{BASE}/whatsapp", json={"template_id": t.id, "tags": ["past_guests"], "variable_map": VMAP},
                      headers=ws["owner_h"]).status_code == 200
    item = svc.create_item(db, tid, kind="promo", title="Diwali", actor_id=ws["mkt"].id, payload={
        "caption": "Diwali in Coorg", "headline": "Diwali", "body": "Three days", "cta": "Message us",
        "media": {"asset_id": _photo(db, tid).id}})
    db.commit()
    assert client.put(f"{BASE}/content/{item.id}/targets", json={"targets": ["instagram", "whatsapp"]}, headers=ws["mkt_h"]).status_code == 200
    svc.submit(db, tid, item.id, item.current_version_id, ws["mkt"])
    db.commit()
    r = client.post(f"{BASE}/approvals/content/{item.id}/approve", json={}, headers=ws["owner_h"])
    assert r.status_code == 200
    drafts = db.query(WACampaign).filter_by(tenant_id=tid, status=CampaignStatus.DRAFT).all()
    assert len(drafts) == 1 and drafts[0].audience_filter == {"tags": ["past_guests"]}


# ── Newsletters ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _guest(db, tid, email, consent=None, email_out=False):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Guest", email=email)
    db.add(g)
    db.commit()
    now = datetime.now(timezone.utc).isoformat()
    if consent is not None:
        db.add(Consent(tenant_id=tid, guest_id=g.id, channel="whatsapp", scope="marketing", granted=consent, recorded_at=now))
    if email_out:
        db.add(Consent(tenant_id=tid, guest_id=g.id, channel="email", scope="marketing", granted=False, recorded_at=now + "z"))
    db.commit()
    return g


def test_audience_is_email_plus_marketing_consent_minus_email_unsubscribes(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    yes = _guest(db, tid, "anu@example.com", consent=True)
    _guest(db, tid, "no@example.com", consent=False)
    _guest(db, tid, "never@example.com")
    _guest(db, tid, "left@example.com", consent=True, email_out=True)
    _guest(db, tid, None, consent=True)
    assert [g.id for g in newsletter.audience(db, tid)] == [yes.id]


def test_newsletter_send_needs_consent_confirmation_and_no_self_approval(client, db, ws, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test")
    tid = ws["tenant"].id
    _guest(db, tid, "anu@example.com", consent=True)
    item = _approved(db, ws)
    r = client.post(f"{BASE}/newsletters", json={"subject": "Diwali dates", "intro": "Hello <b>friends</b>",
                                                 "content_ids": [item.id]}, headers=ws["manager_h"])
    assert r.status_code == 201
    nid = r.json()["id"]
    queued = []
    monkeypatch.setattr("app.workers.tasks.marketing_studio.newsletter_send_batch.delay", lambda *a: queued.append(a))
    assert client.post(f"{BASE}/newsletters/{nid}/send", json={}, headers=ws["owner_h"]).json()["detail"]["code"] == "consent_required"
    assert client.post(f"{BASE}/newsletters/{nid}/send", json={"consent_confirmed": True}, headers=ws["mkt_h"]).status_code == 403
    assert client.post(f"{BASE}/newsletters/{nid}/send", json={"consent_confirmed": True},
                       headers=ws["manager_h"]).json()["detail"]["code"] == "self_approval"
    r = client.post(f"{BASE}/newsletters/{nid}/send", json={"consent_confirmed": True}, headers=ws["owner_h"])
    assert r.status_code == 202 and r.json()["recipients"] == 1 and queued == [(tid, nid)]
    preview = client.get(f"{BASE}/newsletters/{nid}/preview", headers=ws["mkt_h"])
    assert preview.status_code == 200 and "Hello &lt;b&gt;friends&lt;/b&gt;" in preview.text and "Diwali in the hills" in preview.text


def test_batch_sends_once_with_unsubscribe_headers_and_keeps_addresses_out_of_logs(db, ws, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test")
    monkeypatch.setattr("app.core.config.settings.API_BASE_URL", "https://api.haip.test")
    tid = ws["tenant"].id
    _guest(db, tid, "anu@example.com", consent=True)
    _guest(db, tid, "ravi@example.com", consent=True)
    item = _approved(db, ws)
    nl = newsletter.create(db, tid, "Diwali dates", None, [item.id], ws["manager"].id)
    newsletter.start_send(db, ws["tenant"], nl.id, ws["owner"], consent_confirmed=True)
    db.commit()
    sent = []

    def fake_send(**kw):
        sent.append(kw)
        return True
    assert newsletter.send_batch(db, tid, nl.id, sender=fake_send, image_url=lambda a: "https://cdn/x.jpg") == 0
    assert len(sent) == 2 and all(kw["log_to"] is False for kw in sent)
    links = {kw["headers"]["List-Unsubscribe"] for kw in sent}
    assert len(links) == 2 and all(l.startswith("<https://api.haip.test/api/v1/public/email/unsubscribe/") for l in links)
    assert all("@" not in l for l in links)                                       # no address in the link
    assert sent[0]["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    db.refresh(nl)
    assert nl.status == "sent" and nl.delivered == 2
    assert newsletter.send_batch(db, tid, nl.id, sender=fake_send) == 0 and len(sent) == 2      # never twice


def test_unsubscribe_link_get_shows_a_page_post_unsubscribes(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    g = _guest(db, tid, "anu@example.com", consent=True)
    token = newsletter.unsubscribe_token(tid, g.id, "N1")
    assert newsletter.read_token(token[:-2] + "xx") is None                      # tampered
    r = client.get(f"/api/v1/public/email/unsubscribe/{token}")
    assert r.status_code == 200 and "<form" in r.text
    assert newsletter.audience(db, tid) != []                                    # a GET never unsubscribes
    r = client.post(f"/api/v1/public/email/unsubscribe/{token}")
    assert r.status_code == 200 and "unsubscribed" in r.text
    assert newsletter.audience(db, tid) == []
    assert client.post("/api/v1/public/email/unsubscribe/garbage.sig").status_code == 404


# ── Comment-to-DM ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_comment_dm_is_validated_and_the_caption_must_name_the_keyword():
    from app.schemas.marketing import validate_content
    with pytest.raises(ValueError):
        validate_content("post", {"caption": "x", "comment_dm": {"keyword": "two words", "message": "Here are the dates."}})
    found = lint.check("post", {"caption": "Diwali dates are open.", "comment_dm": {"keyword": "STAY", "message": "Here are the dates for you."}})
    assert "comment_keyword_missing" in {f["rule"] for f in found if f["severity"] == "high"}
    ok = lint.check("post", {"caption": "Comment STAY and we'll send the dates.", "comment_dm": {"keyword": "stay", "message": "Here are the dates for you."}})
    assert "comment_keyword_missing" not in {f["rule"] for f in ok}


def test_publishing_activates_one_post_scoped_keyword_rule(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    payload = {"caption": "Comment STAY and we'll send the dates.",
               "comment_dm": {"keyword": "STAY", "message": "Here are the Diwali dates: ...", "public_reply": "Sent you a DM!"}}
    item = svc.create_item(db, tid, kind="post", title="Diwali", actor_id=ws["mkt"].id, payload=payload)
    db.commit()
    rule = comment_dm.activate(db, tid, item, payload, "MEDIA1")
    assert comment_dm.activate(db, tid, item, payload, "MEDIA1").id == rule.id   # a retried publish: same rule
    db.commit()
    assert rule.action_config == {"message": "Here are the Diwali dates: ...", "public_ack_pool": ["Sent you a DM!"]}
    assert find_matching_rule(db, tid, "ig_comment_received", "stay please!", media_id="MEDIA1").id == rule.id
    assert find_matching_rule(db, tid, "ig_comment_received", "stay please!", media_id="OTHER") is None
    assert db.query(AutomationRule).filter_by(tenant_id=tid).count() == 1


def test_whatsapp_and_newsletter_lists_need_read_capability(client, db, ws):  # noqa: F811
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.get(f"{BASE}/whatsapp", headers=foh_h).status_code == 403
    assert client.get(f"{BASE}/newsletters", headers=foh_h).status_code == 403
    r = client.get(f"{BASE}/newsletters", headers=ws["mkt_h"])
    assert r.status_code == 200 and r.json()["audience"] == 0
    assert db.query(MarketingNewsletterRecipient).count() == 0
