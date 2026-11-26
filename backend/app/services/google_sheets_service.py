"""Google Sheets lead sync, the simple way (no Google login): the owner deploys a short Apps Script as a web app and
pastes its address; HAIP POSTs one JSON row per new lead (the same moment lead.created fires, webhook_events).

Stored as an Integration row (kind ``google_sheets``): the address encrypted in ``credentials_kms_blob``, the status
(last row sent / last error) in ``config``. Only https://script.google.com/macros/s/<id>/exec is accepted, so the
request can never be pointed at an internal host (SSRF guard by allow-list).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.integration import Integration

log = structlog.get_logger()

KIND = "google_sheets"
TIMEOUT_SECONDS = 15
_URL_RE = re.compile(r"^https://script\.google\.com/macros/s/[A-Za-z0-9_-]{20,200}/exec$")


class SheetSendError(Exception):
    """The sheet did not accept the row. ``retry`` is False when retrying cannot help (wrong address, removed script)."""

    def __init__(self, message: str, retry: bool = True):
        super().__init__(message)
        self.retry = retry


def valid_url(url: str) -> bool:
    return bool(_URL_RE.match((url or "").strip()))


def get_row(db: Session, tenant_id: str) -> Optional[Integration]:
    return db.query(Integration).filter_by(tenant_id=tenant_id, kind=KIND).first()


def is_on(db: Session, tenant_id: str) -> bool:
    row = get_row(db, tenant_id)
    return bool(row and row.status == "active" and row.credentials_kms_blob)


def _url(row: Integration) -> str:
    blob = bytes(row.credentials_kms_blob) if isinstance(row.credentials_kms_blob, memoryview) else row.credentials_kms_blob
    return decrypt_credentials(blob).get("url", "") if blob else ""


def save(db: Session, tenant_id: str, url: Optional[str], enabled: bool) -> Integration:
    """Set the address (when given) and switch sending on or off. Caller validates the address and commits."""
    row = get_row(db, tenant_id)
    if enabled and not url and not (row and row.credentials_kms_blob):
        raise ValueError("Paste your Apps Script web app address first.")
    if row is None:
        row = Integration(tenant_id=tenant_id, kind=KIND, status="disconnected", config={})
        db.add(row)
    if url:
        row.credentials_kms_blob = encrypt_credentials({"url": url.strip()})
        row.config = {**(row.config or {}), "last_error": None, "last_error_at": None}
    row.status = "active" if enabled else "disconnected"
    db.flush()
    return row


def status(row: Optional[Integration]) -> dict:
    cfg = (row.config or {}) if row else {}
    url = _url(row) if row and row.credentials_kms_blob else ""
    return {
        "enabled": bool(row and row.status == "active"),
        "connected": bool(url),
        # Only the end of the address: enough to recognise it, not enough to post rows into someone's sheet.
        "url_hint": f"…{url[-18:]}" if url else None,
        "last_sent_at": cfg.get("last_sent_at"),
        "rows_sent": cfg.get("rows_sent", 0),
        "last_error": cfg.get("last_error"),
        "last_error_at": cfg.get("last_error_at"),
    }


def lead_row(db: Session, tenant_id: str, guest_id: str) -> Optional[dict]:
    """The row for one lead: name, phone, source, created time, stage, first message preview."""
    from app.models.conversation import Conversation, Message, MessageDirection
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry
    from app.models.pipeline_stage import PipelineStage

    g = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
    if g is None:
        return None
    inq = (db.query(Inquiry).filter_by(tenant_id=tenant_id, guest_id=g.id)
           .order_by(Inquiry.created_at.desc()).first())
    stage = None
    if inq is not None and inq.stage_id:
        stage = db.query(PipelineStage.label).filter_by(id=inq.stage_id, tenant_id=tenant_id).scalar()
    first = (db.query(Message.body).join(Conversation, Conversation.id == Message.conversation_id)
             .filter(Message.tenant_id == tenant_id, Conversation.guest_id == g.id,
                     Message.direction == MessageDirection.INBOUND, Message.is_internal.is_(False), Message.body.isnot(None))
             .order_by(Message.created_at.asc()).first())
    source = inq.source.value if inq is not None and inq.source is not None and hasattr(inq.source, "value") else (
        inq.source if inq is not None and inq.source else (g.lead_identified_via or g.first_touch_channel))
    when = g.lead_identified_at or g.created_at
    return {
        "name": g.name or "", "phone": g.phone or "", "source": source or "",
        "created_at": when.isoformat() if when else "", "stage": stage or "",
        "first_message": ((first[0] if first else "") or "")[:200],
    }


def test_row() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {"name": "Test row from HAIP", "phone": "+910000000000", "source": "test", "created_at": now,
            "stage": "General Enquiry", "first_message": "Hi, is the caravan free next weekend?"}


def post_row(url: str, row: dict, client: Optional[httpx.Client] = None) -> None:
    """POST one row. Raises SheetSendError on failure. Apps Script answers doPost with a 302 to googleusercontent.com
    once the script has run, so 200 and 302/303 both mean the row was written (as in webhook_service._delivered)."""
    if not valid_url(url):
        raise SheetSendError("The saved address is not an Apps Script web app address.", retry=False)
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
    try:
        resp = client.post(url, json=row, headers={"User-Agent": "HAIP-Sheets/1.0"})
    except httpx.HTTPError as exc:
        raise SheetSendError(f"Could not reach Google ({exc.__class__.__name__}).") from exc
    finally:
        if own:
            client.close()
    if 200 <= resp.status_code < 300 or resp.status_code in (302, 303):
        return
    if resp.status_code in (401, 403, 404):
        raise SheetSendError(f"Google answered HTTP {resp.status_code}. Check the script is deployed with access "
                             "'Anyone' and the address is the latest deployment.", retry=False)
    raise SheetSendError(f"Google answered HTTP {resp.status_code}.")


def record(db: Session, row: Integration, error: Optional[str], count: bool = True) -> None:
    """Keep the status the settings card shows. Caller commits."""
    now = datetime.now(timezone.utc).isoformat()
    cfg = dict(row.config or {})
    if error:
        cfg.update(last_error=error[:300], last_error_at=now)
    else:
        cfg.update(last_sent_at=now, rows_sent=int(cfg.get("rows_sent") or 0) + (1 if count else 0), last_error=None, last_error_at=None)
    row.config = cfg


def send_lead(db: Session, tenant_id: str, guest_id: str, client: Optional[httpx.Client] = None) -> str:
    """Send one lead's row now. Returns sent | skipped. Raises SheetSendError (status already recorded) on failure."""
    row = get_row(db, tenant_id)
    if row is None or row.status != "active" or not row.credentials_kms_blob:
        return "skipped"
    data = lead_row(db, tenant_id, guest_id)
    if data is None:
        return "skipped"
    try:
        post_row(_url(row), data, client)
    except SheetSendError as exc:
        record(db, row, str(exc))
        db.commit()
        raise
    record(db, row, None)
    db.commit()
    return "sent"


def send_test(db: Session, tenant_id: str, client: Optional[httpx.Client] = None) -> dict:
    row = get_row(db, tenant_id)
    if row is None or not row.credentials_kms_blob:
        return {"ok": False, "message": "Paste your Apps Script web app address first."}
    try:
        post_row(_url(row), test_row(), client)
    except SheetSendError as exc:
        record(db, row, str(exc))
        return {"ok": False, "message": str(exc)}
    record(db, row, None, count=False)
    return {"ok": True, "message": "A test row was added to your sheet. Open it to check."}
