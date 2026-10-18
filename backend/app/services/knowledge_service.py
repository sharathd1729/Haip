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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.llm.embeddings import EMBED_DIM, embed_texts_sync, embed_one_sync, EmbeddingError
from app.models.knowledge import KnowledgeEntry

log = structlog.get_logger()

# Fields whose change is an edit a person made (not index bookkeeping).
AUDITED_FIELDS = ("category", "question", "content", "property_id", "priority", "is_active", "review_status", "alt_phrasings")
_AUDIT_TEXT_LIMIT = 4000


def snapshot(entry: KnowledgeEntry) -> dict:
    """The audited fields of an entry as plain JSON values, for a before/after comparison."""
    return {f: (list(getattr(entry, f) or []) if f == "alt_phrasings" else getattr(entry, f)) for f in AUDITED_FIELDS}


def _clip(value):
    if isinstance(value, str) and len(value) > _AUDIT_TEXT_LIMIT:
        return value[:_AUDIT_TEXT_LIMIT] + f"...[{len(value)} chars, sha256 {hashlib.sha256(value.encode()).hexdigest()[:16]}]"
    return value


def audit_change(db: Session, tenant_id: str, actor_id: Optional[str], action: str, entry_id: str, before: Optional[dict] = None,
                 after: Optional[dict] = None, **extra) -> bool:
    """One chained audit row for a knowledge-base change: who, what, and for edits the previous and new value of each field that
    changed. Same transaction as the change (the caller commits). Returns False when an edit changed nothing audited."""
    from app.core.audit import append_audit

    payload: dict = dict(extra)
    if before is not None and after is not None:
        changes = {f: {"from": _clip(before.get(f)), "to": _clip(after.get(f))} for f in AUDITED_FIELDS if before.get(f) != after.get(f)}
        if not changes:
            return False
        payload["changes"] = changes
    elif after is not None:
        payload["values"] = {f: _clip(v) for f, v in after.items()}
    elif before is not None:
        payload["deleted_values"] = {f: _clip(v) for f, v in before.items()}
    append_audit(db, tenant_id=tenant_id, action=f"kb.{action}", actor_user_id=actor_id, target_type="knowledge_entry", target_id=entry_id, payload=payload)
    return True


def entry_history(db: Session, tenant_id: str, entry_id: str, limit: int = 50) -> list[dict]:
    """Every audited change to one entry, newest first: who, when, and each changed field's previous and new value."""
    from app.models.audit_event import AuditEvent

    rows = (
        db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant_id, AuditEvent.target_type == "knowledge_entry", AuditEvent.target_id == entry_id,
                AuditEvent.action.like("kb.%"))
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{"id": r.id, "action": r.action.removeprefix("kb."), "at": r.created_at, "actor_user_id": r.actor_user_id,
             "changes": (r.payload or {}).get("changes"), "values": (r.payload or {}).get("values")} for r in rows]


def _iso_day(value) -> Optional[str]:
    """YYYY-MM-DD for a timestamp read through raw SQL (a datetime on PostgreSQL, a string on SQLite)."""
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)[:10] or None


def is_clipped(value) -> bool:
    return isinstance(value, str) and bool(re.search(r"\.\.\.\[\d+ chars, sha256 [0-9a-f]{16}\]$", value))


KB_NAMESPACE = "kb"
KB_REF_TYPE = "knowledge_entry"

# nv-embedqa-e5-v5 (the model these numbers were originally tuned for)
# reached NIM end-of-life 2026-08-25 -- replaced with nemotron-3-embed-1b
# (see embeddings.py, migration 094), which has a materially different,
# better-separated score distribution. Re-measured live 2026-08-30 against
# a realistic on-topic/near-miss/off-topic sample: exact-topic match ~0.64,
# same-topic near-miss ~0.40, off-topic noise ~0.03-0.11. Floor set to sit
# clearly above the noise band while still keeping the near-miss case.
MIN_SCORE = 0.25
DEFAULT_TOP_K = 5

# An entry's answer plus its alternate phrasings.
MAX_VECTORS_PER_ENTRY = 10

# How close a generated phrasing must sit to its own answer to be kept.
# Re-measured live 2026-08-30 against nemotron-3-embed-1b (see MIN_SCORE
# above for why): on-topic phrasings scored 0.896, off-topic drift 0.372 --
# a much wider, cleaner gap than the previous model's 0.52-0.62 vs
# 0.40-0.48. Set with generous margin on both sides of that gap.
PHRASING_MIN_SIMILARITY = 0.65

