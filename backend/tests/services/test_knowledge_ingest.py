"""Knowledge base bulk ingestion: website crawling + document upload.

Text-extraction helpers are tested against real documents built with the
same libraries used to read them (pypdf/python-docx), not hand-crafted
fixture bytes -- a round-trip through the real format is the only way to
know the extractor actually works against real output from those tools.
"""
import io
import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services import knowledge_ingest as ki
from app.models.tenant import Tenant
from app.models.knowledge import KnowledgeEntry


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    """Test hostnames don't resolve offline; the SSRF check itself is
    covered in tests/test_security_review_fixes.py."""
    monkeypatch.setattr("app.core.url_safety.assert_public_url", lambda *a, **k: None)


# ─── extract_text_from_pdf ──────────────────────────────────────────────────

def _make_pdf_bytes(text: str) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import RectangleObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    # pypdf has no simple "write text" helper on a blank page without
    # reportlab -- use its own annotation/content-stream API is overkill
    # for a unit test. Simpler: build via reportlab-free raw content stream.
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject
    content = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode("latin-1")
    from pypdf.generic import StreamObject, ArrayObject, NumberObject
    stream = StreamObject()
    stream.set_data(content)
    stream[NameObject("/Length")] = NumberObject(len(content))
    page[NameObject("/Contents")] = writer._add_object(stream)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
        })
    })
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestExtractTextFromPdf:
    def test_extracts_real_text_from_a_real_pdf(self):
        pdf_bytes = _make_pdf_bytes("Pets are welcome in all caravans")
        text = ki.extract_text_from_pdf(pdf_bytes)
        assert "Pets are welcome" in text

    def test_garbage_bytes_raise_ingest_error(self):
        with pytest.raises(ki.IngestError):
            ki.extract_text_from_pdf(b"not a real pdf at all")


# ─── extract_text_from_docx ──────────────────────────────────────────────────

class TestExtractTextFromDocx:
    def test_extracts_paragraphs_and_table_cells_from_a_real_docx(self):
        from docx import Document

        doc = Document()
        doc.add_paragraph("Check-in is at 2pm, check-out at 11am.")
        table = doc.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "White Caravan"
        table.rows[0].cells[1].text = "8 guests"
        buf = io.BytesIO()
        doc.save(buf)

        text = ki.extract_text_from_docx(buf.getvalue())
        assert "Check-in is at 2pm" in text
        assert "White Caravan" in text
        assert "8 guests" in text

    def test_garbage_bytes_raise_ingest_error(self):
        with pytest.raises(ki.IngestError):
            ki.extract_text_from_docx(b"not a real docx at all")


# ─── extract_text_from_html ──────────────────────────────────────────────────

class TestExtractTextFromHtml:
    def test_strips_nav_script_style_footer_keeps_content(self):
        html = """
        <html><head><style>.x{color:red}</style></head>
        <body>
          <nav>Home | About | Contact</nav>
          <script>console.log('tracking')</script>
          <main><h1>Amenities</h1><p>Free WiFi and AC in every caravan.</p></main>
          <footer>Copyright 2026</footer>
        </body></html>
        """
        text = ki.extract_text_from_html(html)
        assert "Free WiFi and AC" in text
        assert "console.log" not in text
        assert "color:red" not in text
        assert "Home | About | Contact" not in text
        assert "Copyright 2026" not in text


# ─── extract_text_from_upload dispatch ───────────────────────────────────────

class TestExtractTextFromUploadDispatch:
    def test_txt_extension_decodes_as_text(self):
        assert ki.extract_text_from_upload("notes.txt", "text/plain", b"hello world") == "hello world"

    def test_unsupported_extension_raises_ingest_error(self):
        with pytest.raises(ki.IngestError):
            ki.extract_text_from_upload("photo.jpg", "image/jpeg", b"\xff\xd8\xff")


# ─── fetch_url_text ──────────────────────────────────────────────────────────

class TestFetchUrlText:
    def test_invalid_url_raises_immediately(self):
        with pytest.raises(ki.IngestError):
            ki.fetch_url_text("not-a-url")

    def test_non_200_raises_ingest_error(self):
        mock_resp = MagicMock(status_code=404, content=b"", headers={"content-type": "text/html"}, text="")
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.get.return_value = mock_resp
            with pytest.raises(ki.IngestError, match="404"):
                ki.fetch_url_text("https://example.test/missing")

    def test_oversized_page_raises_ingest_error(self):
        big = b"x" * (ki.MAX_PAGE_BYTES + 1)
        mock_resp = MagicMock(status_code=200, content=big, headers={"content-type": "text/html"}, text="<html></html>")
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.get.return_value = mock_resp
            with pytest.raises(ki.IngestError, match="too large"):
                ki.fetch_url_text("https://example.test/huge")

    def test_successful_fetch_extracts_html_text(self):
        html = "<html><body><p>Our villas start at a great rate.</p></body></html>"
        mock_resp = MagicMock(
            status_code=200, content=html.encode(), headers={"content-type": "text/html"}, text=html,
        )
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.get.return_value = mock_resp
            text = ki.fetch_url_text("https://example.test/faq")
        assert "Our villas start at a great rate" in text


# ─── ingest_chunks ───────────────────────────────────────────────────────────

def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.commit()
    return t


class TestIngestChunks:
    def test_creates_pending_entries_with_correct_provenance(self, db, monkeypatch):
        monkeypatch.setattr("app.workers.tasks.embed_knowledge.embed_entry.delay", MagicMock())
        tenant = _make_tenant(db)

        entries = ki.ingest_chunks(
            db, tenant.id, "Free WiFi in every caravan.\n\nPets welcome at no extra charge.",
            source="document", source_ref="brochure.pdf", file_s3_key="t1/knowledge/abc/brochure.pdf",
        )

        assert len(entries) >= 1
        for e in entries:
            assert e.review_status == "pending"  # never auto-approved
            assert e.embedding_status == "pending"
            assert e.source == "document"
            assert e.source_ref == "brochure.pdf"
            assert e.file_s3_key == "t1/knowledge/abc/brochure.pdf"

        stored = db.query(KnowledgeEntry).filter_by(tenant_id=tenant.id).all()
        assert len(stored) == len(entries)

    def test_website_source_carries_source_url_not_file_key(self, db, monkeypatch):
        monkeypatch.setattr("app.workers.tasks.embed_knowledge.embed_entry.delay", MagicMock())
        tenant = _make_tenant(db)

        entries = ki.ingest_chunks(
            db, tenant.id, "Check-in from 2pm.",
            source="website", source_url="https://example.test/faq",
        )
        assert len(entries) == 1
        assert entries[0].source == "website"
        assert entries[0].source_url == "https://example.test/faq"
        assert entries[0].file_s3_key is None

    def test_embed_enqueue_failure_does_not_break_ingestion(self, db, monkeypatch):
        """A broker hiccup must not lose the ingested content -- the rows
        stay pending-embed and a later reembed sweep picks them up, same
        contract as the manual-entry create path (_queue_embed)."""
        def _boom(*a, **kw):
            raise RuntimeError("broker down")
        monkeypatch.setattr("app.workers.tasks.embed_knowledge.embed_entry.delay", _boom)
        tenant = _make_tenant(db)

        entries = ki.ingest_chunks(db, tenant.id, "Some real content here.", source="document")
        assert len(entries) == 1
        assert db.query(KnowledgeEntry).filter_by(tenant_id=tenant.id).count() == 1
