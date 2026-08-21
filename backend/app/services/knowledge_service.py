"""Knowledge base service — write, embed and retrieve tenant knowledge.

This is the only place that writes to the `embeddings` table for KB content.
Retrieval is exposed through `search()`, which the concierge draft path calls
to populate the prompt's knowledge section.

Security note: the original `concierge_service._kb_search()` built its SQL by
f-string-interpolating tenant_id and the vector literal straight into the
statement. It was never reachable (nothing called it), but it is the exact
shape of a tenant-isolation break, so the query is rebuilt here with bound
parameters and an explicit tenant predicate that sits alongside -- not
instead of -- the RLS policy added in migration 078.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.llm.embeddings import EMBED_DIM, embed_texts_sync, embed_one_sync, EmbeddingError
from app.models.knowledge import KnowledgeEntry

log = structlog.get_logger()

KB_NAMESPACE = "kb"
KB_REF_TYPE = "knowledge_entry"

# nv-embedqa-e5-v5 similarity scores sit far below the 0.7-0.8 range people
# expect from OpenAI-style embeddings -- an exact-topic match measures ~0.36
# in practice (verified against the live endpoint). A conventional threshold
# would silently return nothing on every query, so this floor is deliberately
# low and exists only to drop obvious noise; ranking does the real work.
MIN_SCORE = 0.15
DEFAULT_TOP_K = 5

# An entry's answer plus its alternate phrasings.
MAX_VECTORS_PER_ENTRY = 10

# How close a generated phrasing must sit to its own answer to be kept.
# Calibrated against a measured sample: on-topic phrasings scored 0.52-0.62
# and off-topic drift 0.40-0.48, so the gap is real but narrow. Set to
# favour dropping a borderline-useful phrasing over keeping one that
# misroutes another topic's question to this entry.
PHRASING_MIN_SIMILARITY = 0.50


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def content_hash(question: Optional[str], content: str) -> str:
    return hashlib.sha256(f"{question or ''}\x00{content}".encode("utf-8")).hexdigest()


def embed_input(entry_question: Optional[str], entry_content: str) -> str:
    """What actually gets embedded for an entry.

    For FAQ pairs the question carries the guest's vocabulary ("can I bring
    my dog") while the answer carries the brand's ("pets are welcome in
    garden villas"). Embedding the answer alone loses the match; embedding
    both keeps it.
    """
    q = (entry_question or "").strip()
    return f"{q}\n{entry_content}".strip() if q else entry_content.strip()


def chunk_text(body: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Split long text into retrieval-sized chunks on paragraph boundaries.

    Overlap keeps a sentence that straddles a boundary retrievable from
    either side. Used by the website/document ingestion paths; manual
    entries are normally short enough to pass through as one chunk.
    """
    body = re.sub(r"\n{3,}", "\n\n", (body or "").strip())
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]

    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if len(p) > max_chars:
            # A single oversized paragraph: hard-split it.
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(p), max_chars - overlap):
                chunks.append(p[i:i + max_chars])
            continue
        if len(cur) + len(p) + 2 <= max_chars:
            cur = f"{cur}\n\n{p}" if cur else p
        else:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap and len(cur) > overlap else ""
            cur = f"{tail}\n\n{p}".strip() if tail else p
    if cur:
        chunks.append(cur)
    return chunks


# ─── Embedding write path ────────────────────────────────────────────────────

