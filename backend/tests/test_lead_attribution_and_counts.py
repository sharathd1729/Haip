"""Product-review fixes: stage counts that match the list, stage ids that survive the taxonomy change, source/agent attribution that
survives a booking, and "Organic calls" as a real source.

Nothing here invents a source or an agent: a missing one stays missing and is labelled "Not recorded" / left unattributed.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import dashboard_service, inquiry_service, leads_service
from app.services.inquiry_service import get_or_create_from_call


def tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"la-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def stage(db, tid, key, order, **kw):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key=key, label=key.title(), order=order, **kw)
    db.add(s)
    db.flush()
    return s


def taxonomy(db, tid):
    """The current (post-migration-049) taxonomy: no legacy 'new' / 'responding' / 'closed' keys."""
    return {
        "general": stage(db, tid, "general_enquiry", 0, category="invalid", is_default_entry=True),
        "active": stage(db, tid, "active", 1, category="valid", is_valid_lead_entry=True),
        "unsuitable": stage(db, tid, "unsuitable", 2, category="valid"),
        "lost": stage(db, tid, "lost", 3, category="valid", is_closed_lost=True),
        "sold": stage(db, tid, "sold", 4, category="valid", is_closed_won=True),
    }


def guest(db, tid, name="Guest"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name, phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    return g


def lead(db, tid, st, g=None, source=InquirySource.META_IG, assigned_to=None, created=None, **kw):
    g = g or guest(db, tid)
    q = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage=InquiryStage.NEW, stage_id=st.id, source=source,
                assigned_to=assigned_to, **kw)
    if created:
        q.created_at = created
    db.add(q)
    db.flush()
    return q


# ─── stage ids survive the taxonomy change ────────────────────────────────────────────────────────────────

def test_legacy_stages_resolve_to_the_tenants_own_stages_by_meaning(db):
    t = tenant(db)
    s = taxonomy(db, t.id)
    f = lambda e: inquiry_service._stage_id_for(db, t.id, e)
    assert f(InquiryStage.NEW) == s["active"].id and f(InquiryStage.RESPONDING) == s["active"].id and f(InquiryStage.QUOTED) == s["active"].id
    assert f(InquiryStage.BOOKED) == s["sold"].id
    assert f(InquiryStage.LOST) == s["lost"].id and f(InquiryStage.GHOSTED) == s["lost"].id


def test_without_a_valid_entry_stage_new_falls_back_to_the_default_entry_and_never_to_nothing_for_a_won_or_lost_lead(db):
    t = tenant(db)
    general = stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    assert inquiry_service._stage_id_for(db, t.id, InquiryStage.NEW) == general.id
    assert inquiry_service._stage_id_for(db, t.id, InquiryStage.LOST) is None          # no lost stage configured: nothing is invented


def test_a_workspace_still_on_the_old_keys_keeps_working(db):
    t = tenant(db)
    new = stage(db, t.id, "new", 0)
    stage(db, t.id, "active", 1, category="valid", is_valid_lead_entry=True)
    assert inquiry_service._stage_id_for(db, t.id, InquiryStage.NEW) == new.id          # the legacy key wins where it exists


def test_moving_a_lead_to_lost_or_sold_closes_the_legacy_stage_too_so_it_is_not_reused_as_open(db):
    t = tenant(db)
    s = taxonomy(db, t.id)
    owner = User(id=str(uuid.uuid4()), tenant_id=t.id, name="O", email=f"o-{uuid.uuid4().hex[:6]}@t.com", hashed_password="x", role=UserRole.OWNER, is_active=True)
    db.add(owner)
    q = lead(db, t.id, s["active"])
    inquiry_service.update_stage_by_id(db, tenant_id=t.id, inquiry_id=q.id, new_stage_id=s["lost"].id, actor_user_id=owner.id, actor_role="owner", reason="no reply")
    assert q.stage == InquiryStage.LOST and q.stage_id == s["lost"].id
    # a new message from the same guest must open a NEW lead, not resurrect the lost one
    again = inquiry_service.get_or_create(db, t.id, q.guest_id)
    assert again.id != q.id
    won = lead(db, t.id, s["active"])
    inquiry_service.update_stage_by_id(db, tenant_id=t.id, inquiry_id=won.id, new_stage_id=s["sold"].id, actor_user_id=owner.id, actor_role="owner", reason="paid")
    assert won.stage == InquiryStage.BOOKED


def test_inquiries_created_by_calls_land_on_the_board(db):
    t = tenant(db)
    s = taxonomy(db, t.id)
    stage(db, t.id, "rnr", 9, category="invalid")
    q = get_or_create_from_call(db, t.id, guest(db, t.id).id, direction="inbound", answered=True)
    assert q.stage_id == s["active"].id and q.source == InquirySource.ORGANIC_CALL
    out = get_or_create_from_call(db, t.id, guest(db, t.id).id, direction="outbound", answered=True)
    assert out.source == InquirySource.OUTBOUND_CALL                                    # only an inbound call is an organic call


# ─── the stage chips count what the list shows ───────────────────────────────────────────────────────────────

def test_stage_counts_follow_the_same_filters_as_the_list(db):
    t = tenant(db)
    s = taxonomy(db, t.id)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=40)
    for _ in range(3):
        lead(db, t.id, s["active"], created=now)
    for _ in range(5):
        lead(db, t.id, s["active"], created=old)
    lead(db, t.id, s["lost"], created=old)
    lead(db, t.id, s["unsuitable"], created=now, occasion="Anniversary")
    db.flush()

    since = (now - timedelta(days=7)).isoformat()
    res = leads_service.get_leads_pipeline(db, t.id, stage="active", date_from=since, page_size=50)
    assert res.total == 3
    assert res.stages["active"].count == 3                                              # was 8: the date range was ignored
    assert "lost" not in res.stages                                                     # nothing lost in the window

    by_occasion = leads_service.get_leads_pipeline(db, t.id, occasion="anniv", page_size=50)
    assert by_occasion.total == 1 and by_occasion.stages["unsuitable"].count == 1 and "active" not in by_occasion.stages

    everything = leads_service.get_leads_pipeline(db, t.id, page_size=50)
    assert everything.stages["active"].count == 8 and everything.stages["lost"].count == 1 and everything.stages["unsuitable"].count == 1


def test_stage_counts_respect_an_agents_own_scope(db):
    t = tenant(db)
    s = taxonomy(db, t.id)
    mk = lambda: User(id=str(uuid.uuid4()), tenant_id=t.id, name="u", email=f"u-{uuid.uuid4().hex[:8]}@t.com", hashed_password="x", role=UserRole.CONCIERGE, is_active=True)
    me, other = mk(), mk()
    db.add_all([me, other])
    db.flush()
    for uid in (me.id, me.id, other.id, None):
        lead(db, t.id, s["active"], assigned_to=uid)
    res = leads_service.get_leads_pipeline(db, t.id, scope_user_id=me.id, page_size=50)
    assert res.total == 3 and res.stages["active"].count == 3                           # mine + unclaimed, never a peer's


# ─── sources: nothing silently becomes "Other" ───────────────────────────────────────────────────────────

def test_every_inquiry_source_has_a_named_group_and_organic_calls_are_their_own():
    unmapped = [s.value for s in InquirySource if s.value not in dashboard_service._SOURCE_GROUPS]
    assert unmapped == [], f"these would be reported as 'Other': {unmapped}"
    g = dashboard_service._SOURCE_GROUPS
    assert g["organic_call"] == ("organic_call", "Organic calls")
    assert g["inbound_call"][1] == "Phone calls" and g["phone"][1] == "Phone calls"      # earlier call leads are not re-labelled
    assert g["email"][0] == "email" and g["walk_in"][0] == "walk_in" and g["ota_airbnb"][0] == "ota" and g["channel_manager"][0] == "ota"
    assert dashboard_service.UNKNOWN_SOURCE == ("other", "Not recorded")


def test_lead_sources_report_shows_organic_calls_and_not_recorded_separately(db):
    t = tenant(db)
    s = taxonomy(db, t.id)
    for src in (InquirySource.ORGANIC_CALL, InquirySource.ORGANIC_CALL, InquirySource.PHONE, InquirySource.EMAIL, None):
        lead(db, t.id, s["active"], source=src)
    rows = {r["key"]: r for r in dashboard_service.lead_sources(db, t.id, None, "2000-01-01", "2100-01-01")}
    assert rows["organic_call"]["count"] == 2 and rows["organic_call"]["label"] == "Organic calls"
    assert rows["call"]["count"] == 1 and rows["email"]["count"] == 1
    assert rows["other"]["label"] == "Not recorded" and rows["other"]["count"] == 1


# ─── a booking keeps its lead's source and agent ───────────────────────────────────────────────────────────

@pytest.fixture()
def world(db, tenant_and_user):
    t = tenant_and_user["tenant"]
    tid = t["id"] if isinstance(t, dict) else t.id
    s = taxonomy(db, tid)
    prop = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Caravan A", slug="caravan-a", type="caravan", max_adults=4, max_children=0)
    manager = User(id=str(uuid.uuid4()), tenant_id=tid, name="Mgr", email=f"m-{uuid.uuid4().hex[:6]}@t.com", hashed_password="x", role=UserRole.MANAGER, is_active=True)
    db.add_all([prop, manager])
    db.commit()
    w = type("W", (), {"tid": tid, "token": tenant_and_user["access_token"], "mgr": manager})()
    return w, s, prop


def book(client, w, prop, g, **extra):
    body = {"guest_id": g.id, "property_id": prop.id, "check_in": (date.today() + timedelta(days=20)).isoformat(),
            "check_out": (date.today() + timedelta(days=22)).isoformat(), "adults": 2, "total_amount": 40000, **extra}
    return client.post("/api/v1/bookings", json=body, headers={"Authorization": f"Bearer {w.token}"})


def test_a_manual_booking_is_tied_to_the_guests_open_lead_and_keeps_its_source_and_agent(db, client, world):
    w, s, prop = world
    g = guest(db, w.tid)
    q = lead(db, w.tid, s["active"], g=g, source=InquirySource.META_IG, assigned_to=w.mgr.id)
    db.commit()
    r = book(client, w, prop, g)
    assert r.status_code == 201, r.text
    stay = db.query(Stay).filter_by(tenant_id=w.tid).one()
    db.refresh(q)
    assert stay.inquiry_id == q.id and q.stage_id == s["sold"].id
    assert q.source == InquirySource.META_IG and q.assigned_to == w.mgr.id             # unchanged: attribution is read from the lead


def test_an_explicit_lead_is_used_and_must_belong_to_the_guest_and_not_be_booked_twice(db, client, world):
    w, s, prop = world
    g, other = guest(db, w.tid), guest(db, w.tid)
    q = lead(db, w.tid, s["active"], g=g, assigned_to=w.mgr.id)
    stranger = lead(db, w.tid, s["active"], g=other)
    db.commit()
    assert book(client, w, prop, g, inquiry_id=stranger.id).status_code == 422
    ok = book(client, w, prop, g, inquiry_id=q.id)
    assert ok.status_code == 201, ok.text
    assert db.query(Stay).filter_by(tenant_id=w.tid).one().inquiry_id == q.id
    assert book(client, w, prop, g, inquiry_id=q.id).status_code == 409


def test_a_guest_with_two_open_leads_is_not_guessed_and_a_guest_with_none_stays_unattributed(db, client, world):
    w, s, prop = world
    g = guest(db, w.tid)
    lead(db, w.tid, s["active"], g=g, source=InquirySource.META_IG)
    lead(db, w.tid, s["active"], g=g, source=InquirySource.WA_DIRECT)
    db.commit()
    assert book(client, w, prop, g).status_code == 201
    assert db.query(Stay).filter_by(tenant_id=w.tid).one().inquiry_id is None          # ambiguous: nobody guesses
    walkin = guest(db, w.tid)
    db.commit()
    assert book(client, w, prop, walkin, check_in=(date.today() + timedelta(days=40)).isoformat(), check_out=(date.today() + timedelta(days=41)).isoformat()).status_code == 201
    assert db.query(Stay).filter_by(tenant_id=w.tid, guest_id=walkin.id).one().inquiry_id is None


def test_the_booking_resolves_to_its_leads_source_and_agent_in_the_report_join(db, client, world):
    w, s, prop = world
    g = guest(db, w.tid)
    lead(db, w.tid, s["active"], g=g, source=InquirySource.ORGANIC_CALL, assigned_to=w.mgr.id)
    db.commit()
    assert book(client, w, prop, g).status_code == 201
    row = (db.query(Inquiry.source, Inquiry.assigned_to).join(Stay, Stay.inquiry_id == Inquiry.id).filter(Stay.tenant_id == w.tid).one())
    assert row[0] == InquirySource.ORGANIC_CALL and row[1] == w.mgr.id                  # what the source and agent reports group on
