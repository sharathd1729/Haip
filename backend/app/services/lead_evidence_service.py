"""Raw evidence on a lead (sales meetings 22-23 Oct 2026): every interaction recorded in HAIP, so the MACHINE -- not a
person's remark -- can say why a lead was won or lost. POST /leads/{id}/evidence (endpoints/lead_evidence.py).

import_chat       the file WhatsApp "Export chat" makes: .txt (<= 10 MB) or .zip (<= 50 MB) holding a .txt (_chat.txt on
                  iPhone) and the photos / voice notes / documents (<= 16 MB each, known types only; read from memory, never
                  extracted to disk, so no path in the zip can escape). chat_export_parser reads Android and iOS formats.
                  Sides: the sender whose number or name matches the lead's guest is the GUEST (inbound); everyone else is
                  staff (outbound, sender_name = the name in the export, no sender_id: the uploader may not be who typed).
                  If no sender (or more than one) matches, the caller is asked to pick (422 ``pick_guest_sender``).
                  Messages go into the guest's personal-WhatsApp thread (Conversation.source "personal_bridge": the chat
                  happened on a staff phone, so HAIP never answers it from the official number, the 24 h business window
                  is not opened by it, the concierge / reply recovery skip it); none = a new one (closed when the guest
                  already has an open WhatsApp thread, the one-open-thread rule). Every message is marked
                  ``sender_kind = "chat_export"`` + ``channel_metadata.source = "chat_export"``; never AI.
                  Deduplicated on (side, minute, text hash) against every WhatsApp message the guest already has (bridge
                  mirror, Cloud API, an earlier import; +-1 minute for clock rounding), so a re-upload adds nothing.
                  Nothing is queued: no concierge draft, no summary refresh (which would run the lead autopilot), no
                  playbook. An imported message a staff member sent counts as contact for the work queue exactly like a
                  bridge-live one (work_queue_signals.touch_rows: chat_export is not in NOT_CONTACT_KINDS).
import_recording  an audio file (mp3, m4a, aac, wav, ogg, opus, amr; <= 50 MB; duration from ffprobe when installed) ->
                  media_storage -> a Call (ivr_provider "upload", agent = the uploader, the lead's guest, connected) -> the
                  caller queues tasks.transcribe, the SAME pipeline IVR recordings use (transcribe -> classify -> judge ->
                  wrap_up -> scoring). Connected = contact; call-back reminders close like any connected call.
list_imports      the lead's uploads, newest first, with a recording's processing state read from its Call.

Both audited ``lead.evidence_imported``. Scoped roles only on their own or unowned leads (404 otherwise). The caller commits.
"""
from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.orm import Session

from app.models.call import Call, CallDirection, RecordingStatus
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.lead_evidence import LeadEvidenceImport
from app.models.tenant import Tenant
from app.models.user import User
from app.services import chat_export_parser

log = structlog.get_logger()

SOURCE = "chat_export"
UPLOAD_PROVIDER = "upload"
MAX_TXT_BYTES = 10 * 1024 * 1024
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_MEDIA_BYTES = 16 * 1024 * 1024
MAX_ZIP_UNPACKED = 300 * 1024 * 1024
MAX_ZIP_ENTRIES = 3000
MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_MESSAGES = 20000

# Media a chat export may carry: extension -> (content type, Message.media_type). Anything else in the zip is ignored.
MEDIA_TYPES = {
    "jpg": ("image/jpeg", "image"), "jpeg": ("image/jpeg", "image"), "png": ("image/png", "image"),
    "webp": ("image/webp", "sticker"), "gif": ("image/gif", "image"),
    "mp4": ("video/mp4", "video"), "3gp": ("video/3gpp", "video"), "mov": ("video/quicktime", "video"),
    "opus": ("audio/ogg", "audio"), "ogg": ("audio/ogg", "audio"), "m4a": ("audio/mp4", "audio"), "mp3": ("audio/mpeg", "audio"),
    "aac": ("audio/aac", "audio"), "amr": ("audio/amr", "audio"), "pdf": ("application/pdf", "document"),
}
AUDIO_TYPES = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac", "wav": "audio/wav", "ogg": "audio/ogg",
               "opus": "audio/ogg", "amr": "audio/amr"}