def embed_entry(db: Session, entry: KnowledgeEntry) -> bool:
    """Embed one entry and upsert its vectors. Returns True on success.

    An entry produces one vector for the answer itself plus one per
    alternate phrasing, all pointing at the same entry -- a guest's odd
    wording then matches the phrasing rather than having to match the
    canonical question. Retrieval deduplicates by entry.

    Failures are recorded on the row (`embedding_status="failed"` plus the
    error) rather than raised: one bad entry must not abort a bulk ingest,
    and a failed row is visible in the UI so it can be retried.
    """
    texts = [embed_input(entry.question, entry.content)]
    phrasings = [p for p in (entry.alt_phrasings or []) if str(p or "").strip()][:MAX_VECTORS_PER_ENTRY - 1]
    texts.extend(str(p).strip() for p in phrasings)

    try:
        vecs = embed_texts_sync(texts, "passage")
    except EmbeddingError as exc:
        entry.embedding_status = "failed"
        entry.embedding_error = str(exc)[:2000]
        db.commit()
        log.error("kb_embed_failed", entry_id=entry.id, tenant_id=entry.tenant_id, error=str(exc))
        return False

    if len(vecs) != len(texts):
        entry.embedding_status = "failed"
        entry.embedding_error = f"Expected {len(texts)} vectors, got {len(vecs)}"
        db.commit()
        return False

    # Drop generated phrasings that wandered off this entry's topic. Observed
    # in practice: an amenities entry produced "can we bring our cat", which
    # would then match a pets question near-perfectly and beat the real pets
    # entry -- a bad phrasing does not merely fail to help, it actively
    # misroutes. Uses the vectors already computed above, so this costs
    # nothing extra.
    if phrasings:
        kept_vecs, kept_phrasings, dropped = [vecs[0]], [], []
        for phrasing, vec in zip(phrasings, vecs[1:]):
            if _cosine(vecs[0], vec) >= PHRASING_MIN_SIMILARITY:
                kept_vecs.append(vec)
                kept_phrasings.append(phrasing)
            else:
                dropped.append(phrasing)
        if dropped:
            log.info(
                "kb_phrasings_dropped_offtopic",
                entry_id=entry.id, dropped=dropped, kept=len(kept_phrasings),
            )
            entry.alt_phrasings = kept_phrasings
        vecs, phrasings = kept_vecs, kept_phrasings

    _upsert_vectors(db, entry, vecs, phrasings)
    entry.embedding_status = "done"
    entry.embedding_error = None
    entry.embedded_at = datetime.now(timezone.utc)
    entry.content_hash = content_hash(entry.question, entry.content)
    db.commit()
    log.info("kb_embed_done", entry_id=entry.id, tenant_id=entry.tenant_id)
    return True


def _upsert_vectors(
    db: Session, entry: KnowledgeEntry, vecs: list[list[float]], phrasings: list,
) -> None:
    """Store one vector for the answer plus one per alternate phrasing.

    Delete-then-insert, so re-embedding after an edit cannot leave stale
    vectors behind that would keep matching the old wording.
    """
    for vec in vecs:
        if len(vec) != EMBED_DIM:
            raise EmbeddingError(f"Refusing to store {len(vec)}-dim vector; column is {EMBED_DIM}")

    base_meta = {
        "source": entry.source,
        "category": entry.category,
        "question": entry.question,
        "property_id": entry.property_id,
        "priority": entry.priority,
    }

    db.execute(
        text("DELETE FROM embeddings WHERE tenant_id = :tid AND namespace = :ns AND ref_id = :rid"),
        {"tid": entry.tenant_id, "ns": KB_NAMESPACE, "rid": entry.id},
    )

    # vecs[0] is the answer; the rest line up with `phrasings` in order.
    labels: list[Optional[str]] = [None] + [str(p) for p in phrasings]
    for idx, vec in enumerate(vecs):
        phrasing = labels[idx] if idx < len(labels) else None
        meta = dict(base_meta, matched_via="phrasing" if phrasing else "answer")
        if phrasing:
            meta["phrasing"] = phrasing
        db.execute(
            text("""
                INSERT INTO embeddings (id, tenant_id, namespace, ref_id, ref_type, embedding, content, metadata)
                VALUES (:id, :tid, :ns, :rid, :rtype, CAST(:vec AS vector), :content, CAST(:meta AS jsonb))
            """),
            {
                # A vector per phrasing means ids can no longer be the entry
                # id -- ref_id is what ties them back to the entry.
                "id": str(uuid.uuid4()),
                "tid": entry.tenant_id,
                "ns": KB_NAMESPACE,
                "rid": entry.id,
                "rtype": KB_REF_TYPE,
                "vec": "[" + ",".join(repr(float(x)) for x in vec) + "]",
                "content": phrasing or entry.content,
                "meta": json.dumps(meta),
            },
        )


def delete_vector(db: Session, tenant_id: str, entry_id: str) -> None:
    db.execute(
        text("DELETE FROM embeddings WHERE tenant_id = :tid AND namespace = :ns AND ref_id = :rid"),
        {"tid": tenant_id, "ns": KB_NAMESPACE, "rid": entry_id},
    )


def needs_reembed(entry: KnowledgeEntry) -> bool:
    return (
        entry.embedding_status != "done"
        or entry.content_hash != content_hash(entry.question, entry.content)
    )


