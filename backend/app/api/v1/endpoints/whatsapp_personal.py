"""Agent-facing endpoints for the personal/Business-app WhatsApp bridge.

Session lifecycle only (pair/status/logout) -- inbound message ingestion
from the bridge itself lives in webhooks_whatsapp_personal.py, which uses
a per-session secret instead of JWT auth (the bridge is a service, not a
logged-in user).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import structlog

from app.api.v1.deps import get_current_user, get_db, require_roles
from app.models.user import User, UserRole
from app.schemas.whatsapp_personal import WhatsAppPersonalSessionOut, WhatsAppPersonalPairingOut
from app.services import whatsapp_personal_service as svc

log = structlog.get_logger()
router = APIRouter(prefix="/whatsapp-personal", tags=["whatsapp-personal"])


def _mask_phone(phone: str | None) -> str | None:
    """Owner/manager see that an agent's personal number is paired and
    its live status -- not the number itself. It's the agent's own
    personal device, not a tenant-owned credential like the official
    WABA number; the business value (conversations, AI insights) already
    flows into the shared Inbox/Leads360 regardless of this masking."""
    if not phone or len(phone) < 4:
        return phone
    return phone[:3] + "•" * (len(phone) - 5) + phone[-2:]


@router.post("/sessions", response_model=WhatsAppPersonalPairingOut)
def start_pairing(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start (or restart) pairing this agent's own phone. Returns a QR the
    frontend renders for the agent to scan with WhatsApp -> Linked Devices."""
    try:
        session, qr = svc.start_or_restart_pairing(db, current_user.tenant_id, current_user.id)
    except Exception as exc:
        log.error("whatsapp_personal_pairing_endpoint_failed", error=str(exc))
        raise HTTPException(status_code=502, detail="Could not reach the WhatsApp bridge service. Try again shortly.")
    return WhatsAppPersonalPairingOut(session_id=session.id, qr_code_data_url=qr, status=session.status.value)


@router.get("/sessions/me", response_model=WhatsAppPersonalSessionOut | None)
def get_my_session(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = svc.get_session(db, current_user.tenant_id, current_user.id)
    if not session:
        return None
    return WhatsAppPersonalSessionOut(
        id=session.id, status=session.status.value, phone_number=session.phone_number,
        last_seen_at=session.last_seen_at, created_at=session.created_at,
    )


@router.delete("/sessions/me")
def logout_my_session(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = svc.logout_session(db, current_user.tenant_id, current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="No session to unpair")
    return {"status": "logged_out"}


@router.get("/sessions", response_model=list[WhatsAppPersonalSessionOut])
def list_all_sessions(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Ops directory view -- every agent's bridge status for this tenant.
    Owner/manager only: this exposes which agents have paired a personal
    number and its current live/dead state."""
    from app.models.user import User as UserModel

    sessions = svc.list_sessions(db, current_user.tenant_id)
    users_by_id = {
        u.id: u for u in db.query(UserModel).filter(UserModel.id.in_([s.user_id for s in sessions])).all()
    } if sessions else {}
    return [
        WhatsAppPersonalSessionOut(
            id=s.id, status=s.status.value, phone_number=_mask_phone(s.phone_number),
            agent_name=getattr(users_by_id.get(s.user_id), "name", None),
            last_seen_at=s.last_seen_at, created_at=s.created_at,
        )
        for s in sessions
    ]
