"""Ops fleet API (migration 180): papers, defects, services, onboard inventory. Capabilities from 178.

GET    /ops/fleet                                   one card per vehicle (ops_fleet_view.fleet)
GET    /ops/fleet/papers?staff_id=                  a person's papers
POST   /ops/fleet/papers · DELETE /ops/fleet/papers/{id}
POST   /ops/fleet/papers/{id}/file (multipart: file) · GET /ops/fleet/papers/{id}/file (a short-lived link)
POST   /ops/fleet/defects · POST /ops/fleet/defects/{id}/close
POST   /ops/fleet/services · POST /ops/fleet/services/{id}/done · DELETE /ops/fleet/services/{id}
POST   /ops/fleet/inventory · PATCH /ops/fleet/inventory/{id} · DELETE /ops/fleet/inventory/{id}

ops.write: add papers/defects/services/stock, counts, service done. ops.manage: closing a defect (it puts the vehicle back on
sale, audited), removing papers, services and stock lines.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.ops_fleet import OpsPaper
from app.models.user import User
from app.schemas.ops_fleet import (
    DefectCloseIn,
    DefectIn,
    InventoryCountIn,
    InventoryIn,
    PaperIn,
    ServiceDoneIn,
    ServiceIn,
)
from app.services import booking_agenda_service, ops_fleet_view
from app.services import ops_fleet_service as fleet
from app.services.authz_service import require_capability

router = APIRouter(prefix="/ops/fleet", tags=["operations"])

_read = require_capability("ops.read", "ops.manage")
_write = require_capability("ops.write", "ops.manage")
_manage = require_capability("ops.manage")


def _today(db: Session, user: User):
    return booking_agenda_service.tenant_today(db, user.tenant_id)


def _cards(db: Session, user: User) -> list[dict]:
    db.commit()
    return ops_fleet_view.fleet(db, user.tenant_id, _today(db, user))


@router.get("")
def get_fleet(user: User = Depends(_read), db: Session = Depends(get_db)):
    return ops_fleet_view.fleet(db, user.tenant_id, _today(db, user))


@router.get("/papers")
def staff_papers(staff_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    today = _today(db, user)
    return [
        {
            "id": p.id,
            "kind": p.kind,
            "name": p.name,
            "number": p.number,
            "expires_on": p.expires_on.isoformat() if p.expires_on else None,
            "level": fleet.paper_level(p.expires_on, today),
            "words": fleet.paper_words(p, today),
            "has_file": bool(p.file_key),
        }
        for p in db.query(OpsPaper).filter_by(tenant_id=user.tenant_id, staff_id=staff_id, active=True)
    ]


@router.post("/papers", status_code=201)
def add_paper(body: PaperIn, user: User = Depends(_write), db: Session = Depends(get_db)):
    p = fleet.add_paper(db, user.tenant_id, body, user.id)
    db.commit()
    return {"id": p.id}


@router.delete("/papers/{paper_id}", status_code=204)
def remove_paper(paper_id: str, user: User = Depends(_manage), db: Session = Depends(get_db)):
    fleet.remove_paper(db, user.tenant_id, paper_id)
    db.commit()


@router.post("/papers/{paper_id}/file")
async def upload_paper_file(
    paper_id: str,
    file: UploadFile = File(...),
    user: User = Depends(_write),
    db: Session = Depends(get_db),
):
    raw = await file.read(fleet.MAX_PAPER_FILE + 1)
    fleet.attach_file(db, user.tenant_id, paper_id, raw, file.content_type or "")
    db.commit()
    return {"ok": True}


@router.get("/papers/{paper_id}/file")
def paper_file(paper_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    from app.services.media_storage import get_presigned_media_url

    p = db.query(OpsPaper).filter_by(id=paper_id, tenant_id=user.tenant_id).first()
    if p is None or not p.file_key:
        raise HTTPException(status_code=404, detail="No file for this paper")
    return {"url": get_presigned_media_url(p.file_key, expires_in=600)}


@router.post("/defects", status_code=201)
def add_defect(body: DefectIn, user: User = Depends(_write), db: Session = Depends(get_db)):
    fleet.add_defect(db, user.tenant_id, body, actor_id=user.id, today=_today(db, user))
    return _cards(db, user)


@router.post("/defects/{defect_id}/close")
def close_defect(defect_id: str, body: DefectCloseIn, user: User = Depends(_manage), db: Session = Depends(get_db)):
    fleet.close_defect(db, user.tenant_id, defect_id, body.note, user.id)
    return _cards(db, user)


@router.post("/services", status_code=201)
def add_service(body: ServiceIn, user: User = Depends(_write), db: Session = Depends(get_db)):
    fleet.add_service(db, user.tenant_id, body, user.id)
    return _cards(db, user)


@router.post("/services/{service_id}/done")
def service_done(service_id: str, body: ServiceDoneIn, user: User = Depends(_write), db: Session = Depends(get_db)):
    fleet.service_done(db, user.tenant_id, service_id, body, user.id, _today(db, user))
    return _cards(db, user)


@router.delete("/services/{service_id}")
def remove_service(service_id: str, user: User = Depends(_manage), db: Session = Depends(get_db)):
    fleet.remove_service(db, user.tenant_id, service_id)
    return _cards(db, user)


@router.post("/inventory", status_code=201)
def add_item(body: InventoryIn, user: User = Depends(_write), db: Session = Depends(get_db)):
    fleet.add_item(db, user.tenant_id, body, user.id)
    return _cards(db, user)


@router.patch("/inventory/{item_id}")
def set_count(item_id: str, body: InventoryCountIn, user: User = Depends(_write), db: Session = Depends(get_db)):
    fleet.set_count(db, user.tenant_id, item_id, body, user.id)
    return _cards(db, user)


@router.delete("/inventory/{item_id}")
def remove_item(item_id: str, user: User = Depends(_manage), db: Session = Depends(get_db)):
    fleet.remove_item(db, user.tenant_id, item_id)
    return _cards(db, user)
