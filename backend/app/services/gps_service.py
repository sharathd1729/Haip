"""GPS settings, trackers, the live map and a trip's track (endpoints/ops_gps.py). Secrets are written, never read back:
the webhook secret is returned once, when it is made."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.adapters import gps as adapters
from app.adapters.gps import webhook
from app.core.audit import append_audit
from app.core.config import settings
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.core.url_safety import UnsafeURLError, assert_public_url
from app.models.gps import GpsDevice, GpsPosition
from app.models.integration import Integration
from app.models.ops import OpsItem
from app.models.ops_files import OpsFile
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.schemas.gps import GPS_RULES, ConnectionIn, DeviceIn, DevicePatch, RouteIn
from app.services import gps_alerts, gps_geo, gps_ingest
from app.services import ops_money as money

OPEN = ("open", "acknowledged")


def _iso(v: datetime | None) -> str | None:
    return gps_alerts._aware(v).isoformat() if v else None


def webhook_url(db: Session, tenant_id: str) -> str:
    slug = db.query(Tenant.slug).filter(Tenant.id == tenant_id).scalar()
    base = (settings.API_BASE_URL or "").rstrip("/")
    return f"{base}/api/v1/webhooks/gps/{slug}"


def connection(db: Session, tenant_id: str) -> dict:
    row = gps_ingest.integration(db, tenant_id)
    cfg = (row.config or {}) if row else {}
    creds = decrypt_credentials(row.credentials_kms_blob) if row and row.credentials_kms_blob else {}
    return {
        "providers": adapters.catalogue(),
        "provider": cfg.get("provider"),
        "status": row.status if row else "disconnected",
        "base_url": cfg.get("base_url"),
        "username": cfg.get("username"),
        "has_password": bool(creds.get("password")),
        "has_webhook_secret": bool(creds.get("webhook_secret")),
        "webhook_url": webhook_url(db, tenant_id),
        "last_error": cfg.get("last_error"),
        "last_health_at": row.last_health_at if row else None,
        "rules": gps_alerts.rules_for(db, tenant_id),
        "default_rules": GPS_RULES,
    }


def save_connection(db: Session, tenant_id: str, body: ConnectionIn, actor_id: str) -> dict:
    try:
        provider = adapters.get_provider(body.provider)
    except adapters.GpsProviderBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = gps_ingest.integration(db, tenant_id)
    if row is None:
        row = Integration(
            tenant_id=tenant_id, kind="gps", status="active", config={}, installed_at=datetime.now(UTC).isoformat()
        )
        db.add(row)
    cfg = dict(row.config or {})
    creds = decrypt_credentials(row.credentials_kms_blob) if row.credentials_kms_blob else {}
    secret_once = None
    if provider.key == "traccar":
        url = (body.base_url or cfg.get("base_url") or "").strip().rstrip("/")
        try:
            assert_public_url(url, allow_http=False)
        except UnsafeURLError as exc:
            raise HTTPException(status_code=422, detail=f"Server address: {exc}") from exc
        if not (body.password or creds.get("password")):
            raise HTTPException(status_code=422, detail="Enter the Traccar password or API token.")
        cfg.update(base_url=url, username=(body.username or "").strip() or None)
        if body.password:
            creds["password"] = body.password
    if provider.key == "webhook" and not creds.get("webhook_secret"):
        secret_once = creds["webhook_secret"] = webhook.new_secret()
    changed = cfg.get("provider") != provider.key
    cfg["provider"] = provider.key
    cfg.pop("last_error", None)
    if body.rules is not None:
        cfg["rules"] = {**(cfg.get("rules") or {}), **body.rules.model_dump(exclude_none=True)}
    row.config = cfg
    flag_modified(row, "config")
    row.credentials_kms_blob = encrypt_credentials(creds)
    row.status = "active"
    append_audit(
        db,
        tenant_id=tenant_id,
        action="ops.gps.connection_saved",
        actor_user_id=actor_id,
        target_type="integration",
        target_id=row.id,
        payload={  # never the secrets
            "provider": provider.key,
            "provider_changed": changed,
            "base_url": cfg.get("base_url"),
            "password_changed": bool(body.password),
            "rules": body.rules.model_dump(exclude_none=True) if body.rules else None,
        },
    )
    db.flush()
    return {**connection(db, tenant_id), "webhook_secret": secret_once}


def rotate_secret(db: Session, tenant_id: str, actor_id: str) -> dict:
    row = gps_ingest.integration(db, tenant_id)
    if row is None or (row.config or {}).get("provider") != "webhook":
        raise HTTPException(status_code=409, detail="Pick the HAIP webhook first.")
    creds = decrypt_credentials(row.credentials_kms_blob) if row.credentials_kms_blob else {}
    creds["webhook_secret"] = secret = webhook.new_secret()
    row.credentials_kms_blob = encrypt_credentials(creds)
    append_audit(
        db,
        tenant_id=tenant_id,
        action="ops.gps.secret_rotated",
        actor_user_id=actor_id,
        target_type="integration",
        target_id=row.id,
        payload={},
    )
    db.flush()
    return {**connection(db, tenant_id), "webhook_secret": secret}


def webhook_secret(db: Session, tenant_id: str) -> str:
    row = gps_ingest.integration(db, tenant_id)
    if row is None or row.status != "active" or (row.config or {}).get("provider") != "webhook":
        return ""
    return (decrypt_credentials(row.credentials_kms_blob) if row.credentials_kms_blob else {}).get("webhook_secret", "")


# ── Trackers ───────────────────────────────────────────────────────────────


def _vehicle(db: Session, tenant_id: str, property_id: str | None) -> None:
    if (
        property_id
        and db.query(Property.id).filter(Property.id == property_id, Property.tenant_id == tenant_id).first() is None
    ):
        raise HTTPException(status_code=422, detail="That vehicle is not in this business.")


def device_out(d: GpsDevice, names: dict) -> dict:
    return {
        "id": d.id,
        "provider": d.provider,
        "external_id": d.external_id,
        "label": d.label,
        "property_id": d.property_id,
        "property_name": names.get(d.property_id),
        "active": d.active,
        "last_seen_at": _iso(d.last_seen_at),
        "last_position": {
            "lat": d.last_lat,
            "lng": d.last_lng,
            "speed_kmh": d.last_speed_kmh,
            "ignition": d.last_ignition,
        }
        if d.last_lat is not None
        else None,
    }


def _names(db: Session, tenant_id: str) -> dict:
    return dict(db.query(Property.id, Property.name).filter(Property.tenant_id == tenant_id).all())


def list_devices(db: Session, tenant_id: str) -> list[dict]:
    names = _names(db, tenant_id)
    rows = db.query(GpsDevice).filter(GpsDevice.tenant_id == tenant_id).order_by(GpsDevice.created_at)
    return [device_out(d, names) for d in rows]


def get_device(db: Session, tenant_id: str, device_id: str) -> GpsDevice:
    d = db.query(GpsDevice).filter(GpsDevice.id == device_id, GpsDevice.tenant_id == tenant_id).first()
    if d is None:
        raise HTTPException(status_code=404, detail="Tracker not found")
    return d


def _audit_device(db, d: GpsDevice, action: str, actor_id: str) -> None:
    append_audit(
        db,
        tenant_id=d.tenant_id,
        action=f"ops.gps.device_{action}",
        actor_user_id=actor_id,
        target_type="gps_device",
        target_id=d.id,
        payload={"external_id": d.external_id, "property_id": d.property_id, "active": d.active},
    )


def create_device(db: Session, tenant_id: str, body: DeviceIn, actor_id: str) -> dict:
    _vehicle(db, tenant_id, body.property_id)
    provider = ((gps_ingest.integration(db, tenant_id) or Integration(config={})).config or {}).get(
        "provider"
    ) or "webhook"
    if db.query(GpsDevice.id).filter_by(tenant_id=tenant_id, provider=provider, external_id=body.external_id).first():
        raise HTTPException(status_code=409, detail="This tracker id is already added.")
    d = GpsDevice(tenant_id=tenant_id, provider=provider, **body.model_dump())
    db.add(d)
    db.flush()
    _audit_device(db, d, "created", actor_id)
    return device_out(d, _names(db, tenant_id))


def update_device(db: Session, tenant_id: str, device_id: str, body: DevicePatch, actor_id: str) -> dict:
    d = get_device(db, tenant_id, device_id)
    data = body.model_dump(exclude_unset=True)
    if "property_id" in data:
        _vehicle(db, tenant_id, data["property_id"])
    for k, v in data.items():
        setattr(d, k, v)
    db.flush()
    _audit_device(db, d, "updated", actor_id)
    return device_out(d, _names(db, tenant_id))


def delete_device(db: Session, tenant_id: str, device_id: str, actor_id: str) -> None:
    d = get_device(db, tenant_id, device_id)
    _audit_device(db, d, "deleted", actor_id)
    db.delete(d)
    db.flush()


# ── Live map, track, route ─────────────────────────────────────────────────


def live(db: Session, tenant_id: str, now: datetime | None = None) -> dict:
    """Every vehicle: where it is, moving or parked, last seen, its trip, its open GPS alerts. One row per vehicle."""
    now = now or datetime.now(UTC)
    rules = gps_alerts.rules_for(db, tenant_id)
    trips = {
        stay.property_id: (f, stay)
        for f, stay in db.query(OpsFile, Stay)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .filter(OpsFile.tenant_id == tenant_id, OpsFile.state == "on_trip")
    }
    alerts: dict[str, list] = {}
    for it in (
        db.query(OpsItem)
        .filter(OpsItem.tenant_id == tenant_id, OpsItem.category == "gps", OpsItem.status.in_(OPEN))
        .order_by(OpsItem.created_at.desc())
    ):
        alerts.setdefault(it.property_id, []).append(
            {
                "id": it.id,
                "kind": it.kind,
                "title": it.title.split(": ", 1)[-1],
                "severity": it.severity,
                "summary": it.summary,
                "created_at": _iso(it.created_at),
            }
        )
    vehicles = []
    for p in (
        db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True)).order_by(Property.name)
    ):
        dev = gps_alerts.device_for(db, tenant_id, p.id)
        trip = trips.get(p.id)
        if dev is None and trip is None:
            continue
        seen = gps_alerts._aware(dev.last_seen_at) if dev else None
        minutes = round((now - seen).total_seconds() / 60) if seen else None
        moving = bool(
            dev
            and dev.last_speed_kmh is not None
            and dev.last_speed_kmh >= rules["moving_kmh"]
            and minutes is not None
            and minutes < rules["silent_minutes"]
        )
        vehicles.append(
            {
                "property_id": p.id,
                "name": p.name,
                "device_id": dev.id if dev else None,
                "lat": dev.last_lat if dev else None,
                "lng": dev.last_lng if dev else None,
                "speed_kmh": dev.last_speed_kmh if dev else None,
                "heading": dev.last_heading if dev else None,
                "ignition": dev.last_ignition if dev else None,
                "last_seen_at": _iso(dev.last_seen_at) if dev else None,
                "minutes_since": minutes,
                "state": "no_tracker"
                if dev is None
                else "no_signal"
                if seen is None
                else "moving"
                if moving
                else "parked",
                "file_id": trip[0].id if trip else None,
                "guest_name": ((trip[1].guest.name if trip[1].guest is not None else None) or "Guest")
                if trip
                else None,
                "alerts": alerts.get(p.id, []),
            }
        )
    return {"vehicles": vehicles, "at": now.isoformat()}


def _file(db: Session, tenant_id: str, file_id: str) -> OpsFile:
    f = db.query(OpsFile).filter(OpsFile.id == file_id, OpsFile.tenant_id == tenant_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return f


MAX_TRACK = 5000


def track(db: Session, tenant_id: str, file_id: str) -> dict:
    """The trip's fixes, planned route, and GPS distance beside the odometer (a cross-check, never billing)."""
    f = _file(db, tenant_id, file_id)
    rows = (
        db.query(GpsPosition.at, GpsPosition.lat, GpsPosition.lng, GpsPosition.odometer_km)
        .filter(GpsPosition.tenant_id == tenant_id, GpsPosition.file_id == f.id)
        .order_by(GpsPosition.at)
        .all()
    )
    pts = [(gps_alerts._aware(r.at), r.lat, r.lng) for r in rows]
    odos = [r.odometer_km for r in rows if r.odometer_km is not None]
    d = money.details(f)
    end = d.end_odometer
    step = max(1, len(pts) // MAX_TRACK)  # thin a long trip for the map; distance uses every fix
    return {
        "file_id": f.id,
        "points": [[lat, lng] for _, lat, lng in pts[::step]],
        "planned_route": f.gps_route,
        "gps_km": gps_geo.track_km(pts) if pts else None,
        "tracker_odometer_km": round(odos[-1] - odos[0], 1) if len(odos) >= 2 else None,
        "odometer_km": (end - d.start_odometer) if end and d.start_odometer else None,
        "first_at": pts[0][0].isoformat() if pts else None,
        "last_at": pts[-1][0].isoformat() if pts else None,
    }


def set_route(db: Session, tenant_id: str, file_id: str, body: RouteIn, actor_id: str) -> dict:
    f = _file(db, tenant_id, file_id)
    if f.state in ("closed", "cancelled"):
        raise HTTPException(status_code=409, detail="This trip is closed.")
    f.gps_route = {
        "points": [p.model_dump() for p in body.points],
        "night_driving_ok": body.night_driving_ok,
        "detours": [],
        "set_by": actor_id,
        "set_at": datetime.now(UTC).isoformat(),
    }
    flag_modified(f, "gps_route")
    money.event(db, f, f"Planned route set ({len(body.points)} points)", actor_id=actor_id)
    append_audit(
        db,
        tenant_id=tenant_id,
        action="ops.gps.route_set",
        actor_user_id=actor_id,
        target_type="ops_file",
        target_id=f.id,
        payload={"points": len(body.points), "night_driving_ok": body.night_driving_ok},
    )
    db.flush()
    return track(db, tenant_id, file_id)
