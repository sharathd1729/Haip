"""Delete my account (DELETE /me/account): a Yaad user erases their personal workspace. Not undoable.

Every contact goes through the DPDP erasure (dpdp_erasure_service.erase_guest: their calls, transcripts, scores, recordings,
identities, consents...), then whatever is left without a contact (calls from hidden numbers, Calls-app recordings still
waiting for their call). Phones are unlinked, every user of the workspace is anonymised and switched off (no sign-in),
the workspace is switched off with its settings cleared. One transaction, audited (`account.deleted`, counts only);
stored files are deleted only after it commits, so a failed delete never loses a recording.
Personal workspaces only; the endpoint lets only an owner call it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog

from app.services import personal_calls as pc

log = structlog.get_logger()

CONFIRM = "DELETE"


def delete_account(db, tenant, actor) -> dict:
    from app.core.audit import append_audit
    from app.models.call import Call
    from app.models.guest import Guest
    from app.models.mobile_device import MobileCallPending, MobileDevice
    from app.models.score import CallScore
    from app.models.transcript import Transcript
    from app.models.user import User
    from app.services.dpdp_erasure_service import erase_guest
    from app.services.media_storage import delete_tenant_objects

    if not pc.is_personal_tenant(tenant):
        raise ValueError("Only a personal workspace can be deleted this way.")
    tid, now = tenant.id, datetime.now(UTC)
    rows: dict[str, int] = {}
    files: list[str] = []

    def add(name: str, n: int) -> None:
        if n:
            rows[name] = rows.get(name, 0) + n

    for (gid,) in db.query(Guest.id).filter(Guest.tenant_id == tid).all():
        g = db.get(Guest, gid)
        if g is None or g.is_deleted:  # already erased as a duplicate merged into another contact
            continue
        result = erase_guest(db, tid, gid)
        files += result["files"]
        for k, v in result["rows"].items():
            add(k, v)

    left = [cid for (cid,) in db.query(Call.id).filter(Call.tenant_id == tid).all()]
    if left:
        files += [
            k for (k,) in db.query(Call.recording_s3_key).filter(Call.id.in_(left), Call.recording_s3_key.isnot(None))
        ]
        db.query(Call).filter(Call.tenant_id == tid).update(
            {Call.recovered_by_call_id: None}, synchronize_session=False
        )
        add("transcripts", db.query(Transcript).filter(Transcript.call_id.in_(left)).delete(synchronize_session=False))
        add("call_scores", db.query(CallScore).filter(CallScore.call_id.in_(left)).delete(synchronize_session=False))
        add("calls", db.query(Call).filter(Call.tenant_id == tid).delete(synchronize_session=False))
    files += [
        k
        for (k,) in db.query(MobileCallPending.recording_key).filter(
            MobileCallPending.tenant_id == tid, MobileCallPending.recording_key.isnot(None)
        )
    ]
    add(
        "mobile_call_pending",
        db.query(MobileCallPending).filter(MobileCallPending.tenant_id == tid).delete(synchronize_session=False),
    )
    add(
        "devices_unlinked",
        db.query(MobileDevice)
        .filter(MobileDevice.tenant_id == tid, MobileDevice.revoked_at.is_(None))
        .update({MobileDevice.revoked_at: now}, synchronize_session=False),
    )

    users = db.query(User).filter(User.tenant_id == tid).all()
    for u in users:
        u.email = f"deleted-{uuid.uuid4().hex[:12]}@deleted.invalid"
        u.name = "Deleted user"
        u.phone = None
        u.hashed_password = None
        u.mfa_secret = None
        u.is_mfa_enabled = False
        u.google_id = u.microsoft_id = None
        u.notification_prefs = {}
        u.is_active = False
        u.is_deleted = True
    add("users_anonymised", len(users))
    tenant.is_active = False
    tenant.brand_config = {pc.MODE_KEY: pc.PERSONAL, "account_deleted_at": now.isoformat()}
    append_audit(
        db,
        tenant_id=tid,
        actor_user_id=actor.id,
        action="account.deleted",
        target_type="tenant",
        target_id=tid,
        payload={"rows": rows, "files": len(files)},
    )
    db.commit()
    sent = delete_tenant_objects(tid, files) if files else 0
    log.info("personal_account_deleted", tenant_id=tid, rows=sum(rows.values()), files=sent)
    return {"rows": rows, "files": sent}
