"""The AI Executive, phase E1: read-only findings for the founders (owner / manager).

GET  /chief/home                       open findings by role (older insights included), counts, the latest daily pulse
GET  /chief/findings?status=&role=     open | resolved | dismissed
POST /chief/findings/{id}/dismiss      {reason, note}: hidden and snoozed 7 days, reason kept, audited chief.finding_dismissed
POST /chief/run                        queue a full check now (Celery)                                                202
GET  /chief/settings                   brand_config.chief (+ defaults, roles, detectors)
PUT  /chief/settings                   owner only, audited ``chief.settings_changed``

Nothing here calls a language model or acts on anything. Another tenant's finding is a 404.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.chief import ROLE_LABELS, ChiefSettings, DismissIn
from app.services.chief import catalogue, findings
from app.services.chief import settings as settings_svc

router = APIRouter(prefix="/chief", tags=["chief"])
_readers = require_roles(UserRole.OWNER, UserRole.MANAGER)


def _tenant(db: Session, user: User) -> Tenant:
    t = db.query(Tenant).filter_by(id=user.tenant_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return t


@router.get("/home")
def home(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    return findings.home(db, _tenant(db, current_user))


@router.get("/findings")
def list_findings(
    status: str = Query("open", pattern="^(open|resolved|dismissed)$"),
    role: str | None = None,
    current_user: User = Depends(_readers),
    db: Session = Depends(get_db),
):
    if role is not None and role not in ROLE_LABELS:
        raise HTTPException(status_code=422, detail="Unknown role")
    return findings.list_findings(db, current_user.tenant_id, status=status, role=role)


@router.post("/findings/{finding_id}/dismiss")
def dismiss(finding_id: str, body: DismissIn, current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    row = findings.get(db, current_user.tenant_id, finding_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    if row.is_dismissed or row.is_auto_resolved:
        raise HTTPException(status_code=409, detail="This finding is already closed")
    out = findings.dismiss(db, current_user.tenant_id, row, current_user.id, body.reason, body.note)
    db.commit()
    return out


@router.post("/run", status_code=202)
def run_now(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    if not settings_svc.get(_tenant(db, current_user)).enabled:
        raise HTTPException(status_code=409, detail="Turn the AI Executive on first")
    from app.workers.tasks.chief_tasks import detect_tenant

    detect_tenant.delay(current_user.tenant_id, "daily")
    return {"queued": True}


@router.get("/settings")
def get_settings(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    return {
        "settings": settings_svc.get(_tenant(db, current_user)).model_dump(),
        "defaults": ChiefSettings().model_dump(),
        "roles": [{"key": k, "label": v} for k, v in ROLE_LABELS.items()],
        "detectors": [
            {"code": d.code, "role": d.role, "cadence": d.cadence, "next_step": d.next_step}
            for d in catalogue.CATALOGUE
        ],
    }


@router.put("/settings")
def put_settings(
    body: ChiefSettings, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)
):
    tenant = _tenant(db, current_user)
    changes = settings_svc.update(db, tenant, current_user.id, body)
    db.commit()
    db.refresh(tenant)
    if "enabled" in changes and body.enabled:
        from app.workers.tasks.chief_tasks import detect_tenant

        detect_tenant.delay(tenant.id, "daily")  # the first findings show up within a minute, not at the next tick
    return {"settings": settings_svc.get(tenant).model_dump(), "changed": sorted(changes)}