# After this many consecutive failed indexing attempts the periodic sweep stops retrying an entry on its own (a person can
# still force it from the settings page). Without a cap a permanently failing entry cost one provider call per sweep, forever.
MAX_AUTO_ATTEMPTS = 6

# Retrieval is a pgvector query (`<=>` exists only on PostgreSQL). Production and CI use PostgreSQL. Setting this True lets a
# non-PostgreSQL session (the SQLite test database) store vectors as JSON in an `embeddings` table created by
# `ensure_python_vector_table` and score them in Python, so the retrieval RULES (active, approved, indexed, not stale, property
# scope, tenant) can be tested end to end. It stays False by default so unrelated tests never spend an embedding call.
PYTHON_VECTOR_FALLBACK = False

# Which entries retrieval may ever return. One definition, used by every query below, so a change here changes every path.
_ELIGIBLE_SQL = """
    k.tenant_id = :tid
    AND k.is_active IS TRUE
    AND k.review_status = 'approved'
    AND k.embedding_status = 'done'
    AND k.stale_since IS NULL
    AND (k.property_id IS NULL OR k.property_id = :pid)
"""


@dataclass
class SearchOutcome:
    """What a retrieval returned and, when it returned nothing, WHY.

    status: ok | no_match | empty_query | embedding_unavailable | search_failed | unsupported
    A lookup that fails must be distinguishable from one that found nothing: the first means the knowledge base could not be
    consulted (the reply must not claim the base has no answer), the second means it was consulted and has none.
    """
    hits: list[dict] = field(default_factory=list)
    status: str = "ok"
    detail: str = ""


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

    # The text these vectors describe. Compared with the stored row once the vectors exist: a person may have edited the entry
    # while the provider call was in flight, and vectors of the OLD text must never be marked "done" for the NEW text.
    embedded_hash = content_hash(entry.question, entry.content)

    try:
        vecs = embed_texts_sync(texts, "passage")
    except EmbeddingError as exc:
        _record_failure(db, entry, str(exc))
        log.error("kb_embed_failed", entry_id=entry.id, tenant_id=entry.tenant_id, error=str(exc))
        return False

    if len(vecs) != len(texts):
        _record_failure(db, entry, f"Expected {len(texts)} vectors, got {len(vecs)}")
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

    entry_id, tenant_id = entry.id, entry.tenant_id
    try:
        _upsert_vectors(db, entry, vecs, phrasings)
        db.flush()
        fresh = db.execute(
            text("SELECT question, content FROM knowledge_entries WHERE id = :id AND tenant_id = :tid"),
            {"id": entry_id, "tid": tenant_id},
        ).first()
    except Exception as exc:
        # A storage error (bad dimension, SQL failure) used to propagate with the row still "pending" and the session
        # unusable, so the failure was invisible. Record it on the row, where the settings page shows it.
        db.rollback()
        row = db.query(KnowledgeEntry).filter_by(id=entry_id, tenant_id=tenant_id).first()
        if row is not None:
            _record_failure(db, row, f"Could not store the search index: {exc}")
        log.error("kb_embed_store_failed", entry_id=entry_id, tenant_id=tenant_id, error=str(exc))
        return False

    if fresh is None:
        # Deleted while indexing: do not leave vectors for an entry that no longer exists.
        delete_vector(db, tenant_id, entry_id)
        db.commit()
        return False
    if content_hash(fresh.question, fresh.content) != embedded_hash:
        # Edited while indexing. The editor already set the row back to "pending" and queued a new indexing run, which
        # replaces these vectors (delete-then-insert). Leave the row alone so it is not marked done on the old text.
        db.commit()
        db.refresh(entry)
        log.info("kb_embed_superseded_by_edit", entry_id=entry_id, tenant_id=tenant_id)
        return False

    entry.embedding_status = "done"
    entry.embedding_error = None
    entry.embedding_attempts = 0
    entry.embedded_at = datetime.now(timezone.utc)
    entry.content_hash = embedded_hash
    db.commit()
    log.info("kb_embed_done", entry_id=entry.id, tenant_id=entry.tenant_id)
    return True


