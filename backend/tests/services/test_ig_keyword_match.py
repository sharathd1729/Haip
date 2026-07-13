"""
T2.5 — Tests for ig_keyword_match.find_matching_rule()

Tests:
  Keyword match fires the correct reply
  Exclude-keyword suppresses an otherwise-matching rule
  Post-scoped rule does not fire on a different post's comments
  Global rule only fires when no post-scoped rule matched
  Tenant isolation: tenant A's rules never match tenant B's events
"""

import uuid
from app.models.tenant import Tenant
from app.models.automation import AutomationRule
from app.services.ig_keyword_match import find_matching_rule


def _make_tenant(db, name="TenantA"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_rule(db, tenant_id, trigger="ig_dm_received", keywords=None, exclude_keywords=None,
                media_id=None, reply_all=False, is_active=True):
    trigger_config = {}
    if keywords is not None:
        trigger_config["keywords"] = keywords
    if exclude_keywords is not None:
        trigger_config["exclude_keywords"] = exclude_keywords
    if media_id is not None:
        trigger_config["media_id"] = media_id
    if reply_all:
        trigger_config["reply_all"] = True

    rule = AutomationRule(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name="Test rule",
        trigger=trigger,
        trigger_config=trigger_config,
        action="send_instagram_quick_reply",
        action_config={"message": "Thanks for reaching out!"},
        is_active=is_active,
    )
    db.add(rule)
    db.commit()
    return rule


# ── Keyword match fires the correct reply ───────────────────────────────────

def test_keyword_match_returns_correct_rule(db):
    tenant = _make_tenant(db)
    rule = _make_rule(db, tenant.id, keywords=["price", "rate", "availability"])

    matched = find_matching_rule(db, tenant.id, "ig_dm_received", "What is the price for a villa?")
    assert matched is not None
    assert matched.id == rule.id


def test_no_keyword_match_returns_none(db):
    tenant = _make_tenant(db)
    _make_rule(db, tenant.id, keywords=["price", "rate"])

    matched = find_matching_rule(db, tenant.id, "ig_dm_received", "Hello, how are you?")
    assert matched is None


# ── Exclude-keyword suppresses an otherwise-matching rule ───────────────────

def test_exclude_keyword_suppresses_match(db):
    tenant = _make_tenant(db)
    _make_rule(db, tenant.id, keywords=["book", "booking"], exclude_keywords=["cancel"])

    matched = find_matching_rule(db, tenant.id, "ig_dm_received", "I want to cancel my booking")
    assert matched is None


def test_exclude_keyword_absent_still_matches(db):
    tenant = _make_tenant(db)
    rule = _make_rule(db, tenant.id, keywords=["book", "booking"], exclude_keywords=["cancel"])

    matched = find_matching_rule(db, tenant.id, "ig_dm_received", "I'd like to make a booking")
    assert matched is not None
    assert matched.id == rule.id


# ── Post-scoped rule does not fire on a different post's comments ───────────

def test_post_scoped_rule_does_not_fire_on_different_post(db):
    tenant = _make_tenant(db)
    _make_rule(db, tenant.id, trigger="ig_comment_received", keywords=["price"], media_id="post-A")

    matched = find_matching_rule(db, tenant.id, "ig_comment_received", "what's the price?", media_id="post-B")
    assert matched is None


def test_post_scoped_rule_fires_on_matching_post(db):
    tenant = _make_tenant(db)
    rule = _make_rule(db, tenant.id, trigger="ig_comment_received", keywords=["price"], media_id="post-A")

    matched = find_matching_rule(db, tenant.id, "ig_comment_received", "what's the price?", media_id="post-A")
    assert matched is not None
    assert matched.id == rule.id


def test_post_scoped_reply_all_ignores_keywords(db):
    tenant = _make_tenant(db)
    rule = _make_rule(db, tenant.id, trigger="ig_comment_received", media_id="post-A", reply_all=True)

    matched = find_matching_rule(db, tenant.id, "ig_comment_received", "literally anything at all", media_id="post-A")
    assert matched is not None
    assert matched.id == rule.id


# ── Global rule only fires when no post-scoped rule matched ─────────────────

def test_global_rule_fires_when_no_post_scoped_rule_exists(db):
    tenant = _make_tenant(db)
    global_rule = _make_rule(db, tenant.id, trigger="ig_comment_received", keywords=["price"])

    matched = find_matching_rule(db, tenant.id, "ig_comment_received", "what's the price?", media_id="post-X")
    assert matched is not None
    assert matched.id == global_rule.id


def test_post_scoped_rule_wins_over_global_rule(db):
    tenant = _make_tenant(db)
    global_rule = _make_rule(db, tenant.id, trigger="ig_comment_received", keywords=["price"])
    post_rule = _make_rule(db, tenant.id, trigger="ig_comment_received", keywords=["price"], media_id="post-A")

    matched = find_matching_rule(db, tenant.id, "ig_comment_received", "what's the price?", media_id="post-A")
    assert matched is not None
    assert matched.id == post_rule.id
    assert matched.id != global_rule.id


# ── Tenant isolation ──────────────────────────────────────────────────────────

def test_tenant_isolation_rules_never_cross(db):
    tenant_a = _make_tenant(db, "TenantA")
    tenant_b = _make_tenant(db, "TenantB")
    _make_rule(db, tenant_a.id, keywords=["price"])

    matched = find_matching_rule(db, tenant_b.id, "ig_dm_received", "what's the price?")
    assert matched is None


# ── Inactive rules never match ────────────────────────────────────────────────

def test_inactive_rule_never_matches(db):
    tenant = _make_tenant(db)
    _make_rule(db, tenant.id, keywords=["price"], is_active=False)

    matched = find_matching_rule(db, tenant.id, "ig_dm_received", "what's the price?")
    assert matched is None
