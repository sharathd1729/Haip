"""Push availability to Channex soon after a booking changes in HAIP, instead of waiting for the 15-minute sync.

A Stay inserted or updated anywhere (a staff edit, a quote paid, an iCal import, the public API) notes its workspace on
the session; after the flush, only workspaces with Channex connected are kept; after the commit one
`channex.push_soon` task is queued per workspace, at most once a minute (Redis key), 20 seconds out so a burst of edits
becomes one push. Bulk historical imports (session.info["suppress_webhooks"]) do not trigger it. A failure here never
touches the booking write: the 15-minute sync still catches everything.
"""

from __future__ import annotations

import structlog
from sqlalchemy import event
from sqlalchemy.orm import Session, object_session

from app.models.property import Stay

log = structlog.get_logger()

_DIRTY = "channex_dirty_tenants"
_CONNECTED = "channex_push_tenants"
DEBOUNCE_SECONDS = 60
DELAY_SECONDS = 20


def _stay_changed(_m, _c, target: Stay) -> None:
    session = object_session(target)
    if session is None or not target.tenant_id or session.info.get("suppress_webhooks"):
        return
    session.info.setdefault(_DIRTY, set()).add(target.tenant_id)


def _after_flush(session: Session, _ctx) -> None:
    dirty = session.info.pop(_DIRTY, None)
    if not dirty:
        return
    try:
        from app.models.integration import Integration

        connected = {t for (t,) in session.query(Integration.tenant_id).filter(
            Integration.tenant_id.in_(dirty), Integration.kind == "channex", Integration.status == "active")}
    except Exception as exc:  # noqa: BLE001 -- never block the business write
        log.warning("channex_push_hook_check_failed", error=str(exc)[:200])
        return
    if connected:
        session.info.setdefault(_CONNECTED, set()).update(connected)


def _after_commit(session: Session) -> None:
    tenants = session.info.pop(_CONNECTED, None)
    if not tenants:
        return
    from app.core import cache

    for tid in tenants:
        try:
            if not cache.idem_check_and_set(f"haip:channex_push_soon:{tid}", ttl=DEBOUNCE_SECONDS):
                continue
            from app.workers.tasks.channex_sync import push_soon

            push_soon.apply_async(args=[tid], countdown=DELAY_SECONDS)
        except Exception as exc:  # noqa: BLE001 -- the 15-minute sync is the safety net
            log.warning("channex_push_soon_not_queued", tenant_id=tid, error=str(exc)[:200])


def _after_rollback(session: Session, *_a) -> None:
    session.info.pop(_DIRTY, None)
    session.info.pop(_CONNECTED, None)


def register() -> None:
    event.listen(Stay, "after_insert", _stay_changed)
    event.listen(Stay, "after_update", _stay_changed)
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)


register()
