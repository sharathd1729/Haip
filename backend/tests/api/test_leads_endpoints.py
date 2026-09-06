"""
Tests for leads API endpoints — T26 through T33

Tests:
  T26: GET /leads — happy path, returns list + stages
  T27: GET /leads — cross-tenant returns empty list (not 403)
  T28: GET /leads/{id} — cross-tenant returns 404
  T29: POST /leads/{id}/signals — forbidden for concierge role
  T30: POST /leads/{id}/signals — phone signal writes Consent row
  T31: POST /leads/{id}/refresh-summary — allowed for all roles
  T32: POST /leads/{id}/merge — forbidden for reservations role
  T33: GET /leads — lead with no phone renders without errors
"""

import uuid
import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.guest_identity import GuestIdentity
from app.models.consent import Consent
from app.core.security import create_access_token, get_password_hash


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id, role=UserRole.OWNER):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        name="Test User", email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.flush(); return u


def _token(user):
    return create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})


def _make_guest(db, tenant_id, name="Guest", phone=""):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone=phone)
    db.add(g); db.flush(); return g


def _make_inquiry(db, tenant_id, guest_id, stage=InquiryStage.NEW, source=InquirySource.META_IG):
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        guest_id=guest_id, stage=stage, source=source,
    )
    db.add(inq); db.flush(); return inq


def _add_signal(db, tenant_id, guest_id, identity_type, value, confidence=0.70):
    from app.models.base import gen_uuid
    sig = GuestIdentity(
        id=gen_uuid(), tenant_id=tenant_id, guest_id=guest_id,
        identity_type=identity_type, identity_value=value,
        source="test", confidence=confidence,
    )
    db.add(sig); db.flush(); return sig


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── T26: GET /leads happy path ────────────────────────────────────────────────

def test_get_leads_happy_path(client, db):
    """Authenticated GET /leads returns 200 with leads list and stages summary."""
    tenant = _make_tenant(db, "HappyTenant")
    user = _make_user(db, tenant.id, UserRole.OWNER)
    guest = _make_guest(db, tenant.id)
    _make_inquiry(db, tenant.id, guest.id)
    db.commit()

    resp = client.get("/api/v1/leads", headers=_auth(_token(user)))
    assert resp.status_code == 200
    data = resp.json()
    assert "leads" in data
    assert "stages" in data
    assert data["total"] >= 1


# ── T27: cross-tenant GET /leads returns empty ────────────────────────────────

def test_get_leads_cross_tenant_returns_empty(client, db):
    """User from Tenant B cannot see Tenant A's leads — gets empty list, not 403."""
    tenant_a = _make_tenant(db, "CrossA")
    tenant_b = _make_tenant(db, "CrossB")
    guest_a = _make_guest(db, tenant_a.id)
    _make_inquiry(db, tenant_a.id, guest_a.id)
    user_b = _make_user(db, tenant_b.id, UserRole.OWNER)
    db.commit()

    resp = client.get("/api/v1/leads", headers=_auth(_token(user_b)))
    assert resp.status_code == 200
    data = resp.json()
    # No leads from tenant_a visible to tenant_b user
    assert data["total"] == 0
    assert data["leads"] == []


# ── T28: cross-tenant GET /leads/{id} returns 404 ────────────────────────────

def test_get_lead_detail_cross_tenant_404(client, db):
    """GET /leads/{inquiry_id} belonging to another tenant returns 404."""
    tenant_a = _make_tenant(db, "DetailA")
    tenant_b = _make_tenant(db, "DetailB")
    guest_a = _make_guest(db, tenant_a.id)
    inquiry_a = _make_inquiry(db, tenant_a.id, guest_a.id)
    user_b = _make_user(db, tenant_b.id, UserRole.OWNER)
    db.commit()

    resp = client.get(f"/api/v1/leads/{inquiry_a.id}", headers=_auth(_token(user_b)))
    assert resp.status_code == 404


# ── Visibility scope: agents can't see a peer's leads ────────────────────────

