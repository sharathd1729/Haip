"""WhatsApp contacts page: lists, bulk actions, drip enrolment, export and 30-day growth (services/wa_contacts.py).

Owner, manager and marketing only, like the rest of the contacts and campaign tools. Every bulk action is audited
with its count (never phone numbers).
"""
import csv
import io
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.audit import append_audit
from app.api.v1.endpoints.messaging_campaign_reports import _safe   # spreadsheet-formula guard
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import wa_contacts as svc

router = APIRouter(prefix="/messaging", tags=["messaging"])
log = structlog.get_logger()

_MARKETERS = require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING)


class ContactFilter(BaseModel):
    opted_in: Optional[bool] = None
    search: Optional[str] = Field(default=None, max_length=100)
    list_id: Optional[str] = Field(default=None, max_length=64)
    tag: Optional[str] = Field(default=None, max_length=40)


class Targets(BaseModel):
    """Either the picked contact ids, or `filter` for "everyone matching"."""
    ids: Optional[list[str]] = None
    filter: Optional[ContactFilter] = None


class BulkIn(Targets):
    action: Literal["add_tag", "remove_tag", "add_to_list", "remove_from_list", "opt_out"]
    value: Optional[str] = Field(default=None, max_length=80)


class EnrolIn(Targets):
    flow_id: str = Field(max_length=64)


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _targets(db: Session, tenant_id: str, body: Targets) -> list:
    try:
        return svc.targets(db, tenant_id, body.ids, body.filter.model_dump() if body.filter else None)
    except svc.ContactsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _audit(db, user: User, action: str, payload: dict, target_id: Optional[str] = None, target_type="wa_subscribers"):
    append_audit(db, tenant_id=user.tenant_id, action=action, actor_user_id=user.id, target_type=target_type,
                 target_id=target_id, payload=payload)


# ─── Lists ───────────────────────────────────────────────────────────────────

@router.get("/contact-lists")
def list_contact_lists(current_user: User = Depends(_MARKETERS), db: Session = Depends(get_db)):
    return svc.lists_with_counts(db, current_user.tenant_id)


@router.post("/contact-lists", status_code=201)
def create_contact_list(body: ListIn, current_user: User = Depends(_MARKETERS), db: Session = Depends(get_db)):
    try:
        row = svc.create_list(db, current_user.tenant_id, body.name, current_user.id)
    except svc.ContactsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    _audit(db, current_user, "contact_lists.create", {"name": row.name}, row.id, "wa_contact_list")
    db.commit()
    return {"id": row.id, "name": row.name, "count": 0, "created_at": row.created_at}


@router.patch("/contact-lists/{list_id}")
def rename_contact_list(list_id: str, body: ListIn, current_user: User = Depends(_MARKETERS),
                        db: Session = Depends(get_db)):
    row = svc.get_list(db, current_user.tenant_id, list_id)
    if not row:
        raise HTTPException(status_code=404, detail="List not found")
    before = row.name
    try:
        svc.rename_list(db, current_user.tenant_id, row, body.name)
    except svc.ContactsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    _audit(db, current_user, "contact_lists.rename", {"before": before, "after": row.name}, row.id, "wa_contact_list")
    db.commit()
    return {"id": row.id, "name": row.name}


@router.delete("/contact-lists/{list_id}")
def delete_contact_list(list_id: str, current_user: User = Depends(_MARKETERS), db: Session = Depends(get_db)):
    row = svc.get_list(db, current_user.tenant_id, list_id)
    if not row:
        raise HTTPException(status_code=404, detail="List not found")
    name = row.name
    members = svc.delete_list(db, current_user.tenant_id, row)
    _audit(db, current_user, "contact_lists.delete", {"name": name, "members": members}, list_id, "wa_contact_list")
    db.commit()
    return {"deleted": True, "members": members}


# ─── Count, growth ───────────────────────────────────────────────────────────

