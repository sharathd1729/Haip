"""Instagram automations (services/ig_automation.py, ig_keyword_match scopes, endpoints/instagram_automations.py).

A comment is answered with Meta's private reply (a plain DM to someone who only commented is refused), once per person;
a button or follow gate goes through a "Send it" tap; the follow gate asks up to max_asks; links are tracked; stats count.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.ig_automation import IgAutomationEvent, IgTrackedLink
from app.models.tenant import Tenant
from app.services import ig_automation, ig_next_post
from app.services.ig_keyword_match import find_matching_rule
from app.services.ig_quick_reply import dispatch_quick_reply


class FakeIG:
    def __init__(self, follows=None):
        self.calls, self.follows, self._account_id = [], follows, "1784"

    def _ok(self, name, *args):
        self.calls.append((name, *args))
        return {"message_id": f"mid.{len(self.calls)}"}

    def reply_to_comment(self, comment_id, text): return self._ok("public", comment_id, text)
    def send_private_reply(self, comment_id, text, quick=None): return self._ok("private", comment_id, text, quick)
    def send_quick_replies(self, rid, text, quick): return self._ok("quick", rid, text, quick)
    def send_text(self, rid, text): return self._ok("text", rid, text)
    def send_link_button(self, rid, text, title, url): return self._ok("button", rid, text, title, url)
    def follows_us(self, rid): return self.follows

    def names(self): return [c[0] for c in self.calls]


@pytest.fixture
def ig(monkeypatch):
    fake = FakeIG()
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: fake)
    return fake


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t


def _guest(db, tenant_id, name="@asha.travels"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name)
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, channel=ChannelType.INSTAGRAM)
    db.add_all([g, c])
    db.commit()
    return g, c


def _rule(db, tenant_id, trigger="ig_comment_received", tc=None, ac=None):
    r = AutomationRule(id=str(uuid.uuid4()), tenant_id=tenant_id, name="PRICE reel", trigger=trigger,
                       trigger_config=tc if tc is not None else {"keywords": ["price"]},
                       action="send_instagram_quick_reply",
                       action_config={"message": "Hi {first_name}, prices: ₹12,000/night", **(ac or {})},
                       is_active=True, run_count=0)
    db.add(r)
    db.commit()
    return r


def _kinds(db, rule):
    return [e.kind for e in db.query(IgAutomationEvent).filter_by(rule_id=rule.id).order_by(IgAutomationEvent.created_at)]


def test_a_comment_gets_a_public_reply_and_a_private_reply_never_a_plain_dm(db, ig):
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id)
    assert dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id,
                                comment_id="cm1", media_id="m1") is True
    assert ig.names() == ["public", "private"] and "text" not in ig.names()
    assert ig.calls[1][2] == "Hi asha.travels, prices: ₹12,000/night"
    out = db.query(Message).filter_by(conversation_id=c.id).one()
    assert out.sender_kind == "automation" and out.channel_message_id == "mid.2"
    assert _kinds(db, r) == ["triggered", "public_reply", "dm_sent"]

    # the same person comments again: once per person
    assert dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id,
                                comment_id="cm2", media_id="m1") is False
    assert ig.names() == ["public", "private"]
    assert db.query(IgAutomationEvent).filter_by(rule_id=r.id, kind="skipped").one().detail == "already_sent_to_this_person"


def test_a_button_goes_through_a_tap_and_the_link_is_tracked(db, ig, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "API_BASE_URL", "https://genhaip.com")
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, ac={"button": {"title": "See packages", "url": "https://ratha.in/packages"},
                            "opener": "Tap below 👇", "opener_button": "Send it"})
    dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, comment_id="cm1")
    name, comment_id, text, quick = ig.calls[-1]
    assert name == "private" and text == "Tap below 👇" and quick[0]["payload"] == f"igauto:{r.id}:open"

    assert ig_automation.handle_payload(db, t.id, f"igauto:{r.id}:open", recipient_id="igsid", guest_id=g.id,
                                        conversation_id=c.id, guest=g) is True
    name, _, _, title, url = ig.calls[-1]
    link = db.query(IgTrackedLink).filter_by(rule_id=r.id).one()
    assert name == "button" and title == "See packages" and url == f"https://genhaip.com/api/v1/l/{t.slug}/{link.code}"
    # a second tap sends nothing more
    n = len(ig.calls)
    ig_automation.handle_payload(db, t.id, f"igauto:{r.id}:open", recipient_id="igsid", guest_id=g.id, conversation_id=c.id)
    assert len(ig.calls) == n and _kinds(db, r).count("link_sent") == 1


@pytest.mark.parametrize("send_anyway,expect_final", [(True, True), (False, False)])
def test_the_follow_gate_asks_up_to_max_asks_then_sends_anyway_or_stops(db, ig, send_anyway, expect_final):
    ig.follows = False
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, trigger="ig_dm_received",
              ac={"follow_gate": {"enabled": True, "max_asks": 2, "send_anyway": send_anyway}})
    dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id)
    assert ig.calls[-1][0] == "quick"                      # the opener (no comment: a normal quick-reply DM)
    for step in ("open", "followed", "followed"):
        ig_automation.handle_payload(db, t.id, f"igauto:{r.id}:{step}", recipient_id="igsid", guest_id=g.id,
                                     conversation_id=c.id)
    assert _kinds(db, r).count("gate_asked") == 2
    assert ("text" in ig.names()) is expect_final


def test_a_follower_gets_the_message_at_once_and_an_unknown_answer_trusts_the_tap(db, ig):
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, trigger="ig_dm_received", ac={"follow_gate": {"enabled": True}})
    ig.follows = True
    ig_automation.handle_payload(db, t.id, f"igauto:{r.id}:open", recipient_id="igsid", guest_id=g.id, conversation_id=c.id)
    assert ig.calls[-1][0] == "text" and "followed" in _kinds(db, r)

    g2, c2 = _guest(db, t.id, name="IG User 123456")
    ig.follows = None                                       # Meta will not say
    ig_automation.handle_payload(db, t.id, f"igauto:{r.id}:followed", recipient_id="igsid2", guest_id=g2.id,
                                 conversation_id=c2.id, guest=g2)
    assert ig.calls[-1] == ("text", "igsid2", "Hi there, prices: ₹12,000/night")


def test_hourly_cap_and_stop_skip(db, ig, monkeypatch):
    monkeypatch.setattr(ig_automation, "GUEST_HOURLY_CAP", 1)
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r1, r2 = _rule(db, t.id), _rule(db, t.id, tc={"keywords": ["menu"]})
    dispatch_quick_reply(db, t.id, r1, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, comment_id="c1")
    dispatch_quick_reply(db, t.id, r2, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, comment_id="c2")
    assert db.query(IgAutomationEvent).filter_by(rule_id=r2.id, kind="skipped").one().detail == "person_hourly_cap"


def test_matching_scopes_ads_live_stories_and_ad_chats(db):
    t, other = _tenant(db), _tenant(db)
    any_post = _rule(db, t.id, tc={"keywords": ["price"], "scope": "any"})
    this_post = _rule(db, t.id, tc={"reply_all": True, "scope": "post", "media_id": "m1"})
    this_ad = _rule(db, t.id, tc={"keywords": ["price"], "ad_id": "ad9"})
    live = _rule(db, t.id, trigger="ig_live_comment_received", tc={"keywords": ["link"]})
    story = _rule(db, t.id, trigger="ig_story_reply_received", tc={"reply_all": True})
    mention = _rule(db, t.id, trigger="ig_story_mention_received", tc={"reply_all": True})
    ad_chat = _rule(db, t.id, trigger="ig_ad_chat_started", tc={})
    _rule(db, other.id, tc={"keywords": ["price"], "scope": "any"})

    assert find_matching_rule(db, t.id, "ig_comment_received", "nice!", media_id="m1") == this_post
    assert find_matching_rule(db, t.id, "ig_comment_received", "price?", media_id="m2") == any_post
    assert find_matching_rule(db, t.id, "ig_comment_received", "price?", media_id="m3", ad_id="ad9") == this_ad
    assert find_matching_rule(db, t.id, "ig_comment_received", "hello", media_id="m2") is None
    assert find_matching_rule(db, t.id, "ig_live_comment_received", "send the link", media_id="L1") == live
    assert find_matching_rule(db, t.id, "ig_story_reply_received", "😍") == story
    assert find_matching_rule(db, t.id, "ig_story_mention_received", "[Story mention]") == mention
    assert find_matching_rule(db, t.id, "ig_ad_chat_started", "", ad_id="ad1") == ad_chat
    assert find_matching_rule(db, other.id, "ig_comment_received", "hello", media_id="m1") is None


def test_a_next_post_rule_binds_to_the_first_newer_post_once(db, ig, monkeypatch):
    t = _tenant(db)
    r = _rule(db, t.id, tc={"keywords": ["price"], "scope": "next_post"})
    made = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
    times = {"old": made - timedelta(days=2), "new": made + timedelta(hours=1), "newer": made + timedelta(days=1)}
    monkeypatch.setattr(ig_next_post, "_media_time", lambda db, tenant_id, media_id: times[media_id])
    ig_next_post.bind_next_post(db, t.id, "old")
    assert not (db.get(AutomationRule, r.id).trigger_config or {}).get("media_id")
    ig_next_post.bind_next_post(db, t.id, "new")
    ig_next_post.bind_next_post(db, t.id, "newer")
    assert db.get(AutomationRule, r.id).trigger_config["media_id"] == "new"
    assert find_matching_rule(db, t.id, "ig_comment_received", "price", media_id="new").id == r.id


def test_dm_task_routes_a_tap_to_the_automation_not_the_ai(db, monkeypatch):
    from sqlalchemy.orm import Session as SASession

    from app.core.encryption import encrypt_credentials
    from app.models.integration import Integration
    from app.workers.tasks import process_instagram_dm as task

    t = _tenant(db)
    db.add(Integration(tenant_id=t.id, kind="instagram", status="active",
                       config={"instagram_business_account_id": "1784"},
                       credentials_kms_blob=encrypt_credentials({"access_token": "tok"})))
    db.commit()
    r = _rule(db, t.id, trigger="ig_dm_received", ac={"button": {"title": "Open", "url": "https://x.in"}})
    seen = []
    monkeypatch.setattr(task, "SessionLocal", lambda: SASession(bind=db.connection()))
    monkeypatch.setattr(ig_automation, "handle_payload", lambda db, tenant_id, payload, **kw: seen.append(payload) or True)
    monkeypatch.setattr("app.services.ig_keyword_match.find_matching_rule",
                        lambda *a, **k: pytest.fail("a tap must not be keyword-matched"))
    task.process_instagram_dm.run({"ig_account_id": "1784", "sender_id": "igsid", "message_id": "mid.tap",
                                   "text": "Send it", "quick_reply_payload": f"igauto:{r.id}:open"})
    assert seen == [f"igauto:{r.id}:open"]


# ── endpoints ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _auth(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def test_create_rule_validates_the_instagram_config(client, tenant_and_user):
    base = {"name": "PRICE", "trigger": "ig_comment_received", "action": "send_instagram_quick_reply"}
    bad = client.post("/api/v1/automations", headers=_auth(tenant_and_user), json={
        **base, "trigger_config": {"keywords": ["price"]},
        "action_config": {"message": "hi", "button": {"title": "Go", "url": "http://x.in"}}})
    assert bad.status_code == 422 and "https" in bad.json()["detail"]
    nokw = client.post("/api/v1/automations", headers=_auth(tenant_and_user), json={
        **base, "trigger_config": {}, "action_config": {"message": "hi"}})
    assert nokw.status_code == 422
    ok = client.post("/api/v1/automations", headers=_auth(tenant_and_user), json={
        **base, "trigger_config": {"keywords": "price, rates", "media_id": "m1"}, "action_config": {"message": "hi"}})
    assert ok.status_code == 201
    body = ok.json()
    assert body["trigger_config"]["scope"] == "post" and body["trigger_config"]["keywords"] == ["price", "rates"]
    assert body["action_config"]["once_per_person"] is True


def test_stats_count_per_automation_and_stay_in_the_workspace(client, db, tenant_and_user):
    t = tenant_and_user["tenant"]
    other = _tenant(db)
    r = _rule(db, t.id)
    g, _ = _guest(db, t.id)
    for kind in ("triggered", "dm_sent", "link_sent", "clicked"):
        db.add(IgAutomationEvent(tenant_id=t.id, rule_id=r.id, guest_id=g.id, kind=kind))
    db.add(IgAutomationEvent(tenant_id=other.id, rule_id=r.id, kind="clicked"))
    g.lead_identified_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    db.commit()
    res = client.get("/api/v1/instagram/automations/stats", headers=_auth(tenant_and_user))
    assert res.status_code == 200
    s = res.json()["automations"][0]
    assert (s["triggered"], s["dm_sent"], s["link_sent"], s["clicked"], s["people"], s["leads"]) == (1, 1, 1, 1, 1, 1)


def test_stats_and_media_need_owner_or_manager(client, db, tenant_and_user):
    from app.core.security import create_access_token
    from app.models.user import User, UserRole
    t = tenant_and_user["tenant"]
    u = User(id=str(uuid.uuid4()), tenant_id=t.id, name="FOH", email=f"f{uuid.uuid4().hex[:6]}@x.in",
             hashed_password="x", role=UserRole.FOH, is_active=True)
    db.add(u)
    db.commit()
    h = {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'tenant_id': t.id, 'role': u.role.value})}"}
    assert client.get("/api/v1/instagram/automations/stats", headers=h).status_code == 403
    assert client.get("/api/v1/instagram/media", headers=h).status_code == 403


def test_tracked_link_counts_the_click_and_redirects_only_known_codes(client, db):
    t = _tenant(db)
    db.add(IgTrackedLink(tenant_id=t.id, rule_id="r1", code="abc123", target_url="https://ratha.in/p"))
    db.commit()
    res = client.get(f"/api/v1/l/{t.slug}/abc123", follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"] == "https://ratha.in/p"
    assert db.query(IgAutomationEvent).filter_by(tenant_id=t.id, kind="clicked").count() == 1
    assert client.get(f"/api/v1/l/{t.slug}/nope", follow_redirects=False).status_code == 404
    other = _tenant(db)
    assert client.get(f"/api/v1/l/{other.slug}/abc123", follow_redirects=False).status_code == 404


def test_connect_still_subscribes_dms_if_meta_refuses_live_comments(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from app.adapters.instagram import meta_graph
    sent = []

    def post(url, data=None, **k):
        sent.append(data["subscribed_fields"])
        ok = "live_comments" not in data["subscribed_fields"]
        return SimpleNamespace(status_code=200 if ok else 400, content=b"x",
                               json=lambda: {"success": True} if ok else {"error": {"message": "Invalid field"}})
    monkeypatch.setattr(httpx, "post", post)
    assert meta_graph.subscribe_webhooks("IGtok") == (True, "")
    assert sent == [meta_graph.WEBHOOK_FIELDS, "messages,messaging_postbacks,messaging_referral,comments,messaging_seen"]


def test_a_refused_button_reply_falls_back_to_the_whole_message_as_text(db, ig, monkeypatch):
    """Meta answered a private reply carrying a tap button with a 500 (seen live). The comment's one private reply is
    still unused, so the person gets the full message + tracked link as plain text instead of nothing."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "API_BASE_URL", "https://genhaip.com")
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, ac={"button": {"title": "See packages", "url": "https://ratha.in/packages"}, "opener": "Tap below"})
    real = ig.send_private_reply

    def refuse_buttons(comment_id, text, quick=None):
        if quick:
            raise RuntimeError("Instagram 500: An unknown error has occurred. code 1")
        return real(comment_id, text, quick)

    monkeypatch.setattr(ig, "send_private_reply", refuse_buttons)
    assert dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, comment_id="cm1")
    name, _, text, quick = ig.calls[-1]
    link = db.query(IgTrackedLink).filter_by(rule_id=r.id).one()
    assert name == "private" and quick is None and "prices" in text and text.endswith(f"/l/{t.slug}/{link.code}")
    assert _kinds(db, r)[-2:] == ["dm_sent", "link_sent"]


