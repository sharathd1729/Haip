"""Bookings to Meta as Purchase events (Conversions API, agency M5), so Meta learns which ads bring real stays.

Off until the OWNER switches it on and gives the dataset (pixel) id (ads settings). Every booking is decided once
(`marketing_capi_events`, unique per stay):
  * sent    -- the guest's latest MARKETING consent is granted (DPDP: sharing for advertising is marketing);
  * skipped -- no consent, a cancelled stay, no amount, or older than Meta's 7-day window; NOTHING about the guest
               leaves HAIP for a skipped booking.
What is sent: event_id "stay:<id>" (Meta's dedup key), the stay's created time, value + currency, and only HASHED
identifiers (SHA-256 of the E.164 phone digits, the lower-cased email, HAIP's guest id, country "in"). Click-to-
WhatsApp bookings also carry the ad's ctwa_clid with action_source business_messaging; the rest are "chat"/"other".
Hourly sweep (Celery `marketing_capi.sweep_all` -> `marketing_capi.send_tenant`, queue whatsapp), at most 100 per call.

Studio plan phase 5 (Conversions API for Business Messaging), only with `capi_lead_events` on: a chat that came from a
click-to-WhatsApp ad (lead_attribution.ctwa_clid) is also reported when the person became a LEAD (LeadSubmitted, at
guests.lead_identified_at) and when the enquiry became QUALIFIED (QualifiedLead, lead_metrics' qualified rule, found by
the sweep), once each per enquiry, action_source business_messaging + messaging_channel whatsapp + the ctwa_clid, with
the same consent rule and hashed identifiers. A chat without a ctwa_clid is never reported as a lead.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import structlog
from sqlalchemy.orm import Session

from app.adapters.marketing.meta_ads import MetaAdsError
from app.core.audit import append_audit
from app.models.consent import Consent
from app.models.guest import Guest
from app.models.lead_attribution import LeadAttribution
from app.models.marketing_ads import MarketingCapiEvent
from app.models.property import Stay
from app.models.tenant import Tenant
from app.services import marketing_ads_service as ads
from app.services import phone_identity

log = structlog.get_logger()

WINDOW = timedelta(days=7)     # Meta rejects events older than 7 days
BATCH = 100
MAX_TRIES = 5


def _h(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def consented(db: Session, tenant_id: str, guest_ids: list[str]) -> set[str]:
    """Guests whose latest marketing consent (any channel) is granted and not withdrawn."""
    latest: dict[str, Consent] = {}
    if not guest_ids:
        return set()
    for c in (db.query(Consent).filter(Consent.tenant_id == tenant_id, Consent.scope == "marketing",
                                       Consent.guest_id.in_(guest_ids)).order_by(Consent.recorded_at.asc())):
        latest[c.guest_id] = c
    return {g for g, c in latest.items() if c.granted and not c.withdrawn_at}


def user_data(guest: Guest) -> dict:
    out = {"country": [_h("in")], "external_id": [_h(guest.id)]}
    phone = phone_identity.normalize(guest.phone, "IN")
    if phone:
        out["ph"] = [hashlib.sha256(phone.lstrip("+").encode()).hexdigest()]
    if guest.email and "@" in guest.email:
        out["em"] = [_h(guest.email)]
    return out


def event_for(stay: Stay, guest: Guest, attribution: Optional[LeadAttribution]) -> dict:
    created = stay.created_at if stay.created_at.tzinfo else stay.created_at.replace(tzinfo=timezone.utc)
    ev = {"event_name": "Purchase", "event_time": int(created.timestamp()), "event_id": f"stay:{stay.id}",
          "user_data": user_data(guest),
          "custom_data": {"value": float(stay.total_amount), "currency": (stay.currency or "INR").upper(),
                          "num_items": 1}}
    if attribution is not None and attribution.ctwa_clid:
        ev["action_source"] = "business_messaging"
        ev["messaging_channel"] = "whatsapp"
        ev["user_data"]["ctwa_clid"] = attribution.ctwa_clid
    else:
        ev["action_source"] = "chat" if attribution is not None else "other"
    return ev


def queue_new(db: Session, tenant: Tenant, *, now: Optional[datetime] = None) -> int:
    """Decide every booking of the last 7 days that has no event row yet. Returns how many are pending."""
    now = now or datetime.now(timezone.utc)
    seen = {s for (s,) in db.query(MarketingCapiEvent.stay_id).filter_by(tenant_id=tenant.id)}
    stays = [s for s in db.query(Stay).filter(Stay.tenant_id == tenant.id, Stay.created_at >= now - WINDOW).limit(2000)
             if s.id not in seen]
    ok = consented(db, tenant.id, list({s.guest_id for s in stays}))
    pending = 0
    for s in stays:
        reason = ("cancelled" if s.status == "cancelled" else "no amount" if not s.total_amount
                  else "no marketing consent" if s.guest_id not in ok else None)
        db.add(MarketingCapiEvent(tenant_id=tenant.id, stay_id=s.id, event_id=f"stay:{s.id}",
                                  value=s.total_amount, currency=(s.currency or "INR").upper(),
                                  status="skipped" if reason else "pending", reason=reason))
        pending += 0 if reason else 1
    db.commit()
    return pending


LEAD_EVENTS = ("LeadSubmitted", "QualifiedLead")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def queue_leads(db: Session, tenant: Tenant, *, now: Optional[datetime] = None) -> int:
    """Decide LeadSubmitted / QualifiedLead for click-to-WhatsApp enquiries in Meta's 7-day window. Returns pending."""
    from app.models.inquiry import Inquiry
    from app.services.lead_metrics import qualified_inquiry_ids
    now = now or datetime.now(timezone.utc)
    cutoff = now - WINDOW
    atts = (db.query(LeadAttribution).filter(LeadAttribution.tenant_id == tenant.id, LeadAttribution.ctwa_clid.isnot(None),
                                             LeadAttribution.inquiry_id.isnot(None),
                                             LeadAttribution.created_at >= now - timedelta(days=90)).limit(2000).all())
    if not atts:
        return 0
    inq_ids = list({a.inquiry_id for a in atts})
    inqs = {i.id: i for i in db.query(Inquiry).filter(Inquiry.tenant_id == tenant.id, Inquiry.id.in_(inq_ids))}
    guests = {g.id: g for g in db.query(Guest).filter(Guest.tenant_id == tenant.id, Guest.id.in_({a.guest_id for a in atts}))}
    seen = {(i, n) for i, n in db.query(MarketingCapiEvent.inquiry_id, MarketingCapiEvent.event_name).filter(
        MarketingCapiEvent.tenant_id == tenant.id, MarketingCapiEvent.inquiry_id.in_(inq_ids))}
    qualified = qualified_inquiry_ids(db, tenant.id, inq_ids)
    ok = consented(db, tenant.id, list(guests))
    pending, done = 0, set()
    for a in atts:
        g, inq = guests.get(a.guest_id), inqs.get(a.inquiry_id)
        if g is None or inq is None or a.inquiry_id in done:
            continue
        done.add(a.inquiry_id)
        wanted = []
        lead_at = _aware(g.lead_identified_at)
        if lead_at is not None and lead_at >= cutoff:
            wanted.append(("LeadSubmitted", f"lead:{inq.id}"))
        if inq.id in qualified and (_aware(inq.updated_at) or now) >= cutoff:
            wanted.append(("QualifiedLead", f"qualified:{inq.id}"))
        for name, event_id in wanted:
            if (inq.id, name) in seen:
                continue
            reason = None if g.id in ok else "no marketing consent"
            db.add(MarketingCapiEvent(tenant_id=tenant.id, inquiry_id=inq.id, event_name=name, event_id=event_id,
                                      status="skipped" if reason else "pending", reason=reason,
                                      action_source="business_messaging"))
            pending += 0 if reason else 1
    db.commit()
    return pending


