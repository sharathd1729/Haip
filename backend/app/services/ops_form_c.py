"""Form C helper (ops gap 5, Nov 2026). India asks whoever houses a foreign guest to file Form C with the Bureau of
Immigration within 24 hours of arrival, one per guest. HAIP NEVER files it: it prepares the data and reminds a person.

- Arrival = the villa check-in / caravan dispatch tap (`OpsFile.dispatched_at`), else, once the check-in date has come,
  that day at the booking's check-in time (12:00 when none) in the workspace's timezone.
- At arrival, each guest the form says is not an Indian citizen gets ONE ops item (category `form_c`, duty ops_manager,
  high; the roster + escalation decide who hears), due arrival + 24 h; the guest row in the form remembers it
  (`guests[i].form_c`). A website booking that said "not Indian" but whose guest never filled the form gets one item
  for the booking (`hint_form_c`), closed again once the form names the guests.
- The stay page shows a "Form C data" sheet per guest in the portal's order (`sheet`): numbers masked; the full
  passport / visa numbers and the photos only through `reveal` (capability guests.pii.reveal, audited
  `guest.passport.reveal`, like guest.pii.reveal).
- A manager ticks "Submitted on the portal" (`mark_submitted`): the item closes, audited `ops.form_c.submitted`.
Runs: form submit, villa check-in, caravan dispatch, and hourly via ops_auto_messages.run_tenant (the date arriving).
"""

from datetime import UTC, date, datetime, time, timedelta

import structlog
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import append_audit
from app.core.tenant_tz import get_tz
from app.models.ops import OpsItem
from app.models.ops_files import OpsFile
from app.models.ops_fleet import OpsGuestForm
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.schemas.ops_fleet import VISA_TYPES
from app.services import ops_escalation_service as esc
from app.services import ops_guest_form as gf
from app.services import ops_money as money
from app.services import ops_pack_catalog as packs

log = structlog.get_logger()

CATEGORY = "form_c"
NOTE = "Rules vary by state and FRRO office; confirm with your local FRRO."
ENDED = ("closed", "cancelled")
ITEM_HOURS = 24


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _tz(db: Session, tenant_id: str):
    t = db.get(Tenant, tenant_id)
    return get_tz(t) if t else UTC


def arrival_at(db: Session, f: OpsFile, stay: Stay, now: datetime | None = None) -> datetime | None:
    """When the guests arrived, or None while they have not (no check-in tap and the check-in date not reached)."""
    if f.dispatched_at is not None:
        return _aware(f.dispatched_at)
    tz = _tz(db, f.tenant_id)
    try:
        hh, mm = (int(x) for x in (stay.check_in_time or "12:00").split(":")[:2])
        at = time(hh, mm)
    except (TypeError, ValueError):
        at = time(12, 0)
    planned = datetime.combine(stay.check_in, at, tzinfo=tz)
    return planned if _now(now) >= planned else None


def _after_commit(db: Session, tenant_id: str, sends: list[str]) -> None:
    """Deliver the alerts once the caller commits (a lost queue message is re-offered by the escalation tick)."""
    if not sends:
        return

    def fire(_session) -> None:
        from app.workers.tasks.ops_escalation import queue_delivery

        queue_delivery(tenant_id, sends)

    event.listen(db, "after_commit", fire, once=True)


def _unit(db: Session, stay: Stay) -> str:
    return db.query(Property.name).filter_by(id=stay.property_id, tenant_id=stay.tenant_id).scalar() or "Stay"


def _local(dt: datetime, tz) -> str:
    return dt.astimezone(tz).strftime("%d %b, %I:%M %p").lstrip("0").replace(", 0", ", ")


def _raise(db: Session, f: OpsFile, stay: Stay, title: str, summary: str, due: datetime, now: datetime) -> tuple:
    item, sends = esc.create_item(
        db,
        f.tenant_id,
        title=title[:200],
        severity="high",
        duty="ops_manager",
        kind="form_c",
        category=CATEGORY,
        source="system",
        summary=summary,
        property_id=stay.property_id,
        stay_id=stay.id,
        guest_id=stay.guest_id,
        now=now,
    )
    item.resolve_due_at = due
    return item, sends


