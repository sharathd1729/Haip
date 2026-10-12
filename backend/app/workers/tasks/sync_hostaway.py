"""
Celery task: sync Hostaway listings, reservations, and guests into HAIP.

Triggered:
  - On first connect (background task in integrations endpoint)
  - Manually via POST /integrations/hostaway/sync
  - Hourly via Celery Beat (sync_hostaway_all_tenants fires at :10 each hour)
"""

from __future__ import annotations
import asyncio
import logging
import uuid as _uuid
from datetime import datetime, timezone
from celery import shared_task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.encryption import decrypt_credentials
from app.models.integration import Integration
from app.models.property import Property, Stay
from app.services.guest_service import upsert_by_phone

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run one of the adapter's coroutines from this synchronous Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(bind=True, max_retries=3, default_retry_delay=300, name="sync_hostaway")
def sync_hostaway(self, tenant_id: str) -> dict:
    db: Session = SessionLocal()
    try:
        integration = db.query(Integration).filter_by(
            tenant_id=tenant_id, kind="hostaway"
        ).first()

        if not integration or integration.status != "active":
            return {"status": "skipped", "reason": "not connected"}

        creds = decrypt_credentials(integration.credentials_kms_blob)
        account_id = creds.get("account_id", "")
        api_secret = creds.get("api_secret", "")

        if not account_id or not api_secret:
            logger.error("Hostaway sync: missing credentials for tenant %s", tenant_id)
            return {"status": "error", "reason": "missing credentials"}

        from app.adapters.pms.hostaway import HostawayAdapter
        adapter = HostawayAdapter(account_id=account_id, api_secret=api_secret)

        stats = {"listings": 0, "reservations": 0, "skipped": 0, "errors": []}

        # ── Sync listings → properties ─────────────────────────────────────────
        try:
            listings = _run_async(adapter.get_listings())
            for listing in listings:
                _upsert_property(db, tenant_id, listing)
                stats["listings"] += 1
            db.commit()
            logger.info("Hostaway: synced %d listings for tenant %s", stats["listings"], tenant_id)
        except Exception as exc:
            db.rollback()   # a failed flush leaves the session unusable for the reservation step
            logger.error("Hostaway listing sync failed: %s", exc)
            stats["errors"].append(f"listings: {exc}")

        # ── Sync reservations → stays ──────────────────────────────────────────
        try:
            offset = 0
            while True:
                batch = _run_async(adapter.get_reservations(limit=100, offset=offset))
                if not batch:
                    break
                for res in batch:
                    # Commit per reservation (guest resolution commits on its own, so a savepoint
                    # would not hold): one bad row is rolled back and skipped, not the whole batch.
                    try:
                        outcome = _upsert_stay(db, tenant_id, res)
                        db.commit()
                    except Exception as row_exc:  # noqa: BLE001
                        db.rollback()
                        logger.error("Hostaway: reservation %s failed: %s", res.get("id"), row_exc)
                        stats["errors"].append(f"reservation {res.get('id')}: {row_exc}")
                        continue
                    stats["reservations" if outcome == "synced" else "skipped"] += 1
                db.commit()
                if len(batch) < 100:
                    break
                offset += 100
            logger.info("Hostaway: synced %d reservations for tenant %s", stats["reservations"], tenant_id)
        except Exception as exc:
            db.rollback()
            logger.error("Hostaway reservation sync failed: %s", exc)
            stats["errors"].append(f"reservations: {exc}")

        integration.last_health_at = datetime.now(timezone.utc).isoformat()
        if stats["errors"]:
            integration.status = "error"
        db.commit()

        return {"status": "ok", **stats}

    except Exception as exc:
        logger.error("Hostaway sync error for tenant %s: %s", tenant_id, exc)
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


def _upsert_property(db: Session, tenant_id: str, listing: dict):
    external_id = str(listing.get("id", ""))
    if not external_id:
        return

    row = db.query(Property).filter_by(
        tenant_id=tenant_id, hostaway_listing_id=external_id
    ).first()
    name = listing.get("name", "") or (row.name if row else "") or "Unnamed"
    if not row:
        # slug is NOT NULL; reuse the RentalWise helpers so slugs stay unique within the tenant.
        from app.workers.tasks.sync_retalwise import _slugify, _unique_slug
        row = Property(
            id=str(_uuid.uuid4()),
            tenant_id=tenant_id,
            hostaway_listing_id=external_id,
            name=name,
            slug=_unique_slug(db, tenant_id, _slugify(name)),
        )
        db.add(row)
        db.flush()   # sessions run with autoflush off; make this slug visible to the next listing

    row.name = name
    row.type = listing.get("propertyType", "villa")
    row.city = listing.get("city", "") or ""
    row.address = listing.get("address", "") or ""


def _upsert_stay(db: Session, tenant_id: str, res: dict) -> str:
    """Create/update the Stay for one Hostaway reservation. Returns "synced" or "skipped".

    A Stay needs a property and a guest (both NOT NULL). The property is the tenant's own listing
    the reservation points at; the guest is found or created from the reservation's phone. When
    either cannot be established the reservation is skipped -- we never invent a guest or attach
    a booking to a property it does not belong to.
    """
    external_id = str(res.get("id", ""))
    if not external_id:
        return "skipped"

    guest = None
    phone = res.get("phone") or res.get("guestPhone") or ""
    if phone:
        try:
            guest = upsert_by_phone(
                db,
                tenant_id=tenant_id,
                phone=phone,
                name=res.get("guestName", ""),
                email=res.get("guestEmail", ""),
            )
        except Exception:
            guest = None

    listing_id = str(res.get("listingMapId") or res.get("listingId") or "")
    prop = (
        db.query(Property).filter_by(tenant_id=tenant_id, hostaway_listing_id=listing_id).first()
        if listing_id else None
    )
    if guest is None or prop is None:
        logger.warning(
            "Hostaway: skipping reservation %s -- %s", external_id,
            "no guest phone" if guest is None else f"no property for listing {listing_id!r}",
        )
        return "skipped"

    # migration 071: Stay.check_in/check_out are real DATE columns, NOT
    # NULL -- a bare string (or "") assignment that worked against the old
    # String column now fails at flush. Parse before touching `row` at all
    # so a bad reservation is skipped cleanly (not the whole sync batch,
    # and not a half-built row left dangling in the session).
    from datetime import date as _date
    arrival = res.get("arrivalDate") or ""
    departure = res.get("departureDate") or ""
    try:
        check_in = _date.fromisoformat(arrival)
        check_out = _date.fromisoformat(departure)
    except ValueError:
        logger.warning(
            "Hostaway: skipping reservation %s -- unparseable dates arrival=%r departure=%r",
            external_id, arrival, departure,
        )
        return "skipped"

    row = db.query(Stay).filter_by(
        tenant_id=tenant_id, hostaway_booking_id=external_id
    ).first()
    if not row:
        row = Stay(
            id=str(_uuid.uuid4()),
            tenant_id=tenant_id,
            hostaway_booking_id=external_id,
        )
        db.add(row)

    row.guest_id = guest.id
    row.property_id = prop.id
    row.check_in = check_in
    row.check_out = check_out
    row.status = res.get("status", "confirmed")
    row.channel_source = res.get("channelName", "hostaway")
    row.total_amount = float(res.get("totalPrice", 0) or 0)
    row.currency = "INR"
    return "synced"
