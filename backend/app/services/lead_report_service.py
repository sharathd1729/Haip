"""The leads report: one row per enquiry, built on the CRM as it stands.

Backs the "Leads" report in Reports. It reads what Leads360 shows -- the
tenant's own stage catalog, the assigned owner, the AI summary -- so a
downloaded list agrees with what the team sees on screen.

Read-only, and no LLM: ai_summary and ai_next_action are returned as stored.

Rules worth knowing:
  * Who: the Leads list's own rule (leads.py _visibility_scope): owners and managers see the team, every other role their
    own leads PLUS unassigned ones (it used to be "own only", so a report disagreed with the list).
  * Guest enquiries only unless "Lead type" picks others (lead_types): b2b / partner are not guest leads.
  * Dates are IST calendar days, inclusive at both ends. "2026-09-01" to
    "2026-09-30" is the whole of September as the team lived it.
  * Nothing is silently cut short. `total` is how many enquiries match;
    `truncated` says so if the row ceiling stopped the list before the end.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Session, contains_eager, joinedload

from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.inquiry import Inquiry, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.models.user import User
from app.services import lead_paid, lead_types
from app.services.date_presets import IST, clean_date_str, ist_range_to_utc

# One download never holds more than this. The report says so when it hits it.
MAX_ROWS = 50_000
_IN_CHUNK = 500

# Every channel an enquiry can arrive on, in the words the team uses, and the
# channel group it belongs to. A caller who left a number is a lead exactly
# like a chat is -- the IVR is a first-class source here.
SOURCE_LABELS: dict[str, tuple[str, str]] = {
    "meta_ig": ("Instagram DM", "Instagram"),
    "meta_fb": ("Facebook", "Facebook"),
    "click_to_wa": ("WhatsApp (ad click)", "WhatsApp"),
    "wa_direct": ("WhatsApp", "WhatsApp"),
    "web_chat": ("Website chat", "Website"),
    "website": ("Website form", "Website"),
    "google": ("Google", "Website"),
    "email": ("Email", "Email"),
    "organic_call": ("Organic call", "Call"),
    "phone": ("Phone call", "Call"),
    "inbound_call": ("Phone call (IVR)", "Call"),
    "outbound_call": ("Outbound call", "Call"),
    "walk_in": ("Walk-in", "Walk-in"),
    "referral": ("Referral", "Referral"),
    "travel_agent": ("Travel agent", "Agent"),
    "channel_manager": ("Channel manager", "OTA"),
    "ota_airbnb": ("Airbnb", "OTA"),
    "ota_booking": ("Booking.com", "OTA"),
    "ota_vrbo": ("Vrbo", "OTA"),
    "ota_mmt": ("MakeMyTrip", "OTA"),
    "ota_goibibo": ("Goibibo", "OTA"),
}

# (key, label, on by default). Keys that existed before the rebuild keep their
# names so a saved column choice still works.
FIELDS: list[tuple[str, str, bool]] = [
    ("created_at", "Enquiry date (IST)", True),
    ("guest_name", "Name", True),
    ("guest_phone", "Phone", True),
    ("guest_email", "Email", False),
    ("instagram", "Instagram (handle or ID)", False),
    ("instagram_id", "Instagram user ID", False),
    ("source", "Source", True),
    ("channel", "Channel", False),
    ("stage", "Stage", True),
    ("owner", "Owner", True),
    ("check_in", "Check-in", True),
    ("check_out", "Check-out", True),
    ("nights", "Nights", False),
    ("adults", "Adults", False),
    ("children", "Children", False),
    ("pax", "Guests (total)", False),
    ("budget", "Budget", False),
    ("quoted_amount", "Quoted amount", True),
    ("occasion", "Occasion", False),
    ("route", "Trip / route", False),
    ("property_name", "Property", False),
    ("guest_city", "Guest city", False),
    ("special_requests", "Special requests", False),
    ("last_touch", "Last touch (IST)", False),
    ("ai_summary", "Remarks (AI summary)", True),
    ("next_step", "Suggested next step", False),
    ("lost_reason", "Lost reason", False),
    ("tags", "Tags", False),
    ("qualification", "Qualification", False),
    ("lead_type", "Lead type", True),
    ("came_from", "Came from (paid ad / organic)", False),
    ("validation", "Valid enquiry? (reviewed by a person)", False),
]

# type "multiselect"/"select" with an "@name" options value are filled in per
# workspace by resolve_options(): stages and owners belong to the tenant, so
# they can't be a fixed list.
FILTERS: list[dict[str, Any]] = [
    {"key": "has_phone", "label": "Shared a phone number", "type": "boolean"},
    {"key": "has_email", "label": "Shared an email", "type": "boolean"},
    {"key": "has_instagram", "label": "Has an Instagram ID", "type": "boolean"},
    {"key": "has_dates", "label": "Gave travel dates", "type": "boolean"},
    {"key": "has_budget", "label": "Gave a budget", "type": "boolean"},
    {"key": "sources", "label": "Source", "type": "multiselect", "options": "@sources"},
    {"key": "stages", "label": "Stage", "type": "multiselect", "options": "@stages"},
    {"key": "owner", "label": "Owner", "type": "select", "options": "@owners"},
    {"key": "include_unqualified", "label": "Include spam / unqualified", "type": "boolean"},
    {"key": "lead_types", "label": "Lead type (default: guests)", "type": "multiselect", "options": "@lead_types"},
    {"key": "came_from", "label": "Came from", "type": "select", "options": "@came_from"},
]

CATALOG_ENTRY: dict[str, Any] = {
    "id": "inquiries",
    "name": "Leads",
    "description": (
        "One row per enquiry: who asked, on which channel, who owns it, where it "
        "stands, what they want, and the AI's note on it."
    ),
    "icon": "zap",
    "category": "CRM",
    "fields": [{"key": k, "label": lbl, "default": d} for k, lbl, d in FIELDS],
    "filters": FILTERS,
}


@dataclass
class LeadFilters:
    date_from: Optional[str] = None      # YYYY-MM-DD, IST, inclusive
    date_to: Optional[str] = None
    has_phone: Optional[bool] = None
    has_email: Optional[bool] = None
    has_instagram: Optional[bool] = None
    has_dates: Optional[bool] = None
    has_budget: Optional[bool] = None
    sources: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)      # pipeline stage keys
    owner: Optional[str] = None                          # user id, or "unassigned"
    include_unqualified: bool = False
    lead_types: list[str] = field(default_factory=list)  # empty = guests only
    came_from: Optional[str] = None                      # paid | organic | unknown (lead_paid)


@dataclass
class LeadReport:
    rows: list[dict[str, Any]]
    total: int
    truncated: bool


def _tri(value: Any) -> Optional[bool]:
    """'' / None = no filter; true/false strings and bools = yes / no."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value).split(",") if p.strip()]