def test_agent_cannot_see_peer_agents_lead_on_board(client, db):
    """Krisha/Jishant case: GET /leads for a concierge agent must exclude a
    lead assigned to a different agent, even though it's the same tenant."""
    tenant = _make_tenant(db, "ScopeTenant")
    guest = _make_guest(db, tenant.id)
    krisha = _make_user(db, tenant.id, UserRole.CONCIERGE)
    jishant = _make_user(db, tenant.id, UserRole.CONCIERGE)
    krishas_lead = _make_inquiry(db, tenant.id, guest.id)
    krishas_lead.assigned_to = krisha.id
    unclaimed = _make_inquiry(db, tenant.id, guest.id)
    db.commit()

    resp = client.get("/api/v1/leads", headers=_auth(_token(jishant)))
    assert resp.status_code == 200
    inquiry_ids = {lead["inquiry_id"] for lead in resp.json()["leads"]}
    assert krishas_lead.id not in inquiry_ids
    assert unclaimed.id in inquiry_ids


def test_owner_sees_every_agents_lead_on_board(client, db):
    tenant = _make_tenant(db, "OwnerScopeTenant")
    guest = _make_guest(db, tenant.id)
    owner = _make_user(db, tenant.id, UserRole.OWNER)
    agent = _make_user(db, tenant.id, UserRole.CONCIERGE)
    agents_lead = _make_inquiry(db, tenant.id, guest.id)
    agents_lead.assigned_to = agent.id
    db.commit()

    resp = client.get("/api/v1/leads", headers=_auth(_token(owner)))
    assert resp.status_code == 200
    inquiry_ids = {lead["inquiry_id"] for lead in resp.json()["leads"]}
    assert agents_lead.id in inquiry_ids


def test_agent_gets_404_opening_peer_agents_lead_by_url(client, db):
    """Even with the direct inquiry_id (e.g. a stale link), an agent scoped
    away from a peer's lead on the board must not be able to open it."""
    tenant = _make_tenant(db, "ScopeDetailTenant")
    guest = _make_guest(db, tenant.id)
    krisha = _make_user(db, tenant.id, UserRole.CONCIERGE)
    jishant = _make_user(db, tenant.id, UserRole.CONCIERGE)
    krishas_lead = _make_inquiry(db, tenant.id, guest.id)
    krishas_lead.assigned_to = krisha.id
    db.commit()

    resp = client.get(f"/api/v1/leads/{krishas_lead.id}", headers=_auth(_token(jishant)))
    assert resp.status_code == 404

    resp = client.get(f"/api/v1/leads/{krishas_lead.id}", headers=_auth(_token(krisha)))
    assert resp.status_code == 200


# ── T29: POST /signals forbidden for concierge ───────────────────────────────

def test_add_signal_forbidden_for_concierge_role(client, db):
    """POST /leads/{id}/signals with concierge role returns 403."""
    tenant = _make_tenant(db, "SigForbid")
    user = _make_user(db, tenant.id, UserRole.CONCIERGE)
    guest = _make_guest(db, tenant.id)
    inq = _make_inquiry(db, tenant.id, guest.id)
    db.commit()

    resp = client.post(
        f"/api/v1/leads/{inq.id}/signals",
        json={"type": "whatsapp_number", "value": "+919111111111"},
        headers=_auth(_token(user)),
    )
    assert resp.status_code == 403


# ── T30: POST /signals writes Consent row ────────────────────────────────────

def test_add_signal_dpdp_consent_row_written(client, db):
    """POST /leads/{id}/signals with type=phone writes a Consent row in DB."""
    tenant = _make_tenant(db, "DPDPTenant")
    user = _make_user(db, tenant.id, UserRole.RESERVATIONS)
    guest = _make_guest(db, tenant.id)
    inq = _make_inquiry(db, tenant.id, guest.id)
    db.commit()

    resp = client.post(
        f"/api/v1/leads/{inq.id}/signals",
        json={"type": "phone", "value": "+919222222222"},
        headers=_auth(_token(user)),
    )
    assert resp.status_code == 200

    consent = db.query(Consent).filter_by(
        tenant_id=tenant.id,
        guest_id=guest.id,
        source="agent_manual",
    ).first()
    assert consent is not None
    assert consent.scope == "profiling"


# ── T31: refresh-summary allowed for all roles ───────────────────────────────