# ─── Retrieval ───────────────────────────────────────────────────────────────

def search(
    db: Session,
    tenant_id: str,
    query: str,
    property_id: Optional[str] = None,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = MIN_SCORE,
) -> list[dict]:
    """Cosine-similarity retrieval over a tenant's approved, active KB.

    Returns [] on any failure -- a knowledge lookup that errors must degrade
    the draft to ungrounded, never break the reply pipeline.
    """
    if not (query or "").strip():
        return []

    # pgvector's `<=>` operator only exists on Postgres. Bail out before
    # embedding rather than after: the embedding call is a paid network
    # round-trip, and without this check every test run against the SQLite
    # test database billed a real NVIDIA request only to then fail on the
    # SQL and return [] anyway.
    if db.bind is not None and db.bind.dialect.name != "postgresql":
        return []

    try:
        qvec = embed_one_sync(query, "query")
    except EmbeddingError as exc:
        log.warning("kb_search_embed_failed", tenant_id=tenant_id, error=str(exc))
        return []

    vec_literal = "[" + ",".join(repr(float(x)) for x in qvec) + "]"
    try:
        rows = db.execute(
            text("""
                SELECT e.ref_id            AS entry_id,
                       k.category          AS category,
                       k.question          AS question,
                       -- The entry's answer, distinct from e.content, which
                       -- for a phrasing vector is the phrasing itself.
                       k.content           AS entry_content,
                       k.source            AS source,
                       k.priority          AS priority,
                       1 - (e.embedding <=> CAST(:vec AS vector)) AS score
                FROM embeddings e
                JOIN knowledge_entries k ON k.id = e.ref_id
                WHERE e.tenant_id = :tid
                  AND e.namespace = :ns
                  AND k.tenant_id = :tid
                  AND k.is_active IS TRUE
                  AND k.review_status = 'approved'
                  AND k.embedding_status = 'done'
                  AND (k.property_id IS NULL OR k.property_id = :pid)
                ORDER BY e.embedding <=> CAST(:vec AS vector)
                LIMIT :lim
            """),
            {
                "vec": vec_literal,
                "tid": tenant_id,
                "ns": KB_NAMESPACE,
                "pid": property_id,
                # Over-fetch so the score filter and priority re-rank below
                # have candidates to work with.
                "lim": max(top_k * 3, top_k),
            },
        ).fetchall()
    except Exception as exc:
        log.warning("kb_search_failed", tenant_id=tenant_id, error=str(exc))
        return []

    # An entry now has several vectors (its answer plus one per alternate
    # phrasing), so the same entry can come back more than once. Keep its
    # best-scoring vector -- returning the same answer twice would waste
    # slots in a top_k the prompt is about to render.
    best: dict[str, dict] = {}
    for r in rows:
        score = float(r.score)
        if score < min_score:
            continue
        existing = best.get(r.entry_id)
        if existing is None or score > existing["score"]:
            best[r.entry_id] = {
                "id": r.entry_id,
                "category": r.category,
                "question": r.question,
                # Always the entry's answer, never the phrasing that matched
                # -- the phrasing is a retrieval aid, not content to show the
                # model.
                "content": r.entry_content,
                "source": r.source,
                "score": score,
            }
    hits = list(best.values())
    # Human-authored content wins ties against scraped/mined content of
    # similar relevance; `priority` is the tenant's explicit thumb on the
    # scale. Score still dominates -- this only reorders near-equals.
    priority_by_id = {r.entry_id: (r.priority or 0) for r in rows}
    hits.sort(key=lambda h: (round(h["score"], 2), priority_by_id.get(h["id"], 0)), reverse=True)
    return hits[:top_k]


def search_snippets(
    db: Session, tenant_id: str, query: str, property_id: Optional[str] = None, top_k: int = DEFAULT_TOP_K,
) -> list[dict]:
    """Retrieval shaped for the concierge prompt's `kb_snippets` loop, which
    renders `[{{ s.source }}] {{ s.text }}`."""
    return [
        {
            "text": (f"Q: {h['question']}\nA: {h['content']}" if h.get("question") else h["content"]),
            "source": h["category"],
            "score": h["score"],
        }
        for h in search(db, tenant_id, query, property_id=property_id, top_k=top_k)
    ]