def parse_filters(
    raw: Optional[dict[str, Any]], date_from: Optional[str], date_to: Optional[str],
) -> LeadFilters:
    """Turn the loose filter dict the API receives into a checked LeadFilters.
    Raises ValueError on a value that can't be honoured, so the caller answers
    422 instead of quietly returning the wrong list."""
    raw = raw or {}
    sources = _as_list(raw.get("sources", raw.get("source")))
    unknown = [s for s in sources if s not in SOURCE_LABELS]
    if unknown:
        raise ValueError(f"Unknown source: {', '.join(unknown)}")
    types = _as_list(raw.get("lead_types", raw.get("lead_type")))
    bad = [t for t in types if t not in lead_types.LEAD_TYPES]
    if bad:
        raise ValueError(f"Unknown lead type: {', '.join(bad)}")
    came_from = (str(raw.get("came_from") or "").strip() or None)
    if came_from and came_from not in lead_paid.VALUES:
        raise ValueError("Came from must be paid, organic or unknown")
    return LeadFilters(
        date_from=clean_date_str(date_from),
        date_to=clean_date_str(date_to),
        has_phone=_tri(raw.get("has_phone")),
        has_email=_tri(raw.get("has_email")),
        has_instagram=_tri(raw.get("has_instagram")),
        has_dates=_tri(raw.get("has_dates")),
        has_budget=_tri(raw.get("has_budget")),
        sources=sources,
        stages=_as_list(raw.get("stages", raw.get("stage"))),
        owner=(str(raw["owner"]).strip() or None) if raw.get("owner") else None,
        include_unqualified=bool(_tri(raw.get("include_unqualified"))),
        lead_types=types,
        came_from=came_from,
    )


def resolve_options(db: Session, tenant_id: str) -> dict[str, list[dict[str, str]]]:
    """The choices behind the '@sources' / '@stages' / '@owners' filters."""
    stages = (
        db.query(PipelineStage)
        .filter(PipelineStage.tenant_id == tenant_id)
        .order_by(PipelineStage.order, PipelineStage.key)
        .all()
    )
    users = (
        db.query(User)
        .filter(User.tenant_id == tenant_id, User.is_active.is_(True), User.is_deleted.is_(False))
        .order_by(User.name)
        .all()
    )
    return {
        "@sources": [{"value": k, "label": v[0]} for k, v in SOURCE_LABELS.items()],
        "@stages": [{"value": s.key, "label": s.label} for s in stages],
        "@owners": [{"value": "unassigned", "label": "Unassigned"}]
        + [{"value": u.id, "label": u.name or u.email} for u in users],
        "@lead_types": [{"value": k, "label": lead_types.LABELS[k]} for k in lead_types.LEAD_TYPES],
        "@came_from": [{"value": "paid", "label": "Paid ad"}, {"value": "organic", "label": "Organic"},
                       {"value": "unknown", "label": "Unknown"}],
    }


