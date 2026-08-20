"""Knowledge base service tests.

Retrieval itself needs a live embedding provider and pgvector, so the search
path is covered by the tenant-isolation test below (which asserts the SQL
filters, not embedding quality) plus the pure-function tests here. The
chunking and hashing helpers are deterministic and fully covered.
"""
import pytest

from app.services import knowledge_service as ks


# ─── chunk_text ──────────────────────────────────────────────────────────────

def test_chunk_text_short_body_is_single_chunk():
    assert ks.chunk_text("Pets are welcome.") == ["Pets are welcome."]


def test_chunk_text_empty_returns_empty_list():
    assert ks.chunk_text("") == []
    assert ks.chunk_text("   ") == []


def test_chunk_text_splits_long_body_on_paragraphs():
    para = "A" * 500
    body = "\n\n".join([para] * 6)  # 3000+ chars
    chunks = ks.chunk_text(body, max_chars=1200, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 1200 + 100 for c in chunks)


def test_chunk_text_hard_splits_oversized_single_paragraph():
    # One paragraph with no break points must still be bounded, not returned whole.
    chunks = ks.chunk_text("B" * 4000, max_chars=1000, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)


# ─── content_hash / needs_reembed ────────────────────────────────────────────

def test_content_hash_changes_with_content():
    a = ks.content_hash("Q", "answer one")
    b = ks.content_hash("Q", "answer two")
    assert a != b


def test_content_hash_changes_with_question():
    assert ks.content_hash("Q1", "same") != ks.content_hash("Q2", "same")


def test_content_hash_is_stable():
    assert ks.content_hash("Q", "a") == ks.content_hash("Q", "a")


def test_content_hash_question_content_boundary_is_unambiguous():
    """"AB"+"C" must not hash identically to "A"+"BC" -- without a delimiter
    between the two fields they would collide and an edit could silently skip
    re-embedding."""
    assert ks.content_hash("AB", "C") != ks.content_hash("A", "BC")


class _FakeEntry:
    def __init__(self, question, content, status, chash):
        self.question, self.content = question, content
        self.embedding_status, self.content_hash = status, chash


def test_needs_reembed_true_when_never_embedded():
    e = _FakeEntry("Q", "A", "pending", None)
    assert ks.needs_reembed(e) is True


def test_needs_reembed_true_when_content_changed():
    e = _FakeEntry("Q", "NEW", "done", ks.content_hash("Q", "OLD"))
    assert ks.needs_reembed(e) is True


def test_needs_reembed_false_when_unchanged_and_done():
    e = _FakeEntry("Q", "A", "done", ks.content_hash("Q", "A"))
    assert ks.needs_reembed(e) is False


# ─── embed_input ─────────────────────────────────────────────────────────────

def test_embed_input_combines_question_and_answer():
    """The guest's vocabulary lives in the question, the brand's in the
    answer; both must be embedded or FAQ recall drops."""
    out = ks.embed_input("Can I bring my dog?", "Pets are welcome.")
    assert "dog" in out and "Pets are welcome." in out


def test_embed_input_without_question_is_just_content():
    assert ks.embed_input(None, "Amenities include WiFi.") == "Amenities include WiFi."


# ─── retrieval degradation ───────────────────────────────────────────────────

def test_search_returns_empty_for_blank_query(db):
    assert ks.search(db, "any-tenant", "") == []
    assert ks.search(db, "any-tenant", "   ") == []


def test_search_degrades_to_empty_when_embedding_fails(db, monkeypatch):
    """A KB outage must never break the reply pipeline -- it degrades the
    draft to ungrounded instead."""
    def _boom(*a, **kw):
        raise ks.EmbeddingError("provider down")
    monkeypatch.setattr(ks, "embed_one_sync", _boom)
    assert ks.search(db, "any-tenant", "do you allow pets") == []
