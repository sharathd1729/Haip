"""Inbound webhooks FROM the whatsmeow bridge service (not from WhatsApp/Meta
directly -- the bridge is our own internal component, not a third party).

Auth is a per-session secret read from the X-Bridge-Secret header and
compared with secrets.compare_digest, same discipline CLAUDE.md requires
for the official WhatsApp verify token -- never a global/shared secret
across sessions.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.whatsapp_personal_session import WhatsAppPersonalSession
from app.schemas.whatsapp_personal import WhatsAppPersonalHistoryIn, WhatsAppPersonalInboundMessageIn, WhatsAppPersonalStatusUpdateIn
from app.services import whatsapp_personal_service as svc
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/webhooks/whatsapp-personal", tags=["webhooks-whatsapp-personal"])


def _resolve_session_or_401(db: Session, session_id: str, request: Request) -> WhatsAppPersonalSession:
    session = db.query(WhatsAppPersonalSession).filter_by(id=session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Unknown session")
    provided_secret = request.headers.get("x-bridge-secret", "")
    if not svc.verify_bridge_secret(session, provided_secret):
        log.warning("wa_personal_webhook_bad_secret", session_id=session_id)
        raise HTTPException(status_code=401, detail="Invalid bridge secret")
    return session


@router.post("/{session_id}/message")
def bridge_inbound_message(
    session_id: str,
    body: WhatsAppPersonalInboundMessageIn,
    request: Request,
    db: Session = Depends(get_db),
):
    session = _resolve_session_or_401(db, session_id, request)
    svc.ingest_chat_message(db, session, **body.model_dump())
    return {"status": "ok"}


# Older messages WhatsApp sends right after a phone is linked. One batch per request; capped so a huge history cannot hold a worker.
MAX_HISTORY_BATCH = 200


@router.post("/{session_id}/history")
def bridge_history(
    session_id: str,
    body: WhatsAppPersonalHistoryIn,
    request: Request,
    db: Session = Depends(get_db),
):
    session = _resolve_session_or_401(db, session_id, request)
    stored = 0
    for m in body.messages[:MAX_HISTORY_BATCH]:
        fields = m.model_dump()
        fields.update(history=True, media_base64=None)          # history never carries files
        try:
            if svc.ingest_chat_message(db, session, **fields) is not None:
                stored += 1
        except Exception as exc:  # noqa: BLE001  one bad message must not lose the batch
            db.rollback()
            log.warning("wa_personal_history_message_failed", session_id=session_id, error=str(exc)[:200])
    return {"status": "ok", "stored": stored, "received": min(len(body.messages), MAX_HISTORY_BATCH)}


@router.post("/{session_id}/status")
def bridge_status_update(
    session_id: str,
    body: WhatsAppPersonalStatusUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
):
    session = _resolve_session_or_401(db, session_id, request)
    svc.apply_status_update(
        db, session,
        status=body.status, phone_number=body.phone_number, device_jid=body.device_jid,
        qr_code_data_url=body.qr_code_data_url,
    )
    return {"status": "ok"}
