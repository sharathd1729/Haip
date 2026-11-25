"""Instagram automation options added for ReplyRush parity (Nov 2026): public reply only, @mention comments, opening DM
always, once per post, reply delay, photo/video + shared post after the final message, email-only forms, answering a
post's existing comments, and the media upload / send-existing endpoints."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models.automation import AutomationRule
from app.models.conversation import Message
from app.models.ig_automation import IgAutomationEvent
from app.schemas.ig_automation import validate_ig_rule
from app.services import ig_automation, ig_send_existing
from app.services.ig_keyword_match import find_matching_rule
from app.services.ig_quick_reply import dispatch_quick_reply
from tests.test_ig_automations import FakeIG, _guest, _kinds, _rule, _tenant


class FakeIGPlus(FakeIG):
    def __init__(self, comments=None, media=None):
        super().__init__()
        self.comments, self.media = comments or {}, media or []

    def send_media(self, rid, kind, url): return self._ok("media", rid, kind, url)
    def send_post(self, rid, media_id): return self._ok("post", rid, media_id)
    def list_comments(self, media_id, limit=50, after=None): return self.comments.get(media_id, []), None
    def get_recent_media(self, limit=12): return self.media


@pytest.fixture
def ig(monkeypatch):
    fake = FakeIGPlus()
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: fake)
    return fake


def _run(db, t, g, c, r, comment_id="cm1", media_id="m1"):
    return dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id,
                                comment_id=comment_id, media_id=media_id)


# ── Config validation ───────────────────────────────────────────────────────

def test_public_reply_only_needs_a_comment_trigger_and_a_reply_but_no_message():
    tc, ac = validate_ig_rule("ig_comment_received", {"reply_all": True}, {"send_dm": False, "public_ack_pool": ["Thanks!"]})
    assert ac["send_dm"] is False and ac["message"] == ""
    with pytest.raises(ValueError, match="works for comments"):
        validate_ig_rule("ig_dm_received", {"reply_all": True}, {"send_dm": False, "public_ack_pool": ["Hi"]})
    with pytest.raises(ValueError, match="at least one public reply"):
        validate_ig_rule("ig_comment_received", {"reply_all": True}, {"send_dm": False})
    with pytest.raises(ValidationError, match="Write the message"):
        validate_ig_rule("ig_comment_received", {"reply_all": True}, {"message": " "})


def test_mention_needs_no_keyword_and_only_applies_to_comments():
    tc, _ = validate_ig_rule("ig_comment_received", {"mention_only": True}, {"message": "Hi"})
    assert tc["mention_only"] is True
    tc, _ = validate_ig_rule("ig_dm_received", {"mention_only": True, "keywords": ["hi"]}, {"message": "Hi"})
    assert tc["mention_only"] is False


def test_attachment_must_be_this_workspaces_upload_and_forms_may_skip_the_phone():
    att = {"attachment": {"kind": "image", "key": "other-tenant/ig_automations/x.jpg"}}
    with pytest.raises(ValueError, match="Upload the photo"):
        validate_ig_rule("ig_comment_received", {"reply_all": True}, {"message": "Hi", **att}, "mine")
    _, ac = validate_ig_rule("ig_comment_received", {"reply_all": True},
                             {"message": "Hi", "attachment": {"kind": "image", "key": "mine/ig_automations/x.jpg"}}, "mine")
    assert ac["attachment"]["key"] == "mine/ig_automations/x.jpg"
    form = {"enabled": True, "questions": [{"key": "email", "text": "Your email?"}]}
    assert validate_ig_rule("ig_comment_received", {"reply_all": True}, {"message": "Hi", "form": form})
    with pytest.raises(ValidationError, match="only once"):
        validate_ig_rule("ig_comment_received", {"reply_all": True}, {"message": "Hi", "form": {
            "enabled": True, "questions": [{"key": "phone", "text": "No?"}, {"key": "phone", "text": "No 2?"}]}})
    with pytest.raises(ValueError, match="Pick the post"):
        validate_ig_rule("ig_dm_received", {"reply_all": True}, {"message": "Hi", "share_post": {"enabled": True}})


# ── Engine ──────────────────────────────────────────────────────────────────

def test_public_reply_only_sends_no_dm_and_counts_once_per_person(db, ig):
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, ac={"send_dm": False, "message": "", "public_ack_pool": ["Thank you! ❤️"]})
    assert _run(db, t, g, c, r) is True
    assert ig.names() == ["public"]
    assert db.query(Message).filter_by(conversation_id=c.id).count() == 0
    assert _run(db, t, g, c, r, comment_id="cm2") is False          # once per person: no second public reply
    assert ig.names() == ["public"]


def test_a_mention_rule_fires_only_on_comments_that_tag_someone_and_beats_any_comment(db):
    t = _tenant(db)
    every = _rule(db, t.id, tc={"reply_all": True, "scope": "post", "media_id": "m1"})
    tag = _rule(db, t.id, tc={"mention_only": True, "scope": "post", "media_id": "m1"})
    assert find_matching_rule(db, t.id, "ig_comment_received", "@meera.k we should go!", media_id="m1").id == tag.id
    assert find_matching_rule(db, t.id, "ig_comment_received", "mail me at a@b.com", media_id="m1").id == every.id
    assert find_matching_rule(db, t.id, "ig_comment_received", "lovely", media_id="m1").id == every.id


def test_opener_always_starts_with_the_tap_and_extras_follow_the_final_message(db, ig, monkeypatch):
    monkeypatch.setattr("app.services.media_storage.get_presigned_media_url", lambda key, expires_in=3600: f"https://r2/{key}")
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, ac={"opener_always": True, "attachment": {"kind": "video", "key": f"{t.id}/ig_automations/v.mp4"},
                            "share_post": {"enabled": True}})
    _run(db, t, g, c, r, media_id="m9")
    assert ig.calls[-1][0] == "private" and ig.calls[-1][3][0]["payload"] == f"igauto:{r.id}:open"
    ig_automation.handle_payload(db, t.id, f"igauto:{r.id}:open", recipient_id="igsid", guest_id=g.id,
                                 conversation_id=c.id, guest=g)
    assert ig.names()[-3:] == ["text", "media", "post"]
    assert ig.calls[-2][2:] == ("video", f"https://r2/{t.id}/ig_automations/v.mp4")
    assert ig.calls[-1][2] == "m9"                                    # the post they commented on
    assert {"media_sent", "post_shared"} <= set(_kinds(db, r))
    bodies = {m.body for m in db.query(Message).filter_by(conversation_id=c.id)}
    assert {"[Video]", "[Shared post]"} <= bodies


def test_once_per_post_lets_the_same_person_get_one_dm_per_post(db, ig):
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, tc={"reply_all": True}, ac={"once_per_post": True})
    assert _run(db, t, g, c, r, "cm1", "m1") is True
    assert _run(db, t, g, c, r, "cm2", "m1") is False
    assert _run(db, t, g, c, r, "cm3", "m2") is True


def test_a_delay_queues_the_answer_instead_of_sending(db, ig, monkeypatch):
    queued = []
    from app.workers.tasks import ig_automation_tasks
    monkeypatch.setattr(ig_automation_tasks.start_delayed, "apply_async", lambda kwargs, countdown: queued.append((kwargs, countdown)))
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, ac={"delay_seconds": 90})
    assert _run(db, t, g, c, r) is True
    assert ig.calls == [] and queued[0][1] == 90 and queued[0][0]["comment_id"] == "cm1"
    assert _kinds(db, r) == ["delayed"]
    # the task runs it for real later
    assert dispatch_quick_reply(db, t.id, r, delayed=True, **{k: v for k, v in queued[0][0].items()
                                                             if k not in ("tenant_id", "rule_id")}) is True
    assert ig.names() == ["public", "private"]


# ── Existing comments ──────────────────────────────────────────────────────

def test_send_existing_answers_matching_recent_comments_once_and_skips_ours_and_old_ones(db, ig, monkeypatch):
    queued = []
    from app.workers.tasks import process_instagram_comment as pic
    monkeypatch.setattr(pic.process_instagram_comment, "delay", lambda payload: queued.append(payload))
    t = _tenant(db)
    g, c = _guest(db, t.id)
    now = datetime.now(timezone.utc)
    ts = lambda d: (now - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    db.add(Message(tenant_id=t.id, conversation_id=c.id, direction="inbound", channel="instagram", body="price?",
                   channel_message_id="comment_c1"))
    db.commit()
    ig.comments = {"m1": [
        {"id": "c1", "text": "price?", "timestamp": ts(1), "from": {"id": "igsid"}},           # stored: answered now
        {"id": "c2", "text": "PRICE pls", "timestamp": ts(2), "from": {"id": "new"}, "username": "kiran"},  # unseen
        {"id": "c3", "text": "lovely", "timestamp": ts(1), "from": {"id": "x"}},              # no keyword
        {"id": "c4", "text": "price", "timestamp": ts(1), "from": {"id": "1784"}},            # our own reply
        {"id": "c5", "text": "price", "timestamp": ts(9), "from": {"id": "y"}},               # older than 7 days
    ]}
    r = _rule(db, t.id, tc={"keywords": ["price"], "scope": "post", "media_id": "m1"})
    out = ig_send_existing.run(db, t.id, r.id, now=now)
    assert out["status"] == "done" and out["matched"] == 2 and out["answered"] == 1 and out["queued"] == 1
    assert ig.names() == ["public", "private"] and ig.calls[1][1] == "c1"
    assert queued[0]["backfill"] is True and queued[0]["comment_id"] == "c2" and queued[0]["sender_username"] == "kiran"


def test_send_existing_is_for_this_workspaces_comment_rules_only(db, ig):
    t = _tenant(db)
    dm = _rule(db, t.id, trigger="ig_dm_received")
    assert ig_send_existing.run(db, t.id, dm.id)["status"] == "not_a_comment_automation"
    other = _tenant(db)
    mine = _rule(db, t.id)
    assert ig_send_existing.run(db, other.id, mine.id)["status"] == "not_a_comment_automation"


# ── Endpoints ───────────────────────────────────────────────────────────────

def _headers(db, tenant_id, role):
    from app.core.security import create_access_token, get_password_hash
    from app.models.user import User
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="P", email=f"{uuid.uuid4().hex[:8]}@t.com",
             hashed_password=get_password_hash("pw-123456789"), role=role, is_active=True)
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'tenant_id': tenant_id, 'role': role.value})}"}


def test_send_existing_endpoint_roles_and_isolation(client, db, monkeypatch):
    from app.models.user import UserRole
    from app.workers.tasks import ig_automation_tasks
    sent = []
    monkeypatch.setattr(ig_automation_tasks.send_existing, "delay", lambda *a: sent.append(a))
    t, other = _tenant(db), _tenant(db)
    r = _rule(db, t.id)
    url = f"/api/v1/instagram/automations/{r.id}/send-existing"
    assert client.post(url, headers=_headers(db, t.id, UserRole.CONCIERGE)).status_code == 403
    assert client.post(url, headers=_headers(db, other.id, UserRole.OWNER)).status_code == 404
    assert client.post(url, headers=_headers(db, t.id, UserRole.OWNER)).status_code == 202
    assert sent == [(t.id, r.id)]


def test_media_upload_accepts_photos_and_videos_only(client, db, monkeypatch):
    from app.models.user import UserRole
    monkeypatch.setattr("app.services.media_storage.upload_ig_automation_media",
                        lambda tid, content, ct, ext: f"{tid}/ig_automations/x.{ext}")
    monkeypatch.setattr("app.services.media_storage.get_presigned_media_url", lambda key, expires_in=3600: "https://r2/x")
    t = _tenant(db)
    h = _headers(db, t.id, UserRole.MANAGER)
    url = "/api/v1/instagram/automations/media"
    r = client.post(url, headers=h, files={"file": ("a.jpg", b"\xff\xd8\xff\xe0" + b"0" * 100, "image/jpeg")})
    assert r.status_code == 200 and r.json()["kind"] == "image" and r.json()["key"].startswith(f"{t.id}/ig_automations/")
    r = client.post(url, headers=h, files={"file": ("v.mp4", b"\x00\x00\x00\x18ftypisom" + b"0" * 100, "video/mp4")})
    assert r.status_code == 200 and r.json()["kind"] == "video"
    assert client.post(url, headers=h, files={"file": ("a.gif", b"GIF89a....", "image/gif")}).status_code == 400
    assert client.post(url, headers=_headers(db, t.id, UserRole.CONCIERGE),
                       files={"file": ("a.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")}).status_code == 403


def test_post_stats_count_per_post_and_stay_in_the_workspace(client, db):
    from app.models.user import UserRole
    t, other = _tenant(db), _tenant(db)
    g, c = _guest(db, t.id)
    mine = _rule(db, t.id, tc={"keywords": ["price"], "scope": "post", "media_id": "m1"})
    _rule(db, t.id, tc={"reply_all": True})                          # an "any post" automation
    for kind, media in (("triggered", "m1"), ("dm_sent", "m1"), ("public_reply", "m1"), ("clicked", None)):
        db.add(IgAutomationEvent(tenant_id=t.id, rule_id=mine.id, kind=kind, guest_id=g.id if kind != "clicked" else None,
                                 media_id=media))
    db.add(IgAutomationEvent(tenant_id=t.id, rule_id=mine.id, kind="opened", guest_id=g.id))
    db.add(IgAutomationEvent(tenant_id=other.id, rule_id="x", kind="dm_sent", media_id="m1"))
    db.commit()
    r = client.get("/api/v1/instagram/automations/posts", params={"ids": "m1,m2"}, headers=_headers(db, t.id, UserRole.OWNER))
    assert r.status_code == 200
    m1, m2 = r.json()["posts"]["m1"], r.json()["posts"]["m2"]
    assert m1["rules"] == [mine.id] and m1["sent"] == 1 and m1["public_replies"] == 1 and m1["people"] == 1
    assert m1["opened"] == 1 and m1["clicks"] == 1
    assert m2["rules"] == [] and m2["covered_by_any"] is True and m2["sent"] == 0
    assert client.get("/api/v1/instagram/automations/posts", params={"ids": "m1"},
                      headers=_headers(db, t.id, UserRole.CONCIERGE)).status_code == 403


def test_media_insights_ask_in_groups_and_leave_refused_metrics_empty(client, db, monkeypatch):
    from app.models.user import UserRole

    class Fake(FakeIGPlus):
        def get_media_insights(self, media_id, metrics):
            if "follows" in metrics:
                raise RuntimeError("not for reels")
            return {m: 7 for m in metrics}
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: Fake())
    t = _tenant(db)
    h = _headers(db, t.id, UserRole.OWNER)
    r = client.get("/api/v1/instagram/media/1789/insights", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["views"] == 7 and body["saves"] == 7 and body["interactions"] == 7 and body["follows"] is None
    assert client.get("/api/v1/instagram/media/..%2Fme/insights", headers=h).status_code in (404, 422)
    assert client.get("/api/v1/instagram/media/1789/insights", headers=_headers(db, t.id, UserRole.CONCIERGE)).status_code == 403
