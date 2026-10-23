"""The automatic valid-lead rule (sales meetings 22-23 Oct 2026; KPI catalogue D-28). A workspace setting, owner/manager,
audited; OFF by default (then nothing changes: reports keep the person's review + the pipeline stage).

``brand_config.lead_validity`` = {
    enabled:           bool (default False)
    require_name:      a real name (not a placeholder, not a phone number; guest_names.real_name)
    require_phone:     a usable phone number (the person is a lead: guests.lead_identified_at, or a phone on the guest)
    require_check_in:  a readable check-in date. Default False: genuine leads (an organic call) often have no date yet, so a
                       missing date is a NOTE ("No check-in date yet", a follow-up hint), never an invalid reason
    allowed_locations: e.g. ["Bengaluru", "Bangalore"]; compared case/space/punctuation-insensitively. Empty = no check.
    require_location:  when True an UNKNOWN location is invalid ("No location"); default False = a note. A KNOWN location
                       outside the list is always invalid ("Location: Hyderabad (not Bengaluru)").
    location_field:    where the guest's starting city lives: ``guest_location`` (DEFAULT; inquiries.guest_location,
                       migration 171: the origin of a chat-extracted "A to B" route fills it when empty, the lead page edits
                       it) | ``pickup`` (inquiries.custom_fields["pickup"], the pickup point typed on the lead page) |
                       ``guest_city`` (guests.city, a person-level field). Chosen default: guest_location, because pickup is
                       a street-level point ("Whitefield") and guests.city is never filled from chats.
}

evaluate(...)  -> {auto_valid True|False|None (rule off), reasons [...], notes [...], location}
effective(...) -> the ONE validity everything shows and counts: a PERSON's review (lead_review_service, migration 169)
                  wins; else the rule (when on); else None (not reviewed). B2B / partner enquiries are never valid guest
                  leads, whatever the review says.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.services import lead_types
from app.services.guest_names import real_name

KEY = "lead_validity"
LOCATION_FIELDS = ("guest_location", "pickup", "guest_city")
DEFAULTS = {"enabled": False, "require_name": True, "require_phone": True, "require_check_in": False,
            "require_location": False, "allowed_locations": [], "location_field": "guest_location"}
VALUES = ("valid", "invalid", "not_reviewed")
NOTE_NO_DATE = "No check-in date yet"
NOTE_NO_LOCATION = "Location not known yet"


def settings_of(tenant) -> dict:
    raw = ((getattr(tenant, "brand_config", None) or {}).get(KEY) or {})
    out = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    out["allowed_locations"] = [str(x).strip() for x in (out.get("allowed_locations") or []) if str(x).strip()][:20]
    if out["location_field"] not in LOCATION_FIELDS:
        out["location_field"] = "guest_location"
    for k in ("enabled", "require_name", "require_phone", "require_check_in", "require_location"):
        out[k] = bool(out[k])
    return out


def canon(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def location_of(inquiry, guest, field: str) -> Optional[str]:
    if field == "pickup":
        v = (inquiry.custom_fields or {}).get("pickup") if isinstance(inquiry.custom_fields, dict) else None
    elif field == "guest_city":
        v = getattr(guest, "city", None) if guest is not None else None
    else:
        v = inquiry.guest_location
    v = (str(v).strip() if v else "") or None
    return v[:100] if v else None


def _date(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _has_phone(guest) -> bool:
    if guest is None:
        return False
    phone = (guest.phone or "").strip()
    return bool(guest.lead_identified_at) or (bool(phone) and not phone.startswith("DELETED_") and
                                             sum(ch.isdigit() for ch in phone) >= 10)


def evaluate(inquiry, guest, cfg: dict) -> dict:
    """The rule on one enquiry. Pure (reads the rows it is given)."""
    location = location_of(inquiry, guest, cfg["location_field"])
    if not cfg["enabled"]:
        return {"auto_valid": None, "reasons": [], "notes": [], "location": location}
    reasons, notes = [], []
    if not lead_types.is_guest(inquiry.lead_type):
        reasons.append(f"{lead_types.LABELS.get(inquiry.lead_type, 'Not a guest')} enquiry, not a guest lead")
    if cfg["require_name"] and not real_name(guest.name if guest else None):
        reasons.append("No name")
    if cfg["require_phone"] and not _has_phone(guest):
        reasons.append("No phone")
    if _date(inquiry.check_in) is None:
        (reasons if cfg["require_check_in"] else notes).append("No check-in date" if cfg["require_check_in"] else NOTE_NO_DATE)
    allowed = cfg["allowed_locations"]
    if allowed:
        if location is None:
            (reasons if cfg["require_location"] else notes).append("No location" if cfg["require_location"] else NOTE_NO_LOCATION)
        elif canon(location) not in {canon(a) for a in allowed}:
            reasons.append(f"Location: {location} (not {allowed[0]})")
    return {"auto_valid": not reasons, "reasons": reasons, "notes": notes, "location": location}


def effective(inquiry, auto: dict) -> dict:
    """{status valid|invalid|None, source person|rule|None}. The person's review wins; B2B/partner is never valid."""
    if not lead_types.is_guest(inquiry.lead_type):
        return {"status": "invalid", "source": "type"}
    if inquiry.validation_status in ("valid", "invalid"):
        return {"status": inquiry.validation_status, "source": "person"}
    if auto.get("auto_valid") is None:
        return {"status": None, "source": None}
    return {"status": "valid" if auto["auto_valid"] else "invalid", "source": "rule"}


