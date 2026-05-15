"""Transcription dispatch service — routes to the configured provider."""
import json
import uuid
from typing import Optional
from sqlalchemy.orm import Session
from app.models.transcript import Transcript
from app.core.config import settings
import structlog

log = structlog.get_logger()


def store_transcript(
    db: Session,
    call_id: str,
    tenant_id: str,
    turns: list,
    raw_text: str,
    provider: str,
    language: Optional[str] = None,
) -> Transcript:
    existing = db.query(Transcript).filter_by(call_id=call_id).first()
    if existing:
        existing.turns = json.dumps(turns)
        existing.raw_text = raw_text
        existing.language = language
        return existing

    t = Transcript(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        call_id=call_id,
        provider=provider,
        language=language,
        turns=json.dumps(turns),
        raw_text=raw_text,
        redacted=False,
    )
    db.add(t)
    db.flush()
    log.info("transcript_stored", call_id=call_id, provider=provider, turns=len(turns))
    return t


def redact_pii(text: str) -> str:
    """
    L1 PII redaction: replace Indian phone, Aadhaar, PAN, email patterns with tokens.
    Reversible vault is not needed for the stored version — just anonymise before Claude.
    """
    import re
    # Indian mobile numbers
    text = re.sub(r'\b[6-9]\d{9}\b', '<PHONE>', text)
    # E.164 +91 format
    text = re.sub(r'\+91[-\s]?\d{10}', '<PHONE>', text)
    # Aadhaar (12-digit)
    text = re.sub(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '<AADHAAR>', text)
    # PAN (5 letters, 4 digits, 1 letter)
    text = re.sub(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b', '<PAN>', text)
    # Email
    text = re.sub(r'\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b', '<EMAIL>', text)
    return text
