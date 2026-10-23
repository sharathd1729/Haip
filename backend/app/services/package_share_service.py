"""Send package (sales meetings 23 Oct 2026): a person sends one PUBLISHED retail package to a lead on the official WhatsApp.
GET/POST /leads/{id}/package-share (endpoints/package_share.py; conversations.send + the lead page's visibility).

Packages come ONLY from sales_gateway (published, in effect, never ``audience=b2b``) with the day titles of their published
itinerary. The message: name, a short summary, the length, "Day 1: ..." lines, the price ONLY when the workspace's
price_disclosure is ``grounded`` ("From Rs X + GST", the lowest published rate still in effect; handoff = never a price) and
the link-in-bio page of that package when the workspace has a live site (``https://{host}/links#pkg-{key}``; none = no link).

Sending (never into a personal-WhatsApp-bridge thread; never AI; a person's contact, ``sender_kind="human"``):
  24 h window open      the text as a normal message (wa_booking_messages.send_guest_text). No photo: packages have no
                        linked media asset yet, so none is sent.
  window closed         the UTILITY template ``haip_package_share_v1`` {{1}} name {{2}} package {{3}} link
                        (wa_lead_pack; drafts via POST /workflows/templates/lead-pack) when it is APPROVED and there is a
                        link; otherwise refused with the reason (template waiting for Meta approval / no link) and the
                        text to copy into the guest's chat by hand.
Idempotent per (lead, package, IST day): Message.idempotency_key "pkg:{inquiry}:{package}:{day}". Audited
``lead.package_shared`` (+ the send path's own ``lead.message_queued``).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.tenant import Tenant
from app.models.user import User
from app.services import sales_gateway
from app.services.date_presets import IST

from app.services.wa_lead_pack import PACKAGE_SHARE as TEMPLATE  # noqa: E402  haip_package_share_v1
PREFIX = "pkg:"


class ShareError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: Optional[dict] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra or {}

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message, **self.extra}


def _lead(db: Session, user: User, inquiry_id: str, scope_user_id: Optional[str]) -> tuple[Inquiry, Guest, Tenant]:
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=user.tenant_id).first()
    if inq is None or (scope_user_id and inq.assigned_to and inq.assigned_to != scope_user_id):
        raise ShareError(404, "not_found", "Lead not found")
    guest = db.query(Guest).filter_by(id=inq.guest_id, tenant_id=user.tenant_id).first()
    if guest is None:
        raise ShareError(404, "not_found", "Lead not found")
    return inq, guest, db.query(Tenant).filter_by(id=user.tenant_id).first()


def _length(p: dict) -> str:
    lo, hi = p.get("min_nights") or 0, p.get("max_nights")
    if p.get("product") == "same_day" or hi == 0:
        return "Day trip"
    lo = lo or 1
    if hi is None or hi == lo:
        return f"{lo} night{'s' if lo != 1 else ''} / {lo + 1} days"
    return f"{lo} to {hi} nights"


def _from_price(p: dict, today: date) -> Optional[str]:
    from app.services.bio_packages import _inr
    amounts = []
    for r in p.get("rates") or []:
        try:
            if not r.get("valid_to") or date.fromisoformat(str(r["valid_to"])) >= today:
                amounts.append((Decimal(str(r["amount"])), r.get("unit")))
        except (InvalidOperation, ValueError, KeyError):
            continue
    if not amounts:
        return None
    amount, unit = min(amounts, key=lambda a: a[0])
    per = {"day": " a day", "night": " a night"}.get(str(unit), "")
    return f"From ₹{_inr(amount)}{per} + GST"


def site_link(db: Session, tenant_id: str, package_key: str) -> Optional[str]:
    """The package on the workspace's link-in-bio page, when it has a live site with a working host. Else None."""
    from app.models.website import Site, SiteDomain
    row = (db.query(SiteDomain.hostname).join(Site, Site.id == SiteDomain.site_id)
           .filter(Site.tenant_id == tenant_id, SiteDomain.tenant_id == tenant_id, Site.status == "live",
                   SiteDomain.status.in_(("active", "verified")))
           .order_by(SiteDomain.kind.asc()).first())
    return f"https://{row[0]}/links#pkg-{package_key}" if row else None


def _first(db: Session, tenant_id: str, guest: Guest) -> str:
    from app.services.guest_names import best_first_name
    return best_first_name(db, tenant_id, guest)


