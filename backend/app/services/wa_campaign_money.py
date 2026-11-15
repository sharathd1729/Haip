"""What a WhatsApp campaign earned (WhatsApp step 2): link clicks, leads, bookings, revenue and cost.

Clicks: a template whose URL button is the tracking link ``<site>/api/v1/c/{{1}}`` gets one code per recipient as
that {{1}}; GET /api/v1/c/{code} records the first tap and sends the person on to the campaign's ``link_url``.
Only stored codes resolve, so it can't be used as an open redirect.

Leads and bookings: a recipient whose guest became a lead (a usable phone, HAIP's one lead rule) after the send, and
stays created after the send within ATTRIBUTION_DAYS (cancelled ones left out). Revenue only for viewers with
revenue.read. Cost from wa_costs (Meta's pricing x the workspace's rates).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient

TRACK_MARKER = "/api/v1/c/{{1}}"
ATTRIBUTION_DAYS = 30


def _aware(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def tracked_button_index(components: list) -> int | None:
    """Position of the template's tracking-link URL button, or None."""
    for comp in components or []:
        if (comp.get("type") or "").upper() != "BUTTONS":
            continue
        for i, b in enumerate(comp.get("buttons") or []):
            if (b.get("type") or "").upper() == "URL" and TRACK_MARKER in (b.get("url") or ""):
                return i
    return None


def click_code(db: Session, row: Recipient) -> str:
    """This recipient's code, made on first use (10 url-safe characters, unique)."""
    if row.click_code:
        return row.click_code
    while True:
        code = secrets.token_urlsafe(8)[:10]
        if not db.query(Recipient.id).filter_by(click_code=code).first():
            row.click_code = code
            db.flush()
            return code


def follow(db: Session, code: str) -> str | None:
    """Record a tap on a tracked link and return where it goes, or None for an unknown code. Commits."""
    from app.api.v1.endpoints.messaging import WACampaign

    row = db.query(Recipient).filter_by(click_code=code).first() if code else None
    if row is None:
        return None
    campaign = db.query(WACampaign).filter_by(id=row.campaign_id, tenant_id=row.tenant_id).first()
    if campaign is None or not campaign.link_url:
        return None
    if row.clicked_at is None:
        row.clicked_at = datetime.now(UTC)
        db.commit()
    return campaign.link_url


def _guests_by_recipient(db: Session, tenant_id: str, rows: list[Recipient]) -> dict[str, str]:
    """recipient id -> guest id: the audience's own guest, else the guest whose phone/WhatsApp number matches."""
    from app.models.guest_identity import GuestIdentity
    from app.services import chat_phone_capture, phone_identity

    out = {r.id: r.guest_id for r in rows if r.guest_id}
    rest = [r for r in rows if not r.guest_id and r.phone]
    if not rest:
        return out
    region = chat_phone_capture.region_for(db, tenant_id)
    by_phone: dict[str, list[str]] = {}
    for r in rest:
        e164 = phone_identity.normalize(r.phone if r.phone.startswith("+") else f"+{r.phone}", region) \
            or phone_identity.normalize(r.phone, region)
        if e164:
            by_phone.setdefault(e164, []).append(r.id)
    if not by_phone:
        return out
    for guest_id, value in db.query(GuestIdentity.guest_id, GuestIdentity.identity_value).filter(
        GuestIdentity.tenant_id == tenant_id, GuestIdentity.identity_type.in_(("phone", "whatsapp_number")),
        GuestIdentity.identity_value.in_(list(by_phone)),
    ):
        for rid in by_phone.get(value, []):
            out.setdefault(rid, guest_id)
    return out


def report(db: Session, tenant, campaign, *, money: bool) -> dict:
    from app.models.guest import Guest
    from app.models.property import Stay
    from app.services import wa_costs

    rows = db.query(Recipient).filter_by(tenant_id=tenant.id, campaign_id=campaign.id).all()
    sent = [r for r in rows if r.sent_at is not None]
    clicks = sum(1 for r in sent if r.clicked_at is not None)
    guest_of = _guests_by_recipient(db, tenant.id, sent)
    sent_at = {}
    for r in sent:
        g = guest_of.get(r.id)
        if g:
            sent_at[g] = min(_aware(r.sent_at), sent_at.get(g, _aware(r.sent_at)))
    leads = 0
    if sent_at:
        for gid, lead_at in db.query(Guest.id, Guest.lead_identified_at).filter(
            Guest.tenant_id == tenant.id, Guest.id.in_(list(sent_at)), Guest.lead_identified_at.isnot(None),
        ):
            if _aware(lead_at) >= sent_at[gid]:
                leads += 1
    bookings, revenue = 0, 0.0
    if sent_at:
        for gid, amount, created in db.query(Stay.guest_id, Stay.total_amount, Stay.created_at).filter(
            Stay.tenant_id == tenant.id, Stay.guest_id.in_(list(sent_at)), Stay.status != "cancelled",
        ):
            c = _aware(created)
            if c is not None and sent_at[gid] <= c <= sent_at[gid] + timedelta(days=ATTRIBUTION_DAYS):
                bookings += 1
                revenue += float(amount or 0)
    cost = wa_costs.cost_of(db, tenant, [r.wa_message_id for r in sent if r.wa_message_id])
    tracked = tracked_button_index(_template_components(db, tenant.id, campaign)) is not None
    return {
        "tracked_link": tracked,
        "clicks": clicks if tracked else None,
        "click_rate": round(clicks / len(sent) * 100, 1) if tracked and sent else None,
        "leads": leads,
        "bookings": bookings,
        "revenue_inr": round(revenue, 2) if money else None,
        "money_restricted": not money,
        "cost_inr": cost["amount_inr"],
        "billable_messages": cost["messages"],
        "cost_per_lead_inr": round(cost["amount_inr"] / leads, 2) if leads else None,
        "cost_per_booking_inr": round(cost["amount_inr"] / bookings, 2) if bookings else None,
        "attribution_days": ATTRIBUTION_DAYS,
    }


def _template_components(db: Session, tenant_id: str, campaign) -> list:
    from app.api.v1.endpoints.messaging import WATemplate

    t = db.query(WATemplate).filter_by(id=campaign.template_id, tenant_id=tenant_id).first() if campaign.template_id else None
    return (t.components or []) if t is not None else []
