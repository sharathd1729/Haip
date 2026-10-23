"""Evidence on a lead (lead_evidence_service): every interaction recorded in HAIP, so the reason a lead was won or lost can be
read from what was actually said.

POST /leads/{inquiry_id}/evidence   multipart: kind = chat_export | call_recording, file, and
                                    chat_export:    guest_sender (when HAIP asked "which name is the guest?"), date_order
                                    call_recording: direction inbound | outbound, started_at (ISO, optional), note
                                    -> the upload's row. 422 {code: pick_guest_sender, senders} asks which name is the guest.
GET  /leads/{inquiry_id}/evidence   the lead's uploads, newest first, with a recording's processing state
leads.write to upload, leads.read to list; scoped roles only on their own or unowned leads (404). Audited
lead.evidence_imported.
"""
from datetime import datetime
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.endpoints.leads import _visibility_scope
from app.core.database import get_db
from app.models.user import User
from app.services import lead_evidence_service as svc
from app.services.authz_service import require_capability

log = structlog.get_logger()
router = APIRouter(prefix="/leads", tags=["leads360"])

_READ_LIMIT = svc.MAX_ZIP_BYTES + 1


async def _read(file: UploadFile) -> bytes:
    data = await file.read(_READ_LIMIT)
    if len(data) >= _READ_LIMIT:
        raise HTTPException(status_code=413, detail={"code": "file_too_large", "message": "That file is larger than 50 MB."})
    return data


@router.post("/{inquiry_id}/evidence", status_code=201)
async def upload_evidence(
    inquiry_id: str,
    kind: Literal["chat_export", "call_recording"] = Form(...),
    file: UploadFile = File(...),
    guest_sender: Optional[str] = Form(default=None, max_length=200),
    date_order: Optional[Literal["dmy", "mdy", "ymd"]] = Form(default=None),
    direction: Literal["inbound", "outbound"] = Form(default="outbound"),
    started_at: Optional[str] = Form(default=None),
    note: Optional[str] = Form(default=None, max_length=500),
    current_user: User = Depends(require_capability("leads.write")),
    db: Session = Depends(get_db),
) -> dict:
    content = await _read(file)
    scope = _visibility_scope(current_user)
    try:
        if kind == "chat_export":
            out = svc.import_chat(db, current_user, inquiry_id, filename=file.filename or "chat.txt", content=content,
                                  guest_sender_name=guest_sender, date_order=date_order, scope_user_id=scope)
            db.commit()
            return out
        when = None
        if started_at:
            try:
                when = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(status_code=422, detail={"code": "bad_started_at", "message": "started_at must be an ISO date-time."})
        out, call = svc.import_recording(db, current_user, inquiry_id, filename=file.filename or "recording", content=content,
                                         direction=direction, started_at=when, note=note, scope_user_id=scope)
    except svc.EvidenceError as exc:   # raised before anything is written, so there is nothing to roll back
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    db.commit()
    if call.transcription_status == "queued":
        try:   # the SAME pipeline an IVR recording takes: transcribe -> classify -> judge -> wrap_up -> scoring
            from app.workers.tasks.transcribe import transcribe
            transcribe.delay(call_id=call.id, tenant_id=current_user.tenant_id)
        except Exception as exc:  # noqa: BLE001 -- broker down: say so, the recovery sweep picks queued calls up again
            log.warning("lead_evidence_transcribe_enqueue_failed", tenant_id=current_user.tenant_id, call_id=call.id, error=str(exc)[:200])
    return out


@router.get("/{inquiry_id}/evidence")
def list_evidence(inquiry_id: str, current_user: User = Depends(require_capability("leads.read")),
                  db: Session = Depends(get_db)) -> dict:
    try:
        return {"items": svc.list_imports(db, current_user, inquiry_id, scope_user_id=_visibility_scope(current_user))}
    except svc.EvidenceError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail())
