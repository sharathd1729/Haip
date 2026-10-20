"""Knowledge from Instagram posts, running ads, the website re-crawl and the Oct 2026 owner notes; newer content wins a tie.

Owner report: "a Dasara Mysore route was opened and posted on Instagram, but the knowledge base did not mention Mysore". No real
Instagram/website call is made: the Graph adapter and the page fetcher are replaced with fakes."""
import importlib.util
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.encryption import encrypt_credentials
from app.models.ad_entity import AdEntity
from app.models.audit_event import AuditEvent
from app.models.integration import Integration
from app.models.knowledge import KnowledgeEntry
from app.models.tenant import Tenant
from app.services import knowledge_freshness, knowledge_ingest, knowledge_sources
from app.services import knowledge_service as ks


@pytest.fixture(autouse=True)
def _no_dispatch():
    with patch("app.workers.tasks.embed_knowledge.embed_entry.delay", MagicMock()):
        yield


def _tenant(db, **knowledge):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"ks-{uuid.uuid4().hex[:6]}", plan="growth",
               brand_config={"knowledge": knowledge} if knowledge else {})
    db.add(t)
    db.commit()
    return t


def _ig(db, tenant_id):
    integ = Integration(id=str(uuid.uuid4()), tenant_id=tenant_id, kind="instagram", status="active",
                        credentials_kms_blob=encrypt_credentials({"access_token": "tok"}),
                        config={"instagram_business_account_id": "17841"})
    db.add(integ)
    db.commit()
    return integ


class FakeIG:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def list_media_page(self, limit=25, after=None):
        self.calls.append(after)
        idx = int(after or 0)
        nxt = str(idx + 1) if idx + 1 < len(self.pages) else None
        return self.pages[idx], nxt


def _post(media_id, caption, days_ago=1, media_type="IMAGE"):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    return {"id": media_id, "caption": caption, "media_type": media_type, "permalink": f"https://www.instagram.com/p/{media_id}/",
            "timestamp": ts}


def _ig_entries(db, tid):
    return {e.source_ref: e for e in db.query(KnowledgeEntry).filter_by(tenant_id=tid, source="instagram").all()}


# ── Instagram ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_posts_arrive_pending_with_their_date_and_a_price_flag_and_a_rerun_changes_nothing(db):
    t = _tenant(db)
    _ig(db, t.id)
    fake = FakeIG([[_post("m1", "Dasara special: Mysore route now open! Bangalore -> Mysore -> KRS, 2 nights", 2, "VIDEO"),
                    _post("m2", "Coorg weekend offer at Rs 18,000 per night", 3)],
                   [_post("m3", "", 4)]])
    out = knowledge_sources.sync_instagram(db, t, adapter=fake)
    assert out["status"] == "ok" and out["created"] == 2 and fake.calls == [None, "1"]

    rows = _ig_entries(db, t.id)
    mysore = rows["ig:m1"]
    assert mysore.review_status == "pending" and mysore.embedding_status == "pending"     # owner approves before the bot uses it
    assert "Mysore" in mysore.content and mysore.content.startswith("Instagram reel (")
    assert mysore.category == "routes" and mysore.source_published_at is not None
    assert rows["ig:m2"].content_flags == ["mentions_price", "mentions_offer"]
    assert "ig:m3" not in rows                                                            # no caption, nothing to learn
    audit = db.query(AuditEvent).filter_by(tenant_id=t.id, action="kb.ingested").one()
    assert audit.payload["source"] == "instagram" and audit.payload["created"] == 2 and audit.actor_user_id is None

    again = knowledge_sources.sync_instagram(db, t, adapter=FakeIG(fake.pages))
    assert again["created"] == 0 and again["unchanged"] == 2
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="kb.ingested").count() == 1  # nothing changed, nothing audited


