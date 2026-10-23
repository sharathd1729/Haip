"""Studio phase 0 (plan 24 Oct 2026): setup checklist, the no-photos gate, AI images filling their draft, the Instagram
check at scheduling time and autopilot skips that are surfaced, never silent."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.core.encryption import encrypt_credentials
from app.models.integration import Integration
from app.models.marketing import MarketingContent, MarketingImageJob, MarketingTask
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_agency_service as agency
from app.services import marketing_content_service as svc
from app.services import marketing_image_service as images
from app.services import marketing_publish_service as pub
from app.services import marketing_setup as setup
from tests.conftest import seed_capabilities
from tests.test_marketing_studio_content import BASE, enable_module, make_user, seed_photos, ws  # noqa: F401  (fixture)


def _ig(db, tid, permissions=None):
    cfg = {"instagram_business_account_id": "IG1", **({"permissions": permissions} if permissions is not None else {})}
    db.add(Integration(tenant_id=tid, kind="instagram", status="active", config=cfg,
                       credentials_kms_blob=encrypt_credentials({"access_token": "t"})))
    db.commit()


def _items(out):
    return {i["key"]: i for i in out["items"]}


# ── Setup checklist ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_checklist_reflects_what_is_set_up(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    first = _items(setup.checklist(db, tenant))
    assert first["module"]["done"] and not first["photos"]["done"] and not first["instagram"]["done"]
    assert first["photos"]["fix"] == {"tab": "library", "label": "Upload photos"}
    assert first["instagram"]["fix"]["tab"] == "integrations" and not first["autonomy"]["done"]
    assert first["clips"]["required"] is False and first["ads_budget"]["required"] is False

    seed_photos(db, tenant.id, setup.MIN_PHOTOS)
    _ig(db, tenant.id, ["instagram_business_basic", pub.PUBLISH_SCOPE])
    agency.update_agency(db, tenant, ws["owner"].id, roles={"publish": "suggest"})
    db.commit()
    now = _items(setup.checklist(db, tenant))
    assert now["photos"]["done"] and now["instagram"]["done"] and now["autonomy"]["done"]
    assert now["photos"]["fix"] is None


def test_server_keys_are_named_never_shown(db, ws, monkeypatch):  # noqa: F811
    from app.core.config import settings
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "nv-secret-value")
    item = _items(setup.checklist(db, ws["tenant"]))["server"]
    assert "GEMINI_API_KEY" in item["admin_keys"] and "GEMINI_API_KEY" in item["detail"] and not item["done"]
    assert "nv-secret-value" not in str(setup.checklist(db, ws["tenant"]))


def test_setup_api_roles_and_tenant_isolation(client, db, ws):  # noqa: F811
    seed_photos(db, ws["tenant"].id, setup.MIN_PHOTOS)
    r = client.get(f"{BASE}/setup", headers=ws["mkt_h"])
    assert r.status_code == 200 and _items(r.json())["photos"]["done"]
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.get(f"{BASE}/setup", headers=foh_h).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    theirs = _items(client.get(f"{BASE}/setup", headers=other_h).json())
    assert not theirs["photos"]["done"] and theirs["photos"]["detail"].startswith("0 of")      # A's photos never count


# ── No photos, no approval ──────────────────────────────────────────────────────────────────────────────────────────

def test_a_draft_without_photos_cannot_be_sent_for_approval(client, db, ws):  # noqa: F811
    item = svc.create_item(db, ws["tenant"].id, kind="carousel", title="Ghats", actor_id=ws["mkt"].id,
                           payload={"caption": "Two ghats.", "slides": [{"headline": "One"}, {"headline": "Two"}]})
    db.commit()
    r = client.post(f"{BASE}/content/{item.id}/submit", json={"version_id": item.current_version_id}, headers=ws["mkt_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "needs_photos"
    assert r.json()["detail"]["problems"] == ["Without a photo: 1, 2"]
    assert client.get(f"{BASE}/content/{item.id}", headers=ws["mkt_h"]).json()["needs_photos"] == [1, 2]


def test_agency_holds_drafts_without_photos_and_says_so(db, ws):  # noqa: F811
    from tests.test_marketing_agency import _fake_call, _seed_insights
    from app.services import marketing_agency_run as runs
    from app.services import marketing_ai_service as ai
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    tid = ws["tenant"].id
    _seed_insights(db, tid)
    start = datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=1)
    with patch.object(ai, "_call", side_effect=_fake_call(start)), patch.object(agency, "notify_needs_approval") as notify:
        run_id = runs.run_week(db, tid, trigger="manual")
    submit = db.query(MarketingTask).filter_by(run_id=run_id, step="submit").one()
    assert submit.status == "skipped" and submit.detail["needs_photos"] == 3 and "need photos" in submit.detail["reason"]
    assert {i.status for i in db.query(MarketingContent).filter_by(tenant_id=tid)} == {"draft"}
    assert any("photos" in c.args[2] for c in notify.call_args_list)


# ── AI image fills the draft it was made for ────────────────────────────────────────────────────────────────────────

def test_approved_ai_image_fills_its_draft_and_sends_an_agency_draft_on(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    item = svc.create_item(db, tid, kind="post", title="Routes: Coorg", actor_id="agency", payload={"caption": "Coorg."})
    db.commit()
    asset = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key="k/ai.jpg", mime_type="image/jpeg", bytes=10,
                       sha256="b" * 64, status="pending_review", source="ai", created_by="agency")
    db.add(asset)
    db.add(MarketingImageJob(tenant_id=tid, prompt="Coorg", model="m", shape="portrait", status="ready", asset_id=asset.id,
                             content_id=item.id, created_by="agency"))
    db.commit()
    images.review_image(db, tid, asset.id, ws["manager"], approve=True)
    db.commit()
    db.refresh(item)
    v = svc.get_version(db, tid, item.current_version_id)
    assert v.payload["media"]["asset_id"] == asset.id and item.status == "in_review"


def test_ai_image_without_a_draft_stays_in_the_library(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    asset = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key="k/ai2.jpg", mime_type="image/jpeg", bytes=10,
                       sha256="c" * 64, status="pending_review", source="ai", created_by="agency")
    db.add(asset)
    db.commit()
    assert images.review_image(db, tid, asset.id, ws["manager"], approve=True).status == "active"
    assert images.attach_to_draft(db, tid, asset) is None


# ── Instagram checked at scheduling time; autopilot skips are visible ───────────────────────────────────────────────

def _approved(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    photo = seed_photos(db, tid, 1)[0]
    item = svc.create_item(db, tid, kind="post", title="x", actor_id=ws["mkt"].id,
                           payload={"caption": "Coorg.", "media": {"asset_id": photo.id}})
    db.commit()
    svc.submit(db, tid, item.id, item.current_version_id, ws["mkt"])
    svc.approve(db, tid, item.id, item.current_version_id, ws["owner"])
    db.commit()
    return item


def test_instagram_problem_names_connection_and_permission(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    assert "not connected" in pub.instagram_problem(db, tid)
    _ig(db, tid, ["instagram_business_basic"])
    assert "permission to post" in pub.instagram_problem(db, tid)


def test_older_connection_without_recorded_permissions_is_trusted(db, ws):  # noqa: F811
    _ig(db, ws["tenant"].id)
    assert pub.instagram_problem(db, ws["tenant"].id) is None


def test_scheduling_refuses_when_instagram_is_not_connected(db, ws):  # noqa: F811
    item = _approved(db, ws)
    with pytest.raises(svc.MarketingError) as exc:
        pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id)
    assert exc.value.code == "not_publishable" and any("not connected" in p for p in exc.value.problems)


def test_autopilot_skip_is_recorded_and_pushed(client, db, ws):  # noqa: F811
    agency.update_agency(db, ws["tenant"], ws["owner"].id, roles={"publish": "autopilot"})
    db.commit()
    item = _approved(db, ws)
    with patch.object(agency, "notify_needs_approval") as notify:
        assert pub.on_approved(db, ws["tenant"], item.id) is None
    db.commit()
    task = db.query(MarketingTask).filter_by(tenant_id=ws["tenant"].id, step="auto_schedule").one()
    assert task.status == "failed" and "not connected" in task.error and task.ref_id == item.id
    notify.assert_called_once()
    out = client.get(f"{BASE}/content/{item.id}", headers=ws["mkt_h"]).json()
    assert "not connected" in out["auto_schedule_error"]