def _ist_text(dt: Any) -> str:
    if not dt:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return dt[:16].replace("T", " ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%Y-%m-%d %H:%M")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:2000]     # Excel refuses a cell over 32,767 characters


def _query(db: Session, tenant_id: str, f: LeadFilters, scope_user_id: Optional[str]):
    q = (
        db.query(Inquiry)
        .join(Guest, and_(Guest.id == Inquiry.guest_id, Guest.tenant_id == tenant_id))
        .outerjoin(
            PipelineStage,
            and_(PipelineStage.id == Inquiry.stage_id, PipelineStage.tenant_id == tenant_id),
        )
        .filter(
            Inquiry.tenant_id == tenant_id,
            Guest.is_sample.is_(False),
            Guest.deletion_state != "deleted",
        )
    )

    if f.date_from or f.date_to:
        today = datetime.now(IST).date().isoformat()
        _, _, start_dt, end_dt = ist_range_to_utc(f.date_from or "2000-01-01", f.date_to or today)
        q = q.filter(Inquiry.created_at >= start_dt, Inquiry.created_at <= end_dt)

    phone_len = func.length(func.trim(func.coalesce(Guest.phone, "")))
    if f.has_phone is True:
        q = q.filter(phone_len > 0)
    elif f.has_phone is False:
        q = q.filter(phone_len == 0)

    email_len = func.length(func.trim(func.coalesce(Guest.email, "")))
    if f.has_email is True:
        q = q.filter(email_len > 0)
    elif f.has_email is False:
        q = q.filter(email_len == 0)

    has_ig = exists().where(and_(
        GuestIdentity.guest_id == Guest.id,
        GuestIdentity.tenant_id == tenant_id,
        GuestIdentity.identity_type == "instagram_user_id",
    ))
    if f.has_instagram is True:
        q = q.filter(has_ig)
    elif f.has_instagram is False:
        q = q.filter(~has_ig)

    dates_len = func.length(func.trim(func.coalesce(Inquiry.check_in, "")))
    if f.has_dates is True:
        q = q.filter(dates_len > 0)
    elif f.has_dates is False:
        q = q.filter(dates_len == 0)

    if f.has_budget is True:
        q = q.filter(Inquiry.budget.isnot(None), Inquiry.budget > 0)
    elif f.has_budget is False:
        q = q.filter((Inquiry.budget.is_(None)) | (Inquiry.budget <= 0))

    if f.sources:
        q = q.filter(Inquiry.source.in_([InquirySource(s) for s in f.sources]))
    if f.stages:
        q = q.filter(PipelineStage.key.in_(f.stages))

    if scope_user_id:
        # An agent's report is the Leads list's rule: their own leads plus unassigned ones, whatever the request says
        # (asking for "unassigned" narrows it to those).
        q = q.filter(Inquiry.assigned_to.is_(None) if f.owner == "unassigned"
                     else or_(Inquiry.assigned_to == scope_user_id, Inquiry.assigned_to.is_(None)))
    elif f.owner == "unassigned":
        q = q.filter(Inquiry.assigned_to.is_(None))
    elif f.owner:
        q = q.filter(Inquiry.assigned_to == f.owner)

    if not f.include_unqualified:
        q = q.filter(Inquiry.qualification_status != "unqualified")
    if f.lead_types:
        wanted = Inquiry.lead_type.in_(f.lead_types)
        q = q.filter(or_(wanted, Inquiry.lead_type.is_(None)) if lead_types.GUEST in f.lead_types else wanted)
    else:
        q = q.filter(lead_types.is_guest_sql(Inquiry.lead_type))
    if f.came_from:
        q = q.filter(lead_paid.filter_sql(db, tenant_id, f.came_from))
    return q