def lead_event(row: MarketingCapiEvent, guest: Guest, attribution: LeadAttribution) -> dict:
    when = _aware(guest.lead_identified_at) if row.event_name == "LeadSubmitted" else _aware(row.created_at)
    return {"event_name": row.event_name, "event_time": int((when or datetime.now(timezone.utc)).timestamp()),
            "event_id": row.event_id, "action_source": "business_messaging", "messaging_channel": "whatsapp",
            "user_data": {**user_data(guest), "ctwa_clid": attribution.ctwa_clid}}


def send_tenant(db: Session, tenant: Tenant, *, writer_factory: Optional[Callable] = None,
                now: Optional[datetime] = None) -> dict:
    settings = ads.get_settings(tenant)
    if not settings["capi_enabled"] or not settings["dataset_id"]:
        return {"sent": 0, "skipped": "off"}
    queue_new(db, tenant, now=now)
    if settings.get("capi_lead_events"):
        queue_leads(db, tenant, now=now)
    rows = (db.query(MarketingCapiEvent).filter(MarketingCapiEvent.tenant_id == tenant.id,
                                                MarketingCapiEvent.status.in_(("pending", "failed")),
                                                MarketingCapiEvent.tries < MAX_TRIES)
            .order_by(MarketingCapiEvent.created_at.asc()).limit(BATCH).all())
    if not rows:
        return {"sent": 0}
    stays = {s.id: s for s in db.query(Stay).filter(Stay.tenant_id == tenant.id,
                                                    Stay.id.in_([r.stay_id for r in rows if r.stay_id]))}
    lead_atts: dict[str, LeadAttribution] = {}
    for a in db.query(LeadAttribution).filter(LeadAttribution.tenant_id == tenant.id, LeadAttribution.ctwa_clid.isnot(None),
                                              LeadAttribution.inquiry_id.in_([r.inquiry_id for r in rows if r.inquiry_id])):
        lead_atts.setdefault(a.inquiry_id, a)
    guests = {g.id: g for g in db.query(Guest).filter(Guest.tenant_id == tenant.id, Guest.id.in_(
        [s.guest_id for s in stays.values()] + [a.guest_id for a in lead_atts.values()]))}
    ok = consented(db, tenant.id, list(guests))                  # consent is re-checked at send time
    atts = {}
    inquiry_ids = [s.inquiry_id for s in stays.values() if s.inquiry_id]
    if inquiry_ids:
        for a in db.query(LeadAttribution).filter(LeadAttribution.tenant_id == tenant.id,
                                                  LeadAttribution.inquiry_id.in_(inquiry_ids)):
            atts.setdefault(a.inquiry_id, a)
    batch, events = [], []
    cutoff = (now or datetime.now(timezone.utc)) - WINDOW
    for r in rows:
        if r.inquiry_id and not r.stay_id:                  # a lead event (studio plan phase 5)
            a = lead_atts.get(r.inquiry_id)
            g = guests.get(a.guest_id) if a else None
            if g is None or g.id not in ok or not settings.get("capi_lead_events"):
                r.status, r.reason = "skipped", ("no marketing consent" if g is not None and g.id not in ok
                                                 else "lead events switched off" if g is not None else "chat changed")
                continue
            ev = lead_event(r, g, a)
            if ev["event_time"] < int(((now or datetime.now(timezone.utc)) - WINDOW).timestamp()):
                r.status, r.reason = "skipped", "too old for Meta"
                continue
            batch.append(r)
            events.append(ev)
            continue
        s = stays.get(r.stay_id)
        g = guests.get(s.guest_id) if s else None
        created = None
        if s is not None:
            created = s.created_at if s.created_at.tzinfo else s.created_at.replace(tzinfo=timezone.utc)
        if s is None or g is None or s.status == "cancelled" or g.id not in ok or created < cutoff:
            r.status, r.reason = "skipped", ("no marketing consent" if g is not None and g.id not in ok
                                             else "too old for Meta" if created is not None and created < cutoff
                                             else "booking changed")
            continue
        ev = event_for(s, g, atts.get(s.inquiry_id))
        r.action_source = ev["action_source"]
        batch.append(r)
        events.append(ev)
    if not events:
        db.commit()
        return {"sent": 0}
    from app.services.marketing_ads_push import _writer
    writer = (writer_factory or _writer)(db, tenant.id)
    try:
        resp = writer.send_events(settings["dataset_id"], events, test_code=settings["capi_test_code"])
    except MetaAdsError as exc:
        for r in batch:
            r.tries, r.status, r.reason = r.tries + 1, "failed", str(exc)[:300]
        db.commit()
        log.warning("marketing_capi_failed", tenant_id=tenant.id, error=str(exc)[:200])
        return {"sent": 0, "error": str(exc)[:200]}
    finally:
        writer.close()
    when = datetime.now(timezone.utc)
    for r in batch:
        r.tries, r.status, r.sent_at, r.reason, r.fbtrace_id = r.tries + 1, "sent", when, None, resp.get("fbtrace_id")
    append_audit(db, tenant_id=tenant.id, action="marketing.capi.sent", actor_user_id=None, target_type="tenant",
                 target_id=tenant.id, payload={"actor": "system", "events": len(batch),
                                               "received": resp.get("events_received"),
                                               "test": bool(settings["capi_test_code"])})
    db.commit()
    return {"sent": len(batch), "received": resp.get("events_received")}


def recent(db: Session, tenant_id: str, limit: int = 50) -> list[dict]:
    rows = (db.query(MarketingCapiEvent).filter_by(tenant_id=tenant_id)
            .order_by(MarketingCapiEvent.created_at.desc()).limit(limit).all())
    return [{"stay_id": r.stay_id, "inquiry_id": r.inquiry_id, "event_name": r.event_name, "status": r.status, "reason": r.reason, "value": float(r.value) if r.value else None,
             "currency": r.currency, "action_source": r.action_source, "sent_at": r.sent_at, "tries": r.tries,
             "created_at": r.created_at} for r in rows]