def test_refresh_summary_allowed_for_all_roles(client, db):
    """POST /leads/{id}/refresh-summary with concierge JWT returns 200."""
    tenant = _make_tenant(db, "RefreshTenant")
    user = _make_user(db, tenant.id, UserRole.CONCIERGE)
    guest = _make_guest(db, tenant.id)
    inq = _make_inquiry(db, tenant.id, guest.id)
    db.commit()

    resp = client.post(
        f"/api/v1/leads/{inq.id}/refresh-summary",
        headers=_auth(_token(user)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["queued"] is True
    assert data["inquiry_id"] == inq.id


# ── T32: merge forbidden for reservations role ───────────────────────────────

def test_merge_forbidden_for_reservations_role(client, db):
    """POST /leads/{id}/merge with reservations role returns 403."""
    tenant = _make_tenant(db, "MergeForbid")
    user = _make_user(db, tenant.id, UserRole.RESERVATIONS)
    guest_a = _make_guest(db, tenant.id, "A")
    guest_b = _make_guest(db, tenant.id, "B")
    inq_a = _make_inquiry(db, tenant.id, guest_a.id)
    inq_b = _make_inquiry(db, tenant.id, guest_b.id)
    db.commit()

    resp = client.post(
        f"/api/v1/leads/{inq_a.id}/merge",
        json={"merge_with_inquiry_id": inq_b.id},
        headers=_auth(_token(user)),
    )
    assert resp.status_code == 403


# ── T33: lead with no phone renders without errors ────────────────────────────

def test_lead_card_renders_without_phone(client, db):
    """
    GET /leads returns 200 for a guest with only instagram_user_id (no phone).
    Lead card shows display_name and profile_completeness_pct=30, no 500 error.
    """
    tenant = _make_tenant(db, "NoPhoneTenant")
    user = _make_user(db, tenant.id, UserRole.OWNER)
    guest = _make_guest(db, tenant.id, name=None, phone="")  # no name, no phone
    _add_signal(db, tenant.id, guest.id, "instagram_user_id", "ig_anon_user")
    inq = _make_inquiry(db, tenant.id, guest.id, source=InquirySource.META_IG)
    db.commit()

    resp = client.get("/api/v1/leads", headers=_auth(_token(user)))
    assert resp.status_code == 200

    leads = resp.json()["leads"]
    assert len(leads) >= 1

    card = next((c for c in leads if c["inquiry_id"] == inq.id), None)
    assert card is not None
    assert card["display_name"] == "Unknown Guest"
    assert card["profile_completeness_pct"] == 30


# ── Regression: malformed/empty custom date-range params ────────────────────
# A stray empty-string or malformed date_from/date_to used to reach a raw
# Postgres comparison against Inquiry.created_at (timestamptz), surfacing as
# an uncaught 503 DataError ("invalid input syntax for type timestamp with
# time zone") instead of a clean validation error -- confirmed live on
# Leads360's custom date-range filter.

def test_get_leads_empty_string_date_params_are_ignored(client, db):
    """?date_from=&date_to= (present but empty) must not 500/503 -- same as
    omitting the params entirely."""
    tenant = _make_tenant(db, "EmptyDateTenant")
    user = _make_user(db, tenant.id, UserRole.OWNER)
    db.commit()

    resp = client.get(
        "/api/v1/leads?date_from=&date_to=&checkin_date_from=&booked_date_from=",
        headers=_auth(_token(user)),
    )
    assert resp.status_code == 200


def test_get_leads_malformed_date_param_returns_422(client, db):
    """A non-ISO-date date_from must fail loudly with a 422, not reach the DB."""
    tenant = _make_tenant(db, "BadDateTenant")
    user = _make_user(db, tenant.id, UserRole.OWNER)
    db.commit()

    resp = client.get(
        "/api/v1/leads?enquiry_date_preset=custom&date_from=not-a-date",
        headers=_auth(_token(user)),
    )
    assert resp.status_code == 422


def test_get_leads_whitespace_date_param_ignored(client, db):
    """A whitespace-only value (e.g. a stray space) must be treated as absent,
    not passed through to the DB comparison."""
    tenant = _make_tenant(db, "WhitespaceDateTenant")
    user = _make_user(db, tenant.id, UserRole.OWNER)
    db.commit()

    resp = client.get(
        "/api/v1/leads?enquiry_date_preset=custom&date_from=%20&date_to=%20",
        headers=_auth(_token(user)),
    )
    assert resp.status_code == 200