def test_an_edited_caption_is_reindexed_and_reviewed_again_and_a_deleted_post_stops_being_used(db):
    t = _tenant(db)
    _ig(db, t.id)
    knowledge_sources.sync_instagram(db, t, adapter=FakeIG([[_post("m1", "Coorg trip open", 1), _post("m2", "Wayanad trip", 2)]]))
    rows = _ig_entries(db, t.id)
    for e in rows.values():
        e.review_status, e.embedding_status, e.content_hash = "approved", "done", ks.content_hash(e.question, e.content)
    db.commit()

    out = knowledge_sources.sync_instagram(db, t, adapter=FakeIG([[_post("m1", "Coorg trip open, now with a campfire night", 1),
                                                                            _post("m0", "", 3)]]))   # m2 (2 days) sat between them
    assert out["updated"] == 1 and out["marked_out_of_date"] == 1
    db.expire_all()
    rows = _ig_entries(db, t.id)
    assert rows["ig:m1"].review_status == "pending" and rows["ig:m1"].embedding_status == "pending"
    assert rows["ig:m2"].stale_since is not None                                          # gone from the account


def test_auto_approve_uses_posts_at_once_except_one_quoting_a_price(db):
    t = _tenant(db, auto_approve_social=True)
    _ig(db, t.id)
    knowledge_sources.sync_instagram(db, t, adapter=FakeIG([[_post("m1", "Mysore route open for Dasara"),
                                                             _post("m2", "Mysore at just ₹9,999!")]]))
    rows = _ig_entries(db, t.id)
    assert rows["ig:m1"].review_status == "approved"
    assert rows["ig:m2"].review_status == "pending"


def test_old_posts_are_skipped_and_another_workspace_is_never_touched(db):
    t, other = _tenant(db), _tenant(db)
    _ig(db, t.id)
    db.add(KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=other.id, category="other", content="Other's post", source="instagram",
                          source_ref="ig:m1", review_status="approved", embedding_status="done"))
    db.commit()
    out = knowledge_sources.sync_instagram(db, t, adapter=FakeIG([[_post("m1", "Fresh post", 1), _post("m9", "Ancient post", 400)]]))
    assert out["created"] == 1 and out["skipped_old"] == 1
    theirs = db.query(KnowledgeEntry).filter_by(tenant_id=other.id).one()
    assert theirs.content == "Other's post" and theirs.stale_since is None


def test_without_a_connection_nothing_happens_and_an_api_error_is_recorded_without_details(db):
    t = _tenant(db)
    assert knowledge_sources.sync_instagram(db, t)["status"] == "not_connected"
    integ = _ig(db, t.id)

    class Broken:
        def list_media_page(self, **kw):
            raise httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://graph.instagram.com"),
                                        response=httpx.Response(403, text="token tok expired"))
    out = knowledge_sources.sync_instagram(db, t, adapter=Broken())
    assert out == {"status": "api_error", "http_status": 403}
    db.refresh(integ)
    assert integ.config["kb_sync"]["last_error"] == "Instagram API returned HTTP 403"
    assert "tok" not in str(integ.config["kb_sync"])


def test_the_adapter_pages_with_the_cursor_on_graph_instagram_only():
    from app.adapters.instagram.meta_graph import InstagramGraphAdapter
    seen = []

    def fake_get(url, params=None, timeout=None):
        seen.append((url, dict(params)))
        return httpx.Response(200, json={"data": [{"id": "1"}], "paging": {"cursors": {"after": "C2"}, "next": "https://evil.example/x"}},
                              request=httpx.Request("GET", url))
    with patch("app.adapters.instagram.meta_graph.httpx.get", fake_get):
        items, cursor = InstagramGraphAdapter("tok", "17841").list_media_page(limit=25, after="C1")
    assert items == [{"id": "1"}] and cursor == "C2"
    assert seen[0][0] == "https://graph.instagram.com/v20.0/17841/media" and seen[0][1]["after"] == "C1"
    assert seen[0][1]["fields"] == "id,caption,media_type,permalink,timestamp"


