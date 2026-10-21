"""Agency M7 (21 Oct 2026): creator barter stays end to end, ASCI labels, creator attribution, review -> post, OTA copy."""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.base import gen_uuid
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.marketing import MarketingGuestReview
from app.models.marketing_partners import MarketingCreator, MarketingOtaCopy
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_ai_service as ai
from app.services import marketing_attribution as attribution
from app.services import marketing_content_service as svc
from app.services import marketing_creators as creators
from app.services import marketing_reputation as reputation
from tests.test_marketing_studio_content import make_user, ws  # noqa: F401  (fixture)

P = "/api/v1/marketing/studio/partners"


@pytest.fixture(autouse=True)
def _no_holidays(monkeypatch):
    monkeypatch.setattr("app.services.marketing_demand.long_weekends", lambda *a, **k: [])


def _vehicle(db, tid, name="Ratha 1"):
    p = Property(tenant_id=tid, name=name, slug=f"r-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True)
    db.add(p)
    db.commit()
    return p


def _deal(client, ws, prop, *, check_in, nights=2, by="mkt_h"):  # noqa: F811
    r = client.post(f"{P}/creators", json={"handle": "@Coorg.Diaries", "name": "Meera", "followers": 48000},
                    headers=ws["mkt_h"])
    creator_id = r.json()["id"] if r.status_code == 201 else client.get(f"{P}/creators", headers=ws["mkt_h"]).json()[0]["id"]
    r = client.post(f"{P}/deals", json={"creator_id": creator_id, "property_id": prop.id, "check_in": check_in.isoformat(),
                                        "check_out": (check_in + timedelta(days=nights)).isoformat(), "comp_value_inr": 24000,
                                        "deliverables": [{"kind": "reel"}, {"kind": "story"}]}, headers=ws[by])
    assert r.status_code == 201, r.text
    return r.json()


# ── Creators ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_creators_are_unique_per_handle_and_tenant_scoped(client, db, ws):  # noqa: F811
    r = client.post(f"{P}/creators", json={"handle": "@Coorg.Diaries"}, headers=ws["mkt_h"])
    assert r.status_code == 201 and r.json()["handle"] == "coorg.diaries" and r.json()["has_contact"] is False
    assert client.post(f"{P}/creators", json={"handle": "coorg.diaries"}, headers=ws["mkt_h"]).status_code == 409
    assert client.post(f"{P}/creators", json={"handle": "bad handle!"}, headers=ws["mkt_h"]).status_code == 422
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.post(f"{P}/creators", json={"handle": "x"}, headers=foh_h).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    db.add(MarketingCreator(tenant_id=other.id, handle="theirs", platform="instagram"))
    db.commit()
    assert [c["handle"] for c in client.get(f"{P}/creators", headers=ws["mkt_h"]).json()] == ["coorg.diaries"]


def test_free_dates_are_open_runs_of_nights(db, ws):  # noqa: F811
    _vehicle(db, ws["tenant"].id)
    today = date(2026, 11, 2)
    taken = {"2026-11-07", "2026-11-08"}
    with patch("app.services.calculator_service.calculator_service.is_open", side_effect=lambda d, t, p, a, b: a not in taken):
        got = creators.free_windows(db, ws["tenant"], nights=2, horizon=12, today=today)
    assert [(w["check_in"], w["check_out"], w["free_nights"]) for w in got] == [
        ("2026-11-05", "2026-11-07", 2), ("2026-11-09", "2026-11-11", 5)]   # 9-13 Nov; the horizon ends on the 14th


# ── Deal lifecycle ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_creator_stay_runs_end_to_end(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    prop = _vehicle(db, tid)
    d = _deal(client, ws, prop, check_in=date.today() + timedelta(days=20))
    assert d["status"] == "requested" and d["campaign"].startswith("cr-")
    assert client.post(f"{P}/deals/{d['id']}/approve", headers=ws["mkt_h"]).status_code == 403     # needs an approver
    r = client.post(f"{P}/deals/{d['id']}/approve", headers=ws["manager_h"])
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = client.post(f"{P}/deals/{d['id']}/book", json={}, headers=ws["manager_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_contact"
    r = client.post(f"{P}/deals/{d['id']}/book", json={"phone": "+919845012345"}, headers=ws["manager_h"])
    assert r.status_code == 200, r.text
    stay = db.get(Stay, r.json()["stay_id"])
    assert (stay.total_amount, stay.channel_source, stay.property_id) == (0, "creator", prop.id)
    creator = db.query(MarketingCreator).filter_by(tenant_id=tid).one()
    assert creator.guest_id == stay.guest_id and db.get(Guest, stay.guest_id).phone   # contact lives on the guest
    bad = client.post(f"{P}/deals/{d['id']}/deliver", json={"index": 0, "url": "https://www.instagram.com/reel/AbC123/",
                                                            "caption": "Loved our stay in Coorg!"}, headers=ws["mkt_h"])
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "asci_label_missing"
    ok = client.post(f"{P}/deals/{d['id']}/deliver", json={"index": 0, "url": "https://www.instagram.com/reel/AbC123/",
                                                           "caption": "#collab Two days slow in Coorg"}, headers=ws["mkt_h"])
    assert ok.json()["deliverables"][0]["label"] == "#collab" and ok.json()["status"] == "booked"
    done = client.post(f"{P}/deals/{d['id']}/deliver", json={"index": 1, "url": "https://www.instagram.com/stories/x/1/",
                                                             "caption": "Gifted stay #ad"}, headers=ws["mkt_h"])
    assert done.json()["status"] == "delivered"
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="marketing.creator_deal.booked").count() == 1


def test_approval_rules_and_taken_dates(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    prop = _vehicle(db, tid)
    start = date.today() + timedelta(days=30)
    mine = _deal(client, ws, prop, check_in=start, by="manager_h")
    r = client.post(f"{P}/deals/{mine['id']}/approve", headers=ws["manager_h"])
    assert r.status_code == 403 and r.json()["detail"]["code"] == "self_approval"
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Payer", phone="+919845099999")
    db.add(g)
    db.add(Stay(id=gen_uuid(), tenant_id=tid, guest_id=g.id, property_id=prop.id, check_in=start,
                check_out=start + timedelta(days=1), status="confirmed", total_amount=Decimal("20000")))
    db.commit()
    r = client.post(f"{P}/deals/{mine['id']}/approve", headers=ws["owner_h"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "dates_taken"
    assert client.post(f"{P}/deals/{mine['id']}/cancel", headers=ws["mkt_h"]).json()["status"] == "cancelled"


def test_bookings_through_the_creators_link_are_credited_and_the_free_stay_is_not_counted(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    prop = _vehicle(db, tid)
    d = _deal(client, ws, prop, check_in=date.today() + timedelta(days=15))
    client.post(f"{P}/deals/{d['id']}/approve", headers=ws["manager_h"])
    client.post(f"{P}/deals/{d['id']}/book", json={"email": "meera@example.com"}, headers=ws["manager_h"])
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Ravi", phone="+919845077777")
    db.add(g)
    db.flush()
    inq = Inquiry(id=gen_uuid(), tenant_id=tid, guest_id=g.id,
                  custom_fields={"utm": {"utm_source": "instagram", "utm_medium": "creator", "utm_campaign": d["campaign"]}})
    db.add(inq)
    db.flush()
    db.add(Stay(id=gen_uuid(), tenant_id=tid, guest_id=g.id, property_id=prop.id, inquiry_id=inq.id,
                check_in=date.today() + timedelta(days=40), check_out=date.today() + timedelta(days=42),
                status="confirmed", total_amount=Decimal("36000")))
    db.commit()
    out = attribution.bookings(db, tid, date.today() - timedelta(days=1), date.today())
    assert out["total"] == 1 and out["bookings"][0]["credited_title"] == "Creator @coorg.diaries"   # comp stay left out
    res = client.get(f"{P}/deals/{d['id']}/results", headers=ws["owner_h"]).json()
    assert res == {"bookings": 1, "revenue": 36000.0, "cost_inr": 24000, "return_per_rupee": 1.5, "since": res["since"]}
    assert client.get(f"{P}/deals/{d['id']}/results", headers=ws["mkt_h"]).status_code == 403


# ── Review -> post ──────────────────────────────────────────────────────────────────────────────────────────────────

def _review(db, tid, rating=5, comment="The caravan was spotless and the chauffeur knew every coffee estate on the way."):
    r = MarketingGuestReview(tenant_id=tid, source="google", external_id=uuid.uuid4().hex, rating=rating,
                             reviewer="Asha Menon", comment=comment)
    db.add(r)
    db.commit()
    return r


def test_a_five_star_review_becomes_a_draft_post_only_with_recorded_consent(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    four, five = _review(db, tid, rating=4), _review(db, tid)
    assert client.post(f"{P}/reviews/{four.id}/to-post", json={"consent_note": "said yes on WhatsApp"},
                       headers=ws["owner_h"]).status_code == 422
    assert client.post(f"{P}/reviews/{five.id}/to-post", json={}, headers=ws["owner_h"]).status_code == 422
    assert client.post(f"{P}/reviews/{five.id}/to-post", json={"consent_note": "said yes on WhatsApp"},
                       headers=ws["mkt_h"]).status_code == 403
    r = client.post(f"{P}/reviews/{five.id}/to-post", json={"consent_note": "Asha said yes on WhatsApp, 20 Oct"},
                    headers=ws["owner_h"])
    assert r.status_code == 201
    item = svc.get_item(db, tid, r.json()["content_id"])
    payload = svc.get_version(db, tid, item.current_version_id).payload
    assert item.status == "draft" and "spotless" in payload["caption"] and "— Asha," in payload["caption"]
    assert "Menon" not in payload["caption"]                                      # first name only
    db.refresh(five)
    assert five.content_id == item.id and five.consent_by == ws["owner"].id
    assert client.post(f"{P}/reviews/{five.id}/to-post", json={"consent_note": "again please"},
                       headers=ws["owner_h"]).status_code == 409


# ── OTA copy ────────────────────────────────────────────────────────────────────────────────────────────────────────

AIRBNB = {"title": "Caravan with a chauffeur, Coorg routes", "summary": "A caravan that sleeps 4, driven for you.",
          "the_space": "Two beds, a kitchenette and a deck.", "neighbourhood": "Coffee estates around Madikeri."}


def test_ota_copy_is_validated_checked_and_queued(client, db, ws, monkeypatch):  # noqa: F811
    tid = ws["tenant"].id
    prop = _vehicle(db, tid)
    queued = []
    monkeypatch.setattr("app.workers.tasks.marketing_studio.ota_copy.delay", lambda *a: queued.append(a))
    r = client.post(f"{P}/ota", json={"property_id": prop.id, "platform": "airbnb"}, headers=ws["mkt_h"])
    assert r.status_code == 202 and r.json()["status"] == "pending" and queued == [(tid, r.json()["id"])]
    row_id = r.json()["id"]
    seen = {}

    def fake(task, tenant_id, system, user, tool):
        seen.update(task=task, tool=tool["name"])
        return dict(AIRBNB), {"model": "m"}, "nvidia"
    with patch.object(ai, "_call", side_effect=fake):
        row = reputation.run_copy(db, tid, row_id)
    assert seen == {"task": "marketing_ota_copy", "tool": "submit_listing"}
    assert row.status == "ready" and row.body["copy"]["title"] == AIRBNB["title"] and row.prompt_version == "marketing-ota-copy-v1"
    with patch.object(ai, "_call", return_value=({**AIRBNB, "title": "x" * 60}, {}, "nvidia")):
        row = reputation.run_copy(db, tid, row_id)
    assert row.status == "failed" and "limits" in row.error
    with patch.object(ai, "_call", return_value=({**AIRBNB, "summary": "Only Rs 9,999 a night!"}, {}, "nvidia")):
        row = reputation.run_copy(db, tid, row_id)
    assert row.status == "failed"                                                 # handoff price policy: no prices
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = _vehicle(db, other.id, name="Theirs")
    assert client.post(f"{P}/ota", json={"property_id": theirs.id, "platform": "airbnb"}, headers=ws["mkt_h"]).status_code == 404
    assert db.query(MarketingOtaCopy).filter_by(tenant_id=other.id).count() == 0
    assert [c["id"] for c in client.get(f"{P}/ota", headers=ws["mkt_h"]).json()] == [row_id]