def _record_failure(db: Session, entry: KnowledgeEntry, message: str) -> None:
    entry.embedding_status = "failed"
    entry.embedding_error = (message or "unknown error")[:2000]
    entry.embedding_attempts = int(entry.embedding_attempts or 0) + 1
    db.commit()


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

    portable = _use_python_vectors(db)
    insert_sql = (
        "INSERT INTO embeddings (id, tenant_id, namespace, ref_id, ref_type, embedding, content, metadata) "
        "VALUES (:id, :tid, :ns, :rid, :rtype, :vec, :content, :meta)"
        if portable else
        "INSERT INTO embeddings (id, tenant_id, namespace, ref_id, ref_type, embedding, content, metadata) "
        "VALUES (:id, :tid, :ns, :rid, :rtype, CAST(:vec AS vector), :content, CAST(:meta AS jsonb))"
    )

    # vecs[0] is the answer; the rest line up with `phrasings` in order.
    labels: list[Optional[str]] = [None] + [str(p) for p in phrasings]
    for idx, vec in enumerate(vecs):
        phrasing = labels[idx] if idx < len(labels) else None
        meta = dict(base_meta, matched_via="phrasing" if phrasing else "answer")
        if phrasing:
            meta["phrasing"] = phrasing
        db.execute(
            text(insert_sql),
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
    try:
        db.execute(
            text("DELETE FROM embeddings WHERE tenant_id = :tid AND namespace = :ns AND ref_id = :rid"),
            {"tid": tenant_id, "ns": KB_NAMESPACE, "rid": entry_id},
        )
    except Exception:
        # PostgreSQL always has the table; a non-PostgreSQL test database may not, and then there is nothing to delete.
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            raise


def _use_python_vectors(db: Session) -> bool:
    return PYTHON_VECTOR_FALLBACK and db.bind is not None and db.bind.dialect.name != "postgresql"


def ensure_python_vector_table(db: Session) -> None:
    """Create the JSON-vector `embeddings` table used by the non-PostgreSQL fallback (tests). Never used in production."""
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS embeddings (id TEXT PRIMARY KEY, tenant_id TEXT, namespace TEXT, ref_id TEXT, "
        "ref_type TEXT, embedding TEXT, content TEXT, metadata TEXT)"
    ))


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
    """Retrieval hits only. Callers that must tell "nothing matched" from "the lookup failed" use search_detailed()."""
    return search_detailed(db, tenant_id, query, property_id=property_id, top_k=top_k, min_score=min_score).hits


def search_detailed(
    db: Session,
    tenant_id: str,
    query: str,
    property_id: Optional[str] = None,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = MIN_SCORE,
) -> SearchOutcome:
    """Cosine-similarity retrieval over a tenant's approved, active, indexed, current KB.

    This is the ONE retrieval path: real replies and the settings-page "test a question" box both come through here, so what
    the owner sees in the test is what the AI can use. It never raises -- a knowledge lookup that errors must degrade the
    draft to ungrounded, never break the reply pipeline -- but it reports the failure in `status` so it is not mistaken for
    "the knowledge base has no answer".
    """
    if not (query or "").strip():
        return SearchOutcome(status="empty_query")

    # pgvector's `<=>` operator only exists on Postgres. Bail out before embedding rather than after: the embedding call is a
    # paid network round-trip, and without this check every test run against the SQLite test database billed a real NVIDIA
    # request only to then fail on the SQL.
    python_vectors = _use_python_vectors(db)
    if db.bind is not None and db.bind.dialect.name != "postgresql" and not python_vectors:
        return SearchOutcome(status="unsupported", detail="Knowledge search needs PostgreSQL with pgvector.")

    try:
        qvec = embed_one_sync(query, "query")
    except EmbeddingError as exc:
        log.warning("kb_search_embed_failed", tenant_id=tenant_id, error=str(exc))
        return SearchOutcome(status="embedding_unavailable", detail=str(exc)[:300])

    params = {"tid": tenant_id, "ns": KB_NAMESPACE, "pid": property_id}
    try:
        if python_vectors:
            scored = _score_in_python(db, qvec, params)
        else:
            scored = _score_in_postgres(db, qvec, params, max(top_k * 3, top_k))
    except Exception as exc:
        log.warning("kb_search_failed", tenant_id=tenant_id, error=str(exc))
        return SearchOutcome(status="search_failed", detail=str(exc)[:300])

    # An entry has several vectors (its answer plus one per alternate phrasing), so the same entry can come back more than
    # once. Keep its best-scoring vector -- returning the same answer twice would waste slots in a top_k the prompt renders.
    best: dict[str, dict] = {}
    for r, score in scored:
        if score < min_score:
            continue
        existing = best.get(r.entry_id)
        if existing is None or score > existing["score"]:
            best[r.entry_id] = {
                "id": r.entry_id,
                "category": r.category,
                "question": r.question,
                # Always the entry's answer, never the phrasing that matched -- the phrasing is a retrieval aid, not content.
                "content": r.entry_content,
                "source": r.source,
                "property_id": r.property_id,
                "score": score,
                "updated_at": _iso_day(getattr(r, "updated_at", None)),
            }
    hits = list(best.values())
    # Human-authored content wins ties against scraped/mined content of similar relevance; `priority` is the tenant's
    # explicit thumb on the scale. Score still dominates -- this only reorders near-equals.
    # Then the NEWER entry wins: when the owner adds "Mysore route now open" beside an older passage on the same topic, the
    # current one must not lose a tie to the old one (both are shown, newest first, each with its date).
    priority_by_id = {r.entry_id: (r.priority or 0) for r, _ in scored}
    hits.sort(key=lambda h: (round(h["score"], 2), priority_by_id.get(h["id"], 0), h.get("updated_at") or ""), reverse=True)
    hits = hits[:top_k]
    return SearchOutcome(hits=hits, status="ok" if hits else "no_match")


