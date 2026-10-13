"""Knowledge base lifecycle: an edit reaches the next reply, retired content never does, failures are visible.

Retrieval is a pgvector query in production. These tests switch on the JSON-vector fallback (knowledge_service.
PYTHON_VECTOR_FALLBACK) and replace the paid embedding provider with a deterministic word-hash embedder, so the RULES that
decide what the AI may see -- active, approved, indexed, not out of date, property scope, tenant -- run end to end on SQLite.
The pgvector SQL itself is exercised by the PostgreSQL CI job, not here.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.llm.embeddings import EMBED_DIM, EmbeddingError
from app.models.capability import Capability, RoleCapability
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.knowledge import KnowledgeEntry
from app.models.module import Module, WorkspaceModule
from app.models.property import Property
from app.models.tenant import Tenant
from app.services import knowledge_ingest, knowledge_service as ks


_STOP = {"is", "are", "a", "an", "the", "in", "do", "you", "have", "there", "what", "does", "for", "of", "to", "your", "any"}


def _vec(text: str) -> list[float]:
    """Word-hash bag-of-words vector: texts sharing words are similar, texts sharing none are orthogonal."""
    v = [0.0] * EMBED_DIM
    for w in (w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % EMBED_DIM] += 1.0
    return v


@pytest.fixture(autouse=True)
def vector_store(monkeypatch, db):
    monkeypatch.setattr(ks, "PYTHON_VECTOR_FALLBACK", True)
    monkeypatch.setattr(ks, "embed_texts_sync", lambda texts, kind: [_vec(t) for t in texts])
    monkeypatch.setattr(ks, "embed_one_sync", lambda text, kind: _vec(text))
    ks.ensure_python_vector_table(db)
    with patch("app.workers.tasks.embed_knowledge.embed_entry.delay", MagicMock()):
        yield


def _tenant(db, name="Ratha"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t


def _property(db, tenant_id, name="Caravan One"):
    p = Property(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, slug=f"p-{uuid.uuid4().hex[:6]}")
    db.add(p)
    db.commit()
    return p


def _entry(db, tenant_id, question, content, *, property_id=None, review="approved", active=True, source="manual", **kw):
    e = KnowledgeEntry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, category="faq", question=question, content=content,
        property_id=property_id, source=source, is_active=active, review_status=review,
        embedding_status="pending", **kw,
    )
    db.add(e)
    db.commit()
    return e


def _indexed(db, tenant_id, question, content, **kw):
    e = _entry(db, tenant_id, question, content, **kw)
    assert ks.embed_entry(db, e) is True
    return e


def _contents(db, tenant_id, query, property_id=None):
    return [h["content"] for h in ks.search(db, tenant_id, query, property_id=property_id)]


# ─── an edit reaches the next reply, and the old wording never does ────────────

def test_edited_answer_replaces_the_old_one_after_indexing(db):
    t = _tenant(db)
    e = _indexed(db, t.id, "Are pets allowed in the caravan?", "Pets are not allowed in the caravan.")
    assert _contents(db, t.id, "are pets allowed") == ["Pets are not allowed in the caravan."]

    # the owner edits the answer: the entry is waiting to be re-indexed -> it must not answer from the OLD text
    e.content = "Small pets are welcome in the caravan for a fee."
    e.embedding_status = "pending"
    db.commit()
    assert _contents(db, t.id, "are pets allowed") == []

    assert ks.embed_entry(db, e) is True
    assert _contents(db, t.id, "are pets allowed") == ["Small pets are welcome in the caravan for a fee."]
    # no vector of the old wording is left behind
    rows = db.execute(ks.text("SELECT content FROM embeddings WHERE ref_id = :r"), {"r": e.id}).fetchall()
    assert all("not allowed" not in (r[0] or "") for r in rows)


def test_an_edit_made_while_indexing_is_never_marked_done_on_the_old_text(db):
    t = _tenant(db)
    e = _entry(db, t.id, "Is breakfast included?", "Breakfast is included.")

    def edit_midflight(texts, kind):
        # the owner saves a change after the provider call started
        db.execute(ks.text("UPDATE knowledge_entries SET content = :c, embedding_status = 'pending' WHERE id = :i"),
                   {"c": "Breakfast costs extra.", "i": e.id})
        return [_vec(x) for x in texts]

    with patch.object(ks, "embed_texts_sync", edit_midflight):
        assert ks.embed_entry(db, e) is False

    db.refresh(e)
    assert e.embedding_status == "pending"                 # waits for the re-index the editor queued
    assert _contents(db, t.id, "is breakfast included") == []


def test_deactivated_rejected_and_deleted_entries_are_never_retrieved(db):
    t = _tenant(db)
    off = _indexed(db, t.id, "Is parking free?", "Parking is free.")
    rej = _indexed(db, t.id, "Is wifi free?", "Wifi is free.")
    gone = _indexed(db, t.id, "Is there a gym?", "There is a gym.")
    live = _indexed(db, t.id, "Is there a pool?", "There is a pool.")
    off.is_active = False
    rej.review_status = "rejected"
    ks.delete_vector(db, t.id, gone.id)
    db.delete(gone)
    db.commit()

    for q in ("is parking free", "is wifi free", "is there a gym"):
        assert _contents(db, t.id, q) == []
    assert _contents(db, t.id, "is there a pool") == ["There is a pool."]
    assert db.execute(ks.text("SELECT COUNT(*) FROM embeddings WHERE ref_id = :r"), {"r": gone.id}).scalar() == 0


def test_entries_not_yet_approved_or_indexed_are_not_retrieved(db):
    t = _tenant(db)
    _indexed(db, t.id, "Do you serve dinner?", "Dinner is served at 8.", review="pending")
    waiting = _entry(db, t.id, "Do you serve lunch?", "Lunch is served at 1.")
    failed = _entry(db, t.id, "Do you serve tea?", "Tea is served at 5.")
    failed.embedding_status = "failed"
    db.commit()
    for q in ("do you serve dinner", "do you serve lunch", "do you serve tea"):
        assert _contents(db, t.id, q) == []
    assert waiting.embedding_status == "pending"


# ─── scope: properties and tenants never share knowledge ──────────────────────

def test_property_scoped_knowledge_is_not_offered_for_another_property(db):
    t = _tenant(db)
    a, b = _property(db, t.id, "Goa Caravan"), _property(db, t.id, "Coorg Caravan")
    _indexed(db, t.id, "What is the check-in time?", "Check-in at Goa is 2 pm.", property_id=a.id)
    _indexed(db, t.id, "What is the check-in time?", "Check-in at Coorg is 11 am.", property_id=b.id)
    _indexed(db, t.id, "What is the cancellation policy?", "Free cancellation up to 7 days before.")

    assert _contents(db, t.id, "what is the check-in time", property_id=a.id) == ["Check-in at Goa is 2 pm."]
    assert _contents(db, t.id, "what is the check-in time", property_id=b.id) == ["Check-in at Coorg is 11 am."]
    # tenant-wide knowledge is offered for every property
    assert _contents(db, t.id, "cancellation policy", property_id=a.id) == ["Free cancellation up to 7 days before."]
    assert _contents(db, t.id, "cancellation policy", property_id=b.id) == ["Free cancellation up to 7 days before."]
    # no property known: only tenant-wide knowledge, never a guess between two properties
    assert _contents(db, t.id, "what is the check-in time") == []


def test_one_tenants_knowledge_is_invisible_to_another(db):
    t1, t2 = _tenant(db, "Ratha"), _tenant(db, "Jade")
    _indexed(db, t1.id, "Is there a bonfire?", "Bonfire costs 1500.")
    assert _contents(db, t1.id, "is there a bonfire") == ["Bonfire costs 1500."]
    assert _contents(db, t2.id, "is there a bonfire") == []


# ─── failures are visible, bounded and distinguishable from "no answer" ────────

def test_a_failed_indexing_is_recorded_with_its_error_and_attempt_count(db):
    t = _tenant(db)
    e = _entry(db, t.id, "Is there a kitchen?", "There is a kitchenette.")
    with patch.object(ks, "embed_texts_sync", side_effect=EmbeddingError("NIM 504")):
        assert ks.embed_entry(db, e) is False
    db.refresh(e)
    assert (e.embedding_status, e.embedding_error, e.embedding_attempts) == ("failed", "NIM 504", 1)
    assert ks.embed_entry(db, e) is True
    db.refresh(e)
    assert (e.embedding_status, e.embedding_error, e.embedding_attempts) == ("done", None, 0)
    assert e.embedded_at is not None


def test_a_storage_error_is_recorded_not_left_as_silent_pending(db):
    t = _tenant(db)
    e = _entry(db, t.id, "Is there a deck?", "There is a deck.")
    # (rollback is a no-op here: the test session shares one outer transaction, so a real rollback would also erase the fixture rows)
    with patch.object(ks, "_upsert_vectors", side_effect=RuntimeError("disk full")), patch.object(db, "rollback"):
        assert ks.embed_entry(db, e) is False
    db.refresh(e)
    assert e.embedding_status == "failed" and "disk full" in e.embedding_error


def test_a_failed_lookup_is_reported_differently_from_no_match(db):
    t = _tenant(db)
    _indexed(db, t.id, "Is there a deck?", "There is a deck.")
    assert ks.search_detailed(db, t.id, "kayaking tours").status == "no_match"
    with patch.object(ks, "embed_one_sync", side_effect=EmbeddingError("timeout")):
        out = ks.search_detailed(db, t.id, "is there a deck")
    assert out.status == "embedding_unavailable" and out.hits == []


def test_the_periodic_sweep_retries_stuck_entries_backs_off_and_stops(db):
    from app.workers.tasks import embed_knowledge as task

    t = _tenant(db)
    stuck = _entry(db, t.id, "Do you have towels?", "Towels are provided.")
    stuck.updated_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    fresh = _entry(db, t.id, "Do you have soap?", "Soap is provided.")          # queued a moment ago: leave it to its own task
    gave_up = _entry(db, t.id, "Do you have a fan?", "A fan is provided.")
    gave_up.embedding_status, gave_up.embedding_attempts = "failed", ks.MAX_AUTO_ATTEMPTS
    gave_up.updated_at = datetime.now(timezone.utc) - timedelta(days=3)
    db.commit()

    with patch.object(task, "SessionLocal", return_value=db), patch.object(db, "close"):
        result = task.embed_pending.run(t.id, limit=50, min_age_seconds=120)
        db.refresh(stuck), db.refresh(fresh), db.refresh(gave_up)
        assert result["attempted"] == 1 and stuck.embedding_status == "done"
        assert fresh.embedding_status == "pending" and gave_up.embedding_status == "failed"

        # an explicit "retry indexing" click ignores the cap
        task.embed_pending.run(t.id, limit=50, force=True)
        db.refresh(gave_up), db.refresh(fresh)
        assert gave_up.embedding_status == "done" and fresh.embedding_status == "done"


def test_the_sweep_stops_after_repeated_provider_failures(db):
    from app.workers.tasks import embed_knowledge as task

    t = _tenant(db)
    for i in range(6):
        _entry(db, t.id, f"Question number {i}?", f"Answer number {i}.")
    calls = []

    def boom(texts, kind):
        calls.append(1)
        raise EmbeddingError("provider down")

    with patch.object(task, "SessionLocal", return_value=db), patch.object(db, "close"), \
         patch.object(ks, "embed_texts_sync", boom):
        task.embed_pending.run(t.id, limit=50, force=True)
    assert len(calls) == task._CIRCUIT_BREAKER


# ─── re-importing a page or file ──────────────────────────────────────────────

def test_reimporting_a_page_skips_duplicates_and_marks_removed_passages_out_of_date(db):
    t = _tenant(db)
    url = "https://ratha.example/rates"
    first = knowledge_ingest.ingest_chunks_report(db, t.id, "Weekend rate is 8000.\n\nPets are allowed.", source="website", source_url=url)
    assert len(first.created) == 1                         # one chunk (short text)
    e = first.created[0]
    e.review_status = "approved"
    db.commit()
    assert ks.embed_entry(db, e)
    assert _contents(db, t.id, "weekend rate") != []

    same = knowledge_ingest.ingest_chunks_report(db, t.id, "Weekend rate is 8000.\n\nPets are allowed.", source="website", source_url=url)
    assert (len(same.created), same.unchanged, same.marked_out_of_date) == (0, 1, 0)

    changed = knowledge_ingest.ingest_chunks_report(db, t.id, "Weekend rate is 9500.", source="website", source_url=url)
    assert (len(changed.created), changed.marked_out_of_date) == (1, 1)
    db.refresh(e)
    assert e.stale_since is not None
    assert _contents(db, t.id, "weekend rate") == []       # the removed price is no longer retrievable


def test_a_passage_that_returns_to_the_page_is_current_again(db):
    t = _tenant(db)
    url = "https://ratha.example/faq"
    e = knowledge_ingest.ingest_chunks_report(db, t.id, "Old text.", source="website", source_url=url).created[0]
    knowledge_ingest.ingest_chunks_report(db, t.id, "New text.", source="website", source_url=url)
    db.refresh(e)
    assert e.stale_since is not None
    again = knowledge_ingest.ingest_chunks_report(db, t.id, "Old text.", source="website", source_url=url)
    db.refresh(e)
    assert again.unchanged == 1 and e.stale_since is None


# ─── endpoints ────────────────────────────────────────────────────────────────

@pytest.fixture()
def api(db, client, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    module = db.query(Module).filter_by(code="ai_concierge").first() or Module(id=str(uuid.uuid4()), code="ai_concierge", name="AI")
    db.add(module)
    db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=tid, module_id=module.id, enabled=True))
    cap = db.query(Capability).filter_by(key="settings.manage").first() or Capability(
        key="settings.manage", label="x", category="settings", is_write=True, risk="low")
    db.add(cap)
    db.flush()
    db.add(RoleCapability(id=str(uuid.uuid4()), tenant_id=tid, role="owner", capability_key="settings.manage", allowed=True))
    db.commit()
    return client, {"Authorization": f"Bearer {tenant_and_user['access_token']}"}, tid


def test_test_box_and_real_replies_use_the_same_search_and_conversation_property(db, api):
    client, h, tid = api
    a, b = _property(db, tid, "Goa"), _property(db, tid, "Coorg")
    _indexed(db, tid, "What is the check-in time?", "Goa check-in is 2 pm.", property_id=a.id)
    _indexed(db, tid, "What is the check-in time?", "Coorg check-in is 11 am.", property_id=b.id)
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, phone="+919800000001", name="Asha")
    db.add(g)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True, property_id=b.id)
    db.add(conv)
    db.commit()

    r = client.post("/api/v1/knowledge/search", json={"query": "what is the check-in time", "conversation_id": conv.id}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["content"] for x in body["hits"]] == ["Coorg check-in is 11 am."]
    assert body["status"] == "ok" and body["property_id"] == b.id
    # exactly what the reply path retrieves
    assert [x["content"] for x in ks.search(db, tid, "what is the check-in time", property_id=conv.property_id)] == ["Coorg check-in is 11 am."]


def test_search_tells_the_owner_when_entries_are_still_being_indexed(db, api):
    client, h, tid = api
    _entry(db, tid, "Do you have a kitchen?", "Yes a kitchenette.")                # saved but not indexed yet
    r = client.post("/api/v1/knowledge/search", json={"query": "do you have a kitchen"}, headers=h).json()
    assert r["status"] == "no_match" and "still being indexed" in r["message"]
    with patch.object(ks, "embed_one_sync", side_effect=EmbeddingError("down")):
        r = client.post("/api/v1/knowledge/search", json={"query": "do you have a kitchen"}, headers=h).json()
    assert r["status"] == "embedding_unavailable" and "did not respond" in r["message"]


def test_editing_through_the_api_makes_the_entry_unavailable_until_it_is_indexed_again(db, api):
    client, h, tid = api
    e = _indexed(db, tid, "Is there wifi?", "No wifi.")
    r = client.patch(f"/api/v1/knowledge/{e.id}", json={"content": "Free wifi in every caravan."}, headers=h)
    assert r.status_code == 200 and r.json()["embedding_status"] == "pending"
    assert _contents(db, tid, "is there wifi") == []
    db.refresh(e)
    assert ks.embed_entry(db, e)
    assert _contents(db, tid, "is there wifi") == ["Free wifi in every caravan."]


def test_an_entry_cannot_be_scoped_to_another_tenants_property(db, api):
    client, h, tid = api
    other = _property(db, _tenant(db, "Other").id)
    r = client.post("/api/v1/knowledge", json={"category": "other", "content": "Secret.", "property_id": other.id}, headers=h)
    assert r.status_code == 422
    e = _entry(db, tid, None, "Mine.")
    r = client.patch(f"/api/v1/knowledge/{e.id}", json={"property_id": other.id}, headers=h)
    assert r.status_code == 422


def test_property_scope_can_be_set_and_cleared_and_stats_report_health(db, api):
    client, h, tid = api
    p = _property(db, tid)
    e = _indexed(db, tid, "Pets?", "Pets welcome.")
    assert client.patch(f"/api/v1/knowledge/{e.id}", json={"property_id": p.id}, headers=h).json()["property_id"] == p.id
    assert client.patch(f"/api/v1/knowledge/{e.id}", json={"property_id": None}, headers=h).json()["property_id"] is None
    bad = _entry(db, tid, "Gym?", "Gym.")
    bad.embedding_status, bad.embedding_error = "failed", "NIM 504"
    db.commit()
    s = client.get("/api/v1/knowledge/stats", headers=h).json()
    assert s["embedding_failed"] == 1 and s["last_error"] == "NIM 504" and s["search_available"] is True


def test_keep_out_of_date_and_reindex_endpoints(db, api):
    client, h, tid = api
    e = _indexed(db, tid, "Rates?", "Rate 8000.")
    e.stale_since = datetime.now(timezone.utc)
    db.commit()
    assert _contents(db, tid, "rates") == []
    r = client.patch(f"/api/v1/knowledge/{e.id}", json={"keep_out_of_date": True}, headers=h)
    assert r.json()["stale_since"] is None
    assert _contents(db, tid, "rates") == ["Rate 8000."]
    _entry(db, tid, "Q?", "A.")
    # patched on the Task class: the endpoint runs in a worker thread whose "current Celery app" is not the test thread's
    with patch("celery.app.task.Task.apply_async") as q:
        assert client.post("/api/v1/knowledge/reindex", headers=h).json() == {"queued": 1}
    assert q.call_args.kwargs["kwargs"]["force"] is True
