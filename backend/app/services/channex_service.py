"""Channel manager via Channex (adapters/pms/channex.py): HAIP stays the source of truth for its calendar, Channex carries
it to the OTAs (Airbnb, Booking.com, ...) and brings their bookings back.

Push (`push_tenant`): for every mapped unit (channex_mappings), availability for the next HORIZON_DAYS = 1 on a free night,
0 on a night a booking (anything not cancelled) or an active block holds; sent as date ranges. Rates only where the owner
switched `push_rates` on for that unit: the same nightly price HAIP's calendar shows (an active SeasonalRate by priority,
else the cheapest active RatePlan); package-priced units (caravans, price_policy.package_priced) never send a rate.

Pull (`pull_tenant`): Channex's booking-revisions feed. A new revision becomes a HAIP booking through
booking_service.create_booking (lead tie, audit, channel_source "channex"); a modified one updates dates, guests and
amount; a cancelled one cancels the booking. Every revision is stored before it is acknowledged (Channex removes the
guest's contact details after the ack), and channex_booking_links.last_revision_id makes a re-delivered revision a no-op.
An OTA booking is real even when it overlaps another one: it is stored and a task says "Overbooking". A booking for a
room type nobody mapped is not guessed onto a unit: a task asks someone to map it, and it stays in the feed.
After a pull that changed anything, availability is pushed again so every channel sees it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy.orm import Session

from app.adapters.pms.channex import ChannexClient, ChannexError

log = structlog.get_logger()

KIND = "channex"
HORIZON_DAYS = 365
SOURCE = "channex"
_LIVE = ("cancelled",)


class NotConnected(Exception):
    pass


# ─── Connection ──────────────────────────────────────────────────────────────


def integration(db: Session, tenant_id: str):
    from app.models.integration import Integration

    return db.query(Integration).filter_by(tenant_id=tenant_id, kind=KIND).first()


def client_for(db: Session, tenant_id: str, transport=None) -> ChannexClient:
    from app.core.encryption import get_credential

    integ = integration(db, tenant_id)
    if integ is None or integ.status != "active" or not integ.credentials_kms_blob:
        raise NotConnected("Channex is not connected for this workspace")
    key = get_credential(integ.credentials_kms_blob, "api_key")
    return ChannexClient(key, (integ.config or {}).get("base_url"), transport=transport)


# ─── Availability and rates ──────────────────────────────────────────────────


def _d(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def busy_nights(db: Session, tenant_id: str, property_id: str, start: date, end: date) -> set[date]:
    """Nights in [start, end) held by a booking that is not cancelled or by an active block (block end exclusive)."""
    from app.models.property import BlockedDate, Stay

    nights: set[date] = set()
    stays = db.query(Stay.check_in, Stay.check_out).filter(
        Stay.tenant_id == tenant_id, Stay.property_id == property_id, Stay.status.notin_(_LIVE),
        Stay.check_in < end, Stay.check_out > start,
    )
    blocks = db.query(BlockedDate.blocked_from, BlockedDate.blocked_to).filter(
        BlockedDate.tenant_id == tenant_id, BlockedDate.property_id == property_id, BlockedDate.is_active.isnot(False),
        BlockedDate.blocked_from < end.isoformat(), BlockedDate.blocked_to > start.isoformat(),
    )
    for a, b in list(stays) + list(blocks):
        a, b = _d(a), _d(b)
        if a is None or b is None:
            continue
        d = max(a, start)
        while d < min(b, end):
            nights.add(d)
            d += timedelta(days=1)
    return nights


def _ranges(start: date, days: int, value_of) -> list[tuple[date, date, object]]:
    """[(date_from, date_to inclusive, value)] for consecutive days with the same value."""
    out: list[list] = []
    for i in range(days):
        d = start + timedelta(days=i)
        v = value_of(d)
        if out and out[-1][2] == v and out[-1][1] == d - timedelta(days=1):
            out[-1][1] = d
        else:
            out.append([d, d, v])
    return [tuple(r) for r in out]


def availability_values(db: Session, tenant_id: str, mapping, start: date, days: int = HORIZON_DAYS) -> list[dict]:
    busy = busy_nights(db, tenant_id, mapping.property_id, start, start + timedelta(days=days))
    return [
        {"property_id": mapping.channex_property_id, "room_type_id": mapping.channex_room_type_id,
         "date_from": a.isoformat(), "date_to": b.isoformat(), "availability": v}
        for a, b, v in _ranges(start, days, lambda d: 0 if d in busy else 1)
    ]


def nightly_rate(db: Session, prop, day: date, seasonal: list, base: float | None) -> float | None:
    iso = day.isoformat()
    for sr in seasonal:
        if str(sr.date_from) <= iso <= str(sr.date_to):
            return float(sr.price_per_night)
    return base


def rate_values(db: Session, tenant_id: str, mapping, start: date, days: int = HORIZON_DAYS) -> list[dict]:
    from app.models.property import Property, RatePlan, SeasonalRate
    from app.services import price_policy

    if not (mapping.push_rates and mapping.channex_rate_plan_id):
        return []
    prop = db.query(Property).filter_by(id=mapping.property_id, tenant_id=tenant_id).first()
    if prop is None or price_policy.package_priced(prop):
        return []
    plan = (db.query(RatePlan).filter_by(property_id=prop.id, is_active=True)
            .order_by(RatePlan.base_price_per_night).first())
    base = float(plan.base_price_per_night) if plan and plan.base_price_per_night else None
    end = (start + timedelta(days=days)).isoformat()
    seasonal = (db.query(SeasonalRate)
                .filter(SeasonalRate.property_id == prop.id, SeasonalRate.is_active.is_(True),
                        SeasonalRate.date_to >= start.isoformat(), SeasonalRate.date_from <= end)
                .order_by(SeasonalRate.priority.desc(), SeasonalRate.date_from).all())
    return [
        {"property_id": mapping.channex_property_id, "rate_plan_id": mapping.channex_rate_plan_id,
         "date_from": a.isoformat(), "date_to": b.isoformat(), "rate": f"{v:.2f}"}
        for a, b, v in _ranges(start, days, lambda d: nightly_rate(db, prop, d, seasonal, base))
        if v and v > 0   # no price on file for those nights: send nothing rather than a wrong price
    ]


def push_tenant(db: Session, tenant_id: str, start: date | None = None, days: int = HORIZON_DAYS,
                client: ChannexClient | None = None, only: set[str] | None = None) -> dict:
    """Push every mapped unit (or only these property ids). Records the result per mapping; commits."""
    from app.models.channex import ChannexMapping

    start = start or datetime.now(UTC).date()
    own = client is None
    client = client or client_for(db, tenant_id)
    out = {"units": 0, "availability_values": 0, "rate_values": 0, "warnings": [], "failed": 0}
    try:
        for m in db.query(ChannexMapping).filter_by(tenant_id=tenant_id).all():
            if only is not None and m.property_id not in only:
                continue
            try:
                avail = availability_values(db, tenant_id, m, start, days)
                rates = rate_values(db, tenant_id, m, start, days)
                out["warnings"] += client.push_availability(avail) + client.push_restrictions(rates)
                m.last_pushed_at, m.last_push_error = datetime.now(UTC), None
                out["units"] += 1
                out["availability_values"] += len(avail)
                out["rate_values"] += len(rates)
            except ChannexError as exc:
                m.last_push_error = str(exc)[:500]
                out["failed"] += 1
                log.error("channex_push_failed", tenant_id=tenant_id, property_id=m.property_id, error=str(exc))
                if exc.status in (401, 429):
                    break   # bad key / rate limit: the next run tries again; no point hammering
        db.commit()
    finally:
        if own:
            client.close()
    if out["warnings"]:
        log.warning("channex_push_warnings", tenant_id=tenant_id, count=len(out["warnings"]))
    return out


# ─── Bookings ────────────────────────────────────────────────────────────────


def _amount(v) -> Decimal | None:
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except InvalidOperation:
        return None


def _task(db: Session, tenant_id: str, title: str, stay=None, due: date | None = None) -> None:
    from app.models.task import Task

    if db.query(Task.id).filter_by(tenant_id=tenant_id, title=title[:255], is_done=False).first():
        return
    d = due or date.today()
    db.add(Task(tenant_id=tenant_id, title=title[:255], priority="high", guest_id=getattr(stay, "guest_id", None),
                kind="channex", due_date=datetime(d.year, d.month, d.day, tzinfo=UTC)))


def _guest_for(db: Session, tenant_id: str, rev: dict) -> str:
    from app.services.identity_service import resolve_gid

    c = rev.get("customer") or {}
    name = " ".join(x for x in (c.get("name"), c.get("surname")) if x).strip() or "OTA guest"
    for signal, value in (("phone", c.get("phone")), ("email", c.get("mail")),
                          ("ota_guest_id", rev.get("unique_id") or rev.get("ota_reservation_code"))):
        if value:
            gid, _ = resolve_gid(db=db, tenant_id=tenant_id, signal_type=signal, value=str(value), source=SOURCE,
                                 guest_fields={"name": name})
            return gid
    raise ValueError("Channex booking has no guest detail HAIP can use")


def apply_revision(db: Session, tenant_id: str, rev: dict, by_room_type: dict) -> str:
    """Store one booking revision. Returns created | updated | cancelled | unchanged | unmapped. Flushes; caller commits."""
    from app.core.audit import append_audit
    from app.models.channex import ChannexBookingLink
    from app.models.property import Property, Stay
    from app.services import booking_service

    booking_id = str(rev.get("booking_id") or "")
    if not booking_id:
        raise ValueError("revision without booking_id")
    link = db.query(ChannexBookingLink).filter_by(tenant_id=tenant_id, channex_booking_id=booking_id).first()
    if link is not None and link.last_revision_id == rev.get("id"):
        return "unchanged"
    status = str(rev.get("status") or "new")
    rooms = rev.get("rooms") or [{}]
    room = rooms[0]
    check_in = _d(room.get("checkin_date") or rev.get("arrival_date"))
    check_out = _d(room.get("checkout_date") or rev.get("departure_date"))
    occ = room.get("occupancy") or rev.get("occupancy") or {}
    ota = (rev.get("ota_name") or "OTA")[:80]
    stay = db.query(Stay).filter_by(id=link.stay_id, tenant_id=tenant_id).first() if link and link.stay_id else None

    if link is None:
        link = ChannexBookingLink(tenant_id=tenant_id, channex_booking_id=booking_id)
        db.add(link)
    link.ota_name, link.ota_reservation_code = ota, (rev.get("ota_reservation_code") or "")[:120] or None

    def done(result: str) -> str:
        link.last_revision_id, link.status = rev.get("id"), status
        db.flush()
        return result

    if status == "cancelled":
        if stay is not None and stay.status != "cancelled":
            stay.status = "cancelled"
            append_audit(db, tenant_id=tenant_id, action="booking.cancelled_from_channex", target_type="booking",
                         target_id=stay.id, payload={"channex_booking_id": booking_id, "ota": ota})
            return done("cancelled")
        return done("unchanged")

    if check_in is None or check_out is None or check_out <= check_in:
        raise ValueError("Channex revision has no usable dates")
    mapping = by_room_type.get(room.get("room_type_id"))
    if mapping is None and stay is None:
        _task(db, tenant_id, f"Map {ota} room type {room.get('room_type_id')} in Channex settings: a booking is waiting",
              due=check_in)
        db.flush()
        return "unmapped"   # not acknowledged: it comes back once the room type is mapped

    amount = _amount(rev.get("amount"))
    adults, children = int(occ.get("adults") or 1), int(occ.get("children") or 0)
    if stay is None:
        prop = db.query(Property).filter_by(id=mapping.property_id, tenant_id=tenant_id).first()
        clash = booking_service.find_conflicts(db, tenant_id, prop.id, check_in, check_out)
        stay = booking_service.create_booking(
            db, tenant_id, guest_id=_guest_for(db, tenant_id, rev), prop=prop, check_in=check_in, check_out=check_out,
            adults=adults, children=children, total_amount=amount, channel_source=SOURCE, strict_stage=False,
            internal_notes=f"{ota} booking {link.ota_reservation_code or booking_id} (via Channex)",
            reason=f"Booked on {ota} via Channex", audit_extra={"channex_booking_id": booking_id, "ota": ota},
        )
        link.stay_id = stay.id
        if clash:
            _task(db, tenant_id, f"Overbooking: {ota} booking {check_in.isoformat()} to {check_out.isoformat()} "
                                 f"overlaps another booking on {prop.name}", stay, check_in)
        return done("created")

    moved = (stay.check_in, stay.check_out) != (check_in, check_out)
    stay.check_in, stay.check_out, stay.adults, stay.children = check_in, check_out, adults, children
    if amount is not None:
        stay.total_amount = amount
    if stay.status == "cancelled":
        stay.status = "confirmed"
    if moved and booking_service.find_conflicts(db, tenant_id, stay.property_id, check_in, check_out, exclude_stay_id=stay.id):
        _task(db, tenant_id, f"Overbooking: changed {ota} booking {check_in.isoformat()} to {check_out.isoformat()} "
                             f"overlaps another booking", stay, check_in)
    append_audit(db, tenant_id=tenant_id, action="booking.updated_from_channex", target_type="booking", target_id=stay.id,
                 payload={"channex_booking_id": booking_id, "check_in": check_in.isoformat(),
                          "check_out": check_out.isoformat()})
    return done("updated")


def pull_tenant(db: Session, tenant_id: str, client: ChannexClient | None = None) -> dict:
    """Read the feed, store each revision (own savepoint), commit, then acknowledge it. Pushes availability afterwards
    for the units that changed."""
    from app.models.channex import ChannexMapping

    own = client is None
    client = client or client_for(db, tenant_id)
    counts: dict[str, int] = {}
    touched: set[str] = set()
    try:
        by_room_type = {m.channex_room_type_id: m for m in db.query(ChannexMapping).filter_by(tenant_id=tenant_id)}
        for rev in client.booking_feed():
            try:
                # No savepoint: identity resolution commits on its own. Each revision is its own transaction instead.
                result = apply_revision(db, tenant_id, rev, by_room_type)
                db.commit()
            except Exception as exc:  # noqa: BLE001 -- one bad revision must not stop the others; not acked, retried
                db.rollback()
                log.error("channex_revision_failed", tenant_id=tenant_id, revision_id=rev.get("id"), error=str(exc)[:300])
                counts["failed"] = counts.get("failed", 0) + 1
                continue
            counts[result] = counts.get(result, 0) + 1
            if result == "unmapped":
                continue
            try:
                client.ack(str(rev.get("id")))
            except ChannexError as exc:
                log.warning("channex_ack_failed", tenant_id=tenant_id, revision_id=rev.get("id"), error=str(exc))
            if result in ("created", "updated", "cancelled"):
                m = by_room_type.get(((rev.get("rooms") or [{}])[0]).get("room_type_id"))
                if m is not None:
                    touched.add(m.property_id)
        if touched:
            push_tenant(db, tenant_id, client=client, only=touched)
    finally:
        if own:
            client.close()
    if counts:
        log.info("channex_pull_done", tenant_id=tenant_id, **counts)
    return counts
