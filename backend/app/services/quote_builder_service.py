"""The staff quote builder (/dashboard/quotes): preview, save to a lead, list, and the catalogue the builder picks from.

  preview   prices the primary option and an optional fallback, each on its own, with NO database writes. A preview may use a
            route or package that is still a draft (it says so); it never stores anything.
  issue     re-prices both options from PUBLISHED records only and stores them through quote_service.issue_options (snapshot,
            record versions, audit `quote.issued`). The next-step time becomes the lead's follow-up task (the work queue's
            "followup" source), not a second field.
  catalog   effective packages, routes and reseller terms, the experience kits, the vehicles, plus every pending draft of a
            route or package with who made it -- so the Routes and Packages tabs can show what waits for approval.

Lead visibility follows /leads: owner and manager see every lead; other roles see their own and unassigned ones.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.business_record import BusinessRecord
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.property import Property
from app.models.task import Task
from app.models.user import User, UserRole
from app.schemas.business_data import SINGLETON_KEY
from app.schemas.quotes import QuoteIssueIn, QuoteOptionIn, QuotePreviewIn
from app.services import business_data_service as bds
from app.services import package_pricing_service as pps
from app.services import quote_service as qs
from app.services import task_service
from app.services.authz_service import get_capabilities

FOLLOW_UP_PREFIX = "Follow up on the quote"
_NO_DATES = ("invalid_dates", "dates_in_past", "package_not_published")


# ─── visibility ──────────────────────────────────────────────────────────────────────────────────────────

def _sees_all(user: User) -> bool:
    return user.role in (UserRole.OWNER, UserRole.MANAGER)


def visible_inquiry(db: Session, user: User, inquiry_id: str) -> Optional[Inquiry]:
    q = db.query(Inquiry).filter(Inquiry.id == inquiry_id, Inquiry.tenant_id == user.tenant_id)
    if not _sees_all(user):
        q = q.filter(or_(Inquiry.assigned_to == user.id, Inquiry.assigned_to.is_(None)))
    return q.first()


# ─── pricing ─────────────────────────────────────────────────────────────────────────────────────────────

def price_option(db: Session, tenant_id: str, opt: QuoteOptionIn, allow_drafts: bool) -> pps.PackageQuote:
    return pps.quote(
        db, tenant_id, opt.package_key, opt.start_date, opt.start_date + timedelta(days=opt.nights), opt.adults, opt.children,
        planned_km=opt.planned_km, extras=[{"name": k} for k in opt.kits], discount_percent=opt.discount_percent,
        vehicle_property_id=opt.vehicle_property_id, level=opt.level, destination_key=opt.destination_key, sights=opt.sights,
        km_rate=opt.km_rate, extra_hours=opt.extra_hours, channel=opt.channel, reseller_tier=opt.reseller_tier,
        commission_percent=opt.commission_percent, allow_drafts=allow_drafts,
    )


def _option_out(db: Session, tenant_id: str, opt: QuoteOptionIn, q: pps.PackageQuote) -> dict:
    out = q.to_api()
    out["start_date"] = opt.start_date.isoformat()
    out["end_date"] = (opt.start_date + timedelta(days=opt.nights)).isoformat()
    if not out["availability"] and q.reason not in _NO_DATES:
        # A refusal for another reason still shows which vehicles are free, so the agent can pick one.
        out["availability"] = pps._open_vehicles(db, tenant_id, [], opt.start_date, opt.start_date + timedelta(days=opt.nights),
                                                 opt.adults + opt.children)
    return out


def _overnight(q: pps.PackageQuote) -> bool:
    return bool(q.km and any(s.get("overnight") for s in q.km.get("stops") or [])) or bool(q.nights)


def blockers(primary: pps.PackageQuote, fallback: Optional[pps.PackageQuote], stay_check: str) -> tuple[list[str], list[str]]:
    """(save_blockers, send_blockers): what stops saving the quote to a lead, and what must be done before it is sent."""
    save: list[str] = []
    if not primary.ok:
        save.append("The main option cannot be priced yet: " + primary.message)
    elif primary.uses_drafts:
        save.append("The main option uses a route or package waiting for approval.")
    if fallback is not None and not fallback.ok:
        save.append("The fallback option cannot be priced: " + fallback.message)
    elif fallback is not None and fallback.uses_drafts:
        save.append("The fallback option uses a route or package waiting for approval.")
    send = list(save)
    if primary.ok and _overnight(primary) and stay_check != "confirmed":
        send.append("Confirm the overnight stay before sending the price.")
    return save, send


def preview(db: Session, tenant_id: str, body: QuotePreviewIn) -> dict:
    p = price_option(db, tenant_id, body.primary, allow_drafts=True)
    f = price_option(db, tenant_id, body.fallback, allow_drafts=True) if body.fallback else None
    save, send = blockers(p, f, body.stay_check)
    return {
        "primary": _option_out(db, tenant_id, body.primary, p),
        "fallback": _option_out(db, tenant_id, body.fallback, f) if f is not None else None,
        "stay_check": body.stay_check, "can_save": not save, "save_blockers": save, "send_blockers": send,
    }


# ─── issuing ─────────────────────────────────────────────────────────────────────────────────────────────

def _set_next_step(db: Session, user: User, inquiry: Inquiry, when, title: str) -> Task:
    """Move the lead's open quote follow-up to `when`, or create it. One open follow-up per lead from the quote builder."""
    task = (db.query(Task).filter(Task.tenant_id == user.tenant_id, Task.inquiry_id == inquiry.id, Task.is_done.is_(False),
                                  Task.title.like(f"{FOLLOW_UP_PREFIX}%")).order_by(Task.created_at.desc()).first())
    if task is not None:
        task.due_date, task.title = when, title
        db.flush()
        return task
    return task_service.create_task(db, user.tenant_id, title, created_by=user.id, due_date=when, priority="high",
                                    guest_id=inquiry.guest_id, inquiry_id=inquiry.id,
                                    assigned_to=inquiry.assigned_to or user.id, commit=False)


