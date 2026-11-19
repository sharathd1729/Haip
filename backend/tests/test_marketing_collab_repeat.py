"""Marketing Studio: Instagram collaborators on a post, and repeat posts (same approved version every N days)."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from app.adapters.instagram.publishing import PublishError, Publisher
from app.models.audit_event import AuditEvent
from app.models.marketing import MarketingContent, MarketingPublishAttempt
from app.schemas.marketing import validate_content
from app.services import marketing_content_service as svc
from app.services import marketing_publish_service as pub
from app.services.marketing_prompts import content_tool
from tests.test_marketing_publish import (  # noqa: F401  (autouse fixtures + helpers)
    FakePublisher, _approved, _aware, _due, _fake_storage, _instagram_connected, _jpeg, _run,
)
from tests.test_marketing_studio_content import BASE, ws  # noqa: F401  (fixture)


class CollabPublisher(FakePublisher):
    """Records the collaborators each container was created with; can refuse them once like Instagram does."""

    def __init__(self, refuse=False, **kw):
        super().__init__(**kw)
        self.refuse, self.collabs = refuse, []

    def image_container(self, url, caption=None, carousel_item=False, story=False, collaborators=None):
        if collaborators and self.refuse:
            raise PublishError("Instagram 400: collaborator cannot be tagged", transient=False)
        self.collabs.append(collaborators)
        return super().image_container(url, caption, carousel_item, story)


# ── collaborators ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_collaborators_are_normalised_and_limited():
    p = validate_content("post", {"caption": "x", "collaborators": ["@Partner.Stay", "partner.stay", " @travel_anu "]})
    assert p["collaborators"] == ["partner.stay", "travel_anu"]
    with pytest.raises(ValidationError):
        validate_content("post", {"caption": "x", "collaborators": ["a", "b", "c", "d"]})
    with pytest.raises(ValidationError):
        validate_content("post", {"caption": "x", "collaborators": ["not a name!"]})
    with pytest.raises(ValidationError):                       # Instagram refuses collaborators on stories
        validate_content("story", {"frames": [{}], "collaborators": ["a"]})
    assert validate_content("reel", {"caption": "x", "clips": [{}, {}], "collaborators": ["a"]})["collaborators"] == ["a"]


def test_the_ai_is_never_asked_for_collaborators():
    for kind in ("post", "carousel", "promo", "reel"):
        assert "collaborators" not in content_tool(kind)["input_schema"]["properties"]


def test_publisher_sends_collaborators_only_where_instagram_allows():
    seen = []

    def handler(req):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json={"id": "c1"})
    p = Publisher("tok", "178", client=httpx.Client(transport=httpx.MockTransport(handler)))
    p.image_container("https://cdn/x.jpg", caption="hi", collaborators=["anu"])
    p.image_container("https://cdn/y.jpg", carousel_item=True, collaborators=["anu"])
    p.image_container("https://cdn/z.jpg", story=True, collaborators=["anu"])
    p.carousel_container(["k1", "k2"], "hi", collaborators=["anu", "ravi"])
    p.reel_container("https://cdn/r.mp4", caption="hi", collaborators=["anu"])
    got = [s.get("collaborators") for s in seen]
    assert got == ['["anu"]', None, None, json.dumps(["anu", "ravi"]), '["anu"]']


def test_a_post_goes_out_with_its_collaborators(client, db, ws):  # noqa: F811
    a = _jpeg(db, ws["tenant"].id)
    item = _approved(db, ws, payload={"caption": "Coorg", "media": {"asset_id": a.id}, "collaborators": ["anu"]})
    notes = client.get(f"{BASE}/content/{item.id}/publishing", headers=ws["mkt_h"]).json()["notes"]
    assert any("@anu" in n for n in notes)
    attempt = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id)
    db.commit()
    fake = CollabPublisher()
    _run(db, attempt, fake)
    assert attempt.status == "published" and fake.collabs == [["anu"]] and attempt.error is None


def test_a_refused_tag_posts_without_it_and_says_so(db, ws):  # noqa: F811
    a = _jpeg(db, ws["tenant"].id)
    item = _approved(db, ws, payload={"caption": "Coorg", "media": {"asset_id": a.id}, "collaborators": ["anu"]})
    attempt = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id)
    db.commit()
    fake = CollabPublisher(refuse=True)
    _run(db, attempt, fake)
    assert attempt.status == "published" and fake.collabs == [None]
    assert "Posted without @anu" in attempt.error


# ── repeat posts ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_repeat_needs_both_values_within_limits():
    assert pub.check_repeat(None, None) == (None, None)
    for every, times in ((28, None), (None, 2), (7, 2), (91, 2), (28, 0), (28, 7)):
        with pytest.raises(svc.MarketingError):
            pub.check_repeat(every, times)
    assert pub.check_repeat(28, 3) == (28, 3)


def test_a_repeated_post_goes_out_again_then_stops(db, ws):  # noqa: F811
    item = _approved(db, ws)
    first = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id,
                         repeat_every_days=28, repeat_times=2)
    db.commit()
    slot = _aware(first.scheduled_for)
    _run(db, first, FakePublisher())
    runs = db.query(MarketingPublishAttempt).filter_by(content_id=item.id).order_by(MarketingPublishAttempt.run).all()
    assert [(r.run, r.status, r.repeat_left) for r in runs] == [(0, "published", 2), (1, "scheduled", 1)]
    assert _aware(runs[1].scheduled_for) == slot + timedelta(days=28)
    assert db.get(MarketingContent, item.id).status == "scheduled"
    for expected_left in (1, 0):
        nxt = db.query(MarketingPublishAttempt).filter_by(content_id=item.id, status="scheduled").one()
        _due(db, nxt)
        _run(db, nxt, FakePublisher())
        assert nxt.status == "published" and nxt.repeat_left == expected_left
    assert db.query(MarketingPublishAttempt).filter_by(content_id=item.id, status="published").count() == 3
    assert db.query(MarketingPublishAttempt).filter_by(content_id=item.id, status="scheduled").count() == 0
    assert db.get(MarketingContent, item.id).status == "published"
    assert db.query(AuditEvent).filter_by(tenant_id=ws["tenant"].id, action="marketing.content.repeat_scheduled").count() == 2


def test_unschedule_and_edit_stop_repeats(db, ws):  # noqa: F811
    item = _approved(db, ws)
    first = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id,
                         repeat_every_days=14, repeat_times=3)
    db.commit()
    _run(db, first, FakePublisher())
    pub.unschedule(db, ws["tenant"].id, item.id, ws["owner"].id)
    db.commit()
    assert db.query(MarketingPublishAttempt).filter_by(content_id=item.id, status="scheduled").count() == 0
    assert db.get(MarketingContent, item.id).status == "published"     # the first post went out

    other = _approved(db, ws)
    first = pub.schedule(db, ws["tenant"], other.id, datetime.now(timezone.utc), ws["owner"].id,
                         repeat_every_days=14, repeat_times=3)
    db.commit()
    _run(db, first, FakePublisher())
    svc.add_version(db, ws["tenant"].id, other.id, {"caption": "changed"}, origin="human", actor_id=ws["mkt"].id)
    db.commit()
    assert db.query(MarketingPublishAttempt).filter_by(content_id=other.id, status="scheduled").count() == 0


def test_schedule_api_takes_repeat_and_shows_runs(client, db, ws):  # noqa: F811
    item = _approved(db, ws)
    bad = client.post(f"{BASE}/content/{item.id}/schedule", json={"repeat_every_days": 7, "repeat_times": 2}, headers=ws["manager_h"])
    assert bad.status_code == 422
    assert client.post(f"{BASE}/content/{item.id}/schedule", json={"repeat_every_days": 28, "repeat_times": 2},
                       headers=ws["mkt_h"]).status_code == 403
    r = client.post(f"{BASE}/content/{item.id}/schedule", json={"repeat_every_days": 28, "repeat_times": 2}, headers=ws["manager_h"])
    assert r.status_code == 200, r.text
    a = client.get(f"{BASE}/content/{item.id}/publishing", headers=ws["mkt_h"]).json()["attempts"][0]
    assert (a["run"], a["repeat_every_days"], a["repeat_left"]) == (0, 28, 2)


def test_repeats_stay_in_their_workspace(db, ws, tenant_and_user):  # noqa: F811
    from app.models.tenant import Tenant
    item = _approved(db, ws)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    with pytest.raises(svc.MarketingError):
        pub.schedule(db, other, item.id, datetime.now(timezone.utc), ws["owner"].id, repeat_every_days=28, repeat_times=1)
