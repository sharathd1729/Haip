"""Campaign report, recipient export, subscriber import, and scheduling: endpoints."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.api.v1.endpoints.messaging import (
    CampaignStatus, TemplateStatus, WACampaign, WASubscriber, WATemplate,
)
from app.core.security import create_access_token
from app.models.audit_event import AuditEvent
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient

BODY = {"type": "BODY", "text": "Hello from Ratha"}


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _role_headers(db, tenant_id, role):
    user = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="U", email=f"u-{uuid.uuid4().hex[:6]}@t.com",
                hashed_password="x", role=role, is_active=True)
    db.add(user); db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": user.id, "tenant_id": tenant_id, "role": role.value})}


def _other_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush()
    return t.id


def _template(db, tid, status=TemplateStatus.APPROVED):
    t = WATemplate(id=str(uuid.uuid4()), tenant_id=tid, name=f"t_{uuid.uuid4().hex[:6]}", language="en",
                   status=status, components=[BODY])
    db.add(t); db.commit()
    return t


def _campaign(db, tid, template_id=None, status=CampaignStatus.COMPLETED, **kw):
    c = WACampaign(id=str(uuid.uuid4()), tenant_id=tid, name="Diwali push", template_id=template_id,
                   audience_filter={}, variable_map={}, status=status, **kw)
    db.add(c); db.commit()
    return c


def _rows(db, campaign):
    spec = [
        ("+919800000001", "Priya", "read", None), ("+919800000002", "Arjun", "delivered", None),
        ("+919800000003", "=HYPERLINK(\"x\")", "sent", None),
        ("+919800000004", None, "failed", ("131026", "Not on WhatsApp")),
        ("+919800000005", "Meera", "failed", ("131026", "Not on WhatsApp")),
        ("+919800000006", "Karan", "failed", ("131050", "Opted out")),
    ]
    for phone, name, status, err in spec:
        db.add(Recipient(id=str(uuid.uuid4()), tenant_id=campaign.tenant_id, campaign_id=campaign.id, phone=phone,
                         name=name, status=status, error_code=err[0] if err else None,
                         error_reason=err[1] if err else None, wa_message_id=f"w{phone[-1]}"))
    db.commit()


# ─── report ──────────────────────────────────────────────────────────────────

def test_report_summary_failures_and_recipients(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid, _template(db, tid).id)
    _rows(db, c)
    r = client.get(f"/api/v1/messaging/campaigns/{c.id}/report", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    body = r.json()
    s = body["summary"]
    assert (s["total"], s["sent"], s["delivered"], s["read"], s["failed"]) == (6, 3, 2, 1, 3)
    assert s["delivery_rate"] == 66.7 and s["read_rate"] == 50.0 and s["failure_rate"] == 50.0
    assert [(f["group"], f["count"]) for f in body["failures"]] == [("not_reachable", 2), ("opted_out", 1)]
    assert body["failures"][0]["hint"]
    assert body["total_matching"] == 6 and len(body["recipients"]) == 6
    assert body["campaign"]["name"] == "Diwali push"


def test_report_filters_and_paging(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid)
    _rows(db, c)
    url = f"/api/v1/messaging/campaigns/{c.id}/report"
    failed = client.get(url, params={"status": "failed"}, headers=_h(tenant_and_user)).json()
    assert failed["total_matching"] == 3 and {x["status"] for x in failed["recipients"]} == {"failed"}
    delivered = client.get(url, params={"status": "delivered"}, headers=_h(tenant_and_user)).json()
    assert delivered["total_matching"] == 2                      # cumulative: delivered + read
    sent = client.get(url, params={"status": "sent"}, headers=_h(tenant_and_user)).json()
    assert sent["total_matching"] == 3
    found = client.get(url, params={"search": "Priya"}, headers=_h(tenant_and_user)).json()
    assert found["total_matching"] == 1
    page = client.get(url, params={"limit": 2, "offset": 4}, headers=_h(tenant_and_user)).json()
    assert page["total_matching"] == 6 and len(page["recipients"]) == 2


def test_report_bad_filter_is_422(client, db, tenant_and_user):
    c = _campaign(db, _tid(tenant_and_user))
    assert client.get(f"/api/v1/messaging/campaigns/{c.id}/report", params={"status": "bogus"}, headers=_h(tenant_and_user)).status_code == 422


def test_report_forbidden_for_a_concierge_and_404_across_workspaces(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid)
    agent = _role_headers(db, tid, UserRole.CONCIERGE)
    assert client.get(f"/api/v1/messaging/campaigns/{c.id}/report", headers=agent).status_code == 403
    theirs = _campaign(db, _other_tenant(db))
    assert client.get(f"/api/v1/messaging/campaigns/{theirs.id}/report", headers=_h(tenant_and_user)).status_code == 404


# ─── export ──────────────────────────────────────────────────────────────────

def test_export_csv_is_audited_and_defuses_formulas(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid)
    _rows(db, c)
    r = client.get(f"/api/v1/messaging/campaigns/{c.id}/recipients.csv", params={"status": "failed"}, headers=_h(tenant_and_user))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "Diwali-push-recipients.csv" in r.headers["content-disposition"]
    lines = r.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0] == "Phone,Name,Status,Reason,Sent at,Delivered at,Read at,Replied,Replied at" and len(lines) == 4
    everything = client.get(f"/api/v1/messaging/campaigns/{c.id}/recipients.csv", headers=_h(tenant_and_user)).content.decode("utf-8-sig")
    assert "'=HYPERLINK" in everything and ",=HYPERLINK" not in everything
    ev = db.query(AuditEvent).filter_by(tenant_id=tid, action="campaigns.recipients_export").first()
    assert ev is not None and ev.target_id == c.id


def test_export_forbidden_and_cross_tenant(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid)
    agent = _role_headers(db, tid, UserRole.CONCIERGE)
    assert client.get(f"/api/v1/messaging/campaigns/{c.id}/recipients.csv", headers=agent).status_code == 403
    theirs = _campaign(db, _other_tenant(db))
    assert client.get(f"/api/v1/messaging/campaigns/{theirs.id}/recipients.csv", headers=_h(tenant_and_user)).status_code == 404


# ─── import ──────────────────────────────────────────────────────────────────

def _post_import(client, headers, content, consent="true", tag=None, name="c.csv"):
    data = {"consent": consent}
    if tag is not None:
        data["tag"] = tag
    return client.post("/api/v1/messaging/subscribers/import", data=data, files={"file": (name, content, "text/csv")}, headers=headers)


def test_import_requires_consent(client, db, tenant_and_user):
    r = _post_import(client, _h(tenant_and_user), b"phone\n9876543210\n", consent="false")
    assert r.status_code == 400 and "agreed" in r.json()["detail"]
    assert db.query(WASubscriber).filter_by(tenant_id=_tid(tenant_and_user)).count() == 0


def test_import_happy_path_reports_bad_rows_and_writes_audit(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    r = _post_import(client, _h(tenant_and_user), b"phone,name\n9876543210,Priya\n9822011111,Arjun\n12345,Bad\n9876543210,Dup\n", tag="diwali")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["total_rows"], body["added"], body["duplicates_in_file"], body["invalid_count"]) == (4, 2, 1, 1)
    assert body["invalid"][0]["row"] == 4 and "valid" in body["invalid"][0]["reason"]
    subs = db.query(WASubscriber).filter_by(tenant_id=tid).all()
    assert {s.phone for s in subs} == {"+919876543210", "+919822011111"} and all("diwali" in s.tags for s in subs)
    ev = db.query(AuditEvent).filter_by(tenant_id=tid, action="subscribers.import").first()
    assert ev is not None and ev.actor_user_id


def test_import_keeps_opted_out_people_out(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=tid, phone="+919876543210", opted_in=False, tags=[]))
    db.commit()
    body = _post_import(client, _h(tenant_and_user), b"phone\n9876543210\n").json()
    assert body["added"] == 0 and body["opted_out_skipped"] == 1
    assert db.query(WASubscriber).filter_by(tenant_id=tid, phone="+919876543210").one().opted_in is False


@pytest.mark.parametrize("content,fragment", [(b"", "empty"), (b"name\nPriya\n", "phone column")])
def test_import_bad_files_are_400_with_a_reason(client, tenant_and_user, content, fragment):
    r = _post_import(client, _h(tenant_and_user), content)
    assert r.status_code == 400 and fragment in r.json()["detail"]


def test_import_forbidden_for_a_concierge(client, db, tenant_and_user):
    agent = _role_headers(db, _tid(tenant_and_user), UserRole.CONCIERGE)
    assert _post_import(client, agent, b"phone\n9876543210\n").status_code == 403


# ─── scheduling ──────────────────────────────────────────────────────────────

def _future(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _body(template_id, **extra):
    return {"name": "Push", "template_id": template_id, "audience_filter": {}, "variable_map": {}, **extra}


def test_creating_with_a_future_time_schedules_it_in_utc(client, db, tenant_and_user):
    t = _template(db, _tid(tenant_and_user))
    r = client.post("/api/v1/messaging/campaigns", json=_body(t.id, scheduled_at="2099-01-01T10:00"), headers=_h(tenant_and_user))
    assert r.status_code == 400                                       # far too far ahead
    when = _future()
    r = client.post("/api/v1/messaging/campaigns", json=_body(t.id, scheduled_at=when), headers=_h(tenant_and_user))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "scheduled" and r.json()["scheduled_at"].endswith("+00:00")


def test_a_naive_time_is_read_as_india_time(client, db, tenant_and_user):
    t = _template(db, _tid(tenant_and_user))
    local = (datetime.now(timezone.utc) + timedelta(hours=5)).astimezone(timezone(timedelta(hours=5, minutes=30))).replace(tzinfo=None)
    r = client.post("/api/v1/messaging/campaigns", json=_body(t.id, scheduled_at=local.isoformat(timespec="minutes")), headers=_h(tenant_and_user))
    assert r.status_code == 201, r.text
    stored = datetime.fromisoformat(r.json()["scheduled_at"])
    assert abs((stored - datetime.now(timezone.utc)).total_seconds() - 5 * 3600) < 180


def test_past_times_and_unapproved_templates_cannot_be_scheduled(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    ok = _template(db, tid)
    past = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    r = client.post("/api/v1/messaging/campaigns", json=_body(ok.id, scheduled_at=past), headers=_h(tenant_and_user))
    assert r.status_code == 400 and "passed" in r.json()["detail"]
    draft = _template(db, tid, status=TemplateStatus.DRAFT)
    r = client.post("/api/v1/messaging/campaigns", json=_body(draft.id, scheduled_at=_future()), headers=_h(tenant_and_user))
    assert r.status_code == 400 and "approved" in r.json()["detail"]
    r = client.post("/api/v1/messaging/campaigns", json=_body(None, scheduled_at=_future()), headers=_h(tenant_and_user))
    assert r.status_code == 400


def test_patch_can_schedule_reschedule_and_unschedule(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid, _template(db, tid).id, status=CampaignStatus.DRAFT)
    url = f"/api/v1/messaging/campaigns/{c.id}"
    r = client.patch(url, json={"scheduled_at": _future(3)}, headers=_h(tenant_and_user))
    assert r.status_code == 200 and r.json()["status"] == "scheduled"
    r = client.patch(url, json={"scheduled_at": None}, headers=_h(tenant_and_user))
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["scheduled_at"] is None


def test_running_and_completed_campaigns_cannot_be_changed(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    for status in (CampaignStatus.RUNNING, CampaignStatus.COMPLETED):
        c = _campaign(db, tid, status=status)
        r = client.patch(f"/api/v1/messaging/campaigns/{c.id}", json={"name": "x"}, headers=_h(tenant_and_user))
        assert r.status_code == 409


def test_a_scheduled_campaign_can_be_launched_now(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    t = _template(db, tid)
    c = _campaign(db, tid, t.id, status=CampaignStatus.SCHEDULED, scheduled_at=_future())
    with patch("app.workers.tasks.run_campaign.run_campaign.apply_async") as enqueue:
        r = client.post(f"/api/v1/messaging/campaigns/{c.id}/launch", headers=_h(tenant_and_user))
    assert r.status_code == 200 and r.json()["status"] == "running"
    enqueue.assert_called_once()


# ─── stats + audience count ──────────────────────────────────────────────────

def _subs(db, tid):
    for phone, opted, tags, source in [
        ("+919800000001", True, ["vip"], "import"), ("+919800000002", True, ["goa"], "web_widget"),
        ("+919800000003", True, [], "import"), ("+919800000004", False, ["vip"], "import"),
    ]:
        db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=tid, phone=phone, opted_in=opted, tags=tags, source=source))
    db.commit()


def test_subscriber_stats_are_real_totals(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _subs(db, tid)
    db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=_other_tenant(db), phone="+919899999999", opted_in=True, tags=[]))
    db.commit()
    r = client.get("/api/v1/messaging/subscribers/stats", headers=_h(tenant_and_user))
    assert r.status_code == 200 and r.json() == {"total": 4, "opted_in": 3, "opted_out": 1}


def test_audience_count_matches_what_the_campaign_would_send(client, db, tenant_and_user):
    _subs(db, _tid(tenant_and_user))
    def count(af):
        r = client.post("/api/v1/messaging/campaigns/audience-count", json={"audience_filter": af}, headers=_h(tenant_and_user))
        assert r.status_code == 200, r.text
        return r.json()["count"]
    assert count({}) == 3                                       # opted-out person never counts
    assert count({"tags": ["VIP"]}) == 1                        # tags match any case; the opted-out vip is excluded
    assert count({"tags": ["vip", "goa"]}) == 2
    assert count({"source": ["import"]}) == 2
    assert count({"tags": ["vip"], "source": ["web_widget"]}) == 0


def test_stats_and_audience_count_forbidden_for_a_concierge(client, db, tenant_and_user):
    agent = _role_headers(db, _tid(tenant_and_user), UserRole.CONCIERGE)
    assert client.get("/api/v1/messaging/subscribers/stats", headers=agent).status_code == 403
    assert client.post("/api/v1/messaging/campaigns/audience-count", json={}, headers=agent).status_code == 403


def test_tag_list_counts_opted_in_people_only(client, db, tenant_and_user):
    _subs(db, _tid(tenant_and_user))
    r = client.get("/api/v1/messaging/subscribers/tags", headers=_h(tenant_and_user))
    assert r.status_code == 200
    assert r.json() == [{"tag": "goa", "count": 1}, {"tag": "vip", "count": 1}]      # the opted-out vip isn't counted


def test_tag_list_is_scoped_and_role_checked(client, db, tenant_and_user):
    db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=_other_tenant(db), phone="+919877777777", opted_in=True, tags=["secret"]))
    db.commit()
    assert client.get("/api/v1/messaging/subscribers/tags", headers=_h(tenant_and_user)).json() == []
    agent = _role_headers(db, _tid(tenant_and_user), UserRole.CONCIERGE)
    assert client.get("/api/v1/messaging/subscribers/tags", headers=agent).status_code == 403


# ─── CRM-leads audience ──────────────────────────────────────────────────────

def _lead_rows(db, tid):
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry, InquirySource
    now = datetime.now(timezone.utc)
    for name, phone, analysis in [
        ("Priya", "+919876500001", {"sentiment": "positive", "reply_urgency": "high"}),
        ("Arjun", "+919876500002", {"sentiment": "neutral"}),
        ("Instagram only", "", None),
    ]:
        g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name, phone=phone)
        db.add(g); db.flush()
        db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, source=InquirySource.META_IG,
                       ai_analysis=analysis, quoted_amount=5000 if name == "Priya" else None, created_at=now, updated_at=now))
    db.commit()


def test_audience_preview_reports_who_is_reached_and_who_is_left_out(client, db, tenant_and_user):
    _lead_rows(db, _tid(tenant_and_user))
    r = client.post("/api/v1/messaging/campaigns/audience-preview", json={"audience_filter": {}}, headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["matched"], b["will_receive"], b["no_phone"]) == (3, 2, 1)
    assert b["heat"]["hot"] + b["heat"]["warm"] + b["heat"]["cold"] == 2
    top = b["sample"][0]
    assert top["name"] == "Priya" and top["heat"] == "hot" and "••••" in top["phone"] and "9876500001" not in top["phone"]
    assert top["why"]


def test_audience_preview_applies_filters(client, db, tenant_and_user):
    _lead_rows(db, _tid(tenant_and_user))
    r = client.post("/api/v1/messaging/campaigns/audience-preview", json={"audience_filter": {"heat": ["hot"]}}, headers=_h(tenant_and_user))
    assert r.json()["will_receive"] == 1
    r = client.post("/api/v1/messaging/campaigns/audience-preview", json={"audience_filter": {"quoted_open": True}}, headers=_h(tenant_and_user))
    assert r.json()["will_receive"] == 1


def test_audience_options_lists_presets_and_counts(client, db, tenant_and_user):
    _lead_rows(db, _tid(tenant_and_user))
    r = client.get("/api/v1/messaging/campaigns/audience-options", headers=_h(tenant_and_user))
    assert r.status_code == 200
    body = r.json()
    assert body["totals"] == {"leads": 3, "with_phone": 2} and body["presets"] and body["sources"][0]["value"] == "meta_ig"


def test_audience_endpoints_forbidden_for_a_concierge_and_scoped(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _lead_rows(db, _other_tenant(db))
    agent = _role_headers(db, tid, UserRole.CONCIERGE)
    assert client.get("/api/v1/messaging/campaigns/audience-options", headers=agent).status_code == 403
    assert client.post("/api/v1/messaging/campaigns/audience-preview", json={}, headers=agent).status_code == 403
    r = client.post("/api/v1/messaging/campaigns/audience-preview", json={"audience_filter": {}}, headers=_h(tenant_and_user))
    assert r.json()["matched"] == 0                                     # another workspace's leads are invisible


def test_a_leads_campaign_needs_the_confirmation_and_records_it(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    t = _template(db, tid)
    body = lambda af: {"name": "Leads push", "template_id": t.id, "variable_map": {}, "audience_filter": af}
    r = client.post("/api/v1/messaging/campaigns", json=body({"type": "leads", "heat": ["hot"]}), headers=_h(tenant_and_user))
    assert r.status_code == 400 and "Confirm" in r.json()["detail"]
    r = client.post("/api/v1/messaging/campaigns", json=body({"type": "leads", "heat": ["hot"], "consent_confirmed": True, "junk": 1}), headers=_h(tenant_and_user))
    assert r.status_code == 201, r.text
    assert r.json()["audience_filter"] == {"type": "leads", "heat": ["hot"], "consent_confirmed": True}
    ev = db.query(AuditEvent).filter_by(tenant_id=tid, action="campaigns.leads_audience_confirmed").first()
    assert ev is not None and ev.target_id == r.json()["id"]


def test_changing_a_campaigns_audience_to_leads_also_needs_the_confirmation(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid, _template(db, tid).id, status=CampaignStatus.DRAFT)
    r = client.patch(f"/api/v1/messaging/campaigns/{c.id}", json={"audience_filter": {"type": "leads"}}, headers=_h(tenant_and_user))
    assert r.status_code == 400
    r = client.patch(f"/api/v1/messaging/campaigns/{c.id}", json={"audience_filter": {"type": "leads", "consent_confirmed": True}}, headers=_h(tenant_and_user))
    assert r.status_code == 200


def test_subscriber_audiences_are_unchanged(client, db, tenant_and_user):
    t = _template(db, _tid(tenant_and_user))
    r = client.post("/api/v1/messaging/campaigns", json={"name": "Old style", "template_id": t.id, "variable_map": {},
                                                          "audience_filter": {"tags": ["vip"]}}, headers=_h(tenant_and_user))
    assert r.status_code == 201 and r.json()["audience_filter"] == {"tags": ["vip"]}


# ─── replies and counter consistency ─────────────────────────────────────────

def _guest_with_chat(db, tid, phone, *, replied_after=None):
    """A guest with a WhatsApp conversation; `replied_after` = a datetime for one inbound message (None = they never wrote)."""
    from app.models.conversation import ChannelType, Conversation, Message
    from app.models.guest import Guest
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone=phone)
    db.add(g); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.flush()
    if replied_after is not None:
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction="inbound", channel="whatsapp",
                       body="Yes please", created_at=replied_after))
    db.commit()


def test_report_shows_who_replied_within_a_week_and_filters_and_exports_it(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid, _template(db, tid).id)
    sent = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    spec = [("+919800000011", "read", 1), ("+919800000012", "delivered", 3), ("+919800000013", "delivered", 12),
            ("+919800000014", "delivered", None), ("+919800000015", "failed", None)]
    for phone, status, reply_days in spec:
        db.add(Recipient(id=str(uuid.uuid4()), tenant_id=tid, campaign_id=c.id, phone=phone, name=phone[-2:], status=status,
                         sent_at=None if status == "failed" else sent, wa_message_id=f"w{phone[-2:]}"))
        _guest_with_chat(db, tid, phone, replied_after=(sent + timedelta(days=reply_days)) if reply_days is not None else None)
    # a reply BEFORE the campaign message is not a reply to it
    before = "+919800000016"
    db.add(Recipient(id=str(uuid.uuid4()), tenant_id=tid, campaign_id=c.id, phone=before, name="early", status="read", sent_at=sent, wa_message_id="w16"))
    _guest_with_chat(db, tid, before, replied_after=sent - timedelta(days=1))
    db.commit()

    r = client.get(f"/api/v1/messaging/campaigns/{c.id}/report", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["replied"] == 2                                              # day 1 and day 3 only: day 12 is too late, "before" does not count
    assert body["summary"]["reply_rate"] == round(2 / body["summary"]["sent"] * 100, 1)
    by = {x["phone"]: x for x in body["recipients"]}
    assert by["+919800000011"]["replied"] is True and by["+919800000013"]["replied"] is False and by["+919800000016"]["replied"] is False

    only = client.get(f"/api/v1/messaging/campaigns/{c.id}/report", params={"status": "replied"}, headers=_h(tenant_and_user)).json()
    assert {x["phone"] for x in only["recipients"]} == {"+919800000011", "+919800000012"} and only["total_matching"] == 2

    csv_text = client.get(f"/api/v1/messaging/campaigns/{c.id}/recipients.csv", params={"status": "replied"}, headers=_h(tenant_and_user)).content.decode("utf-8-sig")
    assert csv_text.splitlines()[0].endswith("Replied,Replied at") and csv_text.count("yes") == 2


def test_replies_never_leak_across_tenants(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    other = _other_tenant(db)
    c = _campaign(db, tid, _template(db, tid).id)
    sent = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    db.add(Recipient(id=str(uuid.uuid4()), tenant_id=tid, campaign_id=c.id, phone="+919800000021", name="A", status="read", sent_at=sent, wa_message_id="w21"))
    db.commit()
    _guest_with_chat(db, other, "+919800000021", replied_after=sent + timedelta(hours=2))      # same number, ANOTHER workspace's guest
    r = client.get(f"/api/v1/messaging/campaigns/{c.id}/report", headers=_h(tenant_and_user)).json()
    assert r["summary"]["replied"] == 0


def test_stored_campaign_counters_match_the_recipient_rows(db, tenant_and_user):
    """accepted (sent) >= delivered >= read, failed apart, and the counters on the campaign equal what the rows say."""
    from app.services import wa_campaign_delivery as d
    tid = _tid(tenant_and_user)
    c = _campaign(db, tid, _template(db, tid).id)
    for i, st in enumerate(["queued", "sent", "sent", "delivered", "delivered", "delivered", "read", "read", "failed"]):
        db.add(Recipient(id=str(uuid.uuid4()), tenant_id=tid, campaign_id=c.id, phone=f"+91980000003{i}", status=st))
    db.commit()
    d.refresh_campaign_counters(db, tid, c.id)
    db.flush()
    counts = d.cumulative(d.status_counts(db, c.id))
    assert counts == {"total": 9, "sent": 7, "delivered": 5, "read": 2, "failed": 1, "queued": 1}
    assert (c.sent_count, c.delivered_count, c.read_count, c.failed_count) == ("7", "5", "2", "1")
    assert counts["sent"] >= counts["delivered"] >= counts["read"]
