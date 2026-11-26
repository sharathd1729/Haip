"""Second ReplyRush parity round (Nov 2026): global triggers, random messages, quick replies, swipeable cards + saved
card library, caption-code automations, default reply, pause all automations."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.ig_automation import IgAutomationEvent
from app.models.tenant import Tenant
from app.schemas.ig_automation import validate_ig_rule
from app.services import ig_automation
from app.services.ig_keyword_match import caption_has_code, find_matching_rule
from app.services.ig_quick_reply import dispatch_quick_reply
from tests.test_ig_automation_gaps import FakeIGPlus, _headers
from tests.test_ig_automations import _guest, _kinds, _rule, _tenant


class FakeCards(FakeIGPlus):
    def send_cards(self, rid, elements): return self._ok("cards", rid, elements)


@pytest.fixture
def ig(monkeypatch):
    fake = FakeCards()
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: fake)
    return fake


def test_a_global_automation_answers_where_it_is_switched_on_after_the_specific_ones(db):
    t = _tenant(db)
    glob = _rule(db, t.id, trigger="ig_global", tc={"keywords": ["price"], "surfaces": ["comment", "dm"]})
    assert find_matching_rule(db, t.id, "ig_dm_received", "price?").id == glob.id
    assert find_matching_rule(db, t.id, "ig_comment_received", "price pls", media_id="m1").id == glob.id
    assert find_matching_rule(db, t.id, "ig_story_reply_received", "price") is None       # not a chosen place
    own = _rule(db, t.id, trigger="ig_dm_received", tc={"keywords": ["price"]})
    assert find_matching_rule(db, t.id, "ig_dm_received", "price").id == own.id            # the specific one wins
    with pytest.raises(ValueError, match="Pick where"):
        validate_ig_rule("ig_global", {"keywords": ["x"]}, {"message": "Hi"})


def test_caption_code_automations_run_on_posts_that_carry_the_code(db):
    t = _tenant(db)
    r = _rule(db, t.id, tc={"reply_all": True, "scope": "caption_code", "caption_code": "jade1"})
    assert r.trigger_config["caption_code"] == "jade1"  # stored as given by the test helper; the schema upper-cases
    tc, _ = validate_ig_rule("ig_comment_received", {"reply_all": True, "scope": "caption_code", "caption_code": "#jade1"},
                             {"message": "Hi"})
    assert tc["caption_code"] == "JADE1"
    assert caption_has_code("Weekend villa #JADE1 comment PRICE", "JADE1")
    assert not caption_has_code("JADE12 offer", "JADE1")
    assert find_matching_rule(db, t.id, "ig_comment_received", "nice", media_id="m1", caption="Book now #JADE1").id == r.id
    assert find_matching_rule(db, t.id, "ig_comment_received", "nice", media_id="m1", caption="no code here") is None
    with pytest.raises(ValueError, match="caption code"):
        validate_ig_rule("ig_comment_received", {"reply_all": True, "scope": "caption_code", "caption_code": "x"}, {"message": "Hi"})


def test_the_default_reply_answers_anything_not_excluded(db):
    t = _tenant(db)
    d = _rule(db, t.id, trigger="ig_dm_default", tc={"exclude_keywords": ["stop"]})
    assert find_matching_rule(db, t.id, "ig_dm_default", "hello?").id == d.id
    assert find_matching_rule(db, t.id, "ig_dm_default", "stop it") is None


def test_random_messages_and_quick_replies_on_the_final_message(db, ig, monkeypatch):
    monkeypatch.setattr("random.choice", lambda seq: seq[-1])
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, trigger="ig_dm_received", tc={"keywords": ["menu"]},
              ac={"message_variants": ["Hello {first_name}, version two"],
                  "quick_replies": [{"title": "Prices", "reply": "Prices go out on a call."}, {"title": "Location", "reply": "Kanakapura road."}]})
    dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id)
    name, _, text, quick = ig.calls[-1]
    assert name == "quick" and text == "Hello asha.travels, version two"
    assert [q["payload"] for q in quick] == [f"igauto:{r.id}:qr:0", f"igauto:{r.id}:qr:1"]
    assert ig_automation.handle_payload(db, t.id, f"igauto:{r.id}:qr:1", recipient_id="igsid", guest_id=g.id,
                                        conversation_id=c.id, guest=g) is True
    assert ig.calls[-1][:3] == ("text", "igsid", "Kanakapura road.")
    assert "quick_reply" in _kinds(db, r)


def test_cards_go_out_after_the_final_message_with_tracked_links(db, ig, monkeypatch):
    monkeypatch.setattr("app.services.media_storage.get_presigned_media_url", lambda key, expires_in=3600: f"https://r2/{key}")
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, trigger="ig_dm_received", tc={"keywords": ["villas"]}, ac={"cards": [
        {"image_key": f"{t.id}/ig_automations/a.jpg", "title": "Tranquil Woods", "subtitle": "Pool villa",
         "buttons": [{"title": "See it", "url": "https://example.com/tw"}]}]})
    dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id)
    assert ig.names() == ["text", "cards"]
    el = ig.calls[-1][2][0]
    assert el["image_url"] == f"https://r2/{t.id}/ig_automations/a.jpg" and el["buttons"][0]["type"] == "web_url"
    with pytest.raises(ValueError, match="card images"):
        validate_ig_rule("ig_dm_received", {"keywords": ["x"]}, {"message": "Hi", "cards": [{"title": "A", "image_key": "x/ig_automations/a.jpg"}]}, t.id)


def test_pause_all_stops_every_automation_until_it_ends(client, db, ig):
    from app.models.user import UserRole
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id)
    h = _headers(db, t.id, UserRole.OWNER)
    assert client.put("/api/v1/instagram/automations/pause", json={"hours": 5}, headers=h).status_code == 422
    out = client.put("/api/v1/instagram/automations/pause", json={"hours": 24}, headers=h)
    assert out.status_code == 200 and out.json()["paused_until"]
    db.expire_all()
    assert dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, comment_id="cm1") is False
    assert db.query(IgAutomationEvent).filter_by(rule_id=r.id, kind="skipped").one().detail == "all_automations_paused"
    assert client.put("/api/v1/instagram/automations/pause", json={"hours": None}, headers=h).json()["paused_until"] is None
    db.expire_all()
    assert dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, comment_id="cm2") is True
    assert client.put("/api/v1/instagram/automations/pause", json={"hours": 1},
                      headers=_headers(db, t.id, UserRole.CONCIERGE)).status_code == 403


def test_card_library_saves_per_workspace(client, db):
    from app.models.user import UserRole
    t, other = _tenant(db), _tenant(db)
    h = _headers(db, t.id, UserRole.MANAGER)
    items = [{"name": "Villas", "cards": [{"title": "Tranquil Woods", "image_key": f"{t.id}/ig_automations/a.jpg"}]}]
    assert client.put("/api/v1/instagram/card-library", json={"items": items}, headers=h).status_code == 200
    assert client.get("/api/v1/instagram/card-library", headers=h).json()["items"][0]["name"] == "Villas"
    assert client.get("/api/v1/instagram/card-library", headers=_headers(db, other.id, UserRole.OWNER)).json()["items"] == []
    bad = [{"name": "X", "cards": [{"title": "A", "image_key": f"{other.id}/ig_automations/a.jpg"}]}]
    assert client.put("/api/v1/instagram/card-library", json={"items": bad}, headers=h).status_code == 422
