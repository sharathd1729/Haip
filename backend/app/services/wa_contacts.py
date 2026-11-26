"""WhatsApp contacts (wa_subscribers): named lists, bulk actions, drip enrolment and 30-day growth.

Lists are rows in wa_contact_lists; membership is wa_subscribers.list_ids (JSON ids), filtered with the same
cast-to-text LIKE the inbox uses for conversations.labels. Everything is scoped by tenant_id.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Query, Session

from app.models.wa_contact_list import WaContactList
from app.services.wa_subscriber_import import MAX_TAG_LEN

log = structlog.get_logger()

MAX_LIST_NAME = 80
MAX_TARGETS = 20_000          # a "select all matching" never touches more than this in one action
INLINE_ENROL_LIMIT = 50       # more than this goes to Celery in batches
ENROL_BATCH = 50
ENROL_BATCH_GAP_S = 60        # one batch per minute keeps a large drip from flooding the WhatsApp number

BULK_ACTIONS = ("add_tag", "remove_tag", "add_to_list", "remove_from_list", "opt_out")


class ContactsError(ValueError):
    """Message is safe to show."""


def _sub():
    from app.api.v1.endpoints.messaging import WASubscriber
    return WASubscriber


def _json_has(column, value: str):
    # The stored text is json.dumps output, so match a json.dumps'd element. '!' escapes LIKE wildcards
    # (PostgreSQL's default escape is backslash, which json.dumps emits for non-ASCII).
    needle = json.dumps(value).replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return cast(column, String).like(f"%{needle}%", escape="!")


def matching(db: Session, tenant_id: str, *, opted_in: Optional[bool] = None, search: Optional[str] = None,
             list_id: Optional[str] = None, tag: Optional[str] = None) -> Query:
    """The one filter behind the list, its count, bulk "select all matching" and export."""
    S = _sub()
    q = db.query(S).filter(S.tenant_id == tenant_id)
    if opted_in is not None:
        q = q.filter(S.opted_in.is_(opted_in))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(or_(S.phone.ilike(term), S.name.ilike(term)))
    if list_id:
        q = q.filter(_json_has(S.list_ids, list_id))
    if tag:
        q = q.filter(_json_has(S.tags, tag))
    return q


def targets(db: Session, tenant_id: str, ids: Optional[list[str]], flt: Optional[dict]) -> list:
    """Contacts a bulk action applies to: picked ids, or everyone matching the page's filter."""
    S = _sub()
    if ids:
        if len(ids) > MAX_TARGETS:
            raise ContactsError(f"Pick at most {MAX_TARGETS:,} contacts at a time.")
        return db.query(S).filter(S.tenant_id == tenant_id, S.id.in_(list(dict.fromkeys(ids)))).all()
    if flt is None:
        raise ContactsError("Pick some contacts first.")
    q = matching(db, tenant_id, opted_in=flt.get("opted_in"), search=flt.get("search"),
                 list_id=flt.get("list_id"), tag=flt.get("tag"))
    rows = q.limit(MAX_TARGETS + 1).all()
    if len(rows) > MAX_TARGETS:
        raise ContactsError(f"That matches more than {MAX_TARGETS:,} contacts. Narrow the search first.")
    return rows


# ─── Lists ───────────────────────────────────────────────────────────────────

def _clean_name(name: str) -> str:
    clean = " ".join((name or "").split())[:MAX_LIST_NAME]
    if not clean:
        raise ContactsError("Give the list a name.")
    return clean


def get_list(db: Session, tenant_id: str, list_id: str) -> Optional[WaContactList]:
    return db.query(WaContactList).filter_by(id=list_id, tenant_id=tenant_id).first()


def lists_with_counts(db: Session, tenant_id: str) -> list[dict]:
    S = _sub()
    counts: dict[str, int] = {}
    for (ids,) in db.query(S.list_ids).filter(S.tenant_id == tenant_id):
        for lid in set(ids or []):
            counts[lid] = counts.get(lid, 0) + 1
    rows = db.query(WaContactList).filter_by(tenant_id=tenant_id).order_by(WaContactList.name).all()
    return [{"id": r.id, "name": r.name, "count": counts.get(r.id, 0), "created_at": r.created_at} for r in rows]


def create_list(db: Session, tenant_id: str, name: str, user_id: Optional[str]) -> WaContactList:
    clean = _clean_name(name)
    if db.query(WaContactList.id).filter_by(tenant_id=tenant_id, name=clean).first():
        raise ContactsError(f'You already have a list called "{clean}".')
    row = WaContactList(tenant_id=tenant_id, name=clean, created_by=user_id)
    db.add(row)
    db.flush()
    return row


def rename_list(db: Session, tenant_id: str, row: WaContactList, name: str) -> WaContactList:
    clean = _clean_name(name)
    clash = db.query(WaContactList.id).filter(WaContactList.tenant_id == tenant_id, WaContactList.name == clean,
                                              WaContactList.id != row.id).first()
    if clash:
        raise ContactsError(f'You already have a list called "{clean}".')
    row.name = clean
    db.flush()
    return row


def delete_list(db: Session, tenant_id: str, row: WaContactList) -> int:
    """Deletes the list, never the contacts. Returns how many contacts were on it."""
    S = _sub()
    n = 0
    for sub in db.query(S).filter(S.tenant_id == tenant_id, _json_has(S.list_ids, row.id)):
        sub.list_ids = [x for x in (sub.list_ids or []) if x != row.id]
        n += 1
    db.delete(row)
    db.flush()
    return n


# ─── Bulk actions ────────────────────────────────────────────────────────────

