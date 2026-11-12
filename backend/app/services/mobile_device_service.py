"""HAIP Calls app (Android), step 1: device tokens, device settings and call-log upload (docs/MOBILE_CALL_TRACKING_SPEC.md).

Device token: random, returned once at registration, only its SHA-256 stored (the api_key_service pattern). On PostgreSQL the
table is under RLS and a device request has no tenant yet, so the lookup goes through the SECURITY DEFINER function
mobile_device_lookup (migration 202).

Uploaded calls are not written here. Each one becomes a call_ingest.process task with ivr_provider "mobile_app" (the same
ingest IVR calls use): guest resolved through identity_service, voice conversation, inquiry, missed-call / no-answer logic.
The idempotency key is ivr_call_id "mobile_app:<device row id>:<device_call_id>", unique across all calls.

Privacy (spec "Privacy rule in the API"):
  - numbers the staff member marked personal never reach the server: the app drops those calls, and the settings schema
    refuses any personal_numbers key (even hashed, phone numbers are few enough to be reversed);
  - a number that matches no guest is stored only while "Unknown numbers are enquiries" is on for the call's start time:
    setting unknown_numbers = working_hours (default: on inside the staff member's working hours, off outside; on all day
    when no hours are set) | always | never.

Recordings (step 2): POST /device-calls/{device_call_id}/recording stores the phone's own recording of one of ITS calls in
the IVR recordings' bucket and prefix (media_storage.upload_call_recording, key "{tenant_id}/calls/mobile_app/...") and
sets the same calls.recording_s3_key, so playback, transcription -> AI (call_ingest.queue_transcription) and DPDP erasure
are the IVR ones. upload_calls writes a mobile_call_pending row per queued call; a recording that arrives before ingest
has made the call waits on that row and call_ingest attaches it (link_pending). One recording per call: guarded UPDATEs.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.database import set_tenant_context
from app.models.call import Call, RecordingStatus
from app.models.mobile_device import MobileCallPending, MobileDevice
from app.models.user import User
from app.schemas.mobile_device import DeviceCallBatch, DeviceRegister, DeviceSettings

TOKEN_PREFIX = "haip_dev_"
PROVIDER = "mobile_app"
_TOUCH_EVERY = timedelta(minutes=1)
MAX_RECORDING_BYTES = 50 * 1024 * 1024
PENDING_MAX_AGE = timedelta(days=2)  # a call whose ingest never finished by then is not coming


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class RegisterRefused(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class RecordingRefused(RegisterRefused):
    pass


def ivr_call_id_for(device: MobileDevice, device_call_id: str) -> str:
    return f"{PROVIDER}:{device.id}:{device_call_id}"


# ─── Settings ────────────────────────────────────────────────────────────────


def apply_settings(db: Session, device: MobileDevice, new: DeviceSettings) -> None:
    device.settings = {
        "unknown_numbers": new.unknown_numbers,
        "working_hours": new.working_hours.model_dump() if new.working_hours else None,
    }


def settings_out(device: MobileDevice) -> dict:
    s = device.settings or {}
    return {"unknown_numbers": s.get("unknown_numbers", "working_hours"), "working_hours": s.get("working_hours")}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def unknown_numbers_on(device: MobileDevice, started_at: datetime, tz) -> bool:
    s = device.settings or {}
    mode = s.get("unknown_numbers", "working_hours")
    if mode in ("always", "never"):
        return mode == "always"
    hours = s.get("working_hours")
    if not hours:
        return True
    local = started_at.astimezone(tz)
    now_m, start, end = local.hour * 60 + local.minute, _minutes(hours["start"]), _minutes(hours["end"])
    if start <= end:
        return start <= now_m < end
    return now_m >= start or now_m < end  # overnight shift


# ─── Register / authenticate / revoke ────────────────────────────────────────


def register(db: Session, user: User, body: DeviceRegister) -> tuple[MobileDevice, str]:
    """Create the device, or re-register it (same app install id in this workspace): a new token replaces the old one.
    Only an owner/manager may move a phone to another person or bring a revoked phone back (RegisterRefused otherwise),
    so knowing another phone's install id is not enough to take it over or undo a revoke. Audited. Returns the row and
    the raw token (only here)."""
    from app.models.user import UserRole

    device = db.query(MobileDevice).filter_by(tenant_id=user.tenant_id, device_id=body.device_id).first()
    again = device is not None
    if again and user.role not in (UserRole.OWNER, UserRole.MANAGER):
        if device.revoked_at is not None:
            raise RegisterRefused(403, "This phone was removed from HAIP. Ask your manager to add it back.")
        if device.user_id != user.id:
            raise RegisterRefused(409, "This phone is registered to another staff member. Ask your manager to move it.")
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    if device is None:
        device = MobileDevice(tenant_id=user.tenant_id, device_id=body.device_id, settings={})
        db.add(device)
    previous_user = device.user_id
    device.user_id = user.id
    device.token_hash = hash_token(raw)
    device.revoked_at = None
    device.model, device.android_version, device.app_version = body.model, body.android_version, body.app_version
    device.last_seen_at = datetime.now(UTC)
    if body.settings is not None:
        apply_settings(db, device, body.settings)
    db.flush()
    append_audit(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="mobile_device.registered",
        target_type="mobile_device",
        target_id=device.id,
        payload={
            "device_id": device.device_id,
            "model": device.model,
            "app_version": device.app_version,
            "re_registered": again,
            "previous_user_id": previous_user if again else None,
        },
    )
    return device, raw


def revoke(db: Session, device: MobileDevice, actor: User) -> None:
    if device.revoked_at is not None:
        return
    device.revoked_at = datetime.now(UTC)
    append_audit(
        db,
        tenant_id=device.tenant_id,
        actor_user_id=actor.id,
        action="mobile_device.revoked",
        target_type="mobile_device",
        target_id=device.id,
        payload={"device_id": device.device_id, "device_user_id": device.user_id},
    )


def _lookup(db: Session, token_hash: str) -> tuple[str, str] | None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        row = db.execute(text("SELECT device_pk, tenant_id FROM mobile_device_lookup(:h)"), {"h": token_hash}).first()
        return (row[0], row[1]) if row else None
    row = db.query(MobileDevice.id, MobileDevice.tenant_id).filter(MobileDevice.token_hash == token_hash).first()
    return (row[0], row[1]) if row else None


def authenticate(db: Session, raw: str) -> MobileDevice | None:
    """The live device for this token, with the tenant context set; None when unknown, revoked, or its user is no longer an
    active member of the workspace."""
    if not raw or not raw.startswith(TOKEN_PREFIX) or len(raw) > 120:
        return None
    found = _lookup(db, hash_token(raw))
    if not found:
        return None
    device_pk, tenant_id = found
    set_tenant_context(db, tenant_id)
    device = db.query(MobileDevice).filter_by(id=device_pk, tenant_id=tenant_id).first()
    if device is None or device.revoked_at is not None:
        return None
    if (
        not db.query(User.id)
        .filter_by(id=device.user_id, tenant_id=tenant_id, is_active=True, is_deleted=False)
        .first()
    ):
        return None
    now = datetime.now(UTC)
    last = device.last_seen_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if last is None or now - last >= _TOUCH_EVERY:  # avoid a write on every request
        device.last_seen_at = now
        db.commit()
        set_tenant_context(db, tenant_id)
    return device


# ─── Call upload ─────────────────────────────────────────────────────────────


def upload_calls(db: Session, device: MobileDevice, batch: DeviceCallBatch) -> list[dict]:
    """Queue each new call into call_ingest. Per call status: queued | duplicate | skipped_unknown_number |
    invalid_number. Never writes a Call row itself."""
    from app.services import identity_service, phone_identity
    from app.services.roster_service import tenant_tz
    from app.workers.tasks.call_ingest import ingest_call

    tenant_id = device.tenant_id
    region = phone_identity.region_for_tenant(db, tenant_id)
    tz = tenant_tz(db, tenant_id)
    ids = {c.device_call_id: ivr_call_id_for(device, c.device_call_id) for c in batch.calls}
    seen = {
        r[0]
        for r in db.query(Call.ivr_call_id)
        .filter(Call.tenant_id == tenant_id, Call.ivr_call_id.in_(list(ids.values())))
        .all()
    }
    results, to_queue = [], []
    for c in batch.calls:
        ivr_call_id = ids[c.device_call_id]
        e164 = phone_identity.normalize(c.number, region)
        if ivr_call_id in seen:
            status = "duplicate"
        elif not e164:
            status = "invalid_number"  # withheld / private / malformed
        else:
            guest_id = identity_service.find_person_by_phone(db, tenant_id, e164)
            if guest_id is None and not unknown_numbers_on(device, c.started_at, tz):
                status = "skipped_unknown_number"
            else:
                if guest_id is not None:
                    # Known only by the number on their guest row: attach the phone signal so call_ingest's resolve_gid
                    # lands on this same person instead of creating a second guest.
                    identity_service.resolve_person_by_phone(db, tenant_id, e164, source=PROVIDER)
                inbound = c.direction == "in"
                started = c.started_at.astimezone(UTC)
                to_queue.append(
                    {
                        "ivr_call_id": ivr_call_id,
                        "direction": "inbound" if inbound else "outbound",
                        "from_number": e164 if inbound else "",
                        "to_number": "" if inbound else e164,
                        "duration_sec": c.duration_sec,
                        "answered": c.answered,
                        "started_at": started.isoformat(),
                        "ended_at": (started + timedelta(seconds=c.duration_sec)).isoformat(),
                        "agent_id": device.user_id,
                    }
                )
                status = "queued"
        seen.add(ivr_call_id)  # a repeat inside the same batch is a duplicate
        results.append({"device_call_id": c.device_call_id, "status": status})
    # A waiting row per queued call, so its recording can arrive before ingest makes the call (attach_recording).
    new_ids = [p["ivr_call_id"] for p in to_queue]
    waiting = (
        {
            r[0]
            for r in db.query(MobileCallPending.ivr_call_id)
            .filter(MobileCallPending.tenant_id == tenant_id, MobileCallPending.ivr_call_id.in_(new_ids))
            .all()
        }
        if new_ids
        else set()
    )
    for ivr_call_id in new_ids:
        if ivr_call_id not in waiting:
            db.add(MobileCallPending(tenant_id=tenant_id, device_pk=device.id, ivr_call_id=ivr_call_id))
    device.last_seen_at = datetime.now(UTC)
    db.commit()  # signals attached above must be visible to the ingest tasks
    set_tenant_context(db, tenant_id)
    for payload in to_queue:
        ingest_call.delay(payload, tenant_id, PROVIDER)
    return results


# ─── Recordings (step 2) ─────────────────────────────────────────────────────


def sniff_audio(data: bytes) -> str | None:
    """Content type from the file's magic bytes (never the file name or the request's Content-Type); None = not one of
    m4a, mp3, amr, aac, wav, ogg."""
    b = data[:16]
    if b[4:8] == b"ftyp":
        return "audio/mp4"  # m4a / 3gp container
    if b.startswith(b"#!AMR"):
        return "audio/amr"  # AMR-NB and AMR-WB
    if b.startswith(b"OggS"):
        return "audio/ogg"
    if b[:4] == b"RIFF" and b[8:12] == b"WAVE":
        return "audio/wav"
    if b.startswith(b"ID3"):
        return "audio/mpeg"
    if b.startswith(b"ADIF") or (len(b) > 1 and b[0] == 0xFF and (b[1] & 0xF6) == 0xF0):
        return "audio/aac"  # ADIF, or the ADTS sync word (layer bits 00)
    if len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0 and (b[1] & 0x06):
        return "audio/mpeg"  # MPEG audio frame sync, layer I-III
    return None


def recording_key(device: MobileDevice, device_call_id: str) -> str:
    # One key per call: a repeat upload overwrites the same object instead of leaving a second one behind.
    digest = hashlib.sha256(device_call_id.encode()).hexdigest()[:32]
    return f"{device.tenant_id}/calls/{PROVIDER}/{device.id}/{digest}/recording"


def link_pending(db: Session, call: Call) -> bool:
    """Ingest made (or found) this Calls-app call: attach a recording that came first and drop the waiting row. The call
    takes a recording only while it has none (guarded UPDATE), so a race between ingest and the upload still gives one
    recording and one transcription. True when this call attached it (transcription queued)."""
    from app.workers.tasks.call_ingest import queue_transcription

    row = db.query(MobileCallPending).filter_by(tenant_id=call.tenant_id, ivr_call_id=call.ivr_call_id).first()
    if row is None:
        return False
    key = row.recording_key
    db.query(MobileCallPending).filter_by(id=row.id).delete(synchronize_session=False)
    won = (
        bool(key)
        and db.query(Call)
        .filter(Call.id == call.id, Call.tenant_id == call.tenant_id, Call.recording_s3_key.is_(None))
        .update(
            {
                Call.recording_s3_key: key,
                Call.recording_fetched: True,
                Call.recording_status: RecordingStatus.AVAILABLE,
                Call.recording_error: None,
            },
            synchronize_session=False,
        )
        == 1
    )
    db.commit()
    set_tenant_context(db, call.tenant_id)
    db.refresh(call)
    if won:
        queue_transcription(db, call)
    return won


def attach_recording(db: Session, device: MobileDevice, device_call_id: str, data: bytes, *, upload=None) -> dict:
    """Store the phone's recording of one of its own calls. {"status": attached | waiting | duplicate, "call_id"}.
    RecordingRefused: 422 empty, 413 over 50 MB, 415 not an accepted audio type, 404 not a call this phone uploaded
    (another phone's or workspace's call id is simply unknown here)."""
    from sqlalchemy.exc import IntegrityError

    if not data:
        raise RecordingRefused(422, "The recording is empty.")
    if len(data) > MAX_RECORDING_BYTES:
        raise RecordingRefused(413, "A recording may be up to 50 MB.")
    kind = sniff_audio(data)
    if kind is None:
        raise RecordingRefused(415, "Upload an m4a, mp3, amr, aac, wav or ogg recording.")
    tid = device.tenant_id
    ivr_call_id = ivr_call_id_for(device, device_call_id)
    call = db.query(Call).filter_by(tenant_id=tid, ivr_call_id=ivr_call_id).first()
    row = db.query(MobileCallPending).filter_by(tenant_id=tid, ivr_call_id=ivr_call_id).first()
    if call is None and row is None:
        raise RecordingRefused(404, "This phone has not uploaded that call.")
    duplicate = {"status": "duplicate", "call_id": call.id if call else None}
    if (call is not None and call.recording_s3_key) or (row is not None and row.recording_key):
        return duplicate

    key = recording_key(device, device_call_id)
    if upload is None:
        from app.services.media_storage import upload_call_recording as upload
    upload(key, data, kind)
    fields = {"recording_key": key, "recording_type": kind, "recording_bytes": len(data)}
    claimed = (
        row is not None
        and db.query(MobileCallPending)
        .filter(MobileCallPending.id == row.id, MobileCallPending.recording_key.is_(None))
        .update(fields, synchronize_session=False)
        == 1
    )
    if not claimed:
        if row is not None and db.query(MobileCallPending.id).filter_by(id=row.id).first():
            db.rollback()
            set_tenant_context(db, tid)
            return duplicate  # the same file sent twice at once
        # The call exists and its waiting row is gone (ingest finished): wait on a fresh row, linked just below.
        db.add(MobileCallPending(tenant_id=tid, device_pk=device.id, ivr_call_id=ivr_call_id, **fields))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        set_tenant_context(db, tid)
        return duplicate
    set_tenant_context(db, tid)

    call = call or db.query(Call).filter_by(tenant_id=tid, ivr_call_id=ivr_call_id).first()  # ingest may have run
    status = "waiting"
    if call is not None:
        link_pending(db, call)  # whoever links (this request or ingest), the call now holds the recording
        status = "attached" if call.recording_s3_key == key else "duplicate"
    if status != "duplicate":
        append_audit(
            db,
            tenant_id=tid,
            actor_user_id=device.user_id,
            action="call.recording_uploaded",
            target_type="call" if call else "mobile_device",
            target_id=call.id if call else device.id,
            payload={
                "device_pk": device.id,
                "device_call_id": device_call_id,
                "status": status,
                "content_type": kind,
                "bytes": len(data),
            },
        )
        db.commit()
        set_tenant_context(db, tid)
    return {"status": status, "call_id": call.id if call else None}


def purge_stale_pending(db: Session, tenant_id: str, now: datetime | None = None) -> list[str]:
    """Waiting rows older than PENDING_MAX_AGE (the call never arrived: its ingest failed for good). Deletes them; returns
    their files for the caller to delete after commit (media_storage.delete_tenant_objects)."""
    cutoff = (now or datetime.now(UTC)) - PENDING_MAX_AGE
    q = db.query(MobileCallPending).filter(
        MobileCallPending.tenant_id == tenant_id, MobileCallPending.created_at < cutoff
    )
    keys = [k for (k,) in q.with_entities(MobileCallPending.recording_key).all() if k]
    q.delete(synchronize_session=False)
    return keys
