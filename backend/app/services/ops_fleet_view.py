"""The Fleet screen and the fleet part of Ops today, in one place (read side of ops_fleet_service).

`fleet` = one card per vehicle (papers, open defects, services, onboard stock, its problems); `needs` = the same problems in
Ops today's "Needs you" shape (action open_fleet, or open_staff for a person's papers), red first.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.models.ops import StaffProfile
from app.models.ops_fleet import OpsInventoryItem, OpsPaper, OpsService
from app.models.property import Property
from app.schemas.ops_fleet import PAPER_KINDS, VEHICLE_PAPER_KINDS
from app.services.ops_fleet_service import (
    low,
    open_defects,
    paper_level,
    paper_words,
    service_state,
    vehicle_km,
    vehicles,
)

_ORDER = {"red": 0, "amber": 1, None: 2}


def _need(level: str, unit: str, title: str, detail: str, key: str, action: str) -> dict:
    return {
        "key": key,
        "level": level,
        "unit": unit,
        "title": title,
        "detail": detail,
        "file_id": None,
        "item_id": None,
        "action": action,
    }


def _vehicle_needs(p: Property, papers, services, defects, items, km, today) -> list[dict]:
    out = []
    for pp in papers:
        lvl = paper_level(pp.expires_on, today)
        if lvl:
            out.append(
                _need(
                    lvl,
                    p.name,
                    f"{pp.name}: {paper_words(pp, today).lower()}",
                    "Renew it and enter the new date.",
                    f"paper:{pp.id}:{pp.expires_on}",
                    "open_fleet",
                )
            )
    for d in defects:
        out.append(
            _need(
                "red" if d.severity == "critical" else "amber",
                p.name,
                f"Defect: {d.title}",
                "Off sale and cannot be dispatched until it is fixed and closed."
                if d.severity == "critical"
                else "Fix it when the vehicle is free.",
                f"defect:{d.id}",
                "open_fleet",
            )
        )
    for s in services:
        lvl, words = service_state(s, km, today)
        if lvl:
            out.append(
                _need(lvl, p.name, f"{s.name}: {words.lower()}", "Book the service.", f"service:{s.id}", "open_fleet")
            )
    short = [it for it in items if low(it)]
    if short:
        out.append(
            _need(
                "amber",
                p.name,
                "Restock "
                + ", ".join(f"{it.name} ({it.count} of {it.par})" for it in short[:4])
                + ("…" if len(short) > 4 else ""),
                "Below the level kept on board.",
                f"stock:{p.id}:" + ",".join(sorted(it.id for it in short)),
                "open_fleet",
            )
        )
    return out


def _by_property(rows) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r.property_id, []).append(r)
    return out


def _load(db: Session, tenant_id: str):
    papers = _by_property(
        db.query(OpsPaper)
        .filter(OpsPaper.tenant_id == tenant_id, OpsPaper.active.is_(True), OpsPaper.property_id.isnot(None))
        .order_by(OpsPaper.kind)
    )
    services = _by_property(
        db.query(OpsService).filter(OpsService.tenant_id == tenant_id).order_by(OpsService.created_at)
    )
    defects = _by_property(open_defects(db, tenant_id))
    items = _by_property(db.query(OpsInventoryItem).filter_by(tenant_id=tenant_id).order_by(OpsInventoryItem.name))
    return papers, services, defects, items


def staff_needs(db: Session, tenant_id: str, today: date) -> list[dict]:
    out = []
    for p, s in (
        db.query(OpsPaper, StaffProfile)
        .join(StaffProfile, StaffProfile.id == OpsPaper.staff_id)
        .filter(OpsPaper.tenant_id == tenant_id, OpsPaper.active.is_(True), StaffProfile.active.is_(True))
    ):
        lvl = paper_level(p.expires_on, today)
        if lvl:
            detail = "Cannot drive trips ending after this date." if p.kind == "hmv_licence" else "Ask for the new one."
            out.append(
                _need(
                    lvl,
                    s.name,
                    f"{p.name}: {paper_words(p, today).lower()}",
                    detail,
                    f"paper:{p.id}:{p.expires_on}",
                    "open_staff",
                )
            )
    return out


def needs(db: Session, tenant_id: str, today: date) -> dict[str, list[dict]]:
    """property_id -> that vehicle's needs, plus "" -> the people's papers. Red first within each."""
    papers, services, defects, items = _load(db, tenant_id)
    out = {}
    for p in vehicles(db, tenant_id):
        km = vehicle_km(db, tenant_id, p.id)
        n = _vehicle_needs(
            p,
            papers.get(p.id, []),
            [s for s in services.get(p.id, []) if s.status == "open"],
            defects.get(p.id, []),
            items.get(p.id, []),
            km,
            today,
        )
        if n:
            out[p.id] = sorted(n, key=lambda x: _ORDER[x["level"]])
    staff = staff_needs(db, tenant_id, today)
    if staff:
        out[""] = staff
    return out


def fleet(db: Session, tenant_id: str, today: date) -> list[dict]:
    papers, services, defects, items = _load(db, tenant_id)
    cards = []
    for p in vehicles(db, tenant_id):
        km = vehicle_km(db, tenant_id, p.id)
        mine_s = services.get(p.id, [])
        open_s = [s for s in mine_s if s.status == "open"]
        n = _vehicle_needs(p, papers.get(p.id, []), open_s, defects.get(p.id, []), items.get(p.id, []), km, today)
        tone = "red" if any(x["level"] == "red" for x in n) else "amber" if n else "ok"
        cards.append(
            {
                "property_id": p.id,
                "name": p.name,
                "km": km,
                "tone": tone,
                "problems": [x["title"] for x in sorted(n, key=lambda x: _ORDER[x["level"]])],
                "papers": [
                    {
                        "id": x.id,
                        "kind": x.kind,
                        "name": x.name,
                        "number": x.number,
                        "expires_on": x.expires_on.isoformat() if x.expires_on else None,
                        "level": paper_level(x.expires_on, today),
                        "words": paper_words(x, today),
                        "has_file": bool(x.file_key),
                    }
                    for x in papers.get(p.id, [])
                ],
                "missing_papers": [
                    PAPER_KINDS[k][0]
                    for k in VEHICLE_PAPER_KINDS
                    if k != "other" and not any(x.kind == k for x in papers.get(p.id, []))
                ],
                "defects": [
                    {
                        "id": d.id,
                        "title": d.title,
                        "detail": d.detail,
                        "severity": d.severity,
                        "source": d.source,
                        "file_id": d.file_id,
                        "reported_at": d.created_at.isoformat() if d.created_at else None,
                    }
                    for d in defects.get(p.id, [])
                ],
                "services": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "due_on": s.due_on.isoformat() if s.due_on else None,
                        "due_km": s.due_km,
                        "status": s.status,
                        "level": service_state(s, km, today)[0],
                        "words": service_state(s, km, today)[1],
                    }
                    for s in open_s + [s for s in mine_s if s.status == "done"][-3:]
                ],
                "inventory": [
                    {
                        "id": it.id,
                        "name": it.name,
                        "par": it.par,
                        "count": it.count,
                        "low": low(it),
                        "counted_at": it.counted_at.isoformat() if it.counted_at else None,
                    }
                    for it in items.get(p.id, [])
                ],
            }
        )
    return cards
