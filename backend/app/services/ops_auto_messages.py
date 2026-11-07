"""Automatic trip messages (Ops phase 2, the plan's T-72 h / T-24 h rows). Run hourly by Celery (ops.auto_messages_tenant).

crew_brief     72 h before pickup, once the trip is accepted and crewed: driver and helper each get the route, stops, guest
               first name, party, pickup time and special requests.
helper_chase   24 h before: the helper gets the checklist photos still missing (none missing = nothing sent).
guest_pretrip  24 h before, once a driver is set: the guest gets the vehicle, driver name and reporting time.
deposit_nudge  24 h after return with the deposit still held: an ops item for the manager (the roster decides who hears,
               the usual alert template + escalation); it is resolved by itself once the deposit is settled.
midstay_check  day 2 of a 2+ night stay, caravan and villa (ops_midstay_check, its own guards and reply handling).

Staff get plain text while their 24-hour window is open (staff_profiles.last_inbound_at), else the pack's template
(ops_templates). The guest gets text inside their window (wa_booking_messages.send_guest_text), else the approved template.
Each message is one ops_auto_messages row per (file, kind, recipient): sent = never again; failed = retried next hour and
shown on Ops today until it goes. Nothing is dropped silently.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.orm import Session

from app.core.tenant_tz import get_tz
from app.models.ops import OpsItem, StaffProfile
from app.models.ops_files import OpsFile
from app.models.ops_fleet import OpsAutoMessage
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.services import lead_alert_sender
from app.services import ops_escalation_service as esc
from app.services import ops_money as money
from app.services import ops_trip_service as trips
from app.services.ops_alert_sender import _clean
from app.services.ops_today_service import _hours_until

log = structlog.get_logger()

WINDOW = timedelta(hours=24)
LABELS = {
    "crew_brief": "Crew brief",
    "helper_chase": "Photo reminder",
    "guest_pretrip": "Pre-trip message to the guest",
    "deposit_nudge": "Deposit refund reminder",
}


def first_name(name: str | None) -> str:
    """'Mr. Saleem' stays 'Mr. Saleem'; 'Krithika(Brandaid Events)' becomes 'Krithika' (prototype messages.ts)."""
    import re

    n = re.sub(r"\(.*?\)", " ", name or "").strip()
    m = re.match(r"^(Mr|Mrs|Ms|Dr)\.?\s+(\S+)", n, re.IGNORECASE)
    return f"{m.group(1)}. {m.group(2)}" if m else (n.split()[0] if n.split() else "there")


def _pickup(stay: Stay) -> str:
    t = stay.check_in_time or "12:00"
    try:
        h, mi = int(t[:2]), int(t[3:5])
    except ValueError:
        h, mi = 12, 0
    return (
        f"{stay.check_in.strftime('%a %d %b').replace(' 0', ' ')}, {h % 12 or 12}:{mi:02d} {'pm' if h >= 12 else 'am'}"
    )


def _party(stay: Stay) -> str:
    kids = f" + {stay.children} kid{'s' if stay.children != 1 else ''}" if stay.children else ""
    return f"{stay.adults or 0} adult{'s' if stay.adults != 1 else ''}{kids}"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def send_staff(db: Session, staff: StaffProfile, text: str, template: str, values: list[str]) -> tuple[str, str | None]:
    """(via, None) when Meta accepted it, else (via, reason). Text inside the 24-hour window, else the template."""
    if not staff.active:
        return "text", f"{staff.name} is no longer active"
    if staff.whatsapp_opt_in_at is None:
        return "text", f"{staff.name} has not agreed to WhatsApp messages (tick it on the staff screen)"
    phone_number_id, token = lead_alert_sender.wa_credentials(db, staff.tenant_id)
    if not phone_number_id or not token:
        return "text", "WhatsApp is not connected for this workspace"
    last = staff.last_inbound_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    adapter = lead_alert_sender._adapter(phone_number_id, token)
    try:
        if last is not None and datetime.now(UTC) - last <= WINDOW:
            _run(adapter.send_text(to=staff.phone_e164, body=text))
            return "text", None
        language = lead_alert_sender.template_approved(db, staff.tenant_id, template)
        if language is None:
            return "template", f"{staff.name} has not messaged in 24 hours and template {template} is not approved yet"
        comps = [{"type": "body", "parameters": [{"type": "text", "text": _clean(v, 300)} for v in values]}]
        _run(
            adapter.send_template(to=staff.phone_e164, template_name=template, language_code=language, components=comps)
        )
        return "template", None
    except Exception as exc:  # noqa: BLE001 -- the reason is kept on the row and shown on Ops today
        return "template", lead_alert_sender.meta_error(exc)[1]


def _row(db: Session, f: OpsFile, kind: str, recipient: str) -> OpsAutoMessage | None:
    """The row to (re)try, or None when it already went."""
    row = (
        db.query(OpsAutoMessage).filter_by(tenant_id=f.tenant_id, file_id=f.id, kind=kind, recipient=recipient).first()
    )
    if row is None:
        return OpsAutoMessage(tenant_id=f.tenant_id, file_id=f.id, kind=kind, recipient=recipient, attempts=0)
    return None if row.status == "sent" else row


def _record(db: Session, row: OpsAutoMessage, via: str, reason: str | None) -> bool:
    row.via, row.reason, row.attempts = via, reason, (row.attempts or 0) + 1
    row.status = "failed" if reason else "sent"
    if not reason:
        row.sent_at = datetime.now(UTC)
    if row not in db:
        db.add(row)
    db.flush()
    if reason:
        log.warning(
            "ops_auto_message_failed", tenant_id=row.tenant_id, file_id=row.file_id, kind=row.kind, reason=reason
        )
    return not reason


def _crew(db: Session, f: OpsFile) -> tuple[StaffProfile | None, StaffProfile | None]:
    d = money.details(f)
    ids = {
        s.id: s
        for s in db.query(StaffProfile).filter(
            StaffProfile.tenant_id == f.tenant_id,
            StaffProfile.id.in_([d.driver_staff_id or "-", d.helper_staff_id or "-"]),
        )
    }
    return ids.get(d.driver_staff_id), ids.get(d.helper_staff_id)


def _guest_pretrip(db: Session, f: OpsFile, stay: Stay, unit: str, driver: StaffProfile) -> tuple[str, str | None]:
    from app.services.booking_agenda_service import whatsapp_state
    from app.services.wa_booking_messages import Target, send_guest_template, send_guest_text

    first, when = first_name(stay.guest.name if stay.guest else None), _pickup(stay)
    target = Target("ops_file", f.id, "ops:", {"source": "ops", "ops_file_id": f.id}, "ops_file")
    if whatsapp_state(db, f.tenant_id, stay.guest_id)["window_open"]:
        text = f"Hello {first}, your {unit} is ready.\nDriver: {driver.name}\nReporting time: {when}\nSafe travels!"
        out, via = (
            send_guest_text(
                db,
                f.tenant_id,
                stay.guest,
                text,
                target=target,
                event="guest_pretrip",
                sender_kind="system",
                autonomous=True,
            ),
            "text",
        )
    else:
        out, via = (
            send_guest_template(
                db,
                f.tenant_id,
                stay.guest,
                "ops_guest_pretrip_v1",
                [first, unit, driver.name, when],
                target=target,
                event="guest_pretrip",
                sender_kind="system",
                autonomous=True,
            ),
            "template",
        )
    return via, None if out["status"] in ("queued", "duplicate") else out["reason"] or "not sent"


def run_file(db: Session, f: OpsFile, stay: Stay, unit: str, now: datetime, tz) -> list[str]:
    """One file's due messages. Returns ops alert send ids to deliver after commit."""
    hours = _hours_until(stay.check_in, stay.check_in_time, now, tz)
    sends: list[str] = []
    d = money.details(f)
    if f.state in trips.BEFORE_ROAD and 0 < hours <= 72:
        driver, helper = _crew(db, f)
        if f.accepted_at and driver and helper:
            route = (d.route or "to be confirmed") + (f" (stops: {', '.join(d.stops)})" if d.stops else "")
            first = first_name(stay.guest.name if stay.guest else None)
            requests = (stay.concierge_notes or "").strip() or "none"
            for person, role in ((driver, "driver"), (helper, "helper")):
                row = _row(db, f, "crew_brief", f"staff:{person.id}")
                if row is None:
                    continue
                text = (
                    f"Trip brief for {unit} ({role}).\nPickup: {_pickup(stay)}\nRoute: {route}\nGuest: {first} "
                    f"({_party(stay)})\nRequests: {requests}\nSend checklist photos with the check's name, for example: ac."
                )
                via, why = send_staff(
                    db, person, text, "ops_crew_brief_v1", [unit, _pickup(stay), route, first, _party(stay), requests]
                )
                _record(db, row, via, why)
        if 0 < hours <= 24 and helper:
            missing = [
                i.label.split(",")[0].split(":")[0]
                for i in trips.readiness_items(db, f)
                if i.photo_required and i.status != "green"
            ]
            row = _row(db, f, "helper_chase", f"staff:{helper.id}") if missing else None
            if row is not None:
                text = (
                    f"Reminder: {unit} leaves {_pickup(stay)}. Checklist photos still needed: {', '.join(missing)}. "
                    "Send each photo with its name, for example: ac."
                )
                via, why = send_staff(
                    db, helper, text, "ops_helper_chase_v1", [unit, _pickup(stay), ", ".join(missing)]
                )
                _record(db, row, via, why)
        if 0 < hours <= 24 and driver and (row := _row(db, f, "guest_pretrip", "guest")) is not None:
            via, why = _guest_pretrip(db, f, stay, unit, driver)
            _record(db, row, via, why)
    if f.state == "returned" and f.returned_at is not None:
        back = f.returned_at if f.returned_at.tzinfo else f.returned_at.replace(tzinfo=UTC)
        dep = money.account(db, f)["deposit"]
        if now - back >= timedelta(hours=24) and dep and dep["status"] == "held":
            row = _row(db, f, "deposit_nudge", "managers")
            if row is not None:
                _, ids = esc.create_item(
                    db,
                    f.tenant_id,
                    title=f"{unit}: refund deposit Rs {dep['amount']:,}",
                    severity="normal",
                    duty="ops_manager",
                    kind="manual",
                    category="deposit",
                    source="system",
                    summary=f"{first_name(stay.guest.name if stay.guest else None)}'s trip came back over 24 hours ago. "
                    "Refund the deposit (or deduct damage) within 48 hours of return.",
                    property_id=stay.property_id,
                    stay_id=stay.id,
                    guest_id=stay.guest_id,
                )
                sends += ids
                _record(db, row, "alert", None)
    return sends