def preview(db: Session, tenant: Tenant, guest: Guest, pkg: dict) -> dict:
    from app.services.price_policy import price_mode
    from app.services import business_data_service as bds
    grounded = price_mode(tenant) == "grounded"
    it = sales_gateway.get_itinerary(db, tenant.id, package_key=pkg["key"])
    its = it.data if it.ok and isinstance(it.data, list) else ([it.data] if it.ok and it.data else [])
    days = [d["title"] for d in (its[0]["days"] if its else []) if d.get("title")]
    price = _from_price(pkg, bds.tenant_today(db, tenant.id)) if grounded else None
    link = site_link(db, tenant.id, pkg["key"])
    summary = " ".join((pkg.get("summary") or "").split())
    summary = summary if len(summary) <= 280 else summary[:277].rsplit(" ", 1)[0] + "…"
    lines = [f"Hi {_first(db, tenant.id, guest)}, here is {pkg['name']} ({_length(pkg)})."]
    if summary:
        lines.append(summary)
    lines += [f"Day {i}: {t}" for i, t in enumerate(days, start=1)]
    if price:
        lines.append(price)
    if link:
        lines.append(link)
    lines.append("Reply here with your dates and group size and we'll check availability.")
    return {"key": pkg["key"], "name": pkg["name"], "summary": summary, "length": _length(pkg), "days": days, "price": price,
            "link": link, "text": "\n".join(lines)}


def _channel(db: Session, tenant_id: str, guest: Guest) -> dict:
    from app.services.booking_agenda_service import whatsapp_state
    from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
    state = whatsapp_state(db, tenant_id, guest.id)
    open_conv = (db.query(Conversation).filter_by(tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
                 .order_by(Conversation.last_message_at.desc()).first())
    approved = db.query(WATemplate.id).filter_by(tenant_id=tenant_id, name=TEMPLATE, status=TemplateStatus.APPROVED).first() is not None
    return {"window_open": bool(state["window_open"] and state["conversation_id"]),
            "personal_bridge_only": bool(open_conv is not None and open_conv.is_personal_bridge),
            "template": TEMPLATE, "template_approved": approved, "has_phone": bool((guest.phone or "").strip())}


def options(db: Session, user: User, inquiry_id: str, scope_user_id: Optional[str] = None) -> dict:
    from app.services.price_policy import price_mode
    _, guest, tenant = _lead(db, user, inquiry_id, scope_user_id)
    grounded = price_mode(tenant) == "grounded"
    res = sales_gateway.list_packages(db, tenant.id, include_rates=grounded)
    pkgs = [preview(db, tenant, guest, p) for p in (res.data or [])] if res.ok else []
    return {"packages": pkgs, "price_shown": grounded, **_channel(db, tenant.id, guest)}


def share(db: Session, user: User, inquiry_id: str, package_key: str, scope_user_id: Optional[str] = None) -> dict:
    """Send it (see the module docstring). Raises ShareError with the reason and ``text`` to copy when it cannot."""
    from app.core.audit import append_audit
    from app.services import wa_booking_messages as wbm
    from app.services.price_policy import price_mode

    inq, guest, tenant = _lead(db, user, inquiry_id, scope_user_id)
    found = sales_gateway.get_package(db, tenant.id, package_key, include_rates=price_mode(tenant) == "grounded")
    if not found.ok:   # unpublished, unknown, or a partner-only (b2b) package: never to a guest
        raise ShareError(404 if "not_published" in found.flags else 422, "package_not_available",
                         "That package is not published for guests.", {"flags": found.flags})
    view = preview(db, tenant, guest, found.data)
    ch = _channel(db, tenant.id, guest)
    copy = {"text": view["text"]}
    if not ch["has_phone"]:
        raise ShareError(422, "no_phone", "The guest has no phone number.", copy)
    day = datetime.now(IST).date().isoformat()
    target = wbm.Target("inquiry", inq.id, PREFIX, {"source": "package_share", "package_key": package_key, "inquiry_id": inq.id}, "lead")
    event = f"{package_key}:{day}"
    if ch["window_open"]:
        out = wbm.send_guest_text(db, tenant.id, guest, view["text"], target=target, event=event, actor_user_id=user.id,
                                  sender_name=user.name or "Team", sender_kind="human")
        how = "text"
    else:
        if ch["personal_bridge_only"]:
            raise ShareError(409, "personal_bridge", "This guest's chat is on a staff member's personal WhatsApp. Send it from that phone.", copy)
        if not ch["template_approved"]:
            raise ShareError(409, "template_not_approved", "The guest's 24-hour window is closed and the package template is "
                             "waiting for Meta approval. Copy the text and send it from WhatsApp.", copy)
        if not view["link"]:
            raise ShareError(409, "no_link", "The window is closed and this package has no page to link to. Copy the text instead.", copy)
        out = wbm.send_guest_template(db, tenant.id, guest, TEMPLATE, [_first(db, tenant.id, guest), view["name"], view["link"]],
                                      target=target, event=event, actor_user_id=user.id, sender_name=user.name or "Team",
                                      sender_kind="human")
        how = "template"
    if out["status"] == "skipped":
        raise ShareError(409, "not_sent", f"Not sent: {out['reason']}.", copy)
    if out["status"] == "queued":
        append_audit(db, tenant_id=tenant.id, action="lead.package_shared", actor_user_id=user.id, target_type="inquiry",
                     target_id=inq.id, payload={"package_key": package_key, "how": how, "message_id": out["message_id"],
                                                "price_shown": bool(view["price"]), "link": bool(view["link"])})
        db.commit()
    return {"status": out["status"], "how": how, "message_id": out["message_id"], "text": view["text"]}