def sync(db: Session, f: OpsFile, now: datetime | None = None) -> list[str]:
    """Raise the Form C items that are due now (idempotent). Returns the alert send ids (also queued after commit)."""
    now = _now(now)
    form = gf.form_of(db, f)
    if form is None or f.state in ENDED:
        return []
    d = form.data or {}
    abroad = [(n, g) for n, g in enumerate(d.get("guests") or [], start=1) if gf.is_foreign(g)]
    if not abroad and not d.get("hint_foreign"):
        return []
    stay = money.stay_of(db, f)
    arrived = arrival_at(db, f, stay, now)
    if arrived is None:
        return []
    tz, unit, sends, changed = _tz(db, f.tenant_id), _unit(db, stay), [], False
    due = (arrived + timedelta(hours=ITEM_HOURS)).astimezone(UTC)
    word = gf.file_word(f)
    for n, g in abroad:
        fc = g.get("form_c") or {}
        if fc.get("item_id") or fc.get("submitted_at"):
            continue
        item, s = _raise(
            db,
            f,
            stay,
            f"{unit}: Form C due for guest {n} (from {g.get('nationality')})",
            f"A guest who is not an Indian citizen arrived {_local(arrived, tz)}. File Form C on the Bureau of "
            f'Immigration portal within 24 hours of arrival (by {_local(due, tz)}), then tick "Submitted on the portal" '
            f"on the {word} page, where the Form C data is ready to copy. {NOTE}",
            due,
            now,
        )
        g["form_c"] = {"item_id": item.id, "due_at": due.isoformat(), "submitted_at": None}
        sends += s
        changed = True
        money.event(db, f, f"Form C for guest {n} is due by {_local(due, tz)}: an ops item was raised.", auto=True)
    hint = d.get("hint_form_c") or {}
    if form.submitted_at is None and d.get("hint_foreign") and not hint:
        item, s = _raise(
            db,
            f,
            stay,
            f"{unit}: Form C for a guest from abroad",
            f"This booking said the guest is not an Indian citizen, and the guest details form is not filled. Collect "
            f"passport and visa details at check-in (or send the form link) and file Form C on the Bureau of "
            f"Immigration portal within 24 hours of arrival (by {_local(due, tz)}). {NOTE}",
            due,
            now,
        )
        d["hint_form_c"] = {"item_id": item.id, "due_at": due.isoformat()}
        sends += s
        changed = True
        money.event(
            db,
            f,
            "Form C: a guest from abroad arrived and the guest form is not filled. An ops item was raised.",
            auto=True,
        )
    elif form.submitted_at is not None and hint.get("item_id") and not hint.get("closed"):
        item = db.get(OpsItem, hint["item_id"])
        if item is not None and item.tenant_id == f.tenant_id:
            esc.resolve(
                db, item, note="The guest form now names the guests: one Form C item per guest from abroad.", now=now
            )
        hint["closed"] = True
        changed = True
    if changed:
        form.data = d
        flag_modified(form, "data")
        db.flush()
    _after_commit(db, f.tenant_id, sends)
    return sends


def run_tenant(db: Session, tenant_id: str, now: datetime | None = None) -> int:
    """Hourly: open files whose form names a guest from abroad (or a website hint) and whose check-in has come."""
    now, raised = _now(now), 0
    today = now.astimezone(_tz(db, tenant_id)).date()
    rows = (
        db.query(OpsFile)
        .join(OpsGuestForm, OpsGuestForm.file_id == OpsFile.id)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .filter(
            OpsFile.tenant_id == tenant_id,
            OpsFile.state.notin_(ENDED),
            Stay.check_in <= today,
            Stay.check_in >= today - timedelta(days=30),
        )
        .all()
    )
    for f in rows:
        try:
            raised += len(sync(db, f, now))
            db.commit()
        except Exception as exc:  # noqa: BLE001 -- one bad file never stops the others
            db.rollback()
            log.error("ops_form_c_sync_failed", tenant_id=tenant_id, file_id=f.id, error=str(exc)[:300])
    return raised


# ── Staff: the sheet, the reveal, the tick ──────────────────────────────────


def _guest(form: OpsGuestForm | None, n: int) -> dict:
    guests = ((form.data or {}).get("guests") if form is not None else None) or []
    if form is None or form.submitted_at is None or not 1 <= n <= len(guests) or not gf.is_foreign(guests[n - 1]):
        raise HTTPException(status_code=404, detail="No guest from abroad with that number on this form.")
    return guests[n - 1]


def _dmy(iso: str | None) -> str | None:
    return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else None


def _row(key: str, label: str, value, hint: str | None = None, *, fmt: str | None = None, masked: bool = False) -> dict:
    return {"key": key, "label": label, "value": value, "hint": hint, "format": fmt, "masked": masked}


