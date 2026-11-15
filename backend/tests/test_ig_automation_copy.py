"""Instagram toolkit phase 5: keyword-delivery DM rules, public-reply rules, the humanizer at send time, the one
follow-up, and the automations API checks."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.core.encryption import encrypt_credentials
from app.models.automation import AutomationRule, AutomationRun
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import ig_automation_copy as rules
from app.services import ig_quick_reply as qr
from tests.test_marketing_studio_content import make_user, ws  # noqa: F401  (fixture)

DM = "Here it is: the monsoon weekend dates, 12-14 and 19-21 July.\n\nReply with the weekend you like.\n\nWhich one suits you?"


def test_delivery_template_and_dm_rules():
    text = rules.delivery("the July dates", "Reply with the weekend you like.", "Which one suits you?", name="Ananya")
    assert text.startswith("Ananya, here it is: the July dates.") and rules.check_dm(text) == []
    gate = rules.check_dm("Before I send it, can I ask what you do? Then the dates.")
    assert gate[0]["rule"] == "gate" and gate[0]["status"] == "bad"
    assert {f["rule"] for f in rules.check_dm("Here are the dates. Unlock them now.")} == {"question", "stock"}


def test_public_reply_rules_block_selling_and_links():
    assert rules.check_public_reply("Sent you the dates.") == []
    assert rules.check_public_reply("Only Rs 9,000 a night, book now!")[0]["rule"] == "selling"
    assert any(f["rule"] == "link" for f in rules.check_public_reply("See nila.example for more"))
    text, _, why = rules.prepare_public("Price is in our bio link www.nila.example")
    assert text == rules.SAFE_PUBLIC_REPLY and why


def test_follow_up_window_is_clamped():
    assert rules.follow_up_hours({}) == 20 and rules.follow_up_hours({"follow_up_after_hours": 48}) == 23


def _setup(db, tenant_id, trigger="ig_dm_received", config=None):
    db.add(Integration(tenant_id=tenant_id, kind="instagram", status="active",
                       credentials_kms_blob=encrypt_credentials({"access_token": "test-token"}),
                       config={"instagram_business_account_id": "ig-1"}))
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Ananya")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, channel=ChannelType.INSTAGRAM, is_open=True)
    rule = AutomationRule(id=str(uuid.uuid4()), tenant_id=tenant_id, name="MONSOON", trigger=trigger,
                          action="send_instagram_quick_reply", is_active=True, trigger_config={"keywords": ["monsoon"]},
                          action_config=config or {"message": "Here it is—the dates. Unlock them below. Which weekend?",
                                                   "public_ack_pool": ["Only Rs 9,000, book now!"],
                                                   "follow_up": "Did that help? Tell us your dates."})
    db.add_all([c, rule])
    db.commit()
    return g, c, rule


def test_dm_is_humanized_ack_replaced_and_one_follow_up_queued(db, ws):
    tid = ws["tenant"].id
    g, c, rule = _setup(db, tid)
    adapter = MagicMock()
    with patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter", return_value=adapter), \
            patch("app.workers.tasks.ig_follow_up.send_follow_up.apply_async") as queued:
        assert qr.dispatch_quick_reply(db, tid, rule, "igsid-1", g.id, c.id)
    sent = adapter.send_text.call_args.kwargs["text"]
    assert "—" not in sent and "Get them below" in sent
    assert queued.call_args.kwargs["countdown"] == 20 * 3600 and queued.call_args.kwargs["args"][1] == rule.id

    adapter.reset_mock()
    with patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter", return_value=adapter), \
            patch("app.workers.tasks.ig_follow_up.send_follow_up.apply_async") as queued:
        qr.dispatch_quick_reply(db, tid, rule, "igsid-1", g.id, c.id, comment_id="cmt-1")
    assert adapter.reply_to_comment.call_args.args[1] == rules.SAFE_PUBLIC_REPLY     # selling ack never posted
    queued.assert_not_called()                                                       # no follow-up after a comment


def test_follow_up_sends_only_if_nobody_answered(db, ws):
    tid = ws["tenant"].id
    g, c, rule = _setup(db, tid)
    sent_at = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    adapter = MagicMock()
    with patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter", return_value=adapter):
        assert qr.send_follow_up(db, tid, rule.id, "igsid-1", g.id, c.id, sent_at) == "sent"
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=c.id, direction="inbound", channel="instagram",
                       body="19th please", created_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        db.commit()
        assert qr.send_follow_up(db, tid, rule.id, "igsid-1", g.id, c.id, sent_at) == "skipped: answered"
    assert adapter.send_text.call_count == 1
    assert db.query(AutomationRun).filter_by(tenant_id=tid, automation_id=rule.id).count() == 2


def test_follow_up_never_crosses_workspaces(db, ws):
    g, c, rule = _setup(db, ws["tenant"].id)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    adapter = MagicMock()
    with patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter", return_value=adapter):
        out = qr.send_follow_up(db, other.id, rule.id, "igsid-1", g.id, c.id, datetime.now(timezone.utc).isoformat())
    assert out.startswith("skipped") and adapter.send_text.call_count == 0


def _rule_body(**cfg):
    return {"name": "MONSOON", "trigger": cfg.pop("trigger", "ig_dm_received"), "action": "send_instagram_quick_reply",
            "trigger_config": {"keywords": ["monsoon"]}, "action_config": {"message": DM, **cfg}}


def test_automations_api_enforces_copy_rules_roles_and_tenants(client, db, ws):
    url = "/api/v1/automations"
    ok = client.post(url, json=_rule_body(follow_up="Did that help?"), headers=ws["owner_h"])
    assert ok.status_code == 201, ok.text
    bad_ack = client.post(url, json=_rule_body(trigger="ig_comment_received", public_ack_pool=["Rs 9,000 only, book now"]),
                          headers=ws["owner_h"])
    assert bad_ack.status_code == 422 and "Public reply" in bad_ack.json()["detail"]
    on_comment = client.post(url, json=_rule_body(trigger="ig_comment_received", follow_up="Hi again"), headers=ws["owner_h"])
    assert on_comment.status_code == 422 and "follow-up" in on_comment.json()["detail"]
    assert client.post(url, json=_rule_body(), headers=ws["mkt_h"]).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    r = client.patch(f"{url}/{ok.json()['id']}", json={"action_config": {"message": "x"}}, headers=other_h)
    assert r.status_code == 404


def test_local_demo_seed_fills_every_toolkit_screen(client, db, ws):
    """scripts/_demo_ig_toolkit.py (called by seed_local_demo.py) gives each new screen something to show."""
    import importlib.util
    from pathlib import Path
    from app.models.marketing import MarketingContent

    path = Path(__file__).resolve().parents[1] / "scripts" / "_demo_ig_toolkit.py"
    sp = importlib.util.spec_from_file_location("_demo_ig_toolkit", path)
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    mod.seed(db, ws["tenant"], ws["owner"])
    post = db.query(MarketingContent).filter_by(tenant_id=ws["tenant"].id, kind="post").one()
    got = client.get(f"/api/v1/marketing/studio/content/{post.id}", headers=ws["owner_h"]).json()
    assert got["text_checks"]["fixed"]["undoable"] >= 1 and "—" not in got["current"]["payload"]["caption"]
    reel = db.query(MarketingContent).filter_by(tenant_id=ws["tenant"].id, kind="reel").one()
    assert len(reel.hook_plan["options"]) == 3 and reel.hook_plan["options"][2]["score"] < 50
    assert client.get("/api/v1/marketing/studio/profile-score", headers=ws["owner_h"]).json()["score"] == 18
    ranked = client.get("/api/v1/marketing/studio/research", headers=ws["owner_h"]).json()["ranked"]["posts"]
    assert ranked[0]["band"] == "signal" and ranked[0]["formula"] == "Nobody Tells You"


def test_studio_comment_dm_checks_show_on_the_draft():
    checks = rules.payload_checks({"comment_dm": {"keyword": "STAY", "message": DM, "public_reply": "Book now at Rs 9,000"}})
    by = {c["key"]: c for c in checks}
    assert by["keyword_dm"]["status"] == "ok" and by["public_reply"]["status"] == "bad"