# ── Meta ads ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_running_ads_text_becomes_knowledge_and_a_stopped_ad_goes_out_of_date(db):
    t = _tenant(db)
    ad = AdEntity(id=str(uuid.uuid4()), tenant_id=t.id, ad_account_id="act_1", level="ad", entity_id="a1",
                  name="INTERNAL lookalike 2% test", effective_status="ACTIVE", starts_at=datetime.now(timezone.utc) - timedelta(days=3),
                  creative={"title": "Dasara in Mysore", "body": "Caravan trip Bangalore to Mysore palace lights"})
    db.add(ad)
    db.commit()
    assert knowledge_sources.sync_meta_ads(db, t)["created"] == 1
    e = db.query(KnowledgeEntry).filter_by(tenant_id=t.id, source="meta_ad").one()
    assert "Mysore palace" in e.content and "INTERNAL" not in e.content and e.source_ref == "ad:a1"

    ad.effective_status = "PAUSED"
    db.commit()
    assert knowledge_sources.sync_meta_ads(db, t)["marked_out_of_date"] == 1
    db.refresh(e)
    assert e.stale_since is not None


# ── Celery ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_beat_fans_out_only_to_workspaces_that_allow_it(db):
    from app.workers.tasks import knowledge_sources_sync as tasks
    on, off = _tenant(db), _tenant(db, social_sync=False, website_recrawl=True)
    with patch.object(tasks.sync_tenant, "apply_async") as social, patch.object(tasks.recrawl_tenant, "apply_async") as crawl, \
            patch("app.workers.tasks.knowledge_sources_sync.SessionLocal", return_value=db), patch.object(db, "close"):
        tasks.sync_all_tenants()
        tasks.recrawl_all_tenants()
    social_ids = {c.kwargs["kwargs"]["tenant_id"] for c in social.call_args_list}
    crawl_ids = {c.kwargs["kwargs"]["tenant_id"] for c in crawl.call_args_list}
    assert on.id in social_ids and off.id not in social_ids
    assert off.id in crawl_ids and on.id not in crawl_ids                                 # re-crawl is opt-in


# ── website re-crawl ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_recrawl_rereads_saved_pages_new_text_waits_for_review_and_removed_text_goes_out_of_date(db, monkeypatch):
    t, other = _tenant(db), _tenant(db)
    url = "https://ratha.example/routes"
    old = KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=t.id, category="other", content="Routes: Coorg and Chikmagalur.",
                         source="website", source_url=url, review_status="approved", embedding_status="done")
    db.add(old)
    db.add(KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=other.id, category="other", content="x", source="website",
                          source_url="https://other.example/", review_status="approved", embedding_status="done"))
    db.commit()
    fetched = []
    monkeypatch.setattr(knowledge_ingest, "fetch_url_text", lambda u: fetched.append(u) or "Routes: Coorg, Chikmagalur and Mysore.")
    out = knowledge_freshness.recrawl_website(db, t.id)
    assert fetched == [url]                                                              # only this workspace's own pages
    assert out["new_passages"] == 1 and out["marked_out_of_date"] == 1
    new = db.query(KnowledgeEntry).filter(KnowledgeEntry.tenant_id == t.id, KnowledgeEntry.id != old.id).one()
    assert new.review_status == "pending" and "Mysore" in new.content
    db.refresh(old)
    assert old.stale_since is not None
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="kb.ingested").one().payload["actor"] == "website_recrawl"


# ── newer content wins a tie ─────────────────────────────────────────────────────────────────────────────────────────────