_SELECT_COLUMNS = """
    e.ref_id            AS entry_id,
    k.category          AS category,
    k.question          AS question,
    k.content           AS entry_content,
    k.source            AS source,
    k.priority          AS priority,
    k.property_id       AS property_id,
    COALESCE(k.source_published_at, k.updated_at) AS updated_at
"""


def _score_in_postgres(db: Session, qvec: list[float], params: dict, limit: int):
    vec_literal = "[" + ",".join(repr(float(x)) for x in qvec) + "]"
    rows = db.execute(
        text(f"""
            SELECT {_SELECT_COLUMNS},
                   1 - (e.embedding <=> CAST(:vec AS vector)) AS score
            FROM embeddings e
            JOIN knowledge_entries k ON k.id = e.ref_id
            WHERE e.tenant_id = :tid
              AND e.namespace = :ns
              AND {_ELIGIBLE_SQL}
            ORDER BY e.embedding <=> CAST(:vec AS vector)
            LIMIT :lim
        """),
        dict(params, vec=vec_literal, lim=limit),
    ).fetchall()
    return [(r, float(r.score)) for r in rows]


def _score_in_python(db: Session, qvec: list[float], params: dict):
    rows = db.execute(
        text(f"""
            SELECT {_SELECT_COLUMNS}, e.embedding AS embedding
            FROM embeddings e
            JOIN knowledge_entries k ON k.id = e.ref_id
            WHERE e.tenant_id = :tid
              AND e.namespace = :ns
              AND {_ELIGIBLE_SQL}
        """),
        params,
    ).fetchall()
    return [(r, _cosine(qvec, json.loads(r.embedding))) for r in rows]


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
            "updated": h.get("updated_at"),
            "origin": h.get("source"),
        }
        for h in search(db, tenant_id, query, property_id=property_id, top_k=top_k)
    ]


# ─── Indexing health ─────────────────────────────────────────────────────────

def index_health(db: Session, tenant_id: str) -> dict:
    """Counts and recency for the settings page: what the AI can use, what is waiting, what failed and why."""
    from sqlalchemy import func

    base = db.query(KnowledgeEntry).filter(KnowledgeEntry.tenant_id == tenant_id)
    active = base.filter(KnowledgeEntry.is_active.is_(True))
    retrievable = active.filter(
        KnowledgeEntry.review_status == "approved",
        KnowledgeEntry.embedding_status == "done",
        KnowledgeEntry.stale_since.is_(None),
    )
    failed = active.filter(KnowledgeEntry.embedding_status == "failed")
    pending = active.filter(KnowledgeEntry.embedding_status == "pending")
    last_failure = failed.order_by(KnowledgeEntry.updated_at.desc()).first()
    return {
        "total": base.count(),
        "active": active.count(),
        "pending_review": base.filter(KnowledgeEntry.review_status == "pending").count(),
        "embedding_pending": pending.count(),
        "embedding_failed": failed.count(),
        "stale": active.filter(KnowledgeEntry.stale_since.isnot(None)).count(),
        # The number that actually matters: what the concierge can retrieve.
        "retrievable": retrievable.count(),
        "last_indexed_at": retrievable.with_entities(func.max(KnowledgeEntry.embedded_at)).scalar(),
        "oldest_pending_since": pending.with_entities(func.min(KnowledgeEntry.updated_at)).scalar(),
        "last_error": (last_failure.embedding_error if last_failure else None),
        "search_available": _search_available(db),
    }


def _search_available(db: Session) -> bool:
    return db.bind is None or db.bind.dialect.name == "postgresql" or PYTHON_VECTOR_FALLBACK
