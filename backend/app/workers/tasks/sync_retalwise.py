"""
Celery task: sync RentalWise properties, reservations, and guests into HAIP.

Triggered:
  - On first connect (via integrations endpoint background task)
  - Manually via POST /integrations/retalwise/sync
  - Hourly via Celery Beat (sync_retalwise_all_tenants fires at :05 each hour)
"""

from __future__ import annotations
import logging
import re
import uuid as _uuid
from datetime import datetime, timezone
from celery import shared_task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, set_tenant_context
from app.core.encryption import decrypt_credentials
from app.models.integration import Integration
from app.models.property import Property, Stay, BlockedDate
from app.models.guest import Guest
from app.models.base import gen_uuid
from app.services.guest_service import upsert_by_phone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300, name="sync_retalwise")
def sync_retalwise(self, tenant_id: str) -> dict:
    db: Session = SessionLocal()
    try:
        # Must set tenant context BEFORE any tenant-scoped queries (RLS enforcement)
        set_tenant_context(db, tenant_id)

        integration = db.query(Integration).filter_by(
            tenant_id=tenant_id, kind="retalwise"
        ).first()

        if not integration or integration.status != "active":
            return {"status": "skipped", "reason": "not connected"}

        creds = decrypt_credentials(integration.credentials_kms_blob)
        api_token = creds.get("api_token", "")
        username = creds.get("username", creds.get("api_key", ""))
        password = creds.get("password", creds.get("api_secret", ""))

        if not api_token and not username:
            logger.error("RentalWise sync: missing credentials for tenant %s", tenant_id)
            return {"status": "error", "reason": "missing credentials"}

        config = integration.config or {}
        base_url = config.get("base_url", "https://app.rentalwise.io")

        from app.adapters.pms.retalwise import RentalwiseAdapter
        adapter = RentalwiseAdapter(
            username=username, password=password,
            base_url=base_url, api_token=api_token,
        )

        stats = {"properties": 0, "reservations": 0, "guests": 0, "availability_records": 0, "ical_events": 0, "errors": []}

        # ── Sync properties ───────────────────────────────────────────────────
        if config.get("sync_properties", True):
            try:
                properties = adapter.get_properties()
                for p in properties:
                    _upsert_property(db, tenant_id, p)
                    stats["properties"] += 1
                db.commit()
                logger.info("RentalWise: synced %d properties for tenant %s", stats["properties"], tenant_id)
            except Exception as exc:
                logger.error("RentalWise property sync failed: %s", exc)
                stats["errors"].append(f"properties: {exc}")

        # ── Sync guests ───────────────────────────────────────────────────────
        if config.get("sync_guests", True):
            try:
                guests = adapter.get_guests(limit=500)
                for g in guests:
                    if g.get("phone"):
                        upsert_by_phone(
                            db,
                            tenant_id=tenant_id,
                            phone=g["phone"],
                            name=g.get("name"),
                            email=g.get("email"),
                        )
                        stats["guests"] += 1
                db.commit()
            except Exception as exc:
                logger.error("RentalWise guest sync failed: %s", exc)
                stats["errors"].append(f"guests: {exc}")

        # ── Sync reservations ─────────────────────────────────────────────────
        if config.get("sync_reservations", True):
            try:
                reservations = adapter.get_reservations(limit=200)
                for r in reservations:
                    _upsert_stay(db, tenant_id, r)
                    stats["reservations"] += 1
                db.commit()
                logger.info("RentalWise: synced %d reservations for tenant %s", stats["reservations"], tenant_id)
            except Exception as exc:
                logger.error("RentalWise reservation sync failed: %s", exc)
                stats["errors"].append(f"reservations: {exc}")

        # ── Sync availability statuses → BlockedDate records ─────────────────
        if config.get("sync_availability", True):
            try:
                # Sync next 90 days of availability statuses
                from datetime import date
                av_from = date.today().isoformat()
                av_to   = (date.today() + __import__("datetime").timedelta(days=90)).isoformat()
                avail_records = adapter.get_all_availability_statuses_paginated(
                    date_from=av_from, date_to=av_to,
                )
                for av in avail_records:
                    if av.get("status") and av["status"] not in ("available", "booked"):
                        # Only create blocks for non-available, non-booked days
                        # (booked days are already covered by stays)
                        _upsert_availability_block(db, tenant_id, av)
                        stats["availability_records"] += 1
                db.commit()
                logger.info(
                    "RentalWise: synced %d availability blocks for tenant %s",
                    stats["availability_records"], tenant_id
                )
            except Exception as exc:
                logger.error("RentalWise availability sync failed: %s", exc)
                stats["errors"].append(f"availability: {exc}")

        # ── Sync iCal feeds → BlockedDate records ────────────────────────────
        if config.get("sync_ical", False):
            try:
                # Load all RentalWise properties for this tenant
                rw_props = db.query(Property).filter(
                    Property.tenant_id == tenant_id,
                    Property.channel_source == "retalwise",
                ).all()
                for prop in rw_props:
                    rw_id = (prop.hostaway_listing_id or "").replace("rw_", "")
                    if not rw_id:
                        continue
                    try:
                        ical_text = adapter.fetch_property_ical(rw_id)
                        events = adapter.parse_ical_blocks(ical_text, rw_id)
                        for ev in events:
                            _upsert_ical_block(db, tenant_id, prop.id, ev)
                            stats["ical_events"] += 1
                        db.commit()
                    except Exception as exc:
                        logger.warning(
                            "RentalWise iCal sync failed for property %s: %s", rw_id, exc
                        )
                        stats["errors"].append(f"ical_prop_{rw_id}: {exc}")
                logger.info(
                    "RentalWise: synced %d iCal events for tenant %s",
                    stats["ical_events"], tenant_id
                )
            except Exception as exc:
                logger.error("RentalWise iCal sync failed: %s", exc)
                stats["errors"].append(f"ical: {exc}")

        integration.last_health_at = datetime.now(timezone.utc).isoformat()
        if stats["errors"]:
            integration.status = "error"
        db.commit()

        return {"status": "ok", **stats}

    except Exception as exc:
        logger.error("RentalWise sync error for tenant %s: %s", tenant_id, exc)
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


