"""Ops files API (migration 179): one file per booking, caravan pack first. Capabilities from 178.

Files       GET /ops/files?state= · GET /ops/files/today · GET /ops/files/{id}/report.pdf · POST /ops/files/sync · GET /ops/files/by-stay/{stay_id} · GET /ops/files/{id}
Steps       POST /ops/files/{id}/accept | /crew | /dispatch | /return | /settle | /close
Checklist   PUT /ops/files/{id}/checklist/{key}
Money       POST /ops/files/{id}/expenses · POST /ops/files/{id}/extras · POST /ops/files/{id}/extras/{extra_id}/approve|remove

ops.write: checklist, accept, crew, return odometer, expenses, asking for an extra. ops.manage: dispatch (always a person's
tap), approving or removing an extra, settle, close, sync. Guest contact details are never returned here.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.ops import StaffProfile
from app.models.ops_files import OpsExpense, OpsExtra, OpsFile, OpsFileEvent
from app.models.property import Property, Stay
from app.models.user import User
from app.schemas.ops_files import (
    AcceptIn,
    CrewIn,
    ExpenseIn,
    ExtraIn,
    ItemSetIn,
    OdometerIn,
    SettleIn,
)
from app.services import booking_agenda_service, ops_today_service, ops_trip_report
from app.services import ops_money as money
from app.services import ops_trip_service as trips
from app.services.authz_service import require_capability

router = APIRouter(prefix="/ops/files", tags=["operations"])

_read = require_capability("ops.read", "ops.manage")
_write = require_capability("ops.write", "ops.manage")
_manage = require_capability("ops.manage")


def _stay_summary(db: Session, stay: Stay) -> dict:
    prop = db.query(Property.name).filter(Property.id == stay.property_id, Property.tenant_id == stay.tenant_id).first()
    return {
        "id": stay.id,
        "status": stay.status,
        "check_in": stay.check_in.isoformat(),
        "check_out": stay.check_out.isoformat(),
        "check_in_time": stay.check_in_time,
        "check_out_time": stay.check_out_time,
        "adults": stay.adults,
        "children": stay.children,
        "guest_name": (stay.guest.name if stay.guest is not None else None) or "Guest",
        "property_id": stay.property_id,
        "property_name": prop[0] if prop else None,
        "concierge_notes": stay.concierge_notes,
    }


def _card(db: Session, f: OpsFile) -> dict:
    st = trips.stage(db, f)
    return {
        "id": f.id,
        "pack": f.pack,
        "state": f.state,
        "step": st["step"],
        "step_name": st["step_name"],
        "next": st["next"],
        "stay": _stay_summary(db, money.stay_of(db, f)),
    }


def _full(db: Session, f: OpsFile) -> dict:
    d = money.details(f)
    crew_ids = [i for i in (d.driver_staff_id, d.helper_staff_id) if i]
    crew = {
        s.id: s.name
        for s in db.query(StaffProfile).filter(StaffProfile.tenant_id == f.tenant_id, StaffProfile.id.in_(crew_ids))
    }
    items = trips.readiness_items(db, f)

    def q(m):
        return db.query(m).filter(m.tenant_id == f.tenant_id, m.file_id == f.id)

    return {
        **_card(db, f),
        "stage": trips.stage(db, f),
        "details": d.model_dump(mode="json"),
        "crew": {
            "driver": crew.get(d.driver_staff_id),
            "helper": crew.get(d.helper_staff_id),
        },
        "gate": trips.gate(items),
        "checklist": [
            {
                "key": i.key,
                "label": i.label,
                "critical": i.critical,
                "source": i.source,
                "photo_required": i.photo_required,
                "status": i.status,
                "note": i.note,
                "has_photo": bool(i.photo_key),
                "ai_verdict": i.ai_verdict,
                "set_at": i.set_at.isoformat() if i.set_at else None,
            }
            for i in items
        ],
        "account": money.account(db, f),
        "expenses": [
            {
                "id": e.id,
                "category": e.category,
                "amount": e.amount,
                "vendor": e.vendor,
                "source": e.source,
                "bill_date": e.bill_date.isoformat() if e.bill_date else None,
                "has_photo": bool(e.photo_key),
            }
            for e in q(OpsExpense).order_by(OpsExpense.created_at)
        ],
        "extras": [
            {
                "id": x.id,
                "kind": x.kind,
                "label": x.label,
                "amount": x.amount,
                "status": x.status,
            }
            for x in q(OpsExtra).order_by(OpsExtra.created_at)
        ],
        "timeline": [
            {"at": e.at.isoformat(), "text": e.text, "auto": e.auto}
            for e in q(OpsFileEvent).order_by(OpsFileEvent.at, OpsFileEvent.id).limit(200)
        ],
        "close_blockers": trips.close_blockers(db, f) if f.state == "returned" else [],
    }


def _file(db: Session, user: User, file_id: str) -> OpsFile:
    return trips.get_file(db, user.tenant_id, file_id)


def _done(db: Session, f: OpsFile) -> dict:
    db.commit()
    db.refresh(f)
    return _full(db, f)


@router.get("")
def list_files(
    state: str | None = Query(None, max_length=200),
    user: User = Depends(_read),
    db: Session = Depends(get_db),
):
    q = db.query(OpsFile).join(Stay, Stay.id == OpsFile.stay_id).filter(OpsFile.tenant_id == user.tenant_id)
    if state:
        q = q.filter(OpsFile.state.in_([s.strip() for s in state.split(",") if s.strip()]))
    else:
        q = q.filter(OpsFile.state.notin_(("closed", "cancelled")))
    return [_card(db, f) for f in q.order_by(Stay.check_in, OpsFile.id).limit(200)]


@router.get("/today")
def today(user: User = Depends(_read), db: Session = Depends(get_db)):
    """The Ops Today screen in one read (ops_today_service): unit cards, what needs a person, today and tomorrow."""
    out = ops_today_service.build(db, user.tenant_id)
    db.commit()  # files opened for new bookings by the built-in sync
    return out


@router.post("/sync")
def sync(user: User = Depends(_manage), db: Session = Depends(get_db)):
    out = trips.sync_files(db, user.tenant_id, booking_agenda_service.tenant_today(db, user.tenant_id))
    db.commit()
    return out


@router.get("/by-stay/{stay_id}")
def by_stay(stay_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.tenant_id == user.tenant_id).first()
    if stay is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    f = trips.ensure_file(db, user.tenant_id, stay)
    if f is None:
        raise HTTPException(
            status_code=404,
            detail="This booking has no ops file (not live, or this business has no ops pack yet).",
        )
    return _done(db, f)


@router.get("/{file_id}")
def get_file(file_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    return _full(db, _file(db, user, file_id))


@router.get("/{file_id}/report.pdf")
def trip_report(file_id: str, user: User = Depends(_manage), db: Session = Depends(get_db)):
    """The Trip Account Report (Saleem shape). Money for the business, so owner/manager only; "DRAFT" until approved."""
    f = _file(db, user, file_id)
    pdf = ops_trip_report.render(ops_trip_report.build(db, f))
    stay = money.stay_of(db, f)
    name = f"trip-account-{stay.check_in.isoformat()}-{f.id[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/{file_id}/accept")
def accept(
    file_id: str,
    body: AcceptIn,
    user: User = Depends(_write),
    db: Session = Depends(get_db),
):
    f = trips.accept(db, _file(db, user, file_id), body, user.id)
    return _done(db, f)


@router.post("/{file_id}/crew")
def crew(
    file_id: str,
    body: CrewIn,
    user: User = Depends(_write),
    db: Session = Depends(get_db),
):
    return _done(db, trips.set_crew(db, _file(db, user, file_id), body, user.id))


@router.put("/{file_id}/checklist/{key}")
def set_item(
    file_id: str,
    key: str,
    body: ItemSetIn,
    user: User = Depends(_write),
    db: Session = Depends(get_db),
):
    f = _file(db, user, file_id)
    trips.set_item(db, f, key, body.status, body.note, user_id=user.id)
    return _done(db, f)


@router.post("/{file_id}/dispatch")
def dispatch(
    file_id: str,
    body: OdometerIn,
    user: User = Depends(_manage),
    db: Session = Depends(get_db),
):
    return _done(db, trips.dispatch(db, _file(db, user, file_id), body.reading_km, user.id))


@router.post("/{file_id}/return")
def returned(
    file_id: str,
    body: OdometerIn,
    user: User = Depends(_write),
    db: Session = Depends(get_db),
):
    return _done(
        db,
        trips.end_trip(db, _file(db, user, file_id), body.reading_km, actor_id=user.id),
    )


@router.post("/{file_id}/settle")
def settle(
    file_id: str,
    body: SettleIn,
    user: User = Depends(_manage),
    db: Session = Depends(get_db),
):
    return _done(db, trips.settle(db, _file(db, user, file_id), body.step, user.id))


@router.post("/{file_id}/close")
def close(file_id: str, user: User = Depends(_manage), db: Session = Depends(get_db)):
    return _done(db, trips.close(db, _file(db, user, file_id), user.id))


@router.post("/{file_id}/expenses", status_code=201)
def add_expense(
    file_id: str,
    body: ExpenseIn,
    user: User = Depends(_write),
    db: Session = Depends(get_db),
):
    f = _file(db, user, file_id)
    money.add_expense(db, f, body, actor_id=user.id)
    return _done(db, f)


@router.post("/{file_id}/extras", status_code=201)
def propose_extra(
    file_id: str,
    body: ExtraIn,
    user: User = Depends(_write),
    db: Session = Depends(get_db),
):
    f = _file(db, user, file_id)
    money.propose_extra(db, f, body, user.id)
    return _done(db, f)


@router.post("/{file_id}/extras/{extra_id}/{action}")
def decide_extra(
    file_id: str,
    extra_id: str,
    action: str,
    user: User = Depends(_manage),
    db: Session = Depends(get_db),
):
    f = _file(db, user, file_id)
    if action == "approve":
        money.approve_extra(db, f, extra_id, user.id)
    elif action == "remove":
        money.remove_extra(db, f, extra_id, user.id)
    else:
        raise HTTPException(status_code=404, detail="Unknown action")
    trips.refresh(db, f)
    return _done(db, f)