@router.get("/subscribers/count")
def count_subscribers(
    opted_in: Optional[bool] = None,
    search: Optional[str] = Query(default=None, max_length=100),
    list_id: Optional[str] = Query(default=None, max_length=64),
    tag: Optional[str] = Query(default=None, max_length=40),
    current_user: User = Depends(_MARKETERS),
    db: Session = Depends(get_db),
):
    """How many contacts match the page's filters (for "Select all N matching")."""
    q = svc.matching(db, current_user.tenant_id, opted_in=opted_in, search=search, list_id=list_id, tag=tag)
    return {"count": q.count()}


@router.get("/subscribers/growth")
def subscriber_growth(current_user: User = Depends(_MARKETERS), db: Session = Depends(get_db)):
    return svc.growth(db, current_user.tenant_id)


# ─── Bulk actions ────────────────────────────────────────────────────────────

@router.post("/subscribers/bulk")
def bulk_action(body: BulkIn, current_user: User = Depends(_MARKETERS), db: Session = Depends(get_db)):
    subs = _targets(db, current_user.tenant_id, body)
    try:
        changed = svc.apply(db, current_user.tenant_id, subs, body.action, body.value)
    except svc.ContactsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    _audit(db, current_user, f"subscribers.bulk_{body.action}", {
        "selected": len(subs), "changed": changed, "value": body.value,
        "by": "filter" if not body.ids else "selection",
    })
    db.commit()
    log.info("wa_contacts_bulk", tenant_id=current_user.tenant_id, action=body.action, selected=len(subs),
             changed=changed)
    return {"action": body.action, "selected": len(subs), "changed": changed}


@router.post("/subscribers/enrol")
def enrol_in_flow(body: EnrolIn, current_user: User = Depends(_MARKETERS), db: Session = Depends(get_db)):
    """Start an active flow (drip) for each picked contact who is opted in and already a guest."""
    flow = svc.active_flow(db, current_user.tenant_id, body.flow_id)
    if not flow:
        raise HTTPException(status_code=422, detail="Pick a flow that is switched on.")
    subs = _targets(db, current_user.tenant_id, body)
    guest_ids, skipped = svc.enrol_plan(db, current_user.tenant_id, subs)
    queued = len(guest_ids) > svc.INLINE_ENROL_LIMIT
    _audit(db, current_user, "subscribers.bulk_enrol", {
        "flow_id": flow.id, "flow_name": flow.name, "selected": len(subs), "enrolled": len(guest_ids),
        "skipped": skipped, "queued": queued,
    }, flow.id, "wa_flow")
    db.commit()
    if queued:
        batches = svc.queue_enrolment(current_user.tenant_id, flow.id, guest_ids)
        started = 0
    else:
        batches, started = 0, svc.start_flow_for(db, current_user.tenant_id, flow, guest_ids)
    return {"selected": len(subs), "enrolled": len(guest_ids), "started": started, "queued": queued,
            "batches": batches, "skipped": skipped}


@router.post("/subscribers/export")
def export_subscribers(body: Targets, current_user: User = Depends(_MARKETERS), db: Session = Depends(get_db)):
    """CSV of the picked contacts. Phone numbers leave the system, so it's on the audit trail."""
    subs = _targets(db, current_user.tenant_id, body)
    names = {r["id"]: r["name"] for r in svc.lists_with_counts(db, current_user.tenant_id)}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["phone", "name", "opted_in", "source", "tags", "lists"])
    for s in subs:
        w.writerow([s.phone, _safe(s.name or ""), "yes" if s.opted_in else "no", s.source or "",
                    _safe("|".join(s.tags or [])), _safe("|".join(names[i] for i in (s.list_ids or []) if i in names))])
    _audit(db, current_user, "subscribers.export", {"row_count": len(subs), "by": "filter" if not body.ids else "selection"})
    db.commit()
    return StreamingResponse(iter([buf.getvalue().encode("utf-8-sig")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="whatsapp-contacts.csv"'})