_PLACEHOLDER = {"image": "[photo]", "video": "[video]", "audio": "[voice message]", "document": "[document]", "sticker": "[sticker]"}


class EvidenceError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: Optional[dict] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra or {}

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message, **self.extra}


# ── shared ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _lead(db: Session, user: User, inquiry_id: str, scope_user_id: Optional[str]) -> tuple[Inquiry, Guest]:
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=user.tenant_id).first()
    if inq is None or (scope_user_id and inq.assigned_to and inq.assigned_to != scope_user_id):
        raise EvidenceError(404, "not_found", "Lead not found")
    guest = db.query(Guest).filter_by(id=inq.guest_id, tenant_id=user.tenant_id).first()
    if guest is None:
        raise EvidenceError(404, "not_found", "Lead not found")
    return inq, guest


def _ext(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower().lstrip(".")


def _audit(db: Session, user: User, row: LeadEvidenceImport, extra: dict) -> None:
    from app.core.audit import append_audit
    append_audit(db, tenant_id=user.tenant_id, action="lead.evidence_imported", actor_user_id=user.id, target_type="inquiry",
                 target_id=row.inquiry_id, payload={"import_id": row.id, "kind": row.kind, **extra})


# ── chat export ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def _safe_member(name: str) -> bool:
    n = name.replace("\\", "/")
    return bool(n) and not n.startswith("/") and ".." not in n.split("/") and ":" not in n.split("/")[0]


def _read_zip(content: bytes) -> tuple[str, dict]:
    """(chat text, {basename: ZipInfo}) -- members are read from memory only; unsafe or oversized ones are refused."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise EvidenceError(422, "bad_zip", "That zip file could not be opened.")
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise EvidenceError(413, "too_many_files", "That zip holds too many files.")
    if sum(i.file_size for i in infos) > MAX_ZIP_UNPACKED:
        raise EvidenceError(413, "zip_too_large", "That zip unpacks to more than 300 MB.")
    chat, media = None, {}
    for info in infos:
        if info.is_dir():
            continue
        if not _safe_member(info.filename):
            raise EvidenceError(422, "unsafe_zip", "That zip has a file path that is not allowed.")
        if info.flag_bits & 0x1:
            raise EvidenceError(422, "encrypted_zip", "That zip is password protected.")
        base = os.path.basename(info.filename.replace("\\", "/"))
        ext = _ext(base)
        if ext == "txt" and (chat is None or base == "_chat.txt"):
            chat = info
        elif ext in MEDIA_TYPES and info.file_size <= MAX_MEDIA_BYTES:
            media[base] = info
    if chat is None:
        raise EvidenceError(422, "no_chat_text", "No chat text (.txt) found in the zip. Use WhatsApp > Export chat.")
    if chat.file_size > MAX_TXT_BYTES:
        raise EvidenceError(413, "chat_too_large", "The chat text is larger than 10 MB.")
    with zf.open(chat) as fh:
        text = _decode(fh.read(MAX_TXT_BYTES + 1)[:MAX_TXT_BYTES])
    return text, {"zip": zf, "media": media}


def _digits(value: Optional[str]) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _norm_name(value: Optional[str]) -> str:
    return " ".join((value or "").casefold().split())


def guest_sender(senders: list[str], guest: Guest, phones: list[str]) -> Optional[str]:
    """The ONE sender that is the guest: same last 10 digits as one of the guest's numbers, else the same name (or the
    same first name when that is unique). None when nobody or several match."""
    tails = {d[-10:] for d in (_digits(p) for p in phones) if len(d) >= 10}
    by_phone = [s for s in senders if len(_digits(s)) >= 10 and _digits(s)[-10:] in tails]
    if len(by_phone) == 1:
        return by_phone[0]
    name = _norm_name(guest.name)
    if not name or name in ("unknown", "guest", "whatsapp contact"):
        return None
    exact = [s for s in senders if _norm_name(s) == name]
    if len(exact) == 1:
        return exact[0]
    first = name.split()[0]
    loose = [s for s in senders if _norm_name(s).split()[:1] == [first]]
    return loose[0] if len(loose) == 1 else None


def _guest_phones(db: Session, tenant_id: str, guest: Guest) -> list[str]:
    from app.models.guest_identity import GuestIdentity
    rows = (db.query(GuestIdentity.identity_value).filter(GuestIdentity.tenant_id == tenant_id, GuestIdentity.guest_id == guest.id,
                                                         GuestIdentity.identity_type.in_(("phone", "whatsapp_number"))).all())
    return [guest.phone or "", *[r[0] or "" for r in rows]]


def _norm_text(text: str, media: bool) -> str:
    body = " ".join((text or "").casefold().split())
    if body in {v.strip("[]") for v in _PLACEHOLDER.values()} | set(_PLACEHOLDER.values()) | {"[media]"}:
        body = ""
    return ("[media]" if media else "") + body


def _key(direction: str, at: datetime, text_norm: str) -> tuple[str, str, str]:
    minute = at.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()
    return direction, minute, hashlib.sha256(text_norm.encode("utf-8")).hexdigest()[:24]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _existing_keys(db: Session, tenant_id: str, guest_id: str, start: datetime, end: datetime) -> set:
    rows = (db.query(Message.direction, Message.created_at, Message.body, Message.media_type, Message.media_url)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .filter(Conversation.tenant_id == tenant_id, Message.tenant_id == tenant_id, Conversation.guest_id == guest_id,
                    Conversation.channel == ChannelType.WHATSAPP, Message.is_internal.isnot(True),
                    Message.created_at >= start - timedelta(minutes=2), Message.created_at <= end + timedelta(minutes=2)).all())
    keys = set()
    for direction, at, body, media_type, media_url in rows:
        d = getattr(direction, "value", direction)
        keys.add(_key(d, _aware(at), _norm_text(body or "", bool(media_type or media_url) or (body or "").strip() in (*_PLACEHOLDER.values(), "[media]"))))
    return keys


def _thread(db: Session, tenant_id: str, guest: Guest, uploader_id: str) -> Conversation:
    """The guest's personal-WhatsApp thread, else a new one (closed when an open WhatsApp thread already exists)."""
    conv = (db.query(Conversation).filter_by(tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, source="personal_bridge")
            .order_by(Conversation.is_open.desc(), Conversation.last_message_at.desc()).first())
    if conv is not None:
        return conv
    has_open = db.query(Conversation.id).filter_by(tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP,
                                                   is_open=True).first() is not None
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP,
                        source="personal_bridge", is_open=not has_open, assigned_to=uploader_id, ai_mode="off")
    db.add(conv)
    db.flush()
    return conv


