"""Instagram automations scoped to "my next post": bind each such rule to the first post published after it was made
(moved out of services/ig_automation.py to keep that file under 500 lines)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.automation import AutomationRule
from app.services.ig_automation import _adapter


def bind_next_post(db: Session, tenant_id: str, media_id: str | None) -> None:
    """A "next post" rule not yet tied to a post takes the first post published after the rule was made, found on that
    post's first comment (one Graph lookup per post, cached a week). Commits only when it binds."""
    if not media_id:
        return
    from sqlalchemy.orm.attributes import flag_modified

    unbound = [
        r
        for r in db.query(AutomationRule)
        .filter_by(tenant_id=tenant_id, is_active=True, action="send_instagram_quick_reply")
        .all()
        if (r.trigger_config or {}).get("scope") == "next_post" and not (r.trigger_config or {}).get("media_id")
    ]
    if not unbound:
        return
    posted = _media_time(db, tenant_id, media_id)
    if posted is None:
        return
    for rule in unbound:
        made = rule.created_at if rule.created_at.tzinfo else rule.created_at.replace(tzinfo=UTC)
        if posted > made:
            rule.trigger_config = {
                **(rule.trigger_config or {}),
                "media_id": media_id,
                "media_bound_at": datetime.now(UTC).isoformat(),
            }
            flag_modified(rule, "trigger_config")
    db.commit()


def _media_time(db: Session, tenant_id: str, media_id: str) -> datetime | None:
    from app.core import cache

    key = f"igmedia_ts:{tenant_id}:{media_id}"
    raw = cache.get_cached(key)
    if raw is None:
        adapter = _adapter(db, tenant_id)
        if adapter is None:
            return None
        try:
            raw = adapter._get(f"/{media_id}", params={"fields": "timestamp"}).get("timestamp") or ""
        except Exception:  # noqa: BLE001
            return None
        cache.set_cached(key, raw, ttl=7 * 86400)
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z") if raw else None
    except ValueError:
        return None
