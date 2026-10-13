"""Fill in lead state (lead_identified_at, first touch) for guests that existed before migration 122 -- conservatively.

Only fields that are still empty are written, so it is safe to run twice. Nothing is deleted or moved.

What is and is not claimed:
  * A guest is marked identified only when HAIP holds a USABLE phone number for them (phone_identity), either as a phone /
    WhatsApp identity signal or as Guest.phone. A guest with no number stays unidentified: an old Instagram-only DM is not turned
    into a lead.
  * The identification time is the earliest such signal's first_seen_at. With no signal row it is the guest's created_at, which
    can be EARLIER than the day the number was really captured (a number added to an existing guest without a signal row). Counts
    for past periods are therefore best-effort; they never include a guest HAIP has no number for.
  * First-touch channel comes from the guest's earliest identity signal (its source, else its type). With nothing to go on it is
    left NULL, shown as "unknown". It is never guessed from the inquiry source.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import bindparam, text

from app.services import phone_identity
from app.services.lead_state import CHANNEL_BY_IDENTITY_TYPE, channel_for_source

PHONE_TYPES = ("phone", "whatsapp_number")


def _aware(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def backfill(conn, tenant_id: Optional[str] = None, *, dry_run: bool = False, batch: int = 1000) -> dict:
    """``conn`` is a SQLAlchemy Connection or Session. Returns counts; with dry_run nothing is written."""
    regions = {r[0]: phone_identity.region_for_timezone(r[1])
               for r in conn.execute(text("SELECT id, timezone FROM tenants")).fetchall()}
    where = "g.lead_identified_at IS NULL OR g.first_touch_at IS NULL"
    params: dict = {}
    if tenant_id:
        where = f"({where}) AND g.tenant_id = :tid"
        params["tid"] = tenant_id
    guests = conn.execute(text(
        f"SELECT g.id, g.tenant_id, g.phone, g.created_at, g.lead_identified_at, g.first_touch_at, g.first_touch_channel "
        f"FROM guests g WHERE {where}"), params).fetchall()

    stats = {"guests_examined": len(guests), "identified": 0, "first_touch_set": 0, "left_unidentified": 0, "channel_unknown": 0}
    sig_query = text("SELECT guest_id, identity_type, identity_value, source, first_seen_at FROM guest_identities "
                     "WHERE guest_id IN :ids ORDER BY first_seen_at").bindparams(bindparam("ids", expanding=True))
    for start in range(0, len(guests), batch):
        chunk = guests[start:start + batch]
        sigs: dict[str, list] = {}
        for gid, itype, value, source, seen in conn.execute(sig_query, {"ids": [g[0] for g in chunk]}).fetchall():
            sigs.setdefault(gid, []).append((itype, value, source, _aware(seen)))
        for gid, tid, phone, created, ident, touch, touch_channel in chunk:
            created, region = _aware(created), regions.get(tid)
            rows = sigs.get(gid, [])
            update: dict = {}

            if ident is None:
                times, via = [], None
                for itype, value, source, seen in rows:
                    if itype in PHONE_TYPES and phone_identity.normalize(value, region):
                        times.append(seen or created)
                        via = via or channel_for_source(source) or (source or "")[:30] or None
                if not times and phone and phone_identity.normalize(phone, region):
                    times.append(created)
                if times:
                    update["lead_identified_at"] = min(t for t in times if t is not None)
                    update["lead_identified_via"] = via
                    stats["identified"] += 1
                else:
                    stats["left_unidentified"] += 1

            if touch is None:
                update["first_touch_at"] = rows[0][3] if rows and rows[0][3] else created
                channel = None
                if rows:
                    channel = channel_for_source(rows[0][2]) or CHANNEL_BY_IDENTITY_TYPE.get(rows[0][0])
                if touch_channel is None:
                    update["first_touch_channel"] = channel
                    if channel is None:
                        stats["channel_unknown"] += 1
                stats["first_touch_set"] += 1

            if update and not dry_run:
                sets = ", ".join(f"{k} = :{k}" for k in update)
                conn.execute(text(f"UPDATE guests SET {sets} WHERE id = :id"), {**update, "id": gid})
    return stats