def _slugify(text: str) -> str:
    """Convert a property name to a URL-safe slug."""
    text = text.lower()
    # Replace non-alphanumeric characters (including |, spaces, etc.) with hyphens
    text = re.sub(r"[^a-z0-9]+", "-", text)
    # Strip leading/trailing hyphens
    return text.strip("-") or "property"


def _unique_slug(db: Session, tenant_id: str, base: str, exclude_id: str | None = None) -> str:
    """Return a slug that is unique within the tenant's properties."""
    from app.models.property import Property as Prop
    slug = base
    n = 1
    while True:
        q = db.query(Prop).filter_by(tenant_id=tenant_id, slug=slug)
        if exclude_id:
            q = q.filter(Prop.id != exclude_id)
        if not q.first():
            return slug
        slug = f"{base}-{n}"
        n += 1


def _upsert_property(db: Session, tenant_id: str, p: dict):
    """Create or update a Property row from RentalWise data."""
    external_id = p.get("external_id", "")
    if not external_id:
        return

    # Match on hostaway_listing_id (repurposed as generic pms_listing_id)
    # or fall back to name match within the tenant
    row = (
        db.query(Property)
        .filter_by(tenant_id=tenant_id)
        .filter(Property.hostaway_listing_id == f"rw_{external_id}")
        .first()
    )
    if not row:
        # Try name match to avoid duplicates
        row = db.query(Property).filter_by(
            tenant_id=tenant_id, name=p.get("name", "")
        ).first()

    if not row:
        new_id = str(_uuid.uuid4())
        name = p.get("name") or "Unnamed"
        slug = _unique_slug(db, tenant_id, _slugify(name))
        row = Property(
            id=new_id,
            tenant_id=tenant_id,
            hostaway_listing_id=f"rw_{external_id}",  # prefix to distinguish from Hostaway
            slug=slug,
        )
        db.add(row)
    else:
        row.hostaway_listing_id = f"rw_{external_id}"
        # Backfill slug if missing
        if not getattr(row, "slug", None):
            name = p.get("name") or row.name or "Unnamed"
            row.slug = _unique_slug(db, tenant_id, _slugify(name), exclude_id=row.id)

    row.name = p.get("name") or row.name or "Unnamed"
    row.type = p.get("type") or "villa"
    row.city = p.get("city") or ""
    row.address = p.get("address") or ""
    row.channel_source = "retalwise"
    if p.get("max_guests"):
        row.max_adults = p["max_guests"]
    if p.get("bedrooms"):
        row.bedrooms = p["bedrooms"]
    if p.get("bathrooms"):
        row.bathrooms = p["bathrooms"]
    if p.get("description"):
        row.description = p["description"]