def _instagram_ids(db: Session, tenant_id: str, guest_ids: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for i in range(0, len(guest_ids), _IN_CHUNK):
        chunk = guest_ids[i:i + _IN_CHUNK]
        for row in db.query(GuestIdentity).filter(
            GuestIdentity.tenant_id == tenant_id,
            GuestIdentity.guest_id.in_(chunk),
            GuestIdentity.identity_type == "instagram_user_id",
        ):
            found.setdefault(row.guest_id, row.identity_value)
    return found


def _nights(inq: Inquiry) -> Any:
    if not (inq.check_in and inq.check_out):
        return ""
    try:
        return (datetime.fromisoformat(inq.check_out) - datetime.fromisoformat(inq.check_in)).days
    except ValueError:
        return ""


def _validation_text(inq: Inquiry) -> str:
    if not inq.validation_status:
        return "Not reviewed"
    checks = [label for label, ok in (("dates confirmed", inq.validation_dates_confirmed), ("budget fits", inq.validation_budget_fits),
                                      ("clear intent", inq.validation_clear_intent)) if ok]
    return ("Valid" if inq.validation_status == "valid" else "Not valid") + (f" ({', '.join(checks)})" if checks else "")


def _row(inq: Inquiry, ig_ids: dict[str, str], came: Optional[dict[str, str]] = None) -> dict[str, Any]:
    guest = inq.guest
    ai = inq.ai_analysis if isinstance(inq.ai_analysis, dict) else {}
    src = inq.source.value if hasattr(inq.source, "value") else (inq.source or "")
    label, channel = SOURCE_LABELS.get(src, (src.replace("_", " ").title() if src else "Unknown", ""))
    name = (guest.name if guest else "") or ""
    ig_id = ig_ids.get(inq.guest_id, "")
    return {
        "created_at": _ist_text(inq.created_at),
        "guest_name": _clean(name),
        "guest_phone": _clean(guest.phone if guest else ""),
        "guest_email": _clean(guest.email if guest else ""),
        "instagram": _clean(name if name.startswith("@") else ig_id),
        "instagram_id": _clean(ig_id),
        "source": label,
        "channel": channel,
        "stage": _clean(inq.pipeline_stage.label if inq.pipeline_stage else (inq.stage.value if inq.stage else "")),
        "owner": _clean(inq.assigned_user.name if inq.assigned_user else ""),
        "check_in": _clean(inq.check_in),
        "check_out": _clean(inq.check_out),
        "nights": _nights(inq),
        "adults": inq.adults or "",
        "children": inq.children or "",
        "pax": ((inq.adults or 0) + (inq.children or 0)) or "",
        "budget": float(inq.budget) if inq.budget else "",
        "quoted_amount": float(inq.quoted_amount) if inq.quoted_amount else "",
        "occasion": _clean(inq.occasion),
        "route": _clean(inq.route_mentioned),
        "property_name": _clean(inq.property.name if inq.property else ""),
        "guest_city": _clean(guest.city if guest else ""),
        "special_requests": _clean(inq.special_requests),
        "last_touch": _ist_text(inq.updated_at),
        "ai_summary": _clean(inq.ai_summary),
        "next_step": _clean(inq.ai_next_action or ai.get("next_action")),
        "lost_reason": _clean(inq.lost_reason.value if hasattr(inq.lost_reason, "value") else inq.lost_reason),
        "tags": ", ".join(str(t) for t in (inq.tags or [])),
        "qualification": _clean(inq.qualification_status),
        "lead_type": lead_types.LABELS.get(inq.lead_type or lead_types.GUEST, inq.lead_type),
        "came_from": {"paid": "Paid ad", "organic": "Organic"}.get((came or {}).get(inq.id), "Unknown"),
        "validation": _validation_text(inq),
    }


def build_lead_report(
    db: Session,
    tenant_id: str,
    filters: LeadFilters,
    fields: list[str],
    *,
    scope_user_id: Optional[str] = None,
    limit: int = MAX_ROWS,
) -> LeadReport:
    """Rows for the chosen columns, newest first. `limit` caps the rows
    returned (previews ask for a handful); `total` is always the full count."""
    cap = max(1, min(limit, MAX_ROWS))
    q = _query(db, tenant_id, filters, scope_user_id)
    total = q.with_entities(func.count(Inquiry.id)).order_by(None).scalar() or 0

    inquiries = (
        q.options(
            contains_eager(Inquiry.guest),
            contains_eager(Inquiry.pipeline_stage),
            joinedload(Inquiry.assigned_user),
            joinedload(Inquiry.property),
        )
        # id breaks ties so paging and re-runs always give the same order.
        .order_by(Inquiry.created_at.desc(), Inquiry.id)
        .limit(cap)
        .all()
    )
    ig_ids = _instagram_ids(db, tenant_id, list({i.guest_id for i in inquiries if i.guest_id}))
    came = {}
    if "came_from" in fields:
        for i in range(0, len(inquiries), _IN_CHUNK):
            came.update(lead_paid.classify(db, tenant_id, inquiries[i:i + _IN_CHUNK]))
    rows = []
    for inq in inquiries:
        full = _row(inq, ig_ids, came)
        rows.append({k: full[k] for k in fields if k in full})
    return LeadReport(rows=rows, total=total, truncated=total > len(rows) and cap >= MAX_ROWS)
