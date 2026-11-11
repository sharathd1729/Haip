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
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.database import set_tenant_context
from app.models.call import Call
from app.models.mobile_device import MobileDevice
from app.models.user import User
from app.schemas.mobile_device import DeviceCallBatch, DeviceRegister, DeviceSettings

TOKEN_PREFIX = "haip_dev_"
PROVIDER = "mobile_app"
_TOUCH_EVERY = timedelta(minutes=1)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class RegisterRefused(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


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
    return now_m >= start or now_m < end   # overnight shift


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
    device.last_seen_at = datetime.now(timezone.utc)
    if body.settings is not None:
        apply_settings(db, device, body.settings)
    db.flush()
    append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id, action="mobile_device.registered",
                 target_type="mobile_device", target_id=device.id,
                 payload={"device_id": device.device_id, "model": device.model, "app_version": device.app_version,
                          "re_registered": again, "previous_user_id": previous_user if again else None})
    return device, raw


def revoke(db: Session, device: MobileDevice, actor: User) -> None:
    if device.revoked_at is not None:
        return
    device.revoked_at = datetime.now(timezone.utc)
    append_audit(db, tenant_id=device.tenant_id, actor_user_id=actor.id, action="mobile_device.revoked",
                 target_type="mobile_device", target_id=device.id,
                 payload={"device_id": device.device_id, "device_user_id": device.user_id})


def _lookup(db: Session, token_hash: str) -> Optional[tuple[str, str]]:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        row = db.execute(text("SELECT device_pk, tenant_id FROM mobile_device_lookup(:h)"), {"h": token_hash}).first()
        return (row[0], row[1]) if row else None
    row = db.query(MobileDevice.id, MobileDevice.tenant_id).filter(MobileDevice.token_hash == token_hash).first()
    return (row[0], row[1]) if row else None


def authenticate(db: Session, raw: str) -> Optional[MobileDevice]:
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
    if not db.query(User.id).filter_by(id=device.user_id, tenant_id=tenant_id, is_active=True, is_deleted=False).first():
        return None
    now = datetime.now(timezone.utc)
    last = device.last_seen_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is None or now - last >= _TOUCH_EVERY:     # avoid a write on every request
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
    seen = {r[0] for r in db.query(Call.ivr_call_id).filter(Call.tenant_id == tenant_id,
                                                              Call.ivr_call_id.in_(list(ids.values()))).all()}
    results, to_queue = [], []
    for c in batch.calls:
        ivr_call_id = ids[c.device_call_id]
        e164 = phone_identity.normalize(c.number, region)
        if ivr_call_id in seen:
            status = "duplicate"
        elif not e164:
            status = "invalid_number"          # withheld / private / malformed
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
                started = c.started_at.astimezone(timezone.utc)
                to_queue.append({
                    "ivr_call_id": ivr_call_id,
                    "direction": "inbound" if inbound else "outbound",
                    "from_number": e164 if inbound else "",
                    "to_number": "" if inbound else e164,
                    "duration_sec": c.duration_sec,
                    "answered": c.answered,
                    "started_at": started.isoformat(),
                    "ended_at": (started + timedelta(seconds=c.duration_sec)).isoformat(),
                    "agent_id": device.user_id,
                })
                status = "queued"
        seen.add(ivr_call_id)   # a repeat inside the same batch is a duplicate
        results.append({"device_call_id": c.device_call_id, "status": status})
    device.last_seen_at = datetime.now(timezone.utc)
    db.commit()   # signals attached above must be visible to the ingest tasks
    set_tenant_context(db, tenant_id)
    for payload in to_queue:
        ingest_call.delay(payload, tenant_id, PROVIDER)
    return results
