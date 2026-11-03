"""Dynamic SOPs / Get found (migration 188, docs/sops/DYNAMIC_SOPS_PLAN.md).

GET    /sops                                     running checklists + the ones this business can start
POST   /sops                                     start one (sops.manage); its steps are written by Celery
GET    /sops/{id} · GET /sops/{id}/versions[/{no}]
PATCH  /sops/{id}                                assignee, pause/archive, hidden steps, own extra steps (sops.manage)
POST   /sops/{id}/regenerate                     new version from the latest data (sops.manage)
POST   /sops/{id}/steps/{key}/done|skip|undo     (sops.work, or sops.read on a checklist assigned to you)
POST   /sops/{id}/steps/{key}/evidence           multipart screenshot · POST .../evidence-link {url} · GET .../evidence
POST   /sops/{id}/check                          queue HAIP's automatic checks
No LLM or platform call runs in a request handler: generation and checks are Celery tasks (queued after commit).
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.sop import SopVersion
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.sops import EvidenceLinkIn, PatchIn, StartIn
from app.services.authz_service import require_capability
from app.services.ops_fleet_service import MAX_PAPER_FILE
from app.services.sops import service as svc

router = APIRouter(prefix="/sops", tags=["sops"])

_read = require_capability("sops.read", "sops.work", "sops.manage")
_manage = require_capability("sops.manage")


def _fail(exc: svc.SopError):
    raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def _inst(db: Session, user: User, instance_id: str, *, work: bool = False):
    try:
        inst = svc.get(db, user.tenant_id, instance_id)
    except svc.SopError as exc:
        _fail(exc)
    if work and not svc.can_work(db, user, inst):
        raise HTTPException(
            status_code=403,
            detail={"code": "not_allowed", "message": "Only the person it is assigned to, or a manager, can do this."},
        )
    return inst


def _queue_generate(tenant_id: str, instance_id: str, reason: str, actor_id: str) -> None:
    from app.workers.tasks.sops import generate_version

    generate_version.delay(tenant_id, instance_id, reason, actor_id)


@router.get("")
def list_sops(user: User = Depends(_read), db: Session = Depends(get_db)):
    return svc.list_view(db, db.get(Tenant, user.tenant_id))


@router.post("", status_code=201)
def start_sop(body: StartIn, user: User = Depends(_manage), db: Session = Depends(get_db)):
    try:
        inst = svc.start(db, db.get(Tenant, user.tenant_id), body, user.id)
    except svc.SopError as exc:
        _fail(exc)
    db.commit()
    _queue_generate(user.tenant_id, inst.id, "first", user.id)
    return {"id": inst.id}


def _photo_urls(db: Session, tenant_id: str, data: dict) -> dict:
    """Short-lived links for the photos a step lists (stored as asset ids only; links are made at read time)."""
    from app.models.media_asset import MediaAsset
    from app.services.media_storage import get_presigned_media_url

    ids = {p["asset_id"] for s in data["steps"] for p in s.get("photos") or []}
    keys = (
        {
            a.id: a.storage_key
            for a in db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant_id, MediaAsset.id.in_(ids))
        }
        if ids
        else {}
    )
    for s in data["steps"]:  # new dicts: the version's stored JSON is never touched
        if s.get("photos"):
            s["photos"] = [
                {
                    **p,
                    "url": get_presigned_media_url(keys[p["asset_id"]], expires_in=900)
                    if p["asset_id"] in keys
                    else None,
                }
                for p in s["photos"]
            ]
    return data


@router.get("/{instance_id}")
def get_sop(instance_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    inst = _inst(db, user, instance_id)
    data = svc.view(db, db.get(Tenant, user.tenant_id), inst)
    return {**_photo_urls(db, user.tenant_id, data), "can_work": svc.can_work(db, user, inst)}


@router.get("/{instance_id}/versions")
def list_versions(instance_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    inst = _inst(db, user, instance_id)
    rows = (
        db.query(SopVersion)
        .filter_by(tenant_id=user.tenant_id, instance_id=inst.id)
        .order_by(SopVersion.version_no.desc())
    )
    return [{"no": v.version_no, "reason": v.reason, "ai": bool(v.model), "created_at": v.created_at} for v in rows]


@router.get("/{instance_id}/versions/{no}")
def get_version(instance_id: str, no: int, user: User = Depends(_read), db: Session = Depends(get_db)):
    inst = _inst(db, user, instance_id)
    v = db.query(SopVersion).filter_by(tenant_id=user.tenant_id, instance_id=inst.id, version_no=no).first()
    if v is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No such version."})
    return {"no": v.version_no, "reason": v.reason, "steps": v.steps, "ai_note": v.ai_note, "created_at": v.created_at}


@router.patch("/{instance_id}")
def patch_sop(instance_id: str, body: PatchIn, user: User = Depends(_manage), db: Session = Depends(get_db)):
    inst = _inst(db, user, instance_id)
    try:
        svc.patch(db, inst, body, user.id)
    except svc.SopError as exc:
        _fail(exc)
    db.commit()
    return svc.view(db, db.get(Tenant, user.tenant_id), inst)


@router.post("/{instance_id}/regenerate", status_code=202)
def regenerate(instance_id: str, user: User = Depends(_manage), db: Session = Depends(get_db)):
    inst = _inst(db, user, instance_id)
    try:
        svc.queue_regenerate(db, inst, user.id)
    except svc.SopError as exc:
        _fail(exc)
    db.commit()
    _queue_generate(user.tenant_id, inst.id, "manual", user.id)
    return {"queued": True}


@router.post("/{instance_id}/steps/{key}/{action}")
def step_action(instance_id: str, key: str, action: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    if action not in ("done", "skip", "undo"):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown action."})
    inst = _inst(db, user, instance_id, work=True)
    try:
        svc.mark(db, inst, key, action, user.id)
    except svc.SopError as exc:
        _fail(exc)
    db.commit()
    return svc.view(db, db.get(Tenant, user.tenant_id), inst)


@router.post("/{instance_id}/steps/{key}/evidence")
async def upload_evidence(
    instance_id: str, key: str, file: UploadFile = File(...), user: User = Depends(_read), db: Session = Depends(get_db)
):
    inst = _inst(db, user, instance_id, work=True)
    raw = await file.read(MAX_PAPER_FILE + 1)
    try:
        svc.add_evidence_file(db, inst, key, raw, file.content_type or "", user.id)
    except svc.SopError as exc:
        _fail(exc)
    db.commit()
    return {"ok": True}


@router.post("/{instance_id}/steps/{key}/evidence-link")
def evidence_link(
    instance_id: str, key: str, body: EvidenceLinkIn, user: User = Depends(_read), db: Session = Depends(get_db)
):
    inst = _inst(db, user, instance_id, work=True)
    try:
        svc.add_evidence_link(db, inst, key, str(body.url), user.id)
    except svc.SopError as exc:
        _fail(exc)
    db.commit()
    return {"ok": True}


@router.get("/{instance_id}/steps/{key}/evidence")
def get_evidence(instance_id: str, key: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    from app.services.media_storage import get_presigned_media_url

    inst = _inst(db, user, instance_id)
    try:
        return {"url": get_presigned_media_url(svc.evidence_key(db, inst, key), expires_in=600)}
    except svc.SopError as exc:
        _fail(exc)


@router.post("/{instance_id}/check", status_code=202)
def check_now(instance_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    from app.workers.tasks.sops import check_instance

    inst = _inst(db, user, instance_id, work=True)
    check_instance.delay(user.tenant_id, inst.id, user.id)
    return {"queued": True}
