"""WhatsApp growth tools (WhatsApp step 3): tracked click-to-chat links, their QR code and a website chat button.

A link is ``<api>/api/v1/w/{code}``: a tap is counted and redirected to ``https://wa.me/<number>?text=<prefill>``.
The prefilled first message ends with ``(ref w-xxxxxxxx)``, so when the guest sends it the chat is counted against
the link (``count_chat``). The QR code and the website button both point at the tracked link, so every source shows
taps and chats started. Only stored codes resolve (no open redirect); the wa.me target is built from the
workspace's own number.
"""

from __future__ import annotations

import io
import json
import re
import secrets
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.wa_entry_link import WaEntryLink

REF_RE = re.compile(r"\(ref (w-[a-z0-9]{8})\)", re.I)
MAX_LINKS = 50


class EntryLinkError(ValueError):
    pass


def _digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def workspace_phone(db: Session, tenant_id: str) -> str:
    """The connected WhatsApp number in wa.me form (digits), or ""."""
    from app.models.integration import Integration

    row = (db.query(Integration).filter(Integration.tenant_id == tenant_id, Integration.kind.in_(("whatsapp_meta", "whatsapp")),
                                         Integration.status == "active").first())
    return _digits((row.config or {}).get("display_phone")) if row else ""


def ref_tag(link: WaEntryLink) -> str:
    return f"(ref w-{link.code})"


def wa_me_url(link: WaEntryLink) -> str:
    text = f"{(link.prefill_text or '').strip()} {ref_tag(link)}".strip()
    return f"https://wa.me/{link.phone}?text={quote(text)}"


def create(db: Session, tenant_id: str, user_id: str | None, *, name: str, prefill_text: str = "",
           phone: str | None = None) -> WaEntryLink:
    name = (name or "").strip()
    if not 1 <= len(name) <= 80:
        raise EntryLinkError("Give the link a name (up to 80 characters).")
    if len(prefill_text or "") > 400:
        raise EntryLinkError("Keep the first message under 400 characters.")
    number = _digits(phone) or workspace_phone(db, tenant_id)
    if not 8 <= len(number) <= 15:
        raise EntryLinkError("Connect WhatsApp first, or enter the number with its country code.")
    if db.query(WaEntryLink.id).filter_by(tenant_id=tenant_id).count() >= MAX_LINKS:
        raise EntryLinkError(f"You can keep up to {MAX_LINKS} links. Delete one you no longer use.")
    while True:
        code = secrets.token_hex(4)           # 8 lowercase hex characters, matches REF_RE
        if not db.query(WaEntryLink.id).filter_by(code=code).first():
            break
    link = WaEntryLink(tenant_id=tenant_id, code=code, name=name, prefill_text=(prefill_text or "").strip(),
                       phone=number, created_by=user_id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def follow(db: Session, code: str) -> str | None:
    """Count a tap and return the wa.me address, or None for an unknown or switched-off link. Commits."""
    link = db.query(WaEntryLink).filter_by(code=code, active=True).first() if code else None
    if link is None:
        return None
    db.execute(update(WaEntryLink).where(WaEntryLink.id == link.id)
               .values(clicks=WaEntryLink.clicks + 1, last_clicked_at=datetime.now(UTC)))
    db.commit()
    return wa_me_url(link)


def count_chat(db: Session, tenant_id: str, text: str) -> bool:
    """A guest's message carrying a link's ref: count one chat started for that link (same workspace only)."""
    m = REF_RE.search(text or "")
    if not m:
        return False
    code = m.group(1)[2:].lower()
    res = db.execute(update(WaEntryLink).where(WaEntryLink.tenant_id == tenant_id, WaEntryLink.code == code)
                     .values(chats=WaEntryLink.chats + 1))
    return bool(res.rowcount)


def qr_svg(url: str) -> bytes:
    """A QR code for the link as SVG (prints sharp at any size)."""
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


def widget_js(link_url: str, label: str = "Chat with us") -> str:
    """A small script for any website: a floating WhatsApp button that opens the tracked link.
    Values are JSON-encoded into the script, never concatenated as code."""
    cfg = json.dumps({"href": link_url, "label": (label or "Chat with us")[:40]})
    return (
        "(function(){var c=" + cfg + ";if(document.getElementById('haip-wa-btn'))return;"
        "var a=document.createElement('a');a.id='haip-wa-btn';a.href=c.href;a.target='_blank';a.rel='noopener';"
        "a.setAttribute('aria-label',c.label);a.textContent=c.label;"
        "a.style.cssText='position:fixed;right:16px;bottom:16px;z-index:2147483000;display:flex;align-items:center;"
        "gap:8px;min-height:48px;padding:0 18px;border-radius:999px;background:#1E7A5A;color:#fff;"
        "font:600 15px/1 system-ui,sans-serif;text-decoration:none;box-shadow:0 6px 20px rgba(0,0,0,.18)';"
        "(document.body||document.documentElement).appendChild(a);})();"
    )
