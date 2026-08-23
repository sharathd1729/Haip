import uuid
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.core.security import get_password_hash
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole, UserInvitation
from app.models.tenant import Tenant
from app.schemas.user import UserOut, UserInviteRequest, UserUpdateRequest, UserSelfUpdateRequest, InvitationOut
from app.core.audit import append_audit
from app.core.config import settings
from app.services.email_service import send_invitation_email

router = APIRouter(prefix="/users", tags=["users"])


def _require_self_or_owner(user_id: str, current_user: User) -> None:
    """Agent profile pages (scorecard/messages): an agent can always view
    their own, an owner/manager can view anyone's. Same binary check
    dashboard_overview.py already uses for agent-scoped data."""
    if user_id == current_user.id:
        return
    if current_user.role in (UserRole.OWNER, UserRole.MANAGER):
        return
    raise HTTPException(status_code=403, detail="Can only view your own profile")


# ─── Self-service endpoints (any authenticated user) ──────────────────────────

@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the calling user's own profile including notification prefs and digest opt-in."""
    return current_user


@router.patch("/me", response_model=UserOut)
def update_me(
    body: UserSelfUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Self-update: name, phone, notification_prefs, digest_opt_in.
    Cannot change role or is_active (use /users/{id} for that, owner-only).
    """
    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


# ─── Admin / manager endpoints ────────────────────────────────────────────────

@router.get("", response_model=List[UserOut])
def list_users(
    limit: int = 200,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    return (
        db.query(User)
        .filter_by(tenant_id=current_user.tenant_id, is_deleted=False)
        .order_by(User.name)
        .limit(min(limit, 200))
        .all()
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def invite_user(
    body: UserInviteRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    if db.query(User).filter_by(email=body.email, tenant_id=current_user.tenant_id).first():
        raise HTTPException(status_code=400, detail="Email already invited")

    try:
        role = UserRole(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {body.role}")

    temp_password = str(uuid.uuid4())[:12]
    new_user = User(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        name=body.name,
        email=body.email,
        hashed_password=get_password_hash(temp_password),
        role=role,
        property_scope=body.property_scope or [],
        is_active=False,  # Inactive until invitation accepted
    )
    db.add(new_user)

    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
                 action="user.invite", target_type="user", target_id=new_user.id,
                 payload={"email": body.email, "role": body.role})
    db.commit()
    db.refresh(new_user)
    return new_user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    body: UserUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(id=user_id, tenant_id=current_user.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    changes = body.model_dump(exclude_none=True)
    if "role" in changes:
        try:
            changes["role"] = UserRole(changes["role"])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role: {changes['role']}")

    for field, value in changes.items():
        setattr(user, field, value)

    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
                 action="user.role.change", target_type="user", target_id=user_id,
                 payload=changes)
    db.commit()
    db.refresh(user)
    return user


# ─── Invitations ──────────────────────────────────────────────────────────────

def _send_invite_bg(**kwargs) -> None:
    """Sync wrapper so BackgroundTasks can call the async email function."""
    import asyncio
    try:
        asyncio.run(send_invitation_email(**kwargs))
    except Exception:
        pass  # Never crash the background task

@router.post("/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
def create_invitation(
    body: UserInviteRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    # Check no active invite already exists for this email+tenant
    existing = db.query(UserInvitation).filter_by(
        tenant_id=current_user.tenant_id, email=body.email, is_accepted=False, is_revoked=False
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="An active invitation already exists for this email.")

    try:
        role = UserRole(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {body.role}")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    invitation = UserInvitation(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        invited_by=current_user.id,
        email=body.email,
        name=body.name,
        role=role,
        token=token,
        expires_at=expires_at,
    )
    db.add(invitation)

    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
                 action="user.invitation.create", target_type="invitation", target_id=invitation.id,
                 payload={"email": body.email, "role": body.role})
    db.commit()
    db.refresh(invitation)

    # Build invite link pointing to the FRONTEND (not the API server)
    invite_link = f"{settings.FRONTEND_URL.rstrip('/')}/join?token={token}"

    # Fetch tenant name for the email
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    tenant_name = tenant.name if tenant else "your team"

    # Send invite email in background — never block or fail the response
    background_tasks.add_task(
        _send_invite_bg,
        to_email=body.email,
        name=body.name,
        invite_link=invite_link,
        inviter_name=current_user.name,
        tenant_name=tenant_name,
        role=role.value,
    )

    out = InvitationOut(
        id=invitation.id,
        email=invitation.email,
        name=invitation.name,
        role=invitation.role.value,
        token=invitation.token,
        is_accepted=invitation.is_accepted,
        is_revoked=invitation.is_revoked,
        expires_at=invitation.expires_at,
        invited_by_name=current_user.name,
    )
    return out


@router.get("/invitations", response_model=List[InvitationOut])
def list_invitations(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    invitations = db.query(UserInvitation).filter_by(
        tenant_id=current_user.tenant_id
    ).order_by(UserInvitation.created_at.desc()).all()

    inviter_ids = list({inv.invited_by for inv in invitations if inv.invited_by})
    inviters_by_id = {}
    if inviter_ids:
        inviters_by_id = {
            u.id: u for u in db.query(User).filter(User.id.in_(inviter_ids)).all()
        }

    result = []
    for inv in invitations:
        inviter = inviters_by_id.get(inv.invited_by)
        result.append(InvitationOut(
            id=inv.id,
            email=inv.email,
            name=inv.name,
            role=inv.role.value,
            token=inv.token,
            is_accepted=inv.is_accepted,
            is_revoked=inv.is_revoked,
            expires_at=inv.expires_at,
            invited_by_name=inviter.name if inviter else None,
        ))
    return result


@router.get("/invitations/{invitation_id}/wa-link")
def get_invitation_wa_link(
    invitation_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """
    O10 — Return a wa.me deep link for sharing an invitation via WhatsApp.
    Generates the invite URL and prefills a WhatsApp message the operator can forward.
    """
    invitation = db.query(UserInvitation).filter_by(
        id=invitation_id, tenant_id=current_user.tenant_id
    ).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.is_revoked or invitation.is_accepted:
        raise HTTPException(status_code=400, detail="Invitation is no longer active")

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    tenant_name = tenant.name if tenant else "our team"

    invite_link = f"{settings.FRONTEND_URL.rstrip('/')}/join?token={invitation.token}"

    # Build a WhatsApp-ready message
    role_label = invitation.role.value.replace("_", " ").title()
    message = (
        f"Hi {invitation.name or 'there'} 👋\n\n"
        f"You've been invited to join *{tenant_name}* on HAIP as a *{role_label}*.\n\n"
        f"Click the link to accept and set up your account:\n{invite_link}\n\n"
        f"This link expires in 24 hours. See you on the platform! 🙌"
    )
    import urllib.parse
    wa_href = f"https://wa.me/?text={urllib.parse.quote(message)}"

    return {
        "invitation_id": invitation_id,
        "invite_link": invite_link,
        "wa_href": wa_href,
        "expires_at": invitation.expires_at,
    }


@router.delete("/invitations/{token}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(
    token: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    invitation = db.query(UserInvitation).filter_by(
        token=token, tenant_id=current_user.tenant_id
    ).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    invitation.is_revoked = True
    db.commit()


# ── W18: Presence heartbeat ──────────────────────────────────────────────────

@router.post("/me/heartbeat", status_code=204)
def presence_heartbeat(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update last_seen_at for the current user (call every 30s from frontend)."""
    current_user.last_seen_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/presence")
def get_presence(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return which users are 'online' (seen in last 90 seconds)."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
    users = db.query(User).filter(
        User.tenant_id == current_user.tenant_id,
        User.is_active == True,  # noqa
        User.last_seen_at >= cutoff,
    ).all()
    return [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
        }
        for u in users
    ]


# ── Agent profile page ──────────────────────────────────────────────────────

@router.get("/{user_id}/scorecard")
def get_user_scorecard(
    user_id: str,
    date_preset: str = Query(default="today", description="today|yesterday|this_month|last_month|last_7d|last_14d|custom"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One agent's own numbers (leads/response time/calls/follow-ups/AI
    drafts/conversions) -- the Agent Profile page's Overview tab."""
    _require_self_or_owner(user_id, current_user)

    from app.services.date_presets import VALID_PRESETS, resolve_range
    from app.services.agent_analytics_service import get_agent_scorecard_rows

    if date_preset not in VALID_PRESETS:
        raise HTTPException(status_code=422, detail=f"Invalid date_preset: {date_preset}")
    try:
        d_from, d_to = resolve_range(date_preset, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}")
    if not d_from or not d_to:
        raise HTTPException(status_code=422, detail="date_from/date_to required for a custom range")

    rows = get_agent_scorecard_rows(db, current_user.tenant_id, d_from, d_to, agent_id=user_id)
    if not rows:
        raise HTTPException(status_code=404, detail="User not found or inactive")
    return rows[0]


@router.get("/{user_id}/messages")
def get_user_messages(
    user_id: str,
    date_preset: str = Query(default="today", description="today|yesterday|this_month|last_month|last_7d|last_14d|custom"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Conversations this agent personally replied in over the period, one
    row per conversation -- Agent Profile page's Messages tab. Sourced from
    Message.sender_id (stamped on every human-sent reply, conversations.py's
    send/send-media/approve-draft handlers), not Conversation.assigned_to,
    which has no write path anywhere in the app today."""
    _require_self_or_owner(user_id, current_user)

    from sqlalchemy import func
    from app.models.conversation import Conversation, Message, MessageDirection
    from app.services.date_presets import VALID_PRESETS, resolve_range, ist_range_to_utc

    if date_preset not in VALID_PRESETS:
        raise HTTPException(status_code=422, detail=f"Invalid date_preset: {date_preset}")
    try:
        d_from, d_to = resolve_range(date_preset, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}")
    if not d_from or not d_to:
        raise HTTPException(status_code=422, detail="date_from/date_to required for a custom range")
    range_start, range_end, _, _ = ist_range_to_utc(d_from, d_to)

    rows = (
        db.query(
            Conversation.id, Conversation.channel,
            func.count(Message.id), func.max(Message.created_at),
        )
        .join(Message, Message.conversation_id == Conversation.id)
        .filter(
            Message.tenant_id == current_user.tenant_id,
            Message.sender_id == user_id,
            Message.direction == MessageDirection.OUTBOUND,
            Message.is_ai_generated.is_(False),
            Message.created_at >= range_start,
            Message.created_at <= range_end,
        )
        .group_by(Conversation.id, Conversation.channel)
        .order_by(func.max(Message.created_at).desc())
        .all()
    )

    from app.models.guest import Guest
    guest_name_by_conv = {}
    if rows:
        conv_guest = dict(
            db.query(Conversation.id, Conversation.guest_id)
            .filter(Conversation.id.in_([r[0] for r in rows]))
            .all()
        )
        guests_by_id = {
            g.id: g.name for g in db.query(Guest).filter(Guest.id.in_(conv_guest.values())).all()
        }
        guest_name_by_conv = {cid: guests_by_id.get(gid) for cid, gid in conv_guest.items()}

    return [
        {
            "conversation_id": conv_id,
            "channel": str(getattr(channel, "value", channel)).lower(),
            "guest_name": guest_name_by_conv.get(conv_id),
            "message_count": count,
            "last_message_at": last_at.isoformat() if last_at else None,
        }
        for conv_id, channel, count, last_at in rows
    ]
