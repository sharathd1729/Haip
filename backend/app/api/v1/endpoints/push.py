"""
Web Push notification endpoints.

POST /push/subscribe         — register a push subscription
DELETE /push/unsubscribe     — remove a push subscription
GET  /push/vapid-public-key  — return VAPID public key (no auth required)
"""

from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.config import settings
from app.core.database import set_tenant_context
from app.models.push_subscription import PushSubscription
from app.models.user import User

log = structlog.get_logger()
router = APIRouter(prefix="/push", tags=["push"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class PushKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: PushKeys
    user_agent: Optional[str] = None


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/vapid-public-key")
def get_vapid_public_key():
    """Return the VAPID public key for push subscription. No auth needed."""
    if not settings.VAPID_PUBLIC_KEY:
        raise HTTPException(status_code=503, detail="Push notifications not configured on this server.")
    return {"public_key": settings.VAPID_PUBLIC_KEY}


@router.post("/subscribe", status_code=201)
def subscribe(
    body: SubscribeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save or update a push subscription for the current user."""
    set_tenant_context(db, current_user.tenant_id)

    existing = (
        db.query(PushSubscription)
        .filter_by(user_id=current_user.id, endpoint=body.endpoint)
        .first()
    )

    if existing:
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
        existing.user_agent = body.user_agent or request.headers.get("user-agent")
    else:
        sub = PushSubscription(
            id=uuid.uuid4(),
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            user_agent=body.user_agent or request.headers.get("user-agent"),
        )
        db.add(sub)

    db.commit()
    log.info("push_subscription_saved", user_id=str(current_user.id), tenant_id=current_user.tenant_id)
    return {"status": "subscribed"}


@router.delete("/unsubscribe")
def unsubscribe(
    endpoint: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a push subscription."""
    set_tenant_context(db, current_user.tenant_id)

    row = (
        db.query(PushSubscription)
        .filter_by(user_id=current_user.id, endpoint=endpoint)
        .first()
    )
    if row:
        db.delete(row)
        db.commit()

    return {"status": "unsubscribed"}
