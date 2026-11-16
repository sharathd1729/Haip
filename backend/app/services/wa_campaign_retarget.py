"""Retarget part of an earlier WhatsApp campaign (WhatsApp step 2): a new campaign whose audience is
``{"type": "retarget", "campaign_id": ..., "segment": ...}``.

Segments: not_read (reached but never read), not_replied (reached, no reply within the reply window), not_clicked /
clicked (tracked link button), failed (failed for a reason a second try can fix). People who opted out or withdrew
WhatsApp marketing consent are always left out, whatever the segment.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient

SEGMENTS = {
    "not_read": "Reached but didn't read",
    "not_replied": "Didn't reply",
    "not_clicked": "Didn't tap the link",
    "clicked": "Tapped the link",
    "failed": "Failed for a reason worth retrying",
}


class RetargetError(ValueError):
    pass


def _pick(db: Session, tenant_id: str, campaign_id: str, segment: str) -> list[Recipient]:
    from app.services import wa_campaign_delivery as delivery

    rows = db.query(Recipient).filter_by(tenant_id=tenant_id, campaign_id=campaign_id).all()
    reached = [r for r in rows if r.status in ("sent", "delivered", "read")]
    if segment == "not_read":
        return [r for r in reached if r.read_at is None and r.status != "read"]
    if segment == "not_replied":
        replied = delivery.replies(db, tenant_id, campaign_id)
        return [r for r in reached if r.id not in replied]
    if segment == "clicked":
        return [r for r in reached if r.clicked_at is not None]
    if segment == "not_clicked":
        return [r for r in reached if r.clicked_at is None]
    if segment == "failed":
        return [r for r in rows if r.status == "failed" and not delivery.should_skip(r)]
    raise RetargetError("Unknown segment.")


def _blocked(db: Session, tenant_id: str, rows: list[Recipient]) -> set[str]:
    """Recipient ids that must not be messaged: opted-out subscribers, guests who withdrew marketing consent."""
    from app.api.v1.endpoints.messaging import WASubscriber
    from app.models.consent import Consent

    phones = {r.phone for r in rows}
    out_phones = {p for (p,) in db.query(WASubscriber.phone).filter(
        WASubscriber.tenant_id == tenant_id, WASubscriber.phone.in_(phones or {""}), WASubscriber.opted_in.is_(False))}
    guest_ids = {r.guest_id for r in rows if r.guest_id}
    withdrawn = {g for (g,) in db.query(Consent.guest_id).filter(
        Consent.tenant_id == tenant_id, Consent.guest_id.in_(guest_ids or {""}), Consent.scope == "marketing",
        Consent.granted.is_(False))}
    return {r.id for r in rows if r.phone in out_phones or (r.guest_id and r.guest_id in withdrawn)}


def members(db: Session, tenant_id: str, audience_filter: dict) -> list:
    """The people to message, duck-typed like the runner's other audiences (phone, name, guest_id, id)."""
    from app.services.wa_lead_audience import Member

    source = audience_filter.get("campaign_id")
    segment = audience_filter.get("segment")
    if not source or segment not in SEGMENTS:
        return []
    rows = _pick(db, tenant_id, source, segment)
    blocked = _blocked(db, tenant_id, rows)
    return [Member(phone=r.phone, name=r.name, guest_id=r.guest_id, id=r.subscriber_id) for r in rows if r.id not in blocked]


def count(db: Session, tenant_id: str, campaign_id: str) -> dict[str, int]:
    """How many people each segment would reach now (for the retarget buttons)."""
    return {seg: len(members(db, tenant_id, {"campaign_id": campaign_id, "segment": seg})) for seg in SEGMENTS}
