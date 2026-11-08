"""Villa stay meal plan (phase 4): meals per day (breakfast / lunch / dinner, guests, veg / non-veg, notes) kept on the
stay file (ops_files.details.meals, schemas/ops_files.py Meal). The cook gets the unconfirmed meals on WhatsApp and replies
"OK" (ops_photo_intake.handle_text -> cook_reply), or a person marks them confirmed. An unconfirmed meal for today is an Ops
Today need (ops_stay_today). Groceries bills are ordinary expenses (category groceries).
"""

import re
import uuid
from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.ops import StaffProfile
from app.models.ops_files import OpsFile
from app.schemas.ops_files import Meal, MealIn, VillaDetails
from app.services import ops_money as money
from app.services.ops_pack_catalog import STAY_PACKS

PACK = "villa"
OPEN = ("preparing", "ready", "staying", "checked_out", "settling")
_CONFIRM = re.compile(r"^\s*(ok|okay|yes|confirm(ed)?|done|noted|👍)(\W|$)", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(UTC)


def _conflict(msg: str) -> HTTPException:
    return HTTPException(status_code=409, detail=msg)


def _d(f: OpsFile) -> VillaDetails:
    return money.details(f)  # type: ignore[return-value]


def add_meal(db: Session, f: OpsFile, body: MealIn, actor_id: str) -> Meal:
    if f.state in ("closed", "cancelled", "settling"):
        raise _conflict("The stay is over: no more meals to plan.")
    stay = money.stay_of(db, f)
    if not stay.check_in <= date.fromisoformat(body.date) <= stay.check_out:
        raise HTTPException(status_code=422, detail="Pick a day of the stay.")
    d = _d(f)
    if any(m.date == body.date and m.meal == body.meal for m in d.meals):
        raise _conflict(f"{body.meal.title()} on that day is already planned. Remove it first to change it.")
    m = Meal(id=uuid.uuid4().hex[:10], **body.model_dump())
    d.meals = sorted([*d.meals, m], key=lambda x: (x.date, ("breakfast", "lunch", "dinner").index(x.meal)))
    money.save_details(f, d)
    money.event(
        db, f, f"Meal planned: {m.meal} {m.date}, {m.guests} guests, {m.food.replace('_', '-')}", actor_id=actor_id
    )
    return m


def remove_meal(db: Session, f: OpsFile, meal_id: str, actor_id: str) -> None:
    d = _d(f)
    m = next((x for x in d.meals if x.id == meal_id), None)
    if m is None:
        raise HTTPException(status_code=404, detail="Meal not found")
    d.meals = [x for x in d.meals if x.id != meal_id]
    money.save_details(f, d)
    money.event(db, f, f"Meal removed: {m.meal} {m.date}", actor_id=actor_id)


def confirm_meals(db: Session, f: OpsFile, meal_ids: list[str], by: str) -> list[Meal]:
    """by = a user id (a person marked it) or "cook" (the cook replied on WhatsApp)."""
    d, done = _d(f), []
    for m in d.meals:
        if m.id in meal_ids and m.confirmed_at is None:
            m.confirmed_at, m.confirmed_by = _now().isoformat(), by
            done.append(m)
    if not done and meal_ids:
        raise _conflict("Already confirmed.")
    money.save_details(f, d)
    who = "Cook" if by == "cook" else "Marked"
    money.event(db, f, f"{who} confirmed: " + ", ".join(f"{m.meal} {m.date}" for m in done), auto=by == "cook")
    return done


def meal_message(f: OpsFile, guest: str, villa: str) -> str:
    lines = [
        f"{m.date} {m.meal}: {m.guests} guests, {m.food.replace('_', '-')}" + (f" ({m.notes})" if m.notes else "")
        for m in _d(f).meals
        if m.confirmed_at is None
    ]
    return f"Meal plan for {guest} at {villa}:\n" + "\n".join(lines) + "\nReply OK to confirm."


def send_meals(db: Session, f: OpsFile, actor_id: str, *, send=None) -> int:
    """Send the unconfirmed meals to the cook on WhatsApp (best effort: Meta delivers free text only inside the cook's
    24-hour window). Returns how many meals went."""
    from app.models.property import Property
    from app.services import lead_alert_sender

    d = _d(f)
    cook = (
        db.query(StaffProfile).filter_by(id=d.cook_staff_id, tenant_id=f.tenant_id).first() if d.cook_staff_id else None
    )
    if cook is None:
        raise HTTPException(status_code=422, detail="Pick the cook first.")
    todo = [m for m in d.meals if m.confirmed_at is None]
    if not todo:
        raise _conflict("Every meal is confirmed already.")
    stay = money.stay_of(db, f)
    villa = db.query(Property.name).filter_by(id=stay.property_id, tenant_id=f.tenant_id).scalar() or "the villa"
    (send or lead_alert_sender.send_text)(
        db, f.tenant_id, cook.phone_e164, meal_message(f, stay.guest.name if stay.guest else "the guest", villa)
    )
    now = _now().isoformat()
    for m in todo:
        m.sent_at = now
    money.save_details(f, d)
    money.event(db, f, f"Meal plan sent to {cook.name} on WhatsApp ({len(todo)} meals)", actor_id=actor_id)
    return len(todo)


def cook_reply(db: Session, tenant_id: str, staff: StaffProfile, text: str) -> str | None:
    """ "OK" from a cook confirms every meal sent to them and not yet confirmed. None = not a meal reply."""
    if not _CONFIRM.match(text or ""):
        return None
    done: list[Meal] = []
    for f in db.query(OpsFile).filter(
        OpsFile.tenant_id == tenant_id, OpsFile.pack.in_(STAY_PACKS), OpsFile.state.in_(OPEN)
    ):
        d = _d(f)
        if d.cook_staff_id != staff.id:
            continue
        ids = [m.id for m in d.meals if m.sent_at and m.confirmed_at is None]
        if ids:
            done += confirm_meals(db, f, ids, "cook")
    if not done:
        return None
    return f"Thank you. {len(done)} meal{'s' if len(done) != 1 else ''} confirmed."


def unconfirmed_meals(f: OpsFile, day: date) -> list[Meal]:
    return [m for m in _d(f).meals if m.date == day.isoformat() and m.confirmed_at is None]