def test_between_equally_relevant_passages_the_newer_one_comes_first(db, monkeypatch):
    from tests.services.test_knowledge_lifecycle import _vec
    monkeypatch.setattr(ks, "PYTHON_VECTOR_FALLBACK", True)
    monkeypatch.setattr(ks, "embed_texts_sync", lambda texts, kind: [_vec(t) for t in texts])
    monkeypatch.setattr(ks, "embed_one_sync", lambda text, kind: _vec(text))
    ks.ensure_python_vector_table(db)
    t = _tenant(db)
    old = KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=t.id, category="routes", content="Mysore route trips", source="manual",
                         review_status="approved", embedding_status="pending")
    new = KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=t.id, category="routes", content="Mysore route trips", source="instagram",
                         review_status="approved", embedding_status="pending",
                         source_published_at=datetime.now(timezone.utc) + timedelta(days=30))
    db.add_all([old, new])
    db.commit()
    assert ks.embed_entry(db, old) and ks.embed_entry(db, new)
    hits = ks.search(db, t.id, "Mysore route")
    assert [h["id"] for h in hits] == [new.id, old.id]
    assert hits[0]["updated_at"] > hits[1]["updated_at"]


def test_the_reply_prompt_shows_each_snippet_date_and_says_current_data_wins():
    from app.core.prompt_versions import PROMPT_VERSIONS
    from app.workers.tasks.concierge_draft import _jinja_env
    assert PROMPT_VERSIONS["concierge_reply"] == "concierge-reply-v15"
    src = _jinja_env.loader.get_source(_jinja_env, "concierge_reply.jinja")[0]
    assert "updated {{ s.updated }}" in src
    assert "RECENT CONVERSATION and call summaries may be out of date" in src


# ── Oct 2026 owner notes importer ────────────────────────────────────────────────────────────────────────────────────────

_SPEC = importlib.util.spec_from_file_location("import_ratha_kb", os.path.join(os.path.dirname(__file__), "..", "scripts", "import_ratha_kb_2026_10.py"))
imp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(imp)


def test_owner_notes_import_is_a_dry_run_by_default_creates_pending_entries_only_and_is_idempotent(db):
    t, other = _tenant(db), _tenant(db)
    dry = imp.run(db, t.id)
    assert len(dry["created"]) == len(imp.ENTRIES) and db.query(KnowledgeEntry).filter_by(tenant_id=t.id).count() == 0

    first = imp.run(db, t.id, apply=True)
    rows = db.query(KnowledgeEntry).filter_by(tenant_id=t.id, source="owner_notes").all()
    assert len(first["created"]) == len(rows) == len(imp.ENTRIES)
    assert {r.review_status for r in rows} == {"pending"}                                 # never auto-published
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="kb.created").count() == len(imp.ENTRIES)

    again = imp.run(db, t.id, apply=True)
    assert again["created"] == [] and len(again["unchanged"]) == len(imp.ENTRIES)
    assert db.query(KnowledgeEntry).filter_by(tenant_id=t.id).count() == len(imp.ENTRIES)
    assert db.query(KnowledgeEntry).filter_by(tenant_id=other.id).count() == 0

    rows[0].review_status = "approved"
    rows[0].content = "edited by the owner"
    db.commit()
    assert imp.run(db, t.id, apply=True)["left_alone"]                                    # the owner's decision is kept


def test_owner_notes_hold_no_prices_vendor_costs_or_internal_items():
    from app.services.price_policy import strip_prices
    text = " ".join(q + " " + a for _, _, q, a in imp.ENTRIES).lower()
    for banned in ("1,500", "2,000", "vendor", "tie-up", "blocking fee", "action item"):
        assert banned not in text
    assert all(strip_prices(a) == a for _, _, _, a in imp.ENTRIES)


def test_refresh_queues_the_reindex_and_the_instagram_read():
    from app.workers.tasks import knowledge_sources_sync as tasks
    from app.workers.tasks.embed_knowledge import embed_pending
    with patch.object(embed_pending, "apply_async") as embed, patch.object(tasks.sync_tenant, "apply_async") as social:
        knowledge_freshness.enqueue_refresh("t1", reindex=True, social=True)
        knowledge_freshness.enqueue_refresh("t1", reindex=False, social=False)
    assert embed.call_args.kwargs["kwargs"] == {"tenant_id": "t1", "limit": 500, "force": True}
    assert social.call_args.kwargs["kwargs"] == {"tenant_id": "t1"} and embed.call_count == social.call_count == 1