def import_chat(db: Session, user: User, inquiry_id: str, *, filename: str, content: bytes, guest_sender_name: Optional[str] = None,
                date_order: Optional[str] = None, scope_user_id: Optional[str] = None,
                upload=None) -> dict:
    """Write an exported chat into the lead's WhatsApp history. ``upload`` = media_storage.upload_lead_evidence (tests)."""
    inquiry, guest = _lead(db, user, inquiry_id, scope_user_id)
    tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()
    ext = _ext(filename)
    is_zip = content[:2] == b"PK" or ext == "zip"
    if is_zip:
        if len(content) > MAX_ZIP_BYTES:
            raise EvidenceError(413, "file_too_large", "A chat export zip may be up to 50 MB.")
        text, bundle = _read_zip(content)
    else:
        if ext not in ("txt", ""):
            raise EvidenceError(415, "unsupported_file", "Upload the .txt or .zip file WhatsApp's Export chat makes.")
        if len(content) > MAX_TXT_BYTES:
            raise EvidenceError(413, "file_too_large", "A chat export text file may be up to 10 MB.")
        text, bundle = _decode(content), {"zip": None, "media": {}}

    parsed = chat_export_parser.parse(text, date_order=date_order)
    if not parsed.messages:
        raise EvidenceError(422, "no_messages", "No messages found. Use WhatsApp > Export chat and upload the file it makes.")
    if len(parsed.messages) > MAX_MESSAGES:
        raise EvidenceError(413, "too_many_messages", f"That chat has more than {MAX_MESSAGES:,} messages.")
    senders = [s for s, _ in parsed.senders]
    if guest_sender_name:
        if guest_sender_name not in senders:
            raise EvidenceError(422, "unknown_sender", "That name is not in the chat.", {"senders": _sender_list(parsed)})
        who = guest_sender_name
    else:
        who = guest_sender(senders, guest, _guest_phones(db, user.tenant_id, guest))
        if who is None:
            raise EvidenceError(422, "pick_guest_sender", "Which name in the chat is the guest?", {"senders": _sender_list(parsed)})

    tz = ZoneInfo(getattr(tenant, "timezone", None) or "Asia/Kolkata")
    stamped = [(m, m.at.replace(tzinfo=tz).astimezone(timezone.utc)) for m in parsed.messages]
    first_at, last_at = min(a for _, a in stamped), max(a for _, a in stamped)
    seen = _existing_keys(db, user.tenant_id, guest.id, first_at, last_at)

    row = LeadEvidenceImport(id=str(uuid.uuid4()), tenant_id=user.tenant_id, inquiry_id=inquiry.id, guest_id=guest.id,
                             kind="chat_export", status="done", filename=(filename or "chat.txt")[:255], uploaded_by=user.id)
    conv = _thread(db, user.tenant_id, guest, user.id)
    row.conversation_id = conv.id
    if upload is None:
        from app.services.media_storage import upload_lead_evidence as upload

    added = dupes = media_n = media_skipped = 0
    newest = None
    for m, at in stamped:
        direction = "inbound" if m.sender == who else "outbound"
        has_media = bool(m.media_file or m.media_omitted)
        k = _key(direction, at, _norm_text(m.text, has_media))
        near = {_key(direction, at + timedelta(minutes=d), _norm_text(m.text, has_media)) for d in (-1, 1)}
        if k in seen or near & seen:
            dupes += 1
            continue
        seen.add(k)
        media_key = media_type = None
        if m.media_file and m.media_file in bundle["media"]:
            ctype, kind = MEDIA_TYPES[_ext(m.media_file)]
            try:
                with bundle["zip"].open(bundle["media"][m.media_file]) as fh:
                    data = fh.read(MAX_MEDIA_BYTES + 1)
                if len(data) <= MAX_MEDIA_BYTES:
                    media_key, media_type = upload(user.tenant_id, row.id, m.media_file, data, ctype), kind
                    media_n += 1
            except Exception as exc:  # noqa: BLE001 -- one bad file must not cost the chat
                log.warning("lead_evidence_media_failed", tenant_id=user.tenant_id, import_id=row.id, error=str(exc)[:200])
        if has_media and media_key is None:
            media_skipped += 1
        body = m.text or (_PLACEHOLDER.get(media_type or "", "[media]") if has_media else "")
        meta = {"source": SOURCE, "import_id": row.id, "sender_name": m.sender[:120]}
        if m.media_file:
            meta["filename"] = m.media_file[:200]
        msg = Message(id=str(uuid.uuid4()), tenant_id=user.tenant_id, conversation_id=conv.id,
                      direction=MessageDirection.INBOUND if direction == "inbound" else MessageDirection.OUTBOUND,
                      channel=ChannelType.WHATSAPP, body=body, media_url=media_key, media_type=media_type,
                      channel_message_id=f"export:{k[1]}:{k[2]}:{direction[0]}"[:255], channel_status="imported",
                      channel_metadata=meta, created_at=at, sender_kind=SOURCE, is_ai_generated=False,
                      sender_name=m.sender[:255])
        if direction == "outbound":
            msg.delivery_state = MessageDeliveryState.SENT
        db.add(msg)
        added += 1
        newest = at if newest is None or at > newest else newest
    if newest is not None and (not conv.last_message_at or conv.last_message_at < newest.isoformat()):
        conv.last_message_at = newest.isoformat()

    row.message_count, row.duplicate_count, row.media_count = added, dupes, media_n
    row.first_at, row.last_at = first_at, last_at
    row.detail = {"guest_sender": who, "date_order": parsed.date_order, "format": parsed.fmt, "system_lines": parsed.system_lines,
                  "media_not_stored": media_skipped, "senders": len(senders)}
    db.add(row)
    db.flush()
    _audit(db, user, row, {"messages": added, "duplicates": dupes, "media": media_n, "conversation_id": conv.id})
    log.info("lead_evidence_chat_imported", tenant_id=user.tenant_id, inquiry_id=inquiry.id, import_id=row.id, messages=added,
             duplicates=dupes, media=media_n)
    return out(row, {user.id: user.name})


