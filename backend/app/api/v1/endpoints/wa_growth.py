"""WhatsApp growth tools and in-chat selling (WhatsApp step 3).

- /messaging/entry-links: tracked click-to-chat links with QR code and website button (services/wa_entry_links.py)
- /messaging/booking-form: publish HAIP's booking form (a WhatsApp Flow) on the workspace's account
- /conversations/{id}/send-packages and /send-booking-form: send the packages list or the form in a chat
"""


from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User, UserRole
from app.models.wa_entry_link import WaEntryLink
from app.services import wa_entry_links as links
from app.services.authz_service import require_capability

router = APIRouter(tags=["whatsapp-growth"])

_MARKETERS = (UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING)


class EntryLinkIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    prefill_text: str = Field(default="", max_length=400)
    phone: str | None = Field(default=None, max_length=20)


class EntryLinkPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    prefill_text: str | None = Field(default=None, max_length=400)
    active: bool | None = None


def _base(request: Request) -> str:
    return (settings.API_BASE_URL or str(request.base_url)).rstrip("/")


def _out(link: WaEntryLink, base: str) -> dict:
    url = f"{base}/api/v1/w/{link.code}"
    return {
        "id": link.id, "name": link.name, "prefill_text": link.prefill_text, "phone": link.phone, "active": link.active,
        "clicks": link.clicks, "chats": link.chats, "last_clicked_at": link.last_clicked_at, "created_at": link.created_at,
        "url": url, "wa_me": links.wa_me_url(link), "qr_svg_url": f"{url}/qr.svg",
        "widget_snippet": f'<script src="{url}/widget.js" async></script>',
    }


def _link_or_404(db: Session, tenant_id: str, link_id: str) -> WaEntryLink:
    link = db.query(WaEntryLink).filter_by(id=link_id, tenant_id=tenant_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    return link


@router.get("/messaging/entry-links")
def list_entry_links(request: Request, current_user: User = Depends(require_roles(*_MARKETERS)), db: Session = Depends(get_db)):
    rows = db.query(WaEntryLink).filter_by(tenant_id=current_user.tenant_id).order_by(WaEntryLink.created_at.desc()).all()
    return {"links": [_out(r, _base(request)) for r in rows],
            "workspace_phone": links.workspace_phone(db, current_user.tenant_id)}


@router.post("/messaging/entry-links", status_code=201)
def create_entry_link(body: EntryLinkIn, request: Request, current_user: User = Depends(require_roles(*_MARKETERS)),
                      db: Session = Depends(get_db)):
    try:
        link = links.create(db, current_user.tenant_id, current_user.id, name=body.name, prefill_text=body.prefill_text,
                            phone=body.phone)
    except links.EntryLinkError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _out(link, _base(request))


@router.patch("/messaging/entry-links/{link_id}")
def update_entry_link(link_id: str, body: EntryLinkPatch, request: Request,
                      current_user: User = Depends(require_roles(*_MARKETERS)), db: Session = Depends(get_db)):
    link = _link_or_404(db, current_user.tenant_id, link_id)
    if body.name is not None:
        link.name = body.name.strip()
    if body.prefill_text is not None:
        link.prefill_text = body.prefill_text.strip()
    if body.active is not None:
        link.active = body.active
    db.commit()
    return _out(link, _base(request))


@router.delete("/messaging/entry-links/{link_id}", status_code=204)
def delete_entry_link(link_id: str, current_user: User = Depends(require_roles(*_MARKETERS)), db: Session = Depends(get_db)):
    db.delete(_link_or_404(db, current_user.tenant_id, link_id))
    db.commit()


# ─── booking form ───────────────────────────────────────────────────────────────

@router.get("/messaging/booking-form")
def booking_form_status(current_user: User = Depends(require_roles(*_MARKETERS)), db: Session = Depends(get_db)):
    from app.services import wa_booking_form
    return wa_booking_form.status(db, current_user.tenant_id)


@router.post("/messaging/booking-form/publish")
def publish_booking_form(current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
                         db: Session = Depends(get_db)):
    from app.core.audit import append_audit
    from app.services import wa_booking_form
    try:
        out = wa_booking_form.publish(db, current_user.tenant_id)
    except wa_booking_form.BookingFormError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="whatsapp.booking_form_published",
                 target_type="integration", target_id=out.get("flow_id") or "", payload={"flow_id": out.get("flow_id")})
    db.commit()
    return out


# ─── in a chat ──────────────────────────────────────────────────────────────────

def _open_whatsapp_chat(db: Session, user: User, conversation_id: str):
    from app.api.v1.endpoints.conversations import _channel_value, _whatsapp_window_open
    from app.models.conversation import Conversation

    conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=user.tenant_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if _channel_value(conv).lower() != "whatsapp":
        raise HTTPException(status_code=422, detail="This works in WhatsApp chats only.")
    if not _whatsapp_window_open(db, conv):
        raise HTTPException(status_code=409, detail="WhatsApp's 24-hour window has closed. Send an approved template instead.")
    return conv


@router.post("/conversations/{conversation_id}/send-packages", status_code=201)
def send_packages(conversation_id: str, current_user: User = Depends(get_current_user),
                  _cap=Depends(require_capability("conversations.send")), db: Session = Depends(get_db)):
    from app.services import wa_catalog
    conv = _open_whatsapp_chat(db, current_user, conversation_id)
    try:
        text, spec = wa_catalog.list_message(db, current_user.tenant_id)
    except wa_catalog.CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    mid = wa_catalog.queue(db, current_user.tenant_id, conv, text, spec, sender_kind=None, sender_id=current_user.id,
                           sender_name=current_user.name or "Team", source="packages")
    return {"message_id": mid}


@router.post("/conversations/{conversation_id}/send-booking-form", status_code=201)
def send_booking_form(conversation_id: str, current_user: User = Depends(get_current_user),
                      _cap=Depends(require_capability("conversations.send")), db: Session = Depends(get_db)):
    from app.services import wa_booking_form, wa_catalog
    conv = _open_whatsapp_chat(db, current_user, conversation_id)
    try:
        spec = wa_booking_form.interactive_spec(db, current_user.tenant_id, conv.id)
    except wa_booking_form.BookingFormError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    mid = wa_catalog.queue(db, current_user.tenant_id, conv, "Share your dates and party size here and we'll check availability.",
                           spec, sender_kind=None, sender_id=current_user.id, sender_name=current_user.name or "Team",
                           source="booking_form")
    return {"message_id": mid}
