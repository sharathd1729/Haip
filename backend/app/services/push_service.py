"""
Web Push notification service.

Sends push notifications to all subscribed devices for a tenant.
Requires VAPID keys in .env — generate once:
  python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); \
  print('PRIVATE:', v.private_pem().decode()); \
  print('PUBLIC:', v.public_key.public_bytes_raw().hex())"
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.core.config import settings

log = structlog.get_logger()


def _push_enabled() -> bool:
    return bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY)


def send_push(row, title: str, body: str, url: str = "/dashboard/inbox", tag: str = "haip") -> None:
    """Send push to a single subscription row. Raises on non-410 errors."""
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        log.warning("pywebpush_not_installed")
        return

    try:
        webpush(
            subscription_info={
                "endpoint": row.endpoint,
                "keys": {"p256dh": row.p256dh, "auth": row.auth},
            },
            data=json.dumps({"title": title, "body": body, "url": url, "tag": tag}),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{settings.VAPID_EMAIL}"},
        )
    except Exception as exc:
        # re-raise so caller can handle 410 (expired subscription)
        raise exc


def send_to_tenant(
    db: Session,
    tenant_id: str,
    title: str,
    body: str,
    url: str = "/dashboard/inbox",
    tag: str = "haip",
    user_id: Optional[str] = None,
) -> None:
    """
    Send push to subscribed devices for a tenant.
    If user_id is given, only that user's devices are notified (assigned-agent mode).
    Silently removes expired (410) subscriptions.
    Never raises — push is best-effort.
    """
    if not _push_enabled():
        return

    try:
        from pywebpush import WebPushException
        from app.models.push_subscription import PushSubscription

        q = db.query(PushSubscription).filter_by(tenant_id=tenant_id)
        if user_id:
            q = q.filter_by(user_id=user_id)
        rows = q.all()
        for row in rows:
            try:
                send_push(row, title=title, body=body, url=url, tag=tag)
                log.debug("push_sent", tenant_id=tenant_id, endpoint_prefix=row.endpoint[:40])
            except WebPushException as exc:
                if exc.response is not None and exc.response.status_code == 410:
                    # Subscription expired — clean up
                    db.delete(row)
                    db.flush()
                    log.info("push_subscription_expired_removed", user_id=str(row.user_id))
                else:
                    log.warning("push_send_failed", error=str(exc), user_id=str(row.user_id))
            except Exception as exc:
                log.warning("push_send_error", error=str(exc))
    except Exception as exc:
        log.warning("push_to_tenant_failed", tenant_id=tenant_id, error=str(exc))