def _sender_list(parsed) -> list[dict]:
    return [{"name": s, "messages": n} for s, n in parsed.senders[:20]]


# ── call recording ─────────────────────────────────────────────────────────────────────────────────────────────────────
def probe_seconds(content: bytes, ext: str) -> Optional[int]:
    """Duration in seconds via ffprobe. None when ffprobe is not installed (the transcript still gets made); raises
    EvidenceError when the file is not playable audio."""
    import json
    fd, path = tempfile.mkstemp(suffix=f".{ext or 'bin'}")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        try:
            res = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                                 capture_output=True, timeout=30, check=False)
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            raise EvidenceError(422, "audio_unreadable", "That recording took too long to read.")
        if res.returncode != 0:
            raise EvidenceError(422, "audio_unreadable", "That recording could not be read. Use mp3, m4a, aac, wav, ogg, opus or amr.")
        info = json.loads(res.stdout or b"{}")
        if not any(s.get("codec_type") == "audio" for s in info.get("streams") or []):
            raise EvidenceError(415, "not_audio", "That file has no sound in it.")
        try:
            return int(float((info.get("format") or {}).get("duration") or 0))
        except ValueError:
            return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def import_recording(db: Session, user: User, inquiry_id: str, *, filename: str, content: bytes, direction: str = "outbound",
                     started_at: Optional[datetime] = None, note: Optional[str] = None, scope_user_id: Optional[str] = None,
                     upload=None, probe=None) -> tuple[dict, Call]:
    """Store the recording and create its Call. The CALLER queues tasks.transcribe after commit (returned Call)."""
    from app.core.config import settings

    inquiry, guest = _lead(db, user, inquiry_id, scope_user_id)
    if direction not in ("inbound", "outbound"):
        raise EvidenceError(422, "bad_direction", "Direction must be inbound or outbound.")
    ext = _ext(filename)
    if ext not in AUDIO_TYPES:
        raise EvidenceError(415, "unsupported_file", "Upload an mp3, m4a, aac, wav, ogg, opus or amr recording.")
    if not content:
        raise EvidenceError(422, "empty_file", "That file is empty.")
    if len(content) > MAX_AUDIO_BYTES:
        raise EvidenceError(413, "file_too_large", "A recording may be up to 50 MB.")
    seconds = (probe or probe_seconds)(content, ext)
    if upload is None:
        from app.services.media_storage import upload_lead_evidence as upload

    row = LeadEvidenceImport(id=str(uuid.uuid4()), tenant_id=user.tenant_id, inquiry_id=inquiry.id, guest_id=guest.id,
                             kind="call_recording", status="processing", filename=(filename or "recording")[:255],
                             uploaded_by=user.id, duration_seconds=seconds)
    key = upload(user.tenant_id, row.id, f"recording.{ext}", content, AUDIO_TYPES[ext])
    now = datetime.now(timezone.utc)
    start = _aware(started_at) if started_at else now - timedelta(seconds=seconds or 0)
    phone = (guest.phone or "unknown")[:20]
    outbound = direction == "outbound"
    paused = bool(getattr(settings, "TRANSCRIPTION_PAUSED", False))
    call = Call(id=str(uuid.uuid4()), tenant_id=user.tenant_id, guest_id=guest.id, inquiry_id=inquiry.id, agent_id=user.id,
                ivr_provider=UPLOAD_PROVIDER, ivr_call_id=f"upload-{uuid.uuid4().hex}",
                direction=CallDirection.OUTBOUND if outbound else CallDirection.INBOUND,
                from_number=UPLOAD_PROVIDER if outbound else phone, to_number=phone if outbound else UPLOAD_PROVIDER,
                duration_seconds=seconds or 0, started_at=start.isoformat(), ended_at=(start + timedelta(seconds=seconds or 0)).isoformat(),
                ivr_dial_status="completed", recording_s3_key=key, recording_fetched=True, recording_status=RecordingStatus.AVAILABLE,
                transcription_status="pending" if paused else "queued", disposition_note=(note or "").strip()[:500] or None,
                created_at=start)
    db.add(call)
    db.flush()
    row.call_id, row.first_at, row.last_at = call.id, start, start
    row.detail = {"direction": direction, "transcription_paused": paused}
    db.add(row)
    db.flush()

    from app.services import lead_assignment_service, lead_task_closer
    lead_assignment_service.on_call_logged(db, inquiry, call)
    resolved = lead_task_closer.resolve_callbacks(db, user.tenant_id, call, actor_user_id=user.id)
    _audit(db, user, row, {"call_id": call.id, "direction": direction, "duration_seconds": seconds,
                           "callbacks_closed": resolved["tasks"]})
    log.info("lead_evidence_recording_imported", tenant_id=user.tenant_id, inquiry_id=inquiry.id, call_id=call.id, seconds=seconds)
    return out(row, {user.id: user.name}, call), call


