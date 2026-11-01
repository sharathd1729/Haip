"""GPS alerts for a vehicle on a trip (plan "Route deviation and live alerts"). An alert fires only when a problem LASTS.

Each rule keeps one GpsAlertEpisode per trip while its condition holds: the first bad fix opens it, later bad fixes extend
it, the first good fix ends it. The alert (an ops_items row, category "gps", duty ops_manager, kind gps_<rule>) is raised
once, when the episode has lasted long enough; the next alert for that rule needs a new episode. Thresholds: GPS_RULES
(schemas/gps.py) merged with the business's overrides.

  off_route  > off_route_km from the planned road (+ approved detours) for N fixes in a row or M minutes; needs a route
  halt       stopped (< moving_kmh) for halt_minutes further than stop_radius_km from every planned stop; needs a route
  overspeed  above overspeed_kmh for overspeed_minutes
  night      moving between night_start and night_end local time, unless the route allows night driving
  silent     no fix for silent_minutes while the last fix had the ignition on (beat tick)

An approved detour (approve_detour) adds the off-route stretch to the corridor and keeps extending it while the vehicle
stays off the planned road; it closes when the vehicle is back on the planned road.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import append_audit
from app.models.gps import GpsAlertEpisode, GpsDevice, GpsPosition
from app.models.integration import Integration
from app.models.ops import OpsItem
from app.models.ops_files import OpsFile
from app.models.property import Property, Stay
from app.schemas.gps import GPS_RULES
from app.services import ops_escalation_service as esc
from app.services import ops_money as money
from app.services import roster_service
from app.services.gps_geo import distance_to_line_km, haversine_km

log = structlog.get_logger()

LABELS = {
    "off_route": "off the planned route",
    "halt": "stopped away from a planned stop",
    "overspeed": "driving too fast",
    "night": "driving at night",
    "silent": "tracker has gone quiet",
}
MAX_DETOUR_POINTS = 1000
MAX_TRACK_POINTS = 200


def _aware(v: datetime | None) -> datetime | None:
    return esc._aware(v)


def rules_for(db: Session, tenant_id: str) -> dict:
    row = db.query(Integration).filter_by(tenant_id=tenant_id, kind="gps").first()
    over = ((row.config or {}).get("rules") or {}) if row else {}
    out = {**GPS_RULES, **{k: v for k, v in over.items() if k in GPS_RULES and k != "severity" and v is not None}}
    out["severity"] = {**GPS_RULES["severity"], **(over.get("severity") or {})}
    return out


def _minute(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def is_night(local: datetime, start: str, end: str) -> bool:
    m, s, e = local.hour * 60 + local.minute, _minute(start), _minute(end)
    return (s <= m < e) if s < e else (m >= s or m < e)


def where(lat: float, lng: float) -> str:
    return f"Near {lat:.5f}, {lng:.5f}: https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lng:.5f}#map=15/{lat:.5f}/{lng:.5f}"


def device_for(db: Session, tenant_id: str, property_id: str | None) -> GpsDevice | None:
    if not property_id:
        return None
    return (
        db.query(GpsDevice)
        .filter(GpsDevice.tenant_id == tenant_id, GpsDevice.property_id == property_id, GpsDevice.active.is_(True))
        .order_by(GpsDevice.last_seen_at.desc().nullslast())
        .first()
    )


class _Run:
    def __init__(self, db: Session, f: OpsFile, now: datetime):
        self.db, self.f, self.now = db, f, now
        self.rules = rules_for(db, f.tenant_id)
        self.eps = {
            e.rule: e
            for e in db.query(GpsAlertEpisode).filter(
                GpsAlertEpisode.tenant_id == f.tenant_id,
                GpsAlertEpisode.file_id == f.id,
                GpsAlertEpisode.ended_at.is_(None),
            )
        }
        self.sends: list[str] = []
        self.route_changed = False

    def lasted(self, ep: GpsAlertEpisode, minutes: float, at: datetime | None = None) -> bool:
        return (_aware(at or ep.last_at) - _aware(ep.started_at)) >= timedelta(minutes=minutes)

    def end(self, rule: str, at: datetime) -> None:
        ep = self.eps.pop(rule, None)
        if ep is not None:
            ep.ended_at = at

    def step(self, rule: str, bad: bool, at: datetime, lat: float, lng: float, value: float | None, ready) -> None:
        if not bad:
            self.end(rule, at)
            return
        ep = self.eps.get(rule)
        if ep is None:
            ep = GpsAlertEpisode(
                tenant_id=self.f.tenant_id,
                file_id=self.f.id,
                rule=rule,
                started_at=at,
                last_at=at,
                count=1,
                detail={"lat": lat, "lng": lng, "worst": value, "track": [[lat, lng]]},
            )
            self.db.add(ep)
            self.eps[rule] = ep
        else:
            ep.count = (ep.count or 0) + 1
            ep.last_at = at
            d = dict(ep.detail or {})
            if value is not None and (d.get("worst") is None or value > d["worst"]):
                d["worst"] = value
            if len(d.get("track") or []) < MAX_TRACK_POINTS:
                d["track"] = [*(d.get("track") or []), [lat, lng]]
            d["last_lat"], d["last_lng"] = lat, lng
            ep.detail = d
        if ep.item_id is None and ready(ep):
            self.fire(ep, lat, lng)

    def fire(self, ep: GpsAlertEpisode, lat: float, lng: float) -> None:
        f, rule, r = self.f, ep.rule, self.rules
        stay = money.stay_of(self.db, f)
        unit = self.db.query(Property.name).filter(Property.id == stay.property_id).scalar() or "Trip"
        worst = (ep.detail or {}).get("worst")
        what = {
            "off_route": f"{worst:.1f} km from the planned road" if worst is not None else "Away from the planned road",
            "halt": f"Stopped since {self._local(ep.started_at)}, {worst:.1f} km from the nearest planned stop"
            if worst is not None
            else "Stopped away from a planned stop",
            "overspeed": f"Up to {worst:.0f} km/h for over {r['overspeed_minutes']} min (limit {r['overspeed_kmh']:.0f})"
            if worst is not None
            else "Over the speed limit",
            "night": f"Moving at {self._local(ep.started_at)} (night hours {r['night_start']}-{r['night_end']})",
            "silent": f"No position since {self._local(ep.started_at)} and the ignition was on",
        }[rule]
        item, sends = esc.create_item(
            self.db,
            f.tenant_id,
            title=f"{unit}: {LABELS[rule]}"[:200],
            severity=r["severity"].get(rule, "normal"),
            duty="ops_manager",
            kind=f"gps_{rule}",
            summary=f"{what}. {where(lat, lng)}"[:2000],
            category="gps",
            property_id=stay.property_id,
            stay_id=stay.id,
            guest_id=stay.guest_id,
            source="system",
            now=self.now,
        )
        ep.item_id = item.id
        money.event(self.db, f, f"GPS alert: {LABELS[rule]}. {what}.", auto=True)
        self.sends += sends
        log.info("gps_alert_fired", tenant_id=f.tenant_id, file_id=f.id, rule=rule, item_id=item.id)

    def _local(self, at: datetime) -> str:
        return _aware(at).astimezone(roster_service.tenant_tz(self.db, self.f.tenant_id)).strftime("%H:%M")


def _lock(db: Session, f: OpsFile) -> OpsFile:
    # One evaluation per trip at a time (push, pull and the tick can overlap): no double episodes or alerts.
    return db.query(OpsFile).filter(OpsFile.id == f.id, OpsFile.tenant_id == f.tenant_id).with_for_update().one()


def _off_route_km(run: _Run, route: dict, p: tuple[float, float]) -> float:
    planned = [(pt["lat"], pt["lng"]) for pt in route.get("points") or []]
    d_planned = distance_to_line_km(p, planned)
    detours = route.get("detours") or []
    live = next((d for d in detours if d.get("open")), None)
    if live is not None:
        run.route_changed = True
        if d_planned <= run.rules["off_route_km"]:
            live["open"] = False  # back on the planned road: the detour is over
        else:
            if len(live["points"]) < MAX_DETOUR_POINTS:
                live["points"].append([p[0], p[1]])
            return 0.0
    return min([d_planned] + [distance_to_line_km(p, [tuple(x) for x in d["points"]]) for d in detours])


def _stop_km(route: dict, p: tuple[float, float]) -> float:
    pts = route.get("points") or []
    stops = [(x["lat"], x["lng"]) for i, x in enumerate(pts) if x.get("stop") or i in (0, len(pts) - 1)]
    return min(haversine_km(p, s) for s in stops) if stops else float("inf")


def on_positions(
    db: Session, f: OpsFile, rows: list[GpsPosition], prev: GpsPosition | None, now: datetime | None = None
) -> list[str]:
    """Check new fixes (time order, all newer than `prev`) of a vehicle on this trip. Returns queued alert send ids."""
    now = now or datetime.now(UTC)
    f = _lock(db, f)
    if f.state != "on_trip" or not rows:
        return []
    run = _Run(db, f, now)
    r = run.rules
    route = f.gps_route if (f.gps_route or {}).get("points") else None
    tz = roster_service.tenant_tz(db, f.tenant_id)
    for row in rows:
        at = _aware(row.at)
        run.end("silent", at)
        speed = row.speed_kmh
        if speed is None and prev is not None:
            hours = (at - _aware(prev.at)).total_seconds() / 3600
            speed = haversine_km((prev.lat, prev.lng), (row.lat, row.lng)) / hours if hours > 0 else None
        p = (row.lat, row.lng)
        if speed is not None:
            moving = speed >= r["moving_kmh"]
            run.step(
                "overspeed", speed > r["overspeed_kmh"], at, *p, speed, lambda e: run.lasted(e, r["overspeed_minutes"])
            )
            night_ok = bool((route or {}).get("night_driving_ok"))
            run.step(
                "night",
                moving and not night_ok and is_night(at.astimezone(tz), r["night_start"], r["night_end"]),
                at,
                *p,
                speed,
                lambda e: run.lasted(e, r["night_minutes"]),
            )
        if route is not None:
            off = _off_route_km(run, route, p)
            run.step(
                "off_route",
                off > r["off_route_km"],
                at,
                *p,
                off,
                lambda e: e.count >= r["off_route_positions"] or run.lasted(e, r["off_route_minutes"]),
            )
            if speed is not None:
                run.step(
                    "halt",
                    speed < r["moving_kmh"] and _stop_km(route, p) > r["stop_radius_km"],
                    at,
                    *p,
                    _stop_km(route, p),
                    lambda e: run.lasted(e, r["halt_minutes"]),
                )
        prev = row
    if run.route_changed:
        f.gps_route = dict(route)
        flag_modified(f, "gps_route")
    db.flush()
    return run.sends


def tick(db: Session, tenant_id: str, now: datetime | None = None) -> list[str]:
    """Beat, every minute: the rules that need no new fix (tracker silent, a long halt with the tracker asleep)."""
    now = now or datetime.now(UTC)
    for ep in (
        db.query(GpsAlertEpisode)
        .join(OpsFile, OpsFile.id == GpsAlertEpisode.file_id)
        .filter(GpsAlertEpisode.tenant_id == tenant_id, GpsAlertEpisode.ended_at.is_(None), OpsFile.state != "on_trip")
    ):
        ep.ended_at = now  # the trip is over
    sends: list[str] = []
    files = (
        db.query(OpsFile, Stay)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .filter(OpsFile.tenant_id == tenant_id, OpsFile.state == "on_trip")
        .all()
    )
    for f, stay in files:
        dev = device_for(db, tenant_id, stay.property_id)
        if dev is None or dev.last_seen_at is None:
            continue
        f = _lock(db, f)
        run = _Run(db, f, now)
        r = run.rules
        seen = _aware(dev.last_seen_at)
        ign_on = dev.last_ignition is True or (
            dev.last_ignition is None and (dev.last_speed_kmh or 0) >= r["moving_kmh"]
        )
        if ign_on and now - seen >= timedelta(minutes=r["silent_minutes"]):
            if "silent" not in run.eps:
                run.step("silent", True, seen, dev.last_lat, dev.last_lng, None, lambda e: True)
        halt = run.eps.get("halt")
        if halt is not None and halt.item_id is None and run.lasted(halt, r["halt_minutes"], at=now):
            d = halt.detail or {}
            run.fire(halt, d.get("last_lat", d.get("lat")), d.get("last_lng", d.get("lng")))
        sends += run.sends
    db.flush()
    return sends


def approve_detour(db: Session, tenant_id: str, item_id: str, reason: str, actor_id: str) -> OpsItem:
    """One tap on an off-route alert: the road driven joins the corridor, the reason goes on the trip timeline."""
    from fastapi import HTTPException

    item = db.query(OpsItem).filter(OpsItem.id == item_id, OpsItem.tenant_id == tenant_id).first()
    ep = (
        db.query(GpsAlertEpisode)
        .filter(GpsAlertEpisode.tenant_id == tenant_id, GpsAlertEpisode.item_id == item_id)
        .first()
    )
    if item is None or ep is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if ep.rule != "off_route":
        raise HTTPException(status_code=409, detail="Only an off-route alert can be approved as a detour.")
    f = _lock(db, db.query(OpsFile).filter(OpsFile.id == ep.file_id, OpsFile.tenant_id == tenant_id).one())
    route = dict(f.gps_route or {})
    if not route.get("points"):
        raise HTTPException(status_code=409, detail="This trip has no planned route.")
    now = datetime.now(UTC)
    detours = [dict(d, open=False) for d in route.get("detours") or []]
    detours.append(
        {
            "points": list((ep.detail or {}).get("track") or [[ep.detail["lat"], ep.detail["lng"]]]),
            "reason": reason,
            "by": actor_id,
            "at": now.isoformat(),
            "open": ep.ended_at is None and f.state == "on_trip",  # still off the road: keep widening as it drives
        }
    )
    route["detours"] = detours
    f.gps_route = route
    flag_modified(f, "gps_route")
    if ep.ended_at is None:
        ep.ended_at = now
    esc.resolve(db, item, user_id=actor_id, note=f"Approved detour: {reason}"[:500])
    money.event(db, f, f"Detour approved: {reason}", actor_id=actor_id)
    append_audit(
        db,
        tenant_id=tenant_id,
        action="ops.gps.detour_approved",
        actor_user_id=actor_id,
        target_type="ops_file",
        target_id=f.id,
        payload={"item_id": item_id, "reason": reason},
    )
    db.flush()
    return item