def sheet(db: Session, f: OpsFile, n: int, *, reveal: bool = False, can_reveal: bool = False) -> dict:
    """The Form C fields in the portal's order. Masked unless `reveal` (the caller checked the capability and audits)."""
    form = gf.form_of(db, f)
    g = _guest(form, n)
    fb, fc = g.get("foreign") or {}, g.get("form_c") or {}
    stay = money.stay_of(db, f)
    tz = _tz(db, f.tenant_id)
    arrived = arrival_at(db, f, stay)
    nums = gf.numbers(g) if reveal else {}
    unit = packs.get(f.pack)["unit_word"] if f.pack in packs.PACKS else "property"
    parts = (g.get("name") or "").split()
    photo = "Read it from the passport photo"
    ask = "Not on the form: ask the guest"
    visa_word = "OCI card" if fb.get("visa_type") == "oci" else "Visa"

    def number(kind: str, last4: str | None):
        if not last4:
            return None
        return nums.get(kind) if reveal else f"••••{last4}"

    rows = [
        _row("surname", "Surname", parts[-1] if parts else None, "Check the spelling against the passport"),
        _row("given_name", "Given name", " ".join(parts[:-1]) or None, "Check the spelling against the passport"),
        _row("gender", "Gender", None, photo),
        _row(
            "date_of_birth",
            "Date of birth",
            None,
            f"{photo} (age given: {g['age']})" if g.get("age") is not None else photo,
        ),
        _row("nationality", "Nationality", g.get("nationality"), fmt="country"),
        _row("address_abroad", "Address in the country of residence", None, ask),
        _row(
            "passport_number",
            "Passport number",
            number("passport", fb.get("passport_last4")),
            masked=not reveal and bool(fb.get("passport_last4")),
        ),
        _row("passport_issued", "Passport place and date of issue", None, photo),
        _row("passport_expiry", "Passport expiry date", _dmy(fb.get("passport_expires_on"))),
        _row(
            "visa_number",
            f"{visa_word} number",
            number("visa", fb.get("visa_last4")),
            masked=not reveal and bool(fb.get("visa_last4")),
        ),
        _row("visa_type", "Visa type", VISA_TYPES.get(fb.get("visa_type") or "")),
        _row(
            "visa_issued", f"{visa_word} place and date of issue", None, f"Read it from the {visa_word.lower()} photo"
        ),
        _row("visa_expiry", f"{visa_word} expiry date", _dmy(fb.get("visa_expires_on"))),
        _row("arrived_from", "Arrived from (city, country)", fb.get("arrived_from") or None),
        _row("arrived_india", "Date of arrival in India", _dmy(fb.get("arrived_india_on"))),
        _row(
            "arrived_here",
            f"Date and time of arrival at the {unit}",
            arrived.astimezone(tz).strftime("%d/%m/%Y %H:%M") if arrived else None,
            None if arrived else "Not arrived yet",
        ),
        _row(
            "duration",
            "Intended stay (days)",
            str((stay.check_out - stay.check_in).days or 1),
            f"Until {stay.check_out:%d/%m/%Y}",
        ),
        _row("next_destination", "Next destination", fb.get("onward_to") or None),
        _row("purpose", "Purpose of visit", None, ask),
        _row("employed", "Employed in India?", None, ask),
        _row("contact_india", "Contact number in India", None, "The booking's phone number (see the booking)"),
    ]
    out = {
        "guest": n,
        "fields": rows,
        "note": NOTE,
        "photos": [],
        "can_reveal": can_reveal,
        "revealed": reveal,
        "due_at": fc.get("due_at"),
        "submitted_at": fc.get("submitted_at"),
        "submitted_note": fc.get("note"),
    }
    if reveal:
        from app.services import media_storage

        for kind, key in (("passport", fb.get("passport_photo_key")), ("visa", fb.get("visa_photo_key"))):
            if key:
                out["photos"].append(
                    {
                        "kind": kind,
                        "url": media_storage.get_presigned_media_url(key, expires_in=600),
                        "pdf": key.endswith(".pdf"),
                    }
                )
    return out


def reveal(db: Session, f: OpsFile, n: int, user_id: str) -> dict:
    """The full numbers + photos for one guest. Caller has already checked guests.pii.reveal. Audited every time."""
    out = sheet(db, f, n, reveal=True, can_reveal=True)
    append_audit(
        db,
        tenant_id=f.tenant_id,
        action="guest.passport.reveal",
        actor_user_id=user_id,
        target_type="ops_file",
        target_id=f.id,
        payload={"stay_id": f.stay_id, "guest": n, "photos": len(out["photos"]), "fields": ["passport", "visa"]},
    )
    return out


def mark_submitted(db: Session, f: OpsFile, n: int, user_id: str, note: str | None) -> dict:
    form = gf.form_of(db, f)
    g = _guest(form, n)
    fc = dict(g.get("form_c") or {})
    if fc.get("submitted_at"):
        raise HTTPException(status_code=409, detail="Already marked as submitted.")
    now = datetime.now(UTC)
    clean = gf._clean(note, 300) or None
    item = db.get(OpsItem, fc["item_id"]) if fc.get("item_id") else None
    if item is not None and item.tenant_id == f.tenant_id:
        esc.resolve(
            db, item, user_id=user_id, note="Form C submitted on the portal" + (f": {clean}" if clean else ""), now=now
        )
    fc.update({"submitted_at": now.isoformat(), "submitted_by": user_id, "note": clean})
    g["form_c"] = fc
    flag_modified(form, "data")
    money.event(db, f, f"Form C for guest {n} marked as submitted on the portal", actor_id=user_id)
    append_audit(
        db,
        tenant_id=f.tenant_id,
        action="ops.form_c.submitted",
        actor_user_id=user_id,
        target_type="ops_file",
        target_id=f.id,
        payload={"stay_id": f.stay_id, "guest": n, "item_id": fc.get("item_id")},
    )
    db.flush()
    return fc
