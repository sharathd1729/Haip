"""Knowledge retrieval against real PostgreSQL + pgvector (the `<=>` query and the vector(2048) column).

The SQLite tests (test_knowledge_lifecycle.py) run the retrieval RULES with a Python scorer. This file runs the production SQL:
the CAST(:vec AS vector) insert, the cosine-distance ordering, and the eligibility predicate (active, approved, indexed, not out
of date, property scope, tenant). Skips on SQLite; CI sets REQUIRE_POSTGRES_TESTS=1 so a missing PostgreSQL is a failure.
"""
import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.adapters.llm.embeddings import EMBED_DIM
from app.models.knowledge import KnowledgeEntry
from app.models.property import Property
from app.models.tenant import Tenant
from app.services import knowledge_service as ks
from tests.conftest import engine

IS_POSTGRES = engine.dialect.name == "postgresql"
pytestmark = pytest.mark.skipif(
    not IS_POSTGRES and os.environ.get("REQUIRE_POSTGRES_TESTS") != "1",
    reason="needs PostgreSQL with the pgvector extension. Runs in CI.",
)

_STOP = {"is", "are", "a", "an", "the", "in", "do", "you", "have", "there", "what", "does", "for", "of", "to", "your", "any"}


def _vec(text: str) -> list[float]:
    v = [0.0] * EMBED_DIM
    for w in (w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % EMBED_DIM] += 1.0
    return v


@pytest.fixture(autouse=True)
def embedder(monkeypatch):
    assert ks.PYTHON_VECTOR_FALLBACK is False                      # the production SQL path, not the test scorer
    monkeypatch.setattr(ks, "embed_texts_sync", lambda texts, kind: [_vec(t) for t in texts])
    monkeypatch.setattr(ks, "embed_one_sync", lambda text, kind: _vec(text))


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t


def _indexed(db, tenant_id, question, content, **kw):
    e = KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=tenant_id, category="faq", question=question, content=content,
                       source="manual", review_status=kw.pop("review", "approved"), embedding_status="pending", **kw)
    db.add(e)
    db.commit()
    assert ks.embed_entry(db, e) is True
    return e


def _contents(db, tenant_id, query, property_id=None):
    return [h["content"] for h in ks.search(db, tenant_id, query, property_id=property_id)]


def test_the_vector_column_is_the_size_the_embedding_model_produces(db):
    from sqlalchemy import text
    assert db.execute(text("SELECT atttypmod FROM pg_attribute WHERE attrelid = 'embeddings'::regclass AND attname = 'embedding'")).scalar() == EMBED_DIM


def test_pgvector_retrieval_ranks_by_cosine_and_returns_the_answer_not_the_phrasing(db):
    t = _tenant(db)
    _indexed(db, t.id, "Are pets allowed?", "Small pets are welcome.")
    _indexed(db, t.id, "Is there a kitchen?", "A kitchenette with a stove.")
    assert _contents(db, t.id, "are pets allowed") == ["Small pets are welcome."]
    hits = ks.search(db, t.id, "kitchen stove")
    assert [h["content"] for h in hits] == ["A kitchenette with a stove."] and 0 < hits[0]["score"] <= 1.0


def test_pgvector_eligibility_rules_hold_in_sql(db):
    t = _tenant(db)
    a = Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Goa", slug="g")
    b = Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Coorg", slug="c")
    db.add_all([a, b])
    db.commit()
    live = _indexed(db, t.id, "Check-in time Goa?", "Goa check-in is 2 pm.", property_id=a.id)
    _indexed(db, t.id, "Check-in time Coorg?", "Coorg check-in is 11 am.", property_id=b.id)
    off = _indexed(db, t.id, "Is parking free?", "Parking is free.")
    rej = _indexed(db, t.id, "Is wifi free?", "Wifi is free.")
    old = _indexed(db, t.id, "Is breakfast included?", "Breakfast is included.")
    waiting = _indexed(db, t.id, "Is there a gym?", "There is a gym.")
    off.is_active = False
    rej.review_status = "rejected"
    old.stale_since = datetime.now(timezone.utc)
    waiting.embedding_status = "pending"                         # edited, not yet re-indexed
    db.commit()

    assert _contents(db, t.id, "check-in time", property_id=a.id) == ["Goa check-in is 2 pm."]
    assert _contents(db, t.id, "check-in time") == []             # no property known -> property-only entries are not offered
    for q in ("is parking free", "is wifi free", "is breakfast included", "is there a gym"):
        assert _contents(db, t.id, q) == []
    live.is_active = False
    db.commit()
    assert _contents(db, t.id, "check-in time", property_id=a.id) == []


def test_pgvector_reindex_replaces_the_old_vectors_and_tenants_are_isolated(db):
    t, other = _tenant(db), _tenant(db)
    e = _indexed(db, t.id, "Are pets allowed?", "Pets are not allowed.")
    e.content = "Pets are welcome for a fee."
    e.embedding_status = "pending"
    db.commit()
    assert ks.embed_entry(db, e)
    assert _contents(db, t.id, "are pets allowed") == ["Pets are welcome for a fee."]
    from sqlalchemy import text
    assert db.execute(text("SELECT COUNT(*) FROM embeddings WHERE ref_id = :r AND content LIKE '%not allowed%'"), {"r": e.id}).scalar() == 0
    assert _contents(db, other.id, "are pets allowed") == []


def test_a_wrong_sized_vector_is_recorded_as_a_failed_index_not_left_pending(db):
    t = _tenant(db)
    e = KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=t.id, category="faq", question="Q?", content="A.", source="manual",
                       review_status="approved", embedding_status="pending")
    db.add(e)
    db.commit()
    with patch.object(ks, "embed_texts_sync", lambda texts, kind: [[0.1] * 10 for _ in texts]):
        assert ks.embed_entry(db, e) is False
    db.refresh(e)
    assert e.embedding_status == "failed" and e.embedding_attempts == 1 and e.embedding_error
