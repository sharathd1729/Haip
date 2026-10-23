"""Studio phase 4 (plan 24 Oct 2026): template Reels from photos, one brief -> several drafts incl. a trial Reel, trial
and licensed-audio parameters at publishing (audio only while the owner's audio source works)."""
import uuid

import pytest

from app.adapters.instagram.publishing import Publisher
from app.models.marketing_research import MarketingStrategyDoc
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.schemas.marketing import ReelContent
from app.services import marketing_content_service as svc
from app.services import marketing_producer as producer
from app.services import marketing_publish_service as pub
from app.services.marketing_prompts import content_tool
from tests.conftest import seed_capabilities
from tests.test_marketing_strategy import BRIEF
from tests.test_marketing_studio_content import BASE, enable_module, make_user, seed_photos, ws  # noqa: F401  (fixture)


def _brief(db, tid, status="ready"):
    doc = MarketingStrategyDoc(tenant_id=tid, kind="brief", title="Shoot brief: Diwali", status=status,
                               input={"theme": "Diwali"}, facts={"tracking": {"code": "c-1234abcd"}},
                               body=dict(BRIEF) if status == "ready" else None)
    db.add(doc)
    db.commit()
    return doc


def test_template_reel_from_photos(db, ws):  # noqa: F811
    photos = seed_photos(db, ws["tenant"].id, 3)
    item = producer.reel_from_photos(db, ws["tenant"], title="Kabini nights", asset_ids=[p.id for p in photos],
                                     lines=["We woke up here", "Coffee on the deck"], caption="Kabini, slowly.",
                                     actor_id=ws["mkt"].id)
    payload = ReelContent.model_validate(svc.get_version(db, ws["tenant"].id, item.current_version_id).payload)
    assert sum(c.seconds for c in payload.clips) == 9 and payload.cover_text == "We woke up here"
    assert all(c.media.asset_id for c in payload.clips) and payload.trial is False
    with pytest.raises(svc.MarketingError) as exc:
        producer.reel_from_photos(db, ws["tenant"], title="x", asset_ids=[photos[0].id], lines=[], caption="x", actor_id="a")
    assert exc.value.code == "too_few_photos"


def test_photos_of_another_workspace_are_refused(db, ws):  # noqa: F811
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = seed_photos(db, other.id, 2)
    with pytest.raises(svc.MarketingError) as exc:
        producer.reel_from_photos(db, ws["tenant"], title="x", asset_ids=[p.id for p in theirs], lines=[], caption="x",
                                  actor_id="a")
    assert exc.value.code == "asset_not_usable"


def test_one_brief_becomes_reels_a_trial_reel_a_carousel_and_a_story(db, ws):  # noqa: F811
    seed_photos(db, ws["tenant"].id, 4)
    doc = _brief(db, ws["tenant"].id)
    items = producer.from_brief(db, ws["tenant"], doc.id, ws["mkt"].id)
    db.commit()
    kinds = sorted(i.kind for i in items)
    assert kinds == ["carousel", "reel", "reel", "reel", "story"]
    payloads = {i.title: svc.get_version(db, ws["tenant"].id, i.current_version_id).payload for i in items}
    trial = [p for p in payloads.values() if p.get("trial")]
    assert len(trial) == 1 and trial[0]["cover_text"] == "Hook 1"
    assert "c-1234abcd" in payloads["Diwali: Night at Kabini"]["caption"]
    with pytest.raises(svc.MarketingError) as exc:
        producer.from_brief(db, ws["tenant"], doc.id, ws["mkt"].id)
    assert exc.value.code == "already_produced"
    pending = _brief(db, ws["tenant"].id, status="pending")
    with pytest.raises(svc.MarketingError) as exc:
        producer.from_brief(db, ws["tenant"], pending.id, ws["mkt"].id)
    assert exc.value.code == "not_ready"


def test_trial_and_audio_reach_the_reel_container_only_when_allowed(db, ws, monkeypatch):  # noqa: F811
    sent = {}
    p = Publisher("t", "IG1")
    monkeypatch.setattr(p, "_req", lambda method, path, **params: sent.update(params) or {"id": "c1"})
    p.reel_container("https://cdn/v.mp4", caption="x", trial=True, audio_id="123")
    assert sent["trial_params"] == '{"graduation_strategy": "SS_PERFORMANCE"}' and sent["audio_configuration"] == '{"audio_id": "123"}'
    assert "share_to_feed" not in sent
    monkeypatch.setattr("app.services.marketing_research_sources.ready", lambda db, t, k: False)
    assert pub._reel_extras(db, ws["tenant"], {"trial": True, "audio_id": "123"}) == {"trial": True}
    monkeypatch.setattr("app.services.marketing_research_sources.ready", lambda db, t, k: k == "audio")
    assert pub._reel_extras(db, ws["tenant"], {"audio_id": "123"}) == {"audio_id": "123"}


def test_the_copywriter_cannot_set_trial_or_audio():
    props = content_tool("reel")["input_schema"]["properties"]
    assert "trial" not in props and "audio_id" not in props


def test_produce_api_roles_and_isolation(client, db, ws):  # noqa: F811
    doc = _brief(db, ws["tenant"].id)
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.post(f"{BASE}/briefs/{doc.id}/produce", headers=foh_h).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.post(f"{BASE}/briefs/{doc.id}/produce", headers=other_h).status_code == 404
    r = client.post(f"{BASE}/briefs/{doc.id}/produce", headers=ws["mkt_h"])
    assert r.status_code == 201 and len(r.json()["items"]) == 5