def issue(db: Session, user: User, body: QuoteIssueIn) -> dict:
    """Price from published records and store. Raises qs.QuoteError (404 / 422). The caller commits."""
    inquiry = visible_inquiry(db, user, body.inquiry_id)
    if inquiry is None:
        raise qs.QuoteError("not_found", "Lead not found.", 404)
    p = price_option(db, user.tenant_id, body.primary, allow_drafts=False)
    if not p.ok:
        raise qs.QuoteError(p.reason or "not_quotable", p.message, 422)
    f = price_option(db, user.tenant_id, body.fallback, allow_drafts=False) if body.fallback else None
    meta = {"stay_check": body.stay_check, "stay_name": body.stay_name, "channel": body.primary.channel}
    rows = qs.issue_options(db, user.tenant_id, inquiry.id, p, f, user.id, meta=meta)
    if body.note:
        rows[0].notes = body.note
    task = None
    if body.next_step_at:
        task = _set_next_step(db, user, inquiry, body.next_step_at, f"{FOLLOW_UP_PREFIX}: {p.package_name}")
    db.flush()
    return {"quotes": [row_out(r) for r in rows],
            "next_step": {"task_id": task.id, "due_date": task.due_date.isoformat() if task.due_date else None} if task else None}


def row_out(r: InquiryQuote) -> dict:
    return {
        "id": r.id, "inquiry_id": r.inquiry_id, "amount": str(r.amount), "currency": r.currency, "status": r.status,
        "is_active": r.is_active, "option_rank": r.option_rank or 1, "option_group_id": r.option_group_id,
        "valid_until": r.valid_until.isoformat() if r.valid_until else None, "created_at": r.created_at.isoformat() if r.created_at else None,
        "created_by": r.created_by, "package_key": r.package_key, "check_in": r.check_in.isoformat() if r.check_in else None,
        "check_out": r.check_out.isoformat() if r.check_out else None, "guests": r.guests, "notes": r.notes,
        "snapshot": r.snapshot or {}, "record_refs": r.record_refs or [],
    }


def list_quotes(db: Session, user: User, inquiry_id: str) -> Optional[list[dict]]:
    if visible_inquiry(db, user, inquiry_id) is None:
        return None
    rows = (db.query(InquiryQuote).filter_by(tenant_id=user.tenant_id, inquiry_id=inquiry_id)
            .order_by(InquiryQuote.created_at.desc(), InquiryQuote.option_rank.asc()).all())
    from app.services.quote_journey import decorate
    return decorate(db, user.tenant_id, [row_out(r) for r in rows])


def get_quote(db: Session, user: User, quote_id: str) -> Optional[dict]:
    row = db.query(InquiryQuote).filter_by(id=quote_id, tenant_id=user.tenant_id).first()
    inquiry = visible_inquiry(db, user, row.inquiry_id) if row is not None else None
    if row is None or inquiry is None:
        return None
    out = row_out(row)
    out["still_valid"] = qs.check_still_valid(db, user.tenant_id, row)
    # Sending (POST /quotes/{id}/send): where it stands, and what would stop it. Both options travel together.
    from app.services import quote_send_service as qss
    from app.services.quote_journey import journey, link_out
    primary = qss.primary_of(db, user.tenant_id, row)
    rows = qss.group_rows(db, user.tenant_id, primary)
    guest = db.query(Guest).filter_by(id=inquiry.guest_id, tenant_id=user.tenant_id).first()
    out["quote_number"] = qss.quote_number(primary)
    out["payment_link"] = link_out(qss.latest_links(db, user.tenant_id, [row.id]).get(row.id))
    out["send"] = journey(db, user.tenant_id, rows)
    out["send_readiness"] = qss.readiness(db, user.tenant_id, primary, rows, guest)
    return out


# ─── lead picker ─────────────────────────────────────────────────────────────────────────────────────────

