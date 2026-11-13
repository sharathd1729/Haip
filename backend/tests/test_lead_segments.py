"""Lead segments (GET /leads/segments, services/lead_segments.py): campaign presets counted like a campaign would, open
leads per AI tag (closed won/lost left out), owner/manager only, never another workspace's leads."""
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.models.user import User, UserRole


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _lead(db, tid, tags, stage_id=None, phone="+919800000061"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone=phone, lead_identified_at=datetime.now(UTC))
    db.add(g)
    db.flush()
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, source=InquirySource.WA_DIRECT, tags=tags,
                   stage_id=stage_id))
    db.commit()


def test_segments_count_presets_and_open_tagged_leads(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    won = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key="sold_x", label="Sold", category="valid", order=99,
                        is_closed_won=True)
    db.add(won)
    db.commit()
    _lead(db, tid, ["anniversary", "couple"])
    _lead(db, tid, ["anniversary"], phone="+919800000062")
    _lead(db, tid, ["anniversary"], stage_id=won.id, phone="+919800000063")    # closed: not an open lead
    _lead(db, tid, [], phone="+919800000064")
    with patch("app.core.cache.get_cached", return_value=None), patch("app.core.cache.set_cached"):
        r = client.get("/api/v1/leads/segments", headers=_h(tenant_and_user))
    assert r.status_code == 200
    body = r.json()
    tags = {t["tag"]: t["open_leads"] for g in body["tags"] for t in g["tags"]}
    assert tags["anniversary"] == 2 and tags["couple"] == 1 and tags["birthday"] == 0
    new_week = next(p for p in body["presets"] if p["id"] == "new_week")
    assert new_week["people"] == 4 and new_week["reachable"] <= new_week["people"]
    assert {p["id"] for p in body["presets"]} >= {"hot", "quoted", "trip_soon", "went_quiet", "past_guests"}


def test_segments_are_for_owners_and_managers_and_stay_in_the_workspace(client, db, tenant_and_user):
    from app.models.tenant import Tenant

    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _lead(db, other.id, ["birthday"])
    with patch("app.core.cache.get_cached", return_value=None), patch("app.core.cache.set_cached"):
        body = client.get("/api/v1/leads/segments", headers=_h(tenant_and_user)).json()
    assert all(t["open_leads"] == 0 for g in body["tags"] for t in g["tags"])
    for u in db.query(User).filter_by(tenant_id=_tid(tenant_and_user)):
        u.role = UserRole.CONCIERGE
    db.commit()
    assert client.get("/api/v1/leads/segments", headers=_h(tenant_and_user)).status_code == 403
