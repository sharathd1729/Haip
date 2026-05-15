import uuid
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.core.security import get_password_hash
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole, UserInvitation
from app.models.tenant import Tenant
from app.schemas.user import UserOut, UserInviteRequest, UserUpdateRequest, InvitationOut
from app.core.audit import append_audit
from app.core.config import settings
from app.services.email_service import send_invitation_email

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=List[UserOut])
def list_users(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    return db.query(User).filter_by(tenant_id=current_user.tenant_id, is_deleted=False).all()


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
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

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

    result = []
    for inv in invitations:
        inviter = db.query(User).filter_by(id=inv.invited_by).first()
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
