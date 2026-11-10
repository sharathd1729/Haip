"""Meta lead-form leads: each submission becomes a lead once, through identity_service, with the ad it came from."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session as SASession

from app.adapters.marketing import meta_ads
from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.meta_form_lead import MetaFormLead
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import lead_paid, work_queue_service
from app.services import meta_business_service as biz
from app.services import meta_lead_forms_service as svc

TOKEN = "EAAWtesttoken" + "x" * 40
PERMS = ["ads_read", "leads_retrieval", "pages_manage_ads", "pages_read_engagement", "pages_show_list"]
URL = "/api/v1/meta-business/lead-forms"
PHONE = "+917349012876"


def _ago(**kw):
    """A Meta created_time that long ago (never a fixed date: the work queue only shows the last 14 days)."""
    return (datetime.now(UTC) - timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def lead(lead_id="L1", phone=PHONE, email="asha@example.com", platform="ig", ad="ad9", extra=True):
    fields = [{"name": "full_name", "values": ["Asha Rao"]}]
    if phone:
        fields.append({"name": "phone_number", "values": [phone]})
    if email:
        fields.append({"name": "email", "values": [email]})
    if extra:
        fields.append({"name": "travel_dates", "values": ["20-22 Dec"]})
    return {
        "id": lead_id,
        "created_time": _ago(hours=1),
        "ad_id": ad,
        "adset_id": "as9",
        "campaign_id": "c9" if ad else None,
        "form_id": "f1",
        "platform": platform,
        "field_data": fields,
    }


class Graph:
    """A fake graph.facebook.com: one page, a live form and an archived one."""

    def __init__(self, leads=None, permissions=PERMS):
        self.leads, self.permissions, self.calls = leads if leads is not None else [lead()], permissions, []

    def __call__(self, url, params=None):
        self.calls.append(url)
        params = params or {}
        if url.endswith("/me"):
            return {"id": "1", "name": "lead crm"}
        if url.endswith("/me/permissions"):
            return {"data": [{"permission": p, "status": "granted"} for p in self.permissions]}
        if url.endswith("/me/adaccounts"):
            return {"data": [{"id": "act_42", "name": "Jade Ads", "currency": "INR", "account_status": 1}]}
        if url.endswith("/me/accounts"):
            return {"data": [{"id": "147", "name": "Jade Page", "access_token": "PAGE-TOKEN"}]}
        assert params.get("access_token") == "PAGE-TOKEN", "forms and leads are read with the page's own token"
        if url.endswith("/147/leadgen_forms"):
            return {
                "data": [
                    {"id": "f1", "name": "Villa enquiry", "status": "ACTIVE"},
                    {"id": "f2", "name": "Old", "status": "ARCHIVED"},
                ]
            }
        if url.endswith("/f1/leads"):
            return {"data": self.leads}
        if url.endswith("/f2/leads"):
            return {"data": [lead("OLD1", phone="+917349012999", email="")]}
        raise AssertionError(url)


@pytest.fixture
def graph(monkeypatch):
    g = Graph()
    monkeypatch.setattr(meta_ads, "_get", g)
    monkeypatch.setattr(biz.meta_token_expiry, "fetch_expiry", lambda token: None)
    return g


def _workspace(db, role=UserRole.OWNER):
    t = Tenant(id=str(uuid.uuid4()), name="W", slug=f"w-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    u = User(
        id=str(uuid.uuid4()),
        tenant_id=t.id,
        name="U",
        email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("x" * 12),
        role=role,
        is_active=True,
    )
    db.add(u)
    db.commit()
    return {
        "tenant": t,
        "user": u,
        "access_token": create_access_token({"sub": u.id, "tenant_id": t.id, "role": u.role.value}),
    }


def _h(w):
    return {"Authorization": f"Bearer {w['access_token']}"}


def _on(db, tenant_id):
    biz.connect(db, tenant_id, TOKEN)
    svc.set_enabled(db, tenant_id, True)
    db.commit()


def test_parse_fields_reads_names_contacts_and_other_answers():
    name, phone, email, answers = svc.parse_fields(
        [
            {"name": "first_name", "values": ["Asha"]},
            {"name": "last_name", "values": ["Rao"]},
            {"name": "phone_number", "values": [PHONE]},
            {"name": "work_email", "values": ["a@b.co"]},
            {"name": "how_many_guests?", "values": ["6", "8"]},
            {"name": "empty", "values": [""]},
        ]
    )
    assert (name, phone, email) == ("Asha Rao", PHONE, "a@b.co") and answers == {"How many guests?": "6, 8"}
    assert svc.parse_fields(None) == ("", "", "", {})


def test_a_submission_becomes_one_lead_with_its_ad(db, tenant_and_user, graph):
    tenant = tenant_and_user["tenant"]
    _on(db, tenant.id)
    assert svc.sync(db, tenant.id) == {"created": 1, "attached": 0, "no_contact": 0, "duplicate": 0, "failed": 0}
    rec = db.query(MetaFormLead).filter_by(tenant_id=tenant.id).one()  # the archived form is not read
    assert (rec.leadgen_id, rec.ad_id, rec.campaign_id, rec.form_name, rec.status) == (
        "L1",
        "ad9",
        "c9",
        "Villa enquiry",
        "created",
    )
    inq = db.query(Inquiry).filter_by(id=rec.inquiry_id).one()
    guest = db.query(Guest).filter_by(id=rec.guest_id).one()
    assert inq.source == InquirySource.META_IG and guest.name == "Asha Rao" and guest.lead_identified_at is not None
    assert inq.custom_fields["lead_form"]["answers"] == {"Travel dates": "20-22 Dec"}
    assert inq.special_requests == 'Meta lead form "Villa enquiry": Travel dates: 20-22 Dec'
    ev = db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="meta_lead_form.lead_imported").one()
    assert PHONE not in str(ev.payload) and "Asha" not in str(ev.payload)

    assert svc.sync(db, tenant.id)["duplicate"] == 1  # the overlap re-reads it; nothing new
    assert db.query(Inquiry).filter_by(tenant_id=tenant.id).count() == 1
    assert lead_paid.classify(db, tenant.id, [inq]) == {inq.id: "paid"}
    assert (
        db.query(Inquiry.id).filter(Inquiry.tenant_id == tenant.id, lead_paid.filter_sql(db, tenant.id, "paid")).count()
        == 1
    )
    queue = work_queue_service.build(db, tenant, None)
    assert [i["kind"] for i in queue["items"] if i.get("guest_id") == guest.id] == ["new_lead"]
    st = biz.status(db, tenant.id)["lead_forms"]
    assert (
        st["enabled"]
        and st["imported"] == 1
        and [f["id"] for f in st["forms"]] == ["f1", "f2"]
        and st["last_error"] is None
    )


def test_a_known_person_with_an_open_lead_gets_no_second_lead(db, tenant_and_user, graph):
    tenant = tenant_and_user["tenant"]
    _on(db, tenant.id)
    svc.sync(db, tenant.id)
    graph.leads = [lead("L2", email="", platform="fb")]  # same phone, another form submission
    assert svc.sync(db, tenant.id)["attached"] == 1
    assert (
        db.query(Inquiry).filter_by(tenant_id=tenant.id).count() == 1
        and db.query(Guest).filter_by(tenant_id=tenant.id).count() == 1
    )
    assert db.query(MetaFormLead).filter_by(tenant_id=tenant.id).count() == 2


def test_no_phone_or_email_is_recorded_but_makes_no_lead(db, tenant_and_user, graph):
    tenant = tenant_and_user["tenant"]
    _on(db, tenant.id)
    graph.leads = [lead("L3", phone="", email=""), lead("L4", phone="", email="only@mail.test", ad=None)]
    assert svc.sync(db, tenant.id) == {"created": 1, "attached": 0, "no_contact": 1, "duplicate": 0, "failed": 0}
    by_email = db.query(MetaFormLead).filter_by(tenant_id=tenant.id, leadgen_id="L4").one()
    inq = db.query(Inquiry).filter_by(id=by_email.inquiry_id).one()
    assert inq.source == InquirySource.META_IG
    assert lead_paid.classify(db, tenant.id, [inq]) == {inq.id: "organic"}  # no ad on the submission
    assert db.query(MetaFormLead).filter_by(tenant_id=tenant.id, leadgen_id="L3").one().inquiry_id is None


def test_import_reads_every_form_and_switch_rules(db, tenant_and_user, graph, monkeypatch):
    tenant = tenant_and_user["tenant"]
    with pytest.raises(svc.NotEnabled):
        svc.set_enabled(db, tenant.id, True)  # nothing connected
    biz.connect(db, tenant.id, TOKEN)
    with pytest.raises(svc.NotEnabled):
        svc.sync(db, tenant.id)  # connected but switched off
    svc.set_enabled(db, tenant.id, True)
    db.commit()
    assert svc.sync(db, tenant.id, since_days=90)["created"] == 2  # the archived form's lead too
    monkeypatch.setattr(meta_ads, "_get", Graph(permissions=["ads_read"]))
    biz.recheck(db, tenant.id)
    svc.set_enabled(db, tenant.id, False)
    with pytest.raises(svc.NotEnabled, match="leads_retrieval"):
        svc.set_enabled(db, tenant.id, True)


def test_a_meta_failure_is_shown_and_the_cursor_stays(db, tenant_and_user, graph, monkeypatch):
    tenant = tenant_and_user["tenant"]
    _on(db, tenant.id)
    since = biz.get_row(db, tenant.id).config["lead_forms"]["since"]

    def down(url, params=None):
        raise meta_ads.MetaAdsError("(#4) Application request limit reached", status=400, code=4)

    monkeypatch.setattr(meta_ads, "_get", down)
    with pytest.raises(meta_ads.MetaAdsError):
        svc.sync(db, tenant.id)
    block = biz.get_row(db, tenant.id).config["lead_forms"]
    assert "limit reached" in block["last_error"] and block["since"] == since


def test_workspaces_do_not_share_leads(db, tenant_and_user, graph):
    a, b = tenant_and_user["tenant"], _workspace(db)["tenant"]
    _on(db, a.id)
    _on(db, b.id)
    svc.sync(db, a.id)
    assert (
        db.query(MetaFormLead).filter_by(tenant_id=b.id).count() == 0
        and db.query(Inquiry).filter_by(tenant_id=b.id).count() == 0
    )
    assert svc.sync(db, b.id)["created"] == 1  # the same Meta lead id is its own lead there
    assert (
        db.query(Guest).filter_by(tenant_id=a.id).count() == 1
        and db.query(Guest).filter_by(tenant_id=b.id).count() == 1
    )


def test_endpoints_switch_import_roles_and_other_workspace(client, db, tenant_and_user, graph, monkeypatch):
    from app.workers.tasks import sync_meta_lead_forms as tasks

    queued = []
    monkeypatch.setattr(tasks.sync_tenant, "apply_async", lambda **kw: queued.append(kw))
    assert client.put(URL, json={"enabled": True}, headers=_h(tenant_and_user)).status_code == 400  # not connected yet
    client.put("/api/v1/meta-business/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    assert client.post(f"{URL}/import", json={"days": 30}, headers=_h(tenant_and_user)).status_code == 400  # still off
    on = client.put(URL, json={"enabled": True}, headers=_h(tenant_and_user))
    assert on.status_code == 200 and on.json()["lead_forms"]["enabled"] is True
    r = client.post(f"{URL}/import", json={"days": 30}, headers=_h(tenant_and_user))
    assert r.status_code == 202 and queued == [
        {"kwargs": {"tenant_id": tenant_and_user["tenant"].id, "since_days": 30}, "queue": "whatsapp"}
    ]
    assert client.post(f"{URL}/import", json={"days": 400}, headers=_h(tenant_and_user)).status_code == 422
    foh = _workspace(db, role=UserRole.FOH)
    assert client.put(URL, json={"enabled": True}, headers=_h(foh)).status_code == 403
    assert client.post(f"{URL}/import", json={}, headers=_h(foh)).status_code == 403
    stranger = _workspace(db)
    assert client.put(URL, json={"enabled": False}, headers=_h(stranger)).status_code == 400
    assert client.get("/api/v1/meta-business", headers=_h(stranger)).json()["lead_forms"]["enabled"] is False
    assert (
        db.query(AuditEvent)
        .filter_by(tenant_id=tenant_and_user["tenant"].id, action="meta_business.lead_forms_on")
        .count()
        == 1
    )


def test_beat_task_queues_only_workspaces_with_lead_forms_on(db, tenant_and_user, graph, monkeypatch):
    from app.workers.tasks import sync_meta_lead_forms as tasks

    on, off = tenant_and_user["tenant"], _workspace(db)["tenant"]
    _on(db, on.id)
    biz.connect(db, off.id, TOKEN)
    db.commit()
    queued = []
    monkeypatch.setattr(tasks, "SessionLocal", lambda: SASession(bind=db.connection()))
    monkeypatch.setattr(tasks.sync_tenant, "apply_async", lambda **kw: queued.append(kw["kwargs"]["tenant_id"]))
    assert tasks.sync_all_tenants.run() == {"queued": 1} and queued == [on.id]
    assert tasks.sync_tenant.run(tenant_id=off.id)["status"] == "skipped"
    assert tasks.sync_tenant.run(tenant_id=on.id)["created"] == 1


def test_a_lead_is_dated_when_the_form_was_filled_not_when_haip_read_it(db, tenant_and_user, graph):
    tenant = tenant_and_user["tenant"]
    _on(db, tenant.id)
    known, _ = svc_identity().resolve_gid(db, tenant.id, signal_type="phone", value="+917349012878", source="whatsapp")
    db.commit()
    known_since = db.query(Guest).filter_by(id=known).one().lead_identified_at
    old, fresh, again = lead("OLD"), lead("NEW", phone="+917349012877", email=""), lead("KNOWN", phone="+917349012878", email="")
    old["created_time"], fresh["created_time"], again["created_time"] = _ago(days=40), _ago(minutes=20), _ago(days=30)
    graph.leads = [old, fresh, again]
    assert svc.sync(db, tenant.id)["created"] == 3

    def of(leadgen_id):
        rec = db.query(MetaFormLead).filter_by(tenant_id=tenant.id, leadgen_id=leadgen_id).one()
        return db.query(Guest).filter_by(id=rec.guest_id).one(), db.query(Inquiry).filter_by(id=rec.inquiry_id).one(), rec

    g_old, i_old, r_old = of("OLD")
    assert abs(_utc(g_old.lead_identified_at) - _utc(r_old.lead_created_at)) < timedelta(seconds=2)
    assert abs(_utc(i_old.created_at) - _utc(r_old.lead_created_at)) < timedelta(seconds=2)
    assert timedelta(days=39) < datetime.now(UTC) - _utc(g_old.first_touch_at) < timedelta(days=41)
    g_known, i_known, r_known = of("KNOWN")  # a person HAIP already knew keeps their first dates; the new lead gets the form's
    assert g_known.id == known and g_known.lead_identified_at == known_since
    assert abs(_utc(i_known.created_at) - _utc(r_known.lead_created_at)) < timedelta(seconds=2)

    items = {i["guest_id"]: i for i in work_queue_service.build(db, tenant, None)["items"] if i["kind"] == "new_lead"}
    g_new = of("NEW")[0]
    assert g_old.id not in items  # 40 days old: not a "new lead" in My day
    assert items[g_new.id]["detail"] == "Filled a lead form: Villa enquiry"  # not "Shared their number": there is no chat
    assert timedelta(minutes=19) < datetime.now(UTC) - datetime.fromisoformat(items[g_new.id]["since"]) < timedelta(minutes=22)


def svc_identity():
    from app.services import identity_service

    return identity_service


def test_repair_script_puts_imported_leads_back_on_the_form_time(db, tenant_and_user, graph, capsys):
    from scripts.repair_form_lead_times import repair

    tenant = tenant_and_user["tenant"]
    _on(db, tenant.id)
    old = lead("OLD")
    old["created_time"] = _ago(days=40)
    graph.leads = [old, lead("NEW", phone="+917349012877", email="")]
    svc.sync(db, tenant.id)
    recs = {r.leadgen_id: r for r in db.query(MetaFormLead).filter_by(tenant_id=tenant.id).all()}
    for rec in recs.values():  # what the first version of the import wrote: everything stamped with the import time
        db.query(Guest).filter_by(id=rec.guest_id).update({"lead_identified_at": rec.created_at, "first_touch_at": rec.created_at})
        db.query(Inquiry).filter_by(id=rec.inquiry_id).update({"created_at": rec.created_at})
    db.commit()
    other = _workspace(db)

    assert repair(db, tenant.id, apply=False) == {"form_leads": 2, "leads_redated": 2, "people_redated": 2}
    db.expire_all()
    guest = db.query(Guest).filter_by(id=recs["OLD"].guest_id).one()
    assert datetime.now(UTC) - _utc(guest.lead_identified_at) < timedelta(minutes=5)  # dry run changed nothing
    assert repair(db, other["tenant"].id, apply=True) == {"form_leads": 0, "leads_redated": 0, "people_redated": 0}
    assert repair(db, tenant.id, apply=True)["people_redated"] == 2
    db.commit()
    db.expire_all()
    guest = db.query(Guest).filter_by(id=recs["OLD"].guest_id).one()
    inquiry = db.query(Inquiry).filter_by(id=recs["OLD"].inquiry_id).one()
    assert timedelta(days=39) < datetime.now(UTC) - _utc(guest.lead_identified_at) < timedelta(days=41)
    assert timedelta(days=39) < datetime.now(UTC) - _utc(inquiry.created_at) < timedelta(days=41)
    assert repair(db, tenant.id, apply=True) == {"form_leads": 2, "leads_redated": 0, "people_redated": 0}  # safe to re-run
    assert db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="meta_lead_form.times_repaired").count() == 1
    assert PHONE not in capsys.readouterr().out
