"""Creator (barter) stays (agency M7): request -> free dates -> approved -> comped stay booked -> deliverables posted
with an ASCI label -> bookings measured.

  * Dates come from HAIP's own calendar: open runs of nights that are NOT a long weekend or festival window (a free
    stay should fill a quiet night, not one a paying guest would take).
  * A person with marketing.approve approves the free stay (not the person who asked, unless owner); the dates are
    checked again when it is booked. The stay is a normal booking (booking_service.create_booking) with amount 0 and
    channel_source "creator", so the calendar, the vehicle pool and check-in all work; it is left out of the
    marketing reports' bookings, which are paying stays.
  * The creator's phone/email go onto a guest record through identity_service; this module never stores them.
  * A deliverable counts only when its caption carries an ASCI disclosure label (schemas.marketing_partners).
  * Each deal has its own link (utm_campaign "cr-<8>"): enquiries and bookings that come through it are credited to
    the deal in every report (marketing_attribution), next to its cost (the stay's value).
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.marketing_partners import MarketingCreator, MarketingCreatorDeal
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.marketing_partners import ASCI_LABELS, BookCompIn, CreatorIn, DealIn, DeliveredIn
from app.services import marketing_content_service as content_svc
from app.services import marketing_links as links
from app.services.marketing_content_service import MarketingError

OPEN = ("requested", "approved", "booked")


def _bad(exc: Exception, code: str, message: str) -> MarketingError:
    return MarketingError(422, code, message, [str(exc)[:300]])


# ── Creators ────────────────────────────────────────────────────────────────────────────────────────────────────────

def create_creator(db: Session, tenant: Tenant, data: dict, actor_id: str) -> MarketingCreator:
    try:
        body = CreatorIn.model_validate(data)
    except ValueError as exc:
        raise _bad(exc, "bad_creator", "Check the creator's handle.")
    if db.query(MarketingCreator.id).filter_by(tenant_id=tenant.id, platform=body.platform, handle=body.handle).first():
        raise MarketingError(409, "duplicate", f"@{body.handle} is already in your creators.")
    c = MarketingCreator(tenant_id=tenant.id, created_by=actor_id, **body.model_dump())
    db.add(c)
    db.flush()
    append_audit(db, tenant_id=tenant.id, action="marketing.creator.added", actor_user_id=actor_id,
                 target_type="marketing_creator", target_id=c.id, payload={"handle": c.handle, "platform": c.platform})
    return c


def get_creator(db: Session, tenant_id: str, creator_id: str) -> MarketingCreator:
    c = db.query(MarketingCreator).filter_by(id=creator_id, tenant_id=tenant_id).first()
    if c is None:
        raise MarketingError(404, "not_found", "No such creator in this workspace.")
    return c


def creator_dict(c: MarketingCreator) -> dict:
    return {"id": c.id, "platform": c.platform, "handle": c.handle, "name": c.name, "followers": c.followers,
            "niche": c.niche, "notes": c.notes, "status": c.status, "has_contact": bool(c.guest_id)}


# ── Free dates ──────────────────────────────────────────────────────────────────────────────────────────────────────

def free_windows(db: Session, tenant: Tenant, *, nights: int = 2, horizon: int = 60,
                 today: Optional[date] = None) -> list[dict]:
    """Open runs of `nights`+ nights per vehicle/property in the next `horizon` days, skipping long weekends."""
    from app.services import marketing_demand as demand
    today = today or date.today()
    start, end = today + timedelta(days=3), today + timedelta(days=horizon)
    busy = set()
    for lw in demand.long_weekends(demand.home_state(db, tenant), start, end):
        d, last = date.fromisoformat(lw["start"]), date.fromisoformat(lw["end"])
        while d <= last:
            busy.add(d)
            d += timedelta(days=1)
    props = dict(db.query(Property.name, Property.id).filter(Property.tenant_id == tenant.id))
    out = []
    for name, days in demand.free_nights(db, tenant.id, start, end).items():
        run: list[date] = []
        for d in days + [None]:
            if d is not None and d not in busy and (not run or d == run[-1] + timedelta(days=1)):
                run.append(d)
                continue
            if len(run) >= nights:
                out.append({"property_id": props.get(name), "property": name, "check_in": run[0].isoformat(),
                            "check_out": (run[0] + timedelta(days=nights)).isoformat(), "free_nights": len(run)})
            run = [d] if d is not None and d not in busy else []
    return sorted(out, key=lambda w: w["check_in"])[:12]


# ── Deals ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def get_deal(db: Session, tenant_id: str, deal_id: str) -> MarketingCreatorDeal:
    d = db.query(MarketingCreatorDeal).filter_by(id=deal_id, tenant_id=tenant_id).first()
    if d is None:
        raise MarketingError(404, "not_found", "No such creator deal in this workspace.")
    return d


def _prop(db: Session, tenant_id: str, property_id: Optional[str]) -> Optional[Property]:
    if not property_id:
        return None
    p = db.query(Property).filter_by(id=property_id, tenant_id=tenant_id).first()
    if p is None:
        raise MarketingError(404, "property_not_found", "No such property in this workspace.")
    return p


def create_deal(db: Session, tenant: Tenant, data: dict, actor_id: str) -> MarketingCreatorDeal:
    try:
        body = DealIn.model_validate(data)
    except ValueError as exc:
        raise _bad(exc, "bad_deal", "Check the dates and deliverables.")
    creator = get_creator(db, tenant.id, body.creator_id)
    _prop(db, tenant.id, body.property_id)
    deal = MarketingCreatorDeal(tenant_id=tenant.id, creator_id=creator.id, status="requested",
                                property_id=body.property_id, check_in=body.check_in, check_out=body.check_out,
                                guests=body.guests, comp_value_inr=body.comp_value_inr, notes=body.notes,
                                deliverables=[{"kind": x.kind, "due": x.due.isoformat() if x.due else None, "url": None,
                                               "label": None, "delivered_at": None} for x in body.deliverables],
                                created_by=actor_id)
    db.add(deal)
    db.flush()
    append_audit(db, tenant_id=tenant.id, action="marketing.creator_deal.requested", actor_user_id=actor_id,
                 target_type="marketing_creator_deal", target_id=deal.id,
                 payload={"creator": creator.handle, "comp_value_inr": deal.comp_value_inr,
                          "deliverables": [x["kind"] for x in deal.deliverables]})
    return deal


def _conflicts(db: Session, tenant_id: str, deal: MarketingCreatorDeal) -> list:
    from app.services import booking_service
    return booking_service.find_conflicts(db, tenant_id, deal.property_id, deal.check_in, deal.check_out)


def approve_deal(db: Session, tenant: Tenant, deal_id: str, actor: User) -> MarketingCreatorDeal:
    deal = get_deal(db, tenant.id, deal_id)
    if deal.status != "requested":
        raise MarketingError(409, "wrong_state", "Only a requested deal can be approved.")
    if content_svc._role(actor) != "owner" and deal.created_by == actor.id:
        raise MarketingError(403, "self_approval", "You asked for this stay, so someone else must approve it.")
    if not (deal.property_id and deal.check_in and deal.check_out):
        raise MarketingError(422, "no_dates", "Choose the stay and dates first.")
    if _conflicts(db, tenant.id, deal):
        raise MarketingError(409, "dates_taken", "Those dates are no longer free; pick others.")
    deal.status, deal.approved_by, deal.approved_at = "approved", actor.id, datetime.now(timezone.utc)
    append_audit(db, tenant_id=tenant.id, action="marketing.creator_deal.approved", actor_user_id=actor.id,
                 target_type="marketing_creator_deal", target_id=deal.id,
                 payload={"comp_value_inr": deal.comp_value_inr, "check_in": deal.check_in.isoformat(),
                          "check_out": deal.check_out.isoformat()})
    return deal


def book_comp(db: Session, tenant: Tenant, deal_id: str, contact: dict, actor_id: str) -> MarketingCreatorDeal:
    """The free stay as a real booking (amount 0, channel_source creator). Needs the creator's phone or email once."""
    from app.services import booking_service, identity_service
    from app.services.phone_identity import normalize, region_for_tenant
    deal = get_deal(db, tenant.id, deal_id)
    if deal.status != "approved":
        raise MarketingError(409, "wrong_state", "Approve the stay before booking it.")
    creator = get_creator(db, tenant.id, deal.creator_id)
    try:
        c = BookCompIn.model_validate(contact or {})
    except ValueError as exc:
        raise _bad(exc, "bad_contact", "Check the phone or email.")
    guest_id = creator.guest_id
    if guest_id is None:
        phone = normalize(c.phone, region_for_tenant(db, tenant.id)) if c.phone else None
        if phone:
            guest_id, _ = identity_service.resolve_gid(db, tenant.id, signal_type="phone", value=phone, source="creator",
                                                       guest_fields={"name": creator.name or f"@{creator.handle}"})
        elif c.email and "@" in c.email:
            guest_id, _ = identity_service.resolve_gid(db, tenant.id, signal_type="email", value=c.email.strip().lower(),
                                                       source="creator",
                                                       guest_fields={"name": creator.name or f"@{creator.handle}"})
        else:
            raise MarketingError(422, "no_contact", "Add the creator's phone or email to book the stay.")
        creator.guest_id = guest_id
    if _conflicts(db, tenant.id, deal):
        raise MarketingError(409, "dates_taken", "Those dates were booked meanwhile; pick others.")
    prop = _prop(db, tenant.id, deal.property_id)
    stay = booking_service.create_booking(
        db, tenant.id, guest_id=guest_id, prop=prop, check_in=deal.check_in, check_out=deal.check_out,
        adults=deal.guests, total_amount=0, channel_source="creator", actor_user_id=actor_id, actor_role="marketing",
        internal_notes=f"Creator stay (barter) for @{creator.handle}. Not a paid booking.", reason="Creator stay",
        audit_extra={"creator_deal_id": deal.id})
    deal.status, deal.stay_id = "booked", stay.id
    append_audit(db, tenant_id=tenant.id, action="marketing.creator_deal.booked", actor_user_id=actor_id,
                 target_type="marketing_creator_deal", target_id=deal.id, payload={"stay_id": stay.id})
    return deal