def test_instagram_errors_never_carry_the_access_token(monkeypatch):
    import httpx

    from app.adapters.instagram.meta_graph import InstagramGraphAdapter

    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        seen.update(url=url, headers=headers, kw=kw)
        body = {"error": {"message": "An unknown error has occurred.", "code": 1, "error_subcode": 99}}
        return httpx.Response(500, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    adapter = InstagramGraphAdapter(access_token="IGAATsecret123", ig_account_id="1784")
    with pytest.raises(httpx.HTTPStatusError) as err:
        adapter.send_private_reply("cm1", "hello")
    assert "IGAATsecret123" not in str(err.value) and "IGAATsecret123" not in seen["url"] and "params" not in seen["kw"]
    assert seen["headers"]["Authorization"] == "Bearer IGAATsecret123"
    assert str(err.value) == "Instagram 500: An unknown error has occurred. code 1/99"
    assert err.value.response.status_code == 500


def test_the_same_comment_delivered_twice_is_answered_once(db, ig, monkeypatch):
    from app.core import cache
    seen = set()
    monkeypatch.setattr(cache, "idem_check_and_set", lambda key, ttl=0: not (key in seen or seen.add(key)))
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, ac={"once_per_person": False})
    for _ in range(2):
        dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, comment_id="cm-dup")
    assert ig.names().count("private") == 1 and ig.names().count("public") == 1
    assert _kinds(db, r).count("skipped") == 1


def test_already_answered_comment_is_a_skip_not_a_failure(db, ig, monkeypatch):
    t = _tenant(db)
    g, c = _guest(db, t.id)
    r = _rule(db, t.id, ac={"button": {"title": "See", "url": "https://ratha.in/p"}})
    calls = []

    def already(comment_id, text, quick=None):
        calls.append(quick)
        raise RuntimeError("Instagram 500: The comment you are trying to reply to already has a reply. code -1/2534023")

    monkeypatch.setattr(ig, "send_private_reply", already)
    assert not dispatch_quick_reply(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, comment_id="cm9")
    assert len(calls) == 1                                 # no plain-text retry: the comment's one reply is used up
    kinds = _kinds(db, r)
    assert "skipped" in kinds and "dm_failed" not in kinds
