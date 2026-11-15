"""Yaad folders (services/personal_folders.py): folders the person makes, with keywords and a sorting rule.

  GET    /me/folders                        folders with call counts + the Unclassified count
  POST   /me/folders                        {name, color?, keywords?, prompt?}: made, then recent calls are sorted into it
  PATCH  /me/folders/{id}                   only the fields sent; new keywords / rule = recent calls sorted again
  DELETE /me/folders/{id}                   the folder goes; its calls stay (they may become Unclassified)
  POST   /me/folders/{id}/calls             {call_id}: put a call in by hand (also brings back one taken out)
  DELETE /me/folders/{id}/calls/{call_id}   take a call out; automatic sorting never puts it back

Calls in a folder / Unclassified: GET /me/calls?folder=<id>|unclassified. Ask in a folder: POST /me/ask {folder_id}.
Personal workspaces only (403 elsewhere). Audited by id and field names only (folder names and rules are the person's words).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.endpoints.personal_calls import personal_user
from app.core.audit import append_audit
from app.core.database import get_db
from app.models.call import Call
from app.models.user import User
from app.models.yaad_folder import YaadFolderCall
from app.services import personal_folders as pf

router = APIRouter(prefix="/me/folders", tags=["personal"])


class FolderIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: str | None = Field(None, max_length=80)
    color: str | None = Field(None, max_length=20)
    keywords: list[str] | None = Field(None, max_length=40)
    prompt: str | None = Field(None, max_length=1000)


class CallIn(BaseModel):
    call_id: str = Field(min_length=1, max_length=64)


def _folder(db: Session, user: User, folder_id: str):
    folder = pf.get(db, user.tenant_id, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


def _resort(tenant_id: str, folder_id: str) -> None:
    from app.workers.tasks.personal_folders import sort_folder

    try:
        sort_folder.delay(tenant_id, folder_id)
    except Exception:  # noqa: BLE001 -- broker down: new calls are still filed as they arrive
        pass


def _audit(db: Session, user: User, action: str, folder_id: str, **payload) -> None:
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action=action,
        actor_user_id=user.id,
        target_type="yaad_folder",
        target_id=folder_id,
        payload=payload,
    )


@router.get("")
def list_folders(user: User = Depends(personal_user), db: Session = Depends(get_db)):
    return pf.listing(db, user.tenant_id)


@router.post("", status_code=201)
def create_folder(body: FolderIn, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    try:
        folder = pf.create(db, user.tenant_id, user.id, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    _audit(db, user, "yaad_folder.created", folder.id)
    db.commit()
    _resort(user.tenant_id, folder.id)
    return pf.view(folder, 0)


@router.patch("/{folder_id}")
def update_folder(folder_id: str, body: FolderIn, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    folder = _folder(db, user, folder_id)
    try:
        changes = pf.clean(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    changed = [k for k, v in changes.items() if getattr(folder, k) != v]
    for k in changed:
        setattr(folder, k, changes[k])
    if changed:
        _audit(db, user, "yaad_folder.updated", folder.id, fields=changed)
        db.commit()
        if {"keywords", "prompt"} & set(changed):
            _resort(user.tenant_id, folder.id)
    return pf.view(folder)


@router.delete("/{folder_id}")
def delete_folder(folder_id: str, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    folder = _folder(db, user, folder_id)
    db.query(YaadFolderCall).filter_by(tenant_id=user.tenant_id, folder_id=folder.id).delete()
    db.delete(folder)
    _audit(db, user, "yaad_folder.deleted", folder_id)
    db.commit()
    return {"deleted": True}


@router.post("/{folder_id}/calls")
def add_call(folder_id: str, body: CallIn, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    folder = _folder(db, user, folder_id)
    if db.query(Call.id).filter_by(id=body.call_id, tenant_id=user.tenant_id).first() is None:
        raise HTTPException(status_code=404, detail="Call not found")
    pf.put(db, user.tenant_id, folder.id, body.call_id)
    db.commit()
    return {"folders": pf.folders_of(db, user.tenant_id, body.call_id)}


@router.delete("/{folder_id}/calls/{call_id}")
def remove_call(folder_id: str, call_id: str, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    folder = _folder(db, user, folder_id)
    if db.query(Call.id).filter_by(id=call_id, tenant_id=user.tenant_id).first() is None:
        raise HTTPException(status_code=404, detail="Call not found")
    pf.take_out(db, user.tenant_id, folder.id, call_id)
    db.commit()
    return {"folders": pf.folders_of(db, user.tenant_id, call_id)}