def asci_label(caption: str) -> Optional[str]:
    low = (caption or "").lower()
    return next((label for label in ASCI_LABELS if label in low), None)


def deliver(db: Session, tenant: Tenant, deal_id: str, data: dict, actor_id: str) -> MarketingCreatorDeal:
    try:
        body = DeliveredIn.model_validate(data)
    except ValueError as exc:
        raise _bad(exc, "bad_deliverable", "Paste the post's https:// link and its caption.")
    deal = get_deal(db, tenant.id, deal_id)
    if deal.status not in ("booked", "delivered"):
        raise MarketingError(409, "wrong_state", "Deliverables come after the stay is booked.")
    items = [dict(x) for x in deal.deliverables or []]
    if body.index >= len(items):
        raise MarketingError(404, "not_found", "No such deliverable on this deal.")
    label = asci_label(body.caption)
    if label is None:
        raise MarketingError(422, "asci_label_missing",
                             "The caption needs a clear disclosure for a free stay (ASCI), e.g. #ad, #collab or #gifted.",
                             list(ASCI_LABELS))
    items[body.index].update(url=body.url, label=label, delivered_at=datetime.now(timezone.utc).isoformat())
    deal.deliverables = items
    if all(x.get("delivered_at") for x in items):
        deal.status, deal.closed_at = "delivered", datetime.now(timezone.utc)
    append_audit(db, tenant_id=tenant.id, action="marketing.creator_deal.delivered", actor_user_id=actor_id,
                 target_type="marketing_creator_deal", target_id=deal.id,
                 payload={"index": body.index, "url": body.url, "label": label})
    return deal


