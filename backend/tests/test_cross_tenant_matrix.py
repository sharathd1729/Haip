"""Cross-tenant matrix (Phase 0, workstream C).

One tenant owns real records (a lead, a conversation with a message, a call with a recording, a
booking, an ops staff member and an ops item). A second tenant, with a valid login of its own, then tries to reach every one of them
through the API, the report export and the background tasks. Each check also runs the same request
as the owning tenant first: without that positive control a 404 could just mean the fixture is broken.

The tests run on whatever database ``DATABASE_URL`` points at. In CI that is PostgreSQL (see
.github/workflows/tenant-isolation.yml). This module proves the application-level tenant filters;
row-level security itself is covered by tests/test_rls_postgres.py.
"""
import uuid

from tests.conftest import seed_capabilities
from datetime import date, datetime, timezone

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.ops import OpsItem, StaffProfile
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.models.user import User, UserRole

SECRET_NAME = "Zorbatron Confidential"
SECRET_PHONE = "+917700000042"


def _tenant_with_owner(db, label):
    tenant = Tenant(id=str(uuid.uuid4()), name=f"Tenant {label}", slug=f"xt-{label}-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()
    user = User(
        id=str(uuid.uuid4()), tenant_id=tenant.id, name=f"Owner {label}",
        email=f"owner-{label}-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw-not-used"), role=UserRole.OWNER, is_active=True,
    )
    db.add(user)
    db.commit()
    seed_capabilities(db, tenant.id)
    token = create_access_token({"sub": user.id, "tenant_id": tenant.id, "role": user.role.value})
    return tenant, {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def world(db, tmp_path):
    """Tenant A's data and both tenants' auth headers."""
    a, headers_a = _tenant_with_owner(db, "a")
    b, headers_b = _tenant_with_owner(db, "b")

    guest = Guest(id=str(uuid.uuid4()), tenant_id=a.id, name=SECRET_NAME, phone=SECRET_PHONE)
    db.add(guest)
    db.flush()
    inquiry = Inquiry(id=str(uuid.uuid4()), tenant_id=a.id, guest_id=guest.id, stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=a.id, guest_id=guest.id, inquiry_id=inquiry.id,
                        channel=ChannelType.WHATSAPP, is_open=True)
    db.add_all([inquiry, conv])
    db.flush()
    message = Message(id=str(uuid.uuid4()), tenant_id=a.id, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                      channel=ChannelType.WHATSAPP, body="Is the lake villa free in December?",
                      channel_message_id=f"wamid.{uuid.uuid4().hex[:10]}")
    recording = tmp_path / "call.mp3"
    recording.write_bytes(b"ID3-not-really-audio")
    call = Call(id=str(uuid.uuid4()), tenant_id=a.id, guest_id=guest.id, inquiry_id=inquiry.id, ivr_provider="callerdesk",
                ivr_call_id=f"cd-{uuid.uuid4().hex[:8]}", direction=CallDirection.INBOUND,
                from_number=SECRET_PHONE, to_number="+919876543210", duration_seconds=95,
                started_at=datetime.now(timezone.utc).isoformat(), recording_s3_key=str(recording))
    prop = Property(id=str(uuid.uuid4()), tenant_id=a.id, name="Lake Villa", slug="lake-villa", type="villa", is_active=True)
    db.add_all([message, call, prop])
    db.flush()
    stay = Stay(id=str(uuid.uuid4()), tenant_id=a.id, guest_id=guest.id, property_id=prop.id,
                check_in=date(2026, 12, 20), check_out=date(2026, 12, 23), status="confirmed", total_amount=42000)
    db.add(stay)
    db.flush()   # ops_items.stay_id has no ORM relationship to order the inserts by; PostgreSQL checks the foreign key
    # Operations module: a staff member and an open item at the property (names carry the secret markers).
    staff = StaffProfile(id=str(uuid.uuid4()), tenant_id=a.id, name=f"{SECRET_NAME} Caretaker", phone_e164="+917700000099",
                         active=True)
    ops_item = OpsItem(id=str(uuid.uuid4()), tenant_id=a.id, kind="incident", title="Lake Villa AC not working",
                       severity="high", duty="maintenance", status="open", source="staff", property_id=prop.id,
                       stay_id=stay.id)
    db.add_all([staff, ops_item])
    db.commit()
    return {"a": a, "b": b, "ha": headers_a, "hb": headers_b, "guest": guest, "inquiry": inquiry,
            "conv": conv, "message": message, "call": call, "stay": stay, "ops_item": ops_item}


def _assert_no_secret(response):
    body = response.text
    assert SECRET_NAME not in body and SECRET_PHONE not in body and "lake villa" not in body.lower(), (
        f"another tenant's data appeared in the response: {body[:300]}"
    )


# ── Single-record reads: owner sees it, the other tenant gets 404 and no data ─────────────────

@pytest.mark.parametrize("path", [
    "/api/v1/conversations/{conv}/messages",
    "/api/v1/calls/{call}",
    "/api/v1/calls/{call}/recording",
    "/api/v1/leads/{inquiry}",
    "/api/v1/bookings/{stay}",
    "/api/v1/ops/items/{ops_item}",
])
def test_single_record_is_not_readable_by_another_tenant(client, world, path):
    url = path.format(conv=world["conv"].id, call=world["call"].id, inquiry=world["inquiry"].id, stay=world["stay"].id,
                      ops_item=world["ops_item"].id)

    owner = client.get(url, headers=world["ha"])
    assert owner.status_code == 200, f"positive control failed for {url}: {owner.status_code} {owner.text[:200]}"

    other = client.get(url, headers=world["hb"])
    assert other.status_code in (403, 404), f"{url} answered {other.status_code} to another tenant"
    _assert_no_secret(other)


# ── Lists: the other tenant's list is empty ─────────────────────────────────────────────────────

def _items(payload):
    if isinstance(payload, list):
        return payload
    for key in ("items", "rows", "leads", "conversations", "data", "results"):
        if key in payload:
            return payload[key]
    raise AssertionError(f"unrecognised list shape: {list(payload)[:8]}")


@pytest.mark.parametrize("path", [
    "/api/v1/calls",
    "/api/v1/leads",
    "/api/v1/conversations",
    "/api/v1/bookings",
    "/api/v1/guests",
    "/api/v1/ops/items",
    "/api/v1/ops/staff",
])
def test_lists_do_not_include_another_tenants_records(client, world, path):
    owner = client.get(path, headers=world["ha"])
    assert owner.status_code == 200, f"positive control failed for {path}: {owner.status_code} {owner.text[:200]}"
    assert _items(owner.json()), f"{path} is empty for the owning tenant, so the check below proves nothing"

    other = client.get(path, headers=world["hb"])
    assert other.status_code == 200
    assert _items(other.json()) == []
    _assert_no_secret(other)


def test_guest_timeline_of_another_tenants_guest_is_empty(client, world):
    url = f"/api/v1/guests/{world['guest'].id}/timeline"
    owner = client.get(url, headers=world["ha"])
    assert owner.status_code == 200 and owner.json()["events"], "positive control failed"

    other = client.get(url, headers=world["hb"])
    assert other.status_code in (200, 403, 404)
    if other.status_code == 200:
        assert other.json()["events"] == [] and other.json()["total_calls"] == 0
    _assert_no_secret(other)


# ── Exports ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("report_id", ["calls", "inquiries"])
def test_report_export_only_contains_the_requesting_tenants_rows(client, world, report_id):
    url = f"/api/v1/reports/export?report_id={report_id}&format=json"
    owner = client.get(url, headers=world["ha"])
    assert owner.status_code == 200, f"positive control failed: {owner.status_code} {owner.text[:200]}"
    assert owner.json()["row_count"] >= 1

    other = client.get(url, headers=world["hb"])
    assert other.status_code == 200
    assert other.json()["row_count"] == 0
    _assert_no_secret(other)


def test_csv_download_only_contains_the_requesting_tenants_rows(client, world):
    from app.api.v1.endpoints.reports import REPORT_CATALOG
    entry = next(r for r in REPORT_CATALOG if r["id"] == "calls")
    body = {"report_id": "calls", "fields": [f["key"] for f in entry["fields"] if f.get("default")]}
    owner = client.post("/api/v1/reports/download?format=csv", json=body, headers=world["ha"])
    other = client.post("/api/v1/reports/download?format=csv", json=body, headers=world["hb"])

    assert owner.status_code == 200, owner.text[:200]
    assert other.status_code == 200
    assert SECRET_PHONE in owner.text, "positive control failed: the owner's CSV should contain its call"
    assert SECRET_PHONE not in other.text


# ── Writes ───────────────────────────────────────────────────────────────────────────────────────

def test_another_tenant_cannot_modify_a_booking_or_change_a_call(client, world, db):
    patch = client.patch(f"/api/v1/bookings/{world['stay'].id}", json={"status": "cancelled"}, headers=world["hb"])
    assert patch.status_code in (403, 404)
    disp = client.patch(f"/api/v1/calls/{world['call'].id}/disposition", json={"disposition": "lost"}, headers=world["hb"])
    assert disp.status_code == 404

    db.refresh(world["stay"])
    db.refresh(world["call"])
    assert world["stay"].status == "confirmed"
    assert world["call"].human_disposition is None


# ── Background tasks: handed another tenant's ids, they must do nothing ───────────────────────────

@pytest.fixture()
def task_session(db, monkeypatch):
    monkeypatch.setattr(db, "close", lambda: None)
    for module in ("generate_ai_summary", "send_whatsapp", "transcribe"):
        monkeypatch.setattr(f"app.workers.tasks.{module}.SessionLocal", lambda: db)
    return db


def test_ai_summary_task_ignores_another_tenants_inquiry(world, task_session):
    from app.workers.tasks.generate_ai_summary import generate_ai_summary

    result = generate_ai_summary.run(inquiry_id=world["inquiry"].id, tenant_id=world["b"].id)

    task_session.refresh(world["inquiry"])
    assert result is None
    assert world["inquiry"].ai_summary is None


def test_send_whatsapp_task_ignores_another_tenants_message(world, task_session, monkeypatch):
    from app.workers.tasks import send_whatsapp as mod

    called = []
    monkeypatch.setattr("httpx.post", lambda *a, **k: called.append(a) or None, raising=False)
    before = world["message"].delivery_state

    result = mod.send_whatsapp.run(message_id=world["message"].id, tenant_id=world["b"].id)

    task_session.refresh(world["message"])
    assert result is None
    assert called == [], "a message belonging to another tenant must never be sent"
    assert world["message"].delivery_state == before


def test_transcribe_task_ignores_another_tenants_call(world, task_session, monkeypatch):
    from app.workers.tasks import transcribe as mod

    monkeypatch.setattr(mod, "get_transcription_adapter",
                        lambda *a, **k: pytest.fail("transcription started for another tenant's call"))
    before = world["call"].transcription_status

    result = mod.transcribe.run(call_id=world["call"].id, tenant_id=world["b"].id)

    task_session.refresh(world["call"])
    assert result is None
    assert world["call"].transcription_status == before
