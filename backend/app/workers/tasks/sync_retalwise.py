"""
Celery task: sync RentalWise properties, reservations, and guests into HAIP.

Triggered:
  - On first connect (via integrations endpoint background task)
  - Manually via POST /integrations/retalwise/sync
  - Hourly via Celery Beat (sync_retalwise_all_tenants fires at :05 each hour)
"""

from __future__ import annotations
import logging
import uuid as _uuid
from datetime import datetime, timezone
from celery import shared_task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.encryption import decrypt_credentials
from app.models.integration import Integration
from app.models.property import Property, Stay
from app.models.guest import Guest
from app.services.guest_service import upsert_by_phone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300, name="sync_retalwise")
def sync_retalwise(self, tenant_id: str) -> dict:
    db: Session = SessionLocal()
    try:
        integration = db.query(Integration).filter_by(
            tenant_id=tenant_id, kind="retalwise"
        ).first()

        if not integration or integration.status != "active":
            return {"status": "skipped", "reason": "not connected"}

        creds = decrypt_credentials(integration.credentials_kms_blob)
        username = creds.get("username", creds.get("api_key", ""))
        password = creds.get("password", creds.get("api_secret", ""))
        if not username or not password:
            logger.error("RentalWise sync: missing credentials for tenant %s", tenant_id)
            return {"status": "error", "reason": "missing username/password"}

        config = integration.config or {}
        base_url = config.get("base_url", "https://partners-api.rentalwise.com")

        from app.adapters.pms.retalwise import RentalwiseAdapter
        adapter = RentalwiseAdapter(username=username, password=password, base_url=base_url)

        stats = {"properties": 0, "reservations": 0, "guests": 0, "errors": []}

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
        row = Property(
            id=str(_uuid.uuid4()),
            tenant_id=tenant_id,
            hostaway_listing_id=f"rw_{external_id}",  # prefix to distinguish from Hostaway
        )
        db.add(row)
    else:
        row.hostaway_listing_id = f"rw_{external_id}"

    row.name = p.get("name") or row.name or "Unnamed"
    row.type = p.get("type") or "villa"
    row.city = p.get("city") or ""
    row.address = p.get("address") or ""
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

    # Find guest by phone if available
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
        )
        db.add(row)

    if guest:
        row.guest_id = guest.id
    row.check_in = r.get("check_in") or ""
    row.check_out = r.get("check_out") or ""
    row.status = r.get("status", "confirmed")
    row.channel_source = r.get("channel", "rentalwise")
    row.total_amount = r.get("total_amount", 0)
    row.currency = r.get("currency", "INR")
