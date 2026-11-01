"""GPS ingest: normalised positions (adapters/gps) -> the business's trackers -> stored fixes -> trip alerts.

Runs only in Celery (workers/tasks/gps.py), never in a request handler. Tenant safety: the tenant comes from the push URL
whose signature checked out, or from the Integration being polled; a device is looked up ONLY inside that tenant, so a
fix can never land on another business's vehicle even if two businesses use the same tracker id.
A tracker id HAIP does not know is added inactive with no vehicle (at most MAX_UNKNOWN per business) so a manager can map
it on the GPS settings page; its fixes are not kept until then. Same device + same time twice = stored once.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters import gps as adapters
from app.core.encryption import decrypt_credentials
from app.models.gps import GpsDevice, GpsPosition
from app.models.integration import Integration
from app.models.ops_files import OpsFile
from app.models.property import Stay
from app.schemas.gps import RETENTION_DAYS
from app.services import gps_alerts

log = structlog.get_logger()

MAX_UNKNOWN = 50


def _aware(v: datetime | None) -> datetime | None:
    return gps_alerts._aware(v)


def integration(db: Session, tenant_id: str) -> Integration | None:
    return db.query(Integration).filter_by(tenant_id=tenant_id, kind="gps").first()


def to_dict(p: adapters.Position) -> dict:
    return {**p.__dict__, "at": p.at.isoformat()}


def from_dict(d: dict) -> adapters.Position:
    return adapters.Position(**{**d, "at": datetime.fromisoformat(d["at"])})


def _on_trip_file(db: Session, tenant_id: str, property_id: str) -> OpsFile | None:
    return (
        db.query(OpsFile)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .filter(OpsFile.tenant_id == tenant_id, OpsFile.state == "on_trip", Stay.property_id == property_id)
        .first()
    )


def ingest(
    db: Session, tenant_id: str, provider: str, positions: list[adapters.Position], now: datetime | None = None
) -> dict:
    """Store new fixes and check the trip rules. Returns counts + `send_ids` (alerts to deliver after commit)."""
    now = now or datetime.now(UTC)
    devices = {
        d.external_id: d
        for d in db.query(GpsDevice).filter(GpsDevice.tenant_id == tenant_id, GpsDevice.provider == provider)
    }
    unknown_left = (
        MAX_UNKNOWN
        - db.query(GpsDevice).filter(GpsDevice.tenant_id == tenant_id, GpsDevice.property_id.is_(None)).count()
    )
    files: dict[str, OpsFile | None] = {}
    prev: dict[str, GpsPosition | None] = {}
    fresh: dict[str, list[GpsPosition]] = defaultdict(list)
    out = {"stored": 0, "duplicates": 0, "unmapped": 0, "new_devices": 0}
    for p in sorted(positions, key=lambda x: (x.device_id, x.at)):
        dev = devices.get(p.device_id)
        if dev is None:
            if unknown_left <= 0:
                out["unmapped"] += 1
                continue
            dev = GpsDevice(tenant_id=tenant_id, provider=provider, external_id=p.device_id, active=False)
            db.add(dev)
            db.flush()
            devices[p.device_id] = dev
            unknown_left -= 1
            out["new_devices"] += 1
        if dev.last_seen_at is None or p.at > _aware(dev.last_seen_at):
            dev.last_seen_at, dev.last_lat, dev.last_lng = p.at, p.lat, p.lng
            dev.last_speed_kmh, dev.last_heading = p.speed_kmh, p.heading
            dev.last_ignition = p.ignition
            if p.odometer_km is not None:
                dev.last_odometer_km = p.odometer_km
        if not dev.active or not dev.property_id:
            out["unmapped"] += 1
            continue
        if dev.property_id not in files:
            files[dev.property_id] = _on_trip_file(db, tenant_id, dev.property_id)
        f = files[dev.property_id]
        file_id = f.id if f is not None and (f.dispatched_at is None or p.at >= _aware(f.dispatched_at)) else None
        if file_id and file_id not in prev:
            prev[file_id] = (
                db.query(GpsPosition)
                .filter(GpsPosition.tenant_id == tenant_id, GpsPosition.file_id == file_id)
                .order_by(GpsPosition.at.desc())
                .first()
            )
        row = GpsPosition(
            tenant_id=tenant_id,
            device_id=dev.id,
            property_id=dev.property_id,
            file_id=file_id,
            at=p.at,
            lat=p.lat,
            lng=p.lng,
            speed_kmh=p.speed_kmh,
            heading=p.heading,
            ignition=p.ignition,
            odometer_km=p.odometer_km,
            source=provider,
            received_at=now,
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            out["duplicates"] += 1
            continue
        out["stored"] += 1
        last = prev.get(file_id) if file_id else None
        if file_id and (last is None or p.at > _aware(last.at)):
            fresh[file_id].append(row)
    send_ids: list[str] = []
    for file_id, rows in fresh.items():
        f = next(x for x in files.values() if x is not None and x.id == file_id)
        send_ids += gps_alerts.on_positions(db, f, rows, prev.get(file_id), now)
    db.flush()
    return {**out, "send_ids": send_ids}


def poll(db: Session, tenant_id: str, now: datetime | None = None) -> dict:
    """Pull the business's provider once (beat, every minute). Errors are recorded on the Integration, never raised."""
    now = now or datetime.now(UTC)
    row = integration(db, tenant_id)
    if row is None or row.status != "active":
        return {"polled": False}
    provider = adapters.PROVIDERS.get((row.config or {}).get("provider") or "")
    if provider is None or provider.shape != "pull" or not provider.enabled:
        return {"polled": False}
    since = {
        d.external_id: _aware(d.last_seen_at)
        for d in db.query(GpsDevice).filter(GpsDevice.tenant_id == tenant_id, GpsDevice.provider == provider.key)
        if d.last_seen_at is not None
    }
    cfg = dict(row.config or {})
    try:
        positions = adapters.fetch_positions(
            provider,
            cfg,
            decrypt_credentials(row.credentials_kms_blob) if row.credentials_kms_blob else {},
            since,
            now=now,
        )
    except adapters.GpsFetchError as exc:
        if cfg.get("last_error") != str(exc):
            cfg["last_error"] = str(exc)[:300]
            row.config = cfg
        log.warning(
            "gps_poll_failed", tenant_id=tenant_id, provider=provider.key, error=str(exc)[:300], transient=exc.transient
        )
        return {"polled": True, "error": str(exc)[:300]}
    if cfg.get("last_error"):
        cfg.pop("last_error")
        row.config = cfg
    row.last_health_at = now.isoformat()
    return {"polled": True, **ingest(db, tenant_id, provider.key, positions, now)}


def purge(db: Session, tenant_id: str, now: datetime | None = None) -> int:
    """Delete fixes older than RETENTION_DAYS (daily beat). Devices keep their latest fix."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)
    return (
        db.query(GpsPosition)
        .filter(GpsPosition.tenant_id == tenant_id, GpsPosition.at < cutoff)
        .delete(synchronize_session=False)
    )
