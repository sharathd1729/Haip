"""Manage outbound webhook endpoints (Settings > Developers).

  GET    /webhook-endpoints                      list, plus the event catalogue
  POST   /webhook-endpoints                      create; the signing secret is returned once
  PATCH  /webhook-endpoints/{id}                 change url / events / description, enable, rotate secret
  DELETE /webhook-endpoints/{id}
  POST   /webhook-endpoints/{id}/test            send a `ping` now and report what your server answered
  GET    /webhook-endpoints/{id}/deliveries      recent deliveries
  POST   /webhook-endpoints/deliveries/{id}/retry  send a failed delivery again

Named webhook-endpoints (not /webhooks) because /api/v1/webhooks/* is where providers call HAIP.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.audit import append_audit
from app.core.database import get_db, set_tenant_context
from app.core.url_safety import UnsafeURLError, assert_public_url
from app.models.user import User, UserRole
from app.models.webhook import WebhookDelivery, WebhookEndpoint
from app.services import webhook_service as ws

router = APIRouter(prefix="/webhook-endpoints", tags=["webhook-endpoints"])

_MAX_ENDPOINTS = 10
_READ = (UserRole.OWNER, UserRole.MANAGER)


class EndpointCreate(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    events: list[str] = Field(min_length=1)
    description: Optional[str] = Field(None, max_length=200)


class EndpointUpdate(BaseModel):
    url: Optional[str] = Field(None, min_length=8, max_length=500)
    events: Optional[list[str]] = Field(None, min_length=1)
    description: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None
    rotate_secret: bool = False


def _check_url(url: str) -> str:
    url = url.strip()
    try:
        assert_public_url(url, allow_http=False)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return url


def _check_events(events: list[str]) -> list[str]:
    unknown = [e for e in events if e not in ws.EVENTS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown event: {', '.join(unknown)}")
    return sorted(set(events))


def _out(ep: WebhookEndpoint) -> dict:
    return {
        "id": ep.id, "url": ep.url, "description": ep.description, "events": ep.events or [], "is_active": ep.is_active,
        "disabled_reason": ep.disabled_reason, "consecutive_failures": ep.consecutive_failures or 0,
        "last_success_at": ep.last_success_at.isoformat() if ep.last_success_at else None,
        "last_failure_at": ep.last_failure_at.isoformat() if ep.last_failure_at else None,
    }


def _delivery_out(d: WebhookDelivery) -> dict:
    return {"id": d.id, "event_id": d.event_id, "event_type": d.event_type, "status": d.status, "attempts": d.attempts,
            "response_status": d.response_status, "error": d.last_error,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
            "next_attempt_at": d.next_attempt_at.isoformat() if d.next_attempt_at else None}


def _get(db: Session, user: User, endpoint_id: str) -> WebhookEndpoint:
    ep = db.query(WebhookEndpoint).filter_by(id=endpoint_id, tenant_id=user.tenant_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    return ep


@router.get("")
def list_endpoints(current_user: User = Depends(require_roles(*_READ)), db: Session = Depends(get_db)):
    rows = db.query(WebhookEndpoint).filter_by(tenant_id=current_user.tenant_id).order_by(WebhookEndpoint.created_at).all()
    return {"endpoints": [_out(e) for e in rows], "events": [{"event": k, "description": v} for k, v in ws.EVENTS.items()]}


@router.post("", status_code=201)
def create_endpoint(body: EndpointCreate, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    url, events = _check_url(body.url), _check_events(body.events)
    if db.query(WebhookEndpoint).filter_by(tenant_id=current_user.tenant_id).count() >= _MAX_ENDPOINTS:
        raise HTTPException(status_code=422, detail=f"You can have at most {_MAX_ENDPOINTS} webhook endpoints.")
    ep, secret = ws.create_endpoint(db, current_user.tenant_id, url, events, body.description, current_user.id)
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="webhook_endpoint.created",
                 target_type="webhook_endpoint", target_id=ep.id, payload={"url": url, "events": events})
    db.commit()
    set_tenant_context(db, current_user.tenant_id)
    db.refresh(ep)
    return {**_out(ep), "secret": secret}          # shown once


@router.patch("/{endpoint_id}")
def update_endpoint(endpoint_id: str, body: EndpointUpdate, current_user: User = Depends(require_roles(UserRole.OWNER)),
                    db: Session = Depends(get_db)):
    ep = _get(db, current_user, endpoint_id)
    out_extra: dict = {}
    if body.url is not None:
        ep.url = _check_url(body.url)
    if body.events is not None:
        ep.events = _check_events(body.events)
    if body.description is not None:
        ep.description = body.description or None
    if body.is_active is not None:
        ep.is_active = body.is_active
        if body.is_active:
            ep.consecutive_failures, ep.disabled_reason = 0, None
    if body.rotate_secret:
        secret = ws.new_secret()
        from app.core.encryption import encrypt_credentials
        ep.secret_enc = encrypt_credentials({"secret": secret})
        out_extra["secret"] = secret
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="webhook_endpoint.updated",
                 target_type="webhook_endpoint", target_id=ep.id, payload={"rotated_secret": body.rotate_secret, "is_active": ep.is_active})
    db.commit()
    set_tenant_context(db, current_user.tenant_id)
    db.refresh(ep)
    return {**_out(ep), **out_extra}


@router.delete("/{endpoint_id}", status_code=204)
def delete_endpoint(endpoint_id: str, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    ep = _get(db, current_user, endpoint_id)
    db.query(WebhookDelivery).filter_by(endpoint_id=ep.id, tenant_id=current_user.tenant_id).delete()
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="webhook_endpoint.deleted",
                 target_type="webhook_endpoint", target_id=ep.id, payload={"url": ep.url})
    db.delete(ep)
    db.commit()


@router.post("/{endpoint_id}/test")
def test_endpoint(endpoint_id: str, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    """Send a `ping` right now (works even if the endpoint doesn't subscribe to it) and report the result."""
    ep = _get(db, current_user, endpoint_id)
    if not ep.is_active:
        raise HTTPException(status_code=422, detail="Enable this endpoint first.")
    ids = ws.queue_event(db, current_user.tenant_id, "ping", {"message": "This is a test event from HAIP."}, only_endpoint=ep.id)
    db.commit()
    ws.deliver(db, ids[0], current_user.tenant_id)
    set_tenant_context(db, current_user.tenant_id)
    d = db.query(WebhookDelivery).filter_by(id=ids[0], tenant_id=current_user.tenant_id).first()
    # A test is a one-off: don't leave a pending retry behind if it failed.
    if d.status == "pending":
        d.status, d.next_attempt_at = "failed", None
        db.commit()
    return _delivery_out(d)


@router.get("/{endpoint_id}/deliveries")
def list_deliveries(endpoint_id: str, limit: int = 30, current_user: User = Depends(require_roles(*_READ)), db: Session = Depends(get_db)):
    ep = _get(db, current_user, endpoint_id)
    rows = (db.query(WebhookDelivery).filter_by(endpoint_id=ep.id, tenant_id=current_user.tenant_id)
            .order_by(WebhookDelivery.created_at.desc()).limit(max(1, min(limit, 100))).all())
    return {"deliveries": [_delivery_out(d) for d in rows]}


@router.post("/deliveries/{delivery_id}/retry")
def retry_delivery(delivery_id: str, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    d = db.query(WebhookDelivery).filter_by(id=delivery_id, tenant_id=current_user.tenant_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Delivery not found")
    ep = db.query(WebhookEndpoint).filter_by(id=d.endpoint_id, tenant_id=current_user.tenant_id).first()
    if not ep or not ep.is_active:
        raise HTTPException(status_code=422, detail="Enable the endpoint first.")
    d.status, d.attempts, d.next_attempt_at = "pending", 0, datetime.now(timezone.utc)
    db.commit()
    ws.deliver(db, d.id, current_user.tenant_id)
    set_tenant_context(db, current_user.tenant_id)
    return _delivery_out(db.query(WebhookDelivery).filter_by(id=d.id, tenant_id=current_user.tenant_id).first())