def apply(db: Session, tenant_id: str, subs: Iterable, action: str, value: Optional[str] = None) -> int:
    """Applies one bulk action; returns how many contacts actually changed."""
    if action not in BULK_ACTIONS:
        raise ContactsError("Unknown action.")
    if action in ("add_tag", "remove_tag"):
        value = (value or "").strip()[:MAX_TAG_LEN]
        if not value:
            raise ContactsError("Type a tag.")
    if action in ("add_to_list", "remove_from_list"):
        if not value or not get_list(db, tenant_id, value):
            raise ContactsError("That list doesn't exist any more.")
    now = datetime.now(timezone.utc).isoformat()
    changed = 0
    for sub in subs:
        tags, lids = list(sub.tags or []), list(sub.list_ids or [])
        if action == "add_tag" and value not in tags:
            sub.tags = [*tags, value]
        elif action == "remove_tag" and value in tags:
            sub.tags = [t for t in tags if t != value]
        elif action == "add_to_list" and value not in lids:
            sub.list_ids = [*lids, value]
        elif action == "remove_from_list" and value in lids:
            sub.list_ids = [x for x in lids if x != value]
        elif action == "opt_out" and sub.opted_in:
            sub.opted_in, sub.opt_out_at = False, now
        else:
            continue
        changed += 1
    db.flush()
    return changed


# ─── Drip / flow enrolment ───────────────────────────────────────────────────

def active_flow(db: Session, tenant_id: str, flow_id: str):
    from app.api.v1.endpoints.messaging import WAFlow
    return db.query(WAFlow).filter_by(id=flow_id, tenant_id=tenant_id, is_active=True).first()


def enrol_plan(db: Session, tenant_id: str, subs: Iterable) -> tuple[list[str], dict]:
    """Guest ids to start the flow for, plus who was left out and why. A flow runs against a guest, so a contact
    who isn't in the guest list yet is skipped, never turned into a new guest (that would count as a lead)."""
    from app.models.guest import Guest
    gids: list[str] = []
    skipped = {"opted_out": 0, "not_a_guest": 0}
    need_phone = []
    for sub in subs:
        if not sub.opted_in:
            skipped["opted_out"] += 1
        elif sub.guest_id:
            gids.append(sub.guest_id)
        else:
            need_phone.append(sub.phone)
    if need_phone:
        by_phone = dict(db.query(Guest.phone, Guest.id).filter(Guest.tenant_id == tenant_id, Guest.is_deleted.is_(False),
                                                               Guest.phone.in_(need_phone)))
        for p in need_phone:
            if p in by_phone:
                gids.append(by_phone[p])
            else:
                skipped["not_a_guest"] += 1
    return list(dict.fromkeys(gids)), skipped


def start_flow_for(db: Session, tenant_id: str, flow, guest_ids: list[str]) -> int:
    """Runs the existing flow engine for each guest; one failure never stops the rest."""
    from app.services.flow_engine import run_flow
    started = 0
    for gid in guest_ids:
        try:
            run_flow(db, tenant_id, flow, gid)
            started += 1
        except Exception as exc:   # noqa: BLE001 -- logged, the batch carries on
            db.rollback()
            log.error("wa_contacts_enrol_failed", tenant_id=tenant_id, flow_id=flow.id, error=str(exc))
    return started


def queue_enrolment(tenant_id: str, flow_id: str, guest_ids: list[str]) -> int:
    """Large enrolments: one Celery batch of ENROL_BATCH guests per minute. Returns the number of batches."""
    from app.workers.tasks.wa_contacts import enrol_flow_batch
    batches = [guest_ids[i:i + ENROL_BATCH] for i in range(0, len(guest_ids), ENROL_BATCH)]
    for n, batch in enumerate(batches):
        enrol_flow_batch.apply_async(kwargs={"tenant_id": tenant_id, "flow_id": flow_id, "guest_ids": batch},
                                     countdown=n * ENROL_BATCH_GAP_S)
    return len(batches)


# ─── 30-day growth ───────────────────────────────────────────────────────────

def _as_utc(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def growth(db: Session, tenant_id: str, days: int = 30, today: Optional[date] = None) -> dict:
    """New contacts and opt-outs per day for the last `days` days (today included), in the workspace timezone.
    Opt-outs come from opt_out_at, which is cleared when someone opts back in, so it counts people still opted out."""
    from app.models.tenant import Tenant
    S = _sub()
    tz_name = db.query(Tenant.timezone).filter_by(id=tenant_id).scalar() or "Asia/Kolkata"
    tz = ZoneInfo(tz_name)
    end = today or datetime.now(tz).date()
    start = end - timedelta(days=days - 1)
    since = datetime.combine(start, datetime.min.time(), tz).astimezone(timezone.utc)
    buckets = {start + timedelta(days=i): {"new": 0, "opted_out": 0} for i in range(days)}

    for (created,) in db.query(S.created_at).filter(S.tenant_id == tenant_id, S.created_at >= since):
        d = _as_utc(created)
        if d and d.astimezone(tz).date() in buckets:
            buckets[d.astimezone(tz).date()]["new"] += 1
    for (out_at,) in db.query(S.opt_out_at).filter(S.tenant_id == tenant_id, S.opted_in.is_(False),
                                                   S.opt_out_at.isnot(None)):
        d = _as_utc(out_at)
        if d and d.astimezone(tz).date() in buckets:
            buckets[d.astimezone(tz).date()]["opted_out"] += 1

    daily = [{"date": d.isoformat(), **v} for d, v in sorted(buckets.items())]
    return {"from": start.isoformat(), "to": end.isoformat(), "timezone": tz_name, "daily": daily,
            "new_total": sum(r["new"] for r in daily), "opted_out_total": sum(r["opted_out"] for r in daily)}