def search_leads(db: Session, user: User, text: str, limit: int = 20) -> list[dict]:
    q = (db.query(Inquiry, Guest).join(Guest, Guest.id == Inquiry.guest_id)
         .filter(Inquiry.tenant_id == user.tenant_id, Guest.tenant_id == user.tenant_id, Guest.is_deleted.is_(False)))
    if not _sees_all(user):
        q = q.filter(or_(Inquiry.assigned_to == user.id, Inquiry.assigned_to.is_(None)))
    text = (text or "").strip()
    if text:
        digits = "".join(ch for ch in text if ch.isdigit())
        conds = [Guest.name.ilike(f"%{text}%")]
        if len(digits) >= 4:
            conds.append(Guest.phone.like(f"%{digits}%"))
        q = q.filter(or_(*conds))
    out = []
    for inq, g in q.order_by(Inquiry.created_at.desc()).limit(limit).all():
        phone = "".join(ch for ch in (g.phone or "") if ch.isdigit())
        out.append({
            "inquiry_id": inq.id, "guest_name": g.name or "Unnamed guest", "phone_last4": phone[-4:] if phone else None,
            "source": inq.source.value if inq.source else None, "check_in": inq.check_in, "adults": inq.adults,
            "children": inq.children, "created_at": inq.created_at.isoformat() if inq.created_at else None,
        })
    return out


# ─── catalogue ───────────────────────────────────────────────────────────────────────────────────────────

def _rec(r: Optional[BusinessRecord], names: dict) -> Optional[dict]:
    if r is None:
        return None
    return {"record_id": r.id, "version": r.version, "status": r.status, "data": r.data, "change_note": r.change_note,
            "effective_from": r.effective_from.isoformat() if r.effective_from else None,
            "created_by": r.created_by, "created_by_name": names.get(r.created_by),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "published_at": r.published_at.isoformat() if r.published_at else None}


def _send_setup(db: Session, tenant_id: str) -> dict:
    """What "Send quote + payment link" needs from the workspace (shown before a quote is saved)."""
    from app.models.integration import Integration
    from app.services.quote_send_service import template_status
    rzp = db.query(Integration.id).filter(Integration.tenant_id == tenant_id, Integration.kind == "razorpay",
                                          Integration.status == "active", Integration.credentials_kms_blob.isnot(None)).first()
    return {"razorpay_connected": rzp is not None, "template_status": template_status(db, tenant_id)}


def catalog(db: Session, user: User) -> dict:
    tid = user.tenant_id
    today = bds.tenant_today(db, tid)
    drafts = db.query(BusinessRecord).filter(BusinessRecord.tenant_id == tid, BusinessRecord.status == "draft",
                                             BusinessRecord.kind.in_(("package", "destination"))).all()
    live = {k: {r.key: r for r in bds.list_effective(db, tid, k, today)} for k in ("package", "destination")}
    people = {r.created_by for r in drafts} | {r.created_by for k in live for r in live[k].values()}
    names = {u.id: u.name for u in db.query(User).filter(User.tenant_id == tid, User.id.in_([p for p in people if p]))}

    def group(kind: str) -> list[dict]:
        pending = {d.key: d for d in drafts if d.kind == kind}
        keys = sorted(set(live[kind]) | set(pending), key=lambda k: str((live[kind].get(k) or pending[k]).data.get("name", k)).lower())
        return [{"key": k, "live": _rec(live[kind].get(k), names), "draft": _rec(pending.get(k), names)} for k in keys]

    kits: dict[str, dict] = {}
    for key, r in live["package"].items():
        for c in bds.parse(r).charges:
            if c.kind == "experience":
                k = kits.setdefault(c.name, {"name": c.name, "amount": str(c.amount), "unit": c.unit, "package_keys": []})
                k["package_keys"].append(key)
    reseller = bds.get_effective(db, tid, "reseller_terms", SINGLETON_KEY, today)
    payment = bds.get_effective(db, tid, "payment_policy", SINGLETON_KEY, today)
    caps = get_capabilities(db, user)
    vehicles = db.query(Property).filter(Property.tenant_id == tid, Property.is_active.is_(True)).order_by(Property.name).all()
    return {
        "today": today.isoformat(),
        "packages": group("package"), "destinations": group("destination"),
        "kits": sorted(kits.values(), key=lambda k: k["name"]),
        "reseller_terms": {"version": reseller.version, "data": reseller.data} if reseller else None,
        "advance_percent": str(bds.parse(payment).advance_percent) if payment else None,
        "vehicles": [{"id": v.id, "name": v.name} for v in vehicles],
        "send_setup": _send_setup(db, tid),
        "permissions": {
            "user_id": user.id, "is_owner": user.role == UserRole.OWNER,
            "can_quote": "quotes.write" in caps,
            "can_draft": bool({"business_data.draft", "settings.manage"} & caps),
            "can_publish": bool({"business_data.publish", "settings.manage"} & caps),
            "can_manage_templates": _sees_all(user),
        },
    }