def cancel_deal(db: Session, tenant: Tenant, deal_id: str, actor_id: str) -> MarketingCreatorDeal:
    deal = get_deal(db, tenant.id, deal_id)
    if deal.status not in ("requested", "approved"):
        raise MarketingError(409, "wrong_state", "A booked stay is cancelled from its booking page.")
    deal.status, deal.closed_at = "cancelled", datetime.now(timezone.utc)
    append_audit(db, tenant_id=tenant.id, action="marketing.creator_deal.cancelled", actor_user_id=actor_id,
                 target_type="marketing_creator_deal", target_id=deal.id, payload={})
    return deal


def campaign(deal_id: str) -> str:
    return f"cr-{deal_id.replace('-', '')[:8]}"


def creator_link(tenant: Tenant, deal: MarketingCreatorDeal, creator: MarketingCreator) -> Optional[str]:
    from app.services.marketing_ai_service import get_profile
    site = ((get_profile(tenant).get("socials") or {}).get("website") or "").strip()
    if not site.startswith("https://"):
        return None
    return links.tag_url(site, links.utm(source=creator.platform, medium="creator", campaign=campaign(deal.id),
                                         content=creator.handle))


def results(db: Session, tenant: Tenant, deal: MarketingCreatorDeal, *, since: Optional[date] = None) -> dict:
    """Bookings traced to this deal's link since it was made, against what the free stay cost."""
    from app.services import marketing_attribution as attribution
    start = since or (deal.created_at.date() if deal.created_at else date.today() - timedelta(days=90))
    books = attribution.bookings(db, tenant.id, start, date.today())
    mine = [r for r in books["bookings"] if (r["chain"]["credited"] or {}).get("creator_deal_id") == deal.id]
    revenue = round(sum(r["amount"] for r in mine), 2)
    return {"bookings": len(mine), "revenue": revenue, "cost_inr": deal.comp_value_inr,
            "return_per_rupee": round(revenue / deal.comp_value_inr, 2) if deal.comp_value_inr else None,
            "since": start.isoformat()}


def deal_dict(db: Session, tenant: Tenant, d: MarketingCreatorDeal, creator: Optional[MarketingCreator] = None) -> dict:
    creator = creator or get_creator(db, tenant.id, d.creator_id)
    return {"id": d.id, "creator": creator_dict(creator), "status": d.status, "property_id": d.property_id,
            "check_in": d.check_in.isoformat() if d.check_in else None,
            "check_out": d.check_out.isoformat() if d.check_out else None, "guests": d.guests,
            "comp_value_inr": d.comp_value_inr, "deliverables": d.deliverables or [], "notes": d.notes,
            "stay_id": d.stay_id, "created_by": d.created_by, "approved_by": d.approved_by,
            "campaign": campaign(d.id), "link": creator_link(tenant, d, creator), "created_at": d.created_at}
