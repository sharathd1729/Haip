"""Knowledge base bulk ingestion -- website crawling + document upload.

Both paths funnel into the same shared ingest_chunks(): extract text,
split into retrieval-sized pieces (knowledge_service.chunk_text, which
was already built for exactly this and never wired up), and store each
as a KnowledgeEntry with review_status="pending" -- a human must approve
before the AI can use any of it (knowledge_service.search() only
retrieves review_status="approved" rows), same safety gate manual entries
skip past because a person typed them directly.

Uploaded documents are stored in R2 via media_storage.py's existing
S3-compatible client (same one WhatsApp media/IVR audio/avatars already
use) -- never Supabase storage, which only ever holds the database in
this stack.
"""
from __future__ import annotations

import uuid
from typing import Optional

import httpx
import structlog
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeEntry
from app.services import knowledge_service

log = structlog.get_logger()

# Generous enough for a real brochure/rate-card PDF, small enough that one
# bad upload can't tie up a request handler or balloon storage costs.
MAX_UPLOAD_MB = 15
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_UPLOAD_EXTS = {".pdf", ".docx", ".txt"}

# Website fetches happen inline in a request handler (like the Sarvam TTS
# call in tenants.py) -- bounded, fast enough not to need a Celery hop.
# A generous but finite cap stops a slow/hanging page from tying up the
# request indefinitely.
FETCH_TIMEOUT_SECONDS = 20.0
MAX_PAGE_BYTES = 5 * 1024 * 1024  # 5 MB -- a real content page, not a stream
MAX_URLS_PER_REQUEST = 5


class IngestError(Exception):
    """Raised for a real, user-facing ingestion failure (bad file, fetch
    failed, etc.) -- callers turn this into an HTTP 400/502 rather than a
    500, and can show the message directly."""


# ─── Text extraction ────────────────────────────────────────────────────────

def extract_text_from_pdf(content: bytes) -> str:
    from pypdf import PdfReader
    import io

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise IngestError(f"Couldn't read this PDF: {exc}") from exc
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue  # one bad page must not fail the whole document
    return "\n\n".join(p for p in pages if p.strip())


def extract_text_from_docx(content: bytes) -> str:
    import io
    from docx import Document

    try:
        doc = Document(io.BytesIO(content))
    except Exception as exc:
        raise IngestError(f"Couldn't read this Word document: {exc}") from exc
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


def extract_text_from_html(html: str) -> str:
    """Strip nav/script/style/footer noise, keep the actual page content --
    a raw HTML dump would bury real sentences in menu links and JS."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def extract_text_from_upload(filename: str, content_type: str, content: bytes) -> str:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext == ".pdf" or "pdf" in content_type:
        return extract_text_from_pdf(content)
    if ext == ".docx" or "wordprocessingml" in content_type:
        return extract_text_from_docx(content)
    if ext == ".txt" or content_type.startswith("text/"):
        try:
            return content.decode("utf-8", errors="replace")
        except Exception as exc:
            raise IngestError(f"Couldn't read this file as text: {exc}") from exc
    raise IngestError(f"Unsupported file type '{ext or content_type}'. Use PDF, Word (.docx), or plain text.")


# ─── Website fetch ──────────────────────────────────────────────────────────

def fetch_url_text(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        raise IngestError(f"'{url}' isn't a valid URL.")
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "HAIP-KnowledgeBot/1.0"})
    except httpx.HTTPError as exc:
        raise IngestError(f"Couldn't reach {url}: {exc}") from exc
    if resp.status_code != 200:
        raise IngestError(f"{url} returned HTTP {resp.status_code}.")
    if len(resp.content) > MAX_PAGE_BYTES:
        raise IngestError(f"{url} is too large ({len(resp.content) / 1024 / 1024:.1f} MB) to ingest.")
    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and "<html" not in resp.text[:500].lower():
        raise IngestError(f"{url} doesn't look like an HTML page.")
    text = extract_text_from_html(resp.text)
    if not text.strip():
        raise IngestError(f"{url} had no readable text content.")
    return text


# ─── Shared ingest → pending KnowledgeEntry rows ───────────────────────────

def ingest_chunks(
    db: Session,
    tenant_id: str,
    text: str,
    *,
    source: str,
    source_url: Optional[str] = None,
    source_ref: Optional[str] = None,
    file_s3_key: Optional[str] = None,
    category: str = "other",
    created_by: Optional[str] = None,
) -> list[KnowledgeEntry]:
    """Chunk `text` and store each piece as a pending KnowledgeEntry,
    queuing embedding for each. Never marks anything approved -- a human
    must review machine-sourced content before the AI can use it
    (knowledge_service.search() only retrieves review_status="approved").
    """
    chunks = knowledge_service.chunk_text(text)
    entries: list[KnowledgeEntry] = []
    for chunk in chunks:
        entry = KnowledgeEntry(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            category=category,
            question=None,
            content=chunk,
            source=source,
            source_url=source_url,
            source_ref=source_ref,
            file_s3_key=file_s3_key,
            priority=0,
            is_active=True,
            review_status="pending",
            embedding_status="pending",
            created_by=created_by,
        )
        db.add(entry)
        entries.append(entry)
    db.commit()
    for entry in entries:
        db.refresh(entry)
        try:
            from app.workers.tasks.embed_knowledge import embed_entry as embed_task
            embed_task.delay(tenant_id, entry.id)
        except Exception as exc:
            log.warning("kb_ingest_embed_enqueue_failed", entry_id=entry.id, tenant_id=tenant_id, error=str(exc))
    log.info(
        "kb_bulk_ingested", tenant_id=tenant_id, source=source, source_url=source_url,
        source_ref=source_ref, chunk_count=len(entries),
    )
    return entries