def _settle_deposit_items(db: Session, tenant_id: str) -> None:
    """A deposit reminder whose deposit is no longer held is sorted: resolve it, so it stops escalating."""
    for item in db.query(OpsItem).filter(
        OpsItem.tenant_id == tenant_id,
        OpsItem.category == "deposit",
        OpsItem.status.in_(("open", "acknowledged")),
        OpsItem.stay_id.isnot(None),
    ):
        f = db.query(OpsFile).filter_by(tenant_id=tenant_id, stay_id=item.stay_id).first()
        dep = money.account(db, f)["deposit"] if f else None
        if dep is None or dep["status"] != "held":
            esc.resolve(db, item, note="Deposit settled")


def run_tenant(db: Session, tenant_id: str, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    tenant = db.get(Tenant, tenant_id)
    tz = get_tz(tenant) if tenant else UTC
    names = {p.id: p.name for p in db.query(Property).filter(Property.tenant_id == tenant_id)}
    sends: list[str] = []
    rows = (
        db.query(OpsFile, Stay)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .filter(OpsFile.tenant_id == tenant_id, OpsFile.state.in_(trips.BEFORE_ROAD + ("returned",)))
        .all()
    )
    for f, stay in rows:
        # One commit per file (the guest senders commit too): a bad file is rolled back alone and logged loudly.
        try:
            sends += run_file(db, f, stay, names.get(stay.property_id, "your trip"), now, tz)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.error("ops_auto_messages_file_failed", tenant_id=tenant_id, file_id=f.id, error=str(exc)[:300])
    _settle_deposit_items(db, tenant_id)
    db.commit()
    from app.services import ops_midstay_check

    ops_midstay_check.run_tenant(db, tenant_id, now, tz)
    return sends


def failed_needs(db: Session, tenant_id: str, names: dict[str, str]) -> list[dict]:
    """Messages that could not go, while they still matter: a Today need each (amber)."""
    out = []
    staff = {s.id: s.name for s in db.query(StaffProfile).filter_by(tenant_id=tenant_id)}
    for row, f, stay in (
        db.query(OpsAutoMessage, OpsFile, Stay)
        .join(OpsFile, OpsFile.id == OpsAutoMessage.file_id)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .filter(OpsAutoMessage.tenant_id == tenant_id, OpsAutoMessage.status == "failed")
    ):
        live = f.state == "returned" if row.kind == "deposit_nudge" else f.state in trips.BEFORE_ROAD
        if not live:
            continue
        who = (
            "the guest" if row.recipient == "guest" else staff.get(row.recipient.removeprefix("staff:"), "the manager")
        )
        out.append(
            {
                "key": f"automsg:{row.id}",
                "level": "amber",
                "unit": names.get(stay.property_id, "Trip"),
                "title": f"{LABELS.get(row.kind, row.kind)} not sent to {who}",
                "detail": (row.reason or "Unknown reason")
                + ". HAIP tries again every hour; send it yourself if it is urgent.",
                "file_id": f.id,
                "item_id": None,
                "action": "open_file",
            }
        )
    return out