def _upsert_stay(db: Session, tenant_id: str, r: dict):
    """Create or update a Stay row from a RentalWise reservation."""
    external_id = r.get("external_id", "")
    if not external_id:
        return

    # Find guest by phone — required (guest_id is NOT NULL)
    guest = None
    if r.get("guest_phone"):
        try:
            guest = upsert_by_phone(
                db,
                tenant_id=tenant_id,
                phone=r["guest_phone"],
                name=r.get("guest_name"),
                email=r.get("guest_email"),
            )
        except Exception:
            pass

    if not guest:
        # Cannot create Stay without a guest — skip
        logger.debug("RentalWise: skipping reservation %s — no guest phone", external_id)
        return

    # Resolve property — property_id is NOT NULL
    property_row = None
    rw_prop_id = r.get("property_id", "")
    if rw_prop_id:
        property_row = (
            db.query(Property)
            .filter_by(tenant_id=tenant_id)
            .filter(Property.hostaway_listing_id == f"rw_{rw_prop_id}")
            .first()
        )

    if not property_row:
        # Cannot create Stay without a property — skip
        logger.debug("RentalWise: skipping reservation %s — property not found", external_id)
        return

    # Use hostaway_booking_id to store the RentalWise reservation ID (prefixed)
    rw_booking_id = f"rw_{external_id}"
    row = db.query(Stay).filter_by(
        tenant_id=tenant_id,
        hostaway_booking_id=rw_booking_id,
    ).first()

    if not row:
        row = Stay(
            id=str(_uuid.uuid4()),
            tenant_id=tenant_id,
            hostaway_booking_id=rw_booking_id,
            guest_id=guest.id,
            property_id=property_row.id,
        )
        db.add(row)
    else:
        row.guest_id = guest.id
        row.property_id = property_row.id

    row.check_in = r.get("check_in") or ""
    row.check_out = r.get("check_out") or ""
    row.status = r.get("status", "confirmed")
    row.channel_source = r.get("channel", "rentalwise")
    row.total_amount = r.get("total_amount", 0)
    row.currency = r.get("currency", "INR")


# ── Availability-status block upsert ─────────────────────────────────────────

# Map Rentalwise availability-status slugs → BlockedDate reason values
_STATUS_TO_REASON: dict[str, str] = {
    "blocked":             "other",
    "maintenance":         "maintenance",
    "owner_use":           "owner_use",
    "owner":               "owner_use",
    "personal":            "personal",
    "hold":                "other",
    "offline_booking":     "offline_booking",
    "unavailable":         "other",
}


def _upsert_availability_block(db: Session, tenant_id: str, av: dict):
    """
    Create or update a single-day BlockedDate from a Rentalwise availability-status record.
    Rentalwise returns one record per day, so each block spans [date, date+1).
    """
    av_date = av.get("date", "")
    if not av_date or len(av_date) < 10:
        return

    status = (av.get("status") or "").lower()
    reason = _STATUS_TO_REASON.get(status, "other")
    prop_rw_id = av.get("property_id", "")
    if not prop_rw_id:
        return

    # Look up the HAIP Property by its RentalWise ID tag
    prop = (
        db.query(Property)
        .filter_by(tenant_id=tenant_id)
        .filter(Property.hostaway_listing_id == f"rw_{prop_rw_id}")
        .first()
    )
    if not prop:
        return

    # External ID: "rw_avail_{property_rw_id}_{date}" — one block per day
    external_marker = f"rw_avail_{prop_rw_id}_{av_date}"
    block_end = _next_day(av_date)

    existing = (
        db.query(BlockedDate)
        .filter_by(tenant_id=tenant_id, property_id=prop.id)
        .filter(BlockedDate.notes == external_marker)
        .first()
    )
    if existing:
        existing.blocked_from = av_date
        existing.blocked_to   = block_end
        existing.reason       = reason
        existing.is_active    = True
    else:
        db.add(BlockedDate(
            id           = gen_uuid(),
            tenant_id    = tenant_id,
            property_id  = prop.id,
            blocked_from = av_date,
            blocked_to   = block_end,
            reason       = reason,
            notes        = external_marker,
            is_active    = True,
        ))


def _upsert_ical_block(db: Session, tenant_id: str, property_id: str, ev: dict):
    """Create or update a BlockedDate from a parsed iCal VEVENT."""
    external_uid = ev.get("uid") or ev.get("external_id", "")
    if not external_uid:
        return

    dtstart = ev.get("dtstart", "")
    dtend   = ev.get("dtend", "")
    if not dtstart or not dtend:
        return

    existing = (
        db.query(BlockedDate)
        .filter_by(tenant_id=tenant_id, property_id=property_id)
        .filter(BlockedDate.notes == f"ical:{external_uid}")
        .first()
    )
    if existing:
        existing.blocked_from = dtstart
        existing.blocked_to   = dtend
        existing.is_active    = True
    else:
        summary = ev.get("summary", "")
        reason = "other"
        sl = summary.lower()
        if "maintenance" in sl:
            reason = "maintenance"
        elif "owner" in sl or "personal" in sl:
            reason = "personal"
        elif "booking" in sl or "reservation" in sl:
            reason = "offline_booking"

        db.add(BlockedDate(
            id           = gen_uuid(),
            tenant_id    = tenant_id,
            property_id  = property_id,
            blocked_from = dtstart,
            blocked_to   = dtend,
            reason       = reason,
            notes        = f"ical:{external_uid}",
            is_active    = True,
        ))


def _next_day(date_str: str) -> str:
    """Return the YYYY-MM-DD string for date_str + 1 day."""
    from datetime import date, timedelta
    try:
        d = date.fromisoformat(date_str)
        return (d + timedelta(days=1)).isoformat()
    except ValueError:
        return date_str