# ── list ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _call_state(call: Optional[Call]) -> str:
    if call is None:
        return "failed"
    t, s = (call.transcription_status or ""), (call.ai_score_status or "")
    if t in ("failed",):
        return "failed"
    if t in ("pending", "queued", "processing"):
        return "transcribing"
    if t == "done" and not call.ai_summary and s not in ("done", "failed") and not s.startswith("skipped"):
        return "analysing"
    return "done"


def out(row: LeadEvidenceImport, names: dict, call: Optional[Call] = None) -> dict:
    status = row.status
    if row.kind == "call_recording":
        status = _call_state(call)
    return {"id": row.id, "kind": row.kind, "status": status, "filename": row.filename, "created_at": _aware(row.created_at).isoformat()
            if row.created_at else datetime.now(timezone.utc).isoformat(),
            "uploaded_by": row.uploaded_by, "uploaded_by_name": names.get(row.uploaded_by) or ("Former teammate" if row.uploaded_by else None),
            "message_count": row.message_count, "duplicate_count": row.duplicate_count, "media_count": row.media_count,
            "duration_seconds": row.duration_seconds, "call_id": row.call_id, "conversation_id": row.conversation_id,
            "first_at": _aware(row.first_at).isoformat() if row.first_at else None,
            "last_at": _aware(row.last_at).isoformat() if row.last_at else None,
            "summary": (call.ai_summary if call is not None else None), "detail": row.detail or {}}


def list_imports(db: Session, user: User, inquiry_id: str, scope_user_id: Optional[str] = None) -> list[dict]:
    inquiry, _ = _lead(db, user, inquiry_id, scope_user_id)
    rows = (db.query(LeadEvidenceImport).filter_by(tenant_id=user.tenant_id, inquiry_id=inquiry.id)
            .order_by(LeadEvidenceImport.created_at.desc()).limit(50).all())
    ids = {r.uploaded_by for r in rows if r.uploaded_by}
    names = dict(db.query(User.id, User.name).filter(User.tenant_id == user.tenant_id, User.id.in_(list(ids))).all()) if ids else {}
    call_ids = [r.call_id for r in rows if r.call_id]
    calls = {c.id: c for c in db.query(Call).filter(Call.tenant_id == user.tenant_id, Call.id.in_(call_ids)).all()} if call_ids else {}
    return [out(r, names, calls.get(r.call_id)) for r in rows]