def view(inquiry, guest, cfg: dict) -> dict:
    """What the lead page / list card shows: the rule's answer and the effective one."""
    auto = evaluate(inquiry, guest, cfg)
    eff = effective(inquiry, auto)
    return {"enabled": cfg["enabled"], "auto_valid": auto["auto_valid"], "reasons": auto["reasons"], "notes": auto["notes"],
            "location": auto["location"], "location_field": cfg["location_field"], "status": eff["status"], "source": eff["source"]}


def classify_many(db: Session, tenant_id: str, inquiries: list, cfg: Optional[dict] = None) -> dict:
    """inquiry id -> view(), guests fetched in one query."""
    from app.models.guest import Guest
    from app.models.tenant import Tenant
    if cfg is None:
        cfg = settings_of(db.query(Tenant).filter_by(id=tenant_id).first())
    ids = list({i.guest_id for i in inquiries if i.guest_id})
    guests = {g.id: g for g in db.query(Guest).filter(Guest.tenant_id == tenant_id, Guest.id.in_(ids)).all()} if ids else {}
    return {i.id: view(i, guests.get(i.guest_id), cfg) for i in inquiries}


def ids_matching(db: Session, tenant_id: str, value: str) -> set:
    """Enquiry ids whose EFFECTIVE validity is ``value`` (valid | invalid), or with no person's review (not_reviewed).
    The rule is evaluated in Python (the name test is not portable SQL), over the light columns of every enquiry."""
    from app.models.inquiry import Inquiry
    if value not in VALUES:
        raise ValueError("validity must be valid, invalid or not_reviewed")
    if value == "not_reviewed":
        return {i for (i,) in db.query(Inquiry.id).filter(Inquiry.tenant_id == tenant_id, Inquiry.validation_status.is_(None))}
    from sqlalchemy.orm import load_only
    rows = (db.query(Inquiry).options(load_only(Inquiry.id, Inquiry.guest_id, Inquiry.lead_type, Inquiry.validation_status,
                                                Inquiry.check_in, Inquiry.guest_location, Inquiry.custom_fields))
            .filter(Inquiry.tenant_id == tenant_id).all())
    views = classify_many(db, tenant_id, rows)
    return {i for i, v in views.items() if v["status"] == value}


def check_value(value: Optional[str]) -> Optional[str]:
    if value and value not in VALUES:
        raise ValueError("validity must be valid, invalid or not_reviewed")
    return value or None


def put_settings(db: Session, tenant, user, body: dict, actor: Optional[str] = None) -> dict:
    """Owner/manager (or a script: user None + ``actor``). Audited ``lead_validity.settings_changed`` with before/after.
    Flushes; caller commits."""
    from app.core.audit import append_audit
    before = settings_of(tenant)
    merged = {**before, **{k: v for k, v in body.items() if k in DEFAULTS and v is not None}}
    cfg = dict(tenant.brand_config or {})
    cfg[KEY] = merged
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    after = settings_of(tenant)
    payload = {"before": before, "after": after, **({"actor": actor} if actor else {})}
    append_audit(db, tenant_id=tenant.id, action="lead_validity.settings_changed", actor_user_id=getattr(user, "id", None),
                 target_type="tenant", target_id=tenant.id, payload=payload)
    return after


def origin_of_route(route: Optional[str]) -> Optional[str]:
    """'Bangalore to Coorg' -> 'Bangalore'; 'from Bengaluru to Mysuru' -> 'Bengaluru'; anything else -> None."""
    text = (route or "").strip()
    m = re.match(r"^(?:from\s+)?(?P<origin>[A-Za-z][A-Za-z .'-]{1,60}?)\s+(?:to|->|-|–)\s+\S", text, re.I)
    if not m:
        return None
    origin = m.group("origin").strip(" .-")
    return origin[:100] if origin and len(origin) >= 3 else None
