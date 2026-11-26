"""Public API: WhatsApp contacts (the opt-in list behind campaigns) and contact lists.

contacts:read lists and reads; contacts:write creates/updates and opts out. Creating is an upsert by phone and never
opts a person who opted out back in (an API call is not consent), the same rule as the CSV import.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.database import get_db
from app.models.api_key import ApiKey
from app.public_api.deps import ApiError, require_scope
from app.services import wa_contacts as svc
from app.services import wa_subscriber_import as importer

router = APIRouter()


class Contact(BaseModel):
    id: str
    phone: str = Field(description="E.164, e.g. +919876543210")
    name: Optional[str] = None
    opted_in: bool = Field(description="false once the person has opted out; HAIP will not send them campaigns")
    opted_in_at: Optional[str] = None
    opted_out_at: Optional[str] = None
    source: Optional[str] = None
    tags: list[str]
    list_ids: list[str] = Field(description="Ids of the contact lists this person is on (see GET /contact-lists)")
    created_at: Optional[str] = None


class ContactResponse(BaseModel):
    data: Contact


class ContactPage(BaseModel):
    class Meta(BaseModel):
        page: int
        per_page: int
        total: int
        total_pages: int
    data: list[Contact]
    meta: Meta


class ContactListItem(BaseModel):
    id: str
    name: str
    count: int


class ContactListList(BaseModel):
    data: list[ContactListItem]


class ContactUpsert(BaseModel):
    phone: str = Field(max_length=30, description="With country code; numbers without one are read as Indian")
    name: Optional[str] = Field(default=None, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=50)
    list_ids: list[str] = Field(default_factory=list, max_length=50)


class ContactPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    add_tags: list[str] = Field(default_factory=list, max_length=50)
    remove_tags: list[str] = Field(default_factory=list, max_length=50)
    add_list_ids: list[str] = Field(default_factory=list, max_length=50)
    remove_list_ids: list[str] = Field(default_factory=list, max_length=50)


def _out(s) -> dict:
    return {"id": s.id, "phone": s.phone, "name": s.name, "opted_in": bool(s.opted_in), "opted_in_at": s.opt_in_at,
            "opted_out_at": s.opt_out_at, "source": s.source, "tags": list(s.tags or []),
            "list_ids": list(s.list_ids or []), "created_at": s.created_at.isoformat() if s.created_at else None}


def _contact_or_404(db: Session, tenant_id: str, contact_id: str):
    from app.api.v1.endpoints.messaging import WASubscriber
    sub = db.query(WASubscriber).filter_by(id=contact_id, tenant_id=tenant_id).first()
    if not sub:
        raise ApiError(404, "contact_not_found", "No contact with this id.")
    return sub


def _check_lists(db: Session, tenant_id: str, list_ids: list[str]) -> None:
    for lid in list_ids:
        if not svc.get_list(db, tenant_id, lid):
            raise ApiError(422, "unknown_list", f"No contact list with id '{lid}'. See GET /contact-lists.")


def _apply(db: Session, tenant_id: str, sub, action: str, values: list[str]) -> None:
    for v in values:
        try:
            svc.apply(db, tenant_id, [sub], action, v)
        except svc.ContactsError as exc:
            raise ApiError(422, "invalid_parameter", str(exc))


@router.get("/contact-lists", tags=["Contacts"], summary="List contact lists", response_model=ContactListList)
def list_contact_lists(key: ApiKey = Depends(require_scope("contacts:read")), db: Session = Depends(get_db)):
    """Named lists (e.g. "Wedding enquiries 2026") with how many contacts are on each. Create lists in HAIP."""
    return {"data": [{"id": r["id"], "name": r["name"], "count": r["count"]}
                     for r in svc.lists_with_counts(db, key.tenant_id)]}


@router.get("/contacts", tags=["Contacts"], summary="List contacts", response_model=ContactPage)
def list_contacts(
    opted_in: Optional[bool] = Query(None, description="true for opted in, false for opted out"),
    tag: Optional[str] = Query(None, max_length=40),
    list_id: Optional[str] = Query(None, max_length=64),
    search: Optional[str] = Query(None, max_length=100, description="Part of a name or phone number"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    key: ApiKey = Depends(require_scope("contacts:read")),
    db: Session = Depends(get_db),
):
    """WhatsApp contacts, newest first."""
    from app.api.v1.endpoints.messaging import WASubscriber
    q = svc.matching(db, key.tenant_id, opted_in=opted_in, search=search, list_id=list_id, tag=tag)
    total = q.count()
    rows = q.order_by(WASubscriber.created_at.desc(), WASubscriber.id).offset((page - 1) * per_page).limit(per_page).all()
    return {"data": [_out(s) for s in rows],
            "meta": {"page": page, "per_page": per_page, "total": total,
                     "total_pages": max(1, (total + per_page - 1) // per_page)}}


@router.get("/contacts/{contact_id}", tags=["Contacts"], summary="Get one contact", response_model=ContactResponse)
def get_contact(contact_id: str, key: ApiKey = Depends(require_scope("contacts:read")), db: Session = Depends(get_db)):
    return {"data": _out(_contact_or_404(db, key.tenant_id, contact_id))}


@router.post("/contacts", tags=["Contacts"], summary="Create or update a contact by phone",
             response_model=ContactResponse, status_code=201)
def upsert_contact(body: ContactUpsert, response: Response, key: ApiKey = Depends(require_scope("contacts:write")),
                   db: Session = Depends(get_db)):
    """Adds the person (opted in) or, if the phone number is already a contact, adds the tags and lists.
    Returns 201 when created, 200 when it already existed. Only add people who agreed to hear from you on WhatsApp.
    Someone who opted out stays opted out."""
    from app.api.v1.endpoints.messaging import WASubscriber
    phone, problem = importer.validate_phone(body.phone)
    if problem:
        raise ApiError(422, "invalid_phone", problem)
    _check_lists(db, key.tenant_id, body.list_ids)
    tags = [t.strip()[:importer.MAX_TAG_LEN] for t in body.tags if t and t.strip()]
    result = importer.import_rows(db, key.tenant_id, [importer.ParsedRow(row=1, raw_phone=phone, name=body.name,
                                                                         tags=tags)], source="api")
    sub = db.query(WASubscriber).filter_by(tenant_id=key.tenant_id, phone=phone).one()
    if result.opted_out_skipped:   # import leaves opted-out people untouched; tags/lists are still the caller's
        _apply(db, key.tenant_id, sub, "add_tag", tags)
    _apply(db, key.tenant_id, sub, "add_to_list", body.list_ids)
    db.commit()
    if not result.added:
        response.status_code = 200
    return {"data": _out(sub)}


@router.patch("/contacts/{contact_id}", tags=["Contacts"], summary="Update a contact's name, tags and lists",
              response_model=ContactResponse)
def update_contact(contact_id: str, body: ContactPatch, key: ApiKey = Depends(require_scope("contacts:write")),
                   db: Session = Depends(get_db)):
    sub = _contact_or_404(db, key.tenant_id, contact_id)
    _check_lists(db, key.tenant_id, body.add_list_ids)
    if body.name is not None:
        sub.name = body.name.strip() or None
    _apply(db, key.tenant_id, sub, "add_tag", body.add_tags)
    _apply(db, key.tenant_id, sub, "remove_tag", body.remove_tags)
    _apply(db, key.tenant_id, sub, "add_to_list", body.add_list_ids)
    sub.list_ids = [x for x in (sub.list_ids or []) if x not in set(body.remove_list_ids)]
    db.commit()
    return {"data": _out(sub)}


@router.post("/contacts/{contact_id}/opt-out", tags=["Contacts"], summary="Opt a contact out",
             response_model=ContactResponse)
def opt_out_contact(contact_id: str, key: ApiKey = Depends(require_scope("contacts:write")),
                    db: Session = Depends(get_db)):
    """The person will no longer get campaigns. Opting back in can only be done by the person (or in HAIP)."""
    sub = _contact_or_404(db, key.tenant_id, contact_id)
    if svc.apply(db, key.tenant_id, [sub], "opt_out"):
        append_audit(db, tenant_id=key.tenant_id, action="subscribers.opt_out", actor_user_id=None,
                     target_type="wa_subscriber", target_id=sub.id, payload={"actor": f"api_key:{key.id}"})
    db.commit()
    return {"data": _out(sub)}
