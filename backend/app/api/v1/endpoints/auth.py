from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional, Literal
from app.core.database import get_db
from app.core.config import settings
from app.core.security import (
    verify_password, get_password_hash,
    create_access_token, create_refresh_token, decode_token,
    create_mfa_challenge_token,
)
from app.models.user import User, RefreshToken, UserInvitation, UserRole
from app.models.tenant import Tenant
from app.core.audit import append_audit
import uuid, hashlib, secrets
from datetime import datetime, timezone, timedelta
import structlog

log = structlog.get_logger()

try:
    import pyotp
    import qrcode
    import io, base64
    _PYOTP_AVAILABLE = True
except ImportError:
    _PYOTP_AVAILABLE = False

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    tenant_name: str
    tenant_slug: str
    business_type: Optional[Literal["caravan", "villa_resort", "homestay", "hotel"]] = None
    consent_transactional: bool = True
    consent_marketing: bool = False
    consent_analytics: bool = False


class MFARequiredResponse(BaseModel):
    mfa_required: bool = True
    mfa_token: str


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=req.email, is_deleted=False).first()
    if not user or not verify_password(req.password, user.hashed_password or ""):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    # MFA-enabled accounts don't get full tokens from password alone — the
    # client must complete /auth/mfa/verify with this challenge token.
    if user.is_mfa_enabled:
        return MFARequiredResponse(mfa_token=create_mfa_challenge_token(user.id)).model_dump()

    payload = {"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value}
    access = create_access_token(payload)
    refresh = create_refresh_token(payload)

    # Store refresh token hash
    token_hash = hashlib.sha256(refresh.encode()).hexdigest()
    db.add(RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        tenant_id=user.tenant_id,
        token_hash=token_hash,
    ))
    db.commit()

    return LoginResponse(
        access_token=access,
        refresh_token=refresh,
        user={
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role.value,
            "tenant_id": user.tenant_id,
        },
    )


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    # Check email unique
    if db.query(User).filter_by(email=req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Check slug unique
    if db.query(Tenant).filter_by(slug=req.tenant_slug).first():
        raise HTTPException(status_code=400, detail="Tenant slug already taken")

    tenant = Tenant(
        id=str(uuid.uuid4()),
        name=req.tenant_name,
        slug=req.tenant_slug,
        plan="growth",
        business_type=req.business_type,
    )
    db.add(tenant)
    db.flush()

    from app.services.workspace_context import provision_default_modules
    provision_default_modules(db, tenant.id)

    from app.services.pipeline_stage_service import seed_default_pipeline_stages
    seed_default_pipeline_stages(db, tenant.id)

    from app.services.authz_service import seed_default_capabilities
    seed_default_capabilities(db, tenant.id)

    from app.models.user import UserRole
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        name=req.name,
        email=req.email,
        hashed_password=get_password_hash(req.password),
        role=UserRole.OWNER,
        is_active=True,
        consent_transactional=req.consent_transactional,
        consent_marketing=req.consent_marketing,
        consent_analytics=req.consent_analytics,
        consent_recorded_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()

    payload = {"sub": user.id, "tenant_id": tenant.id, "role": user.role.value}
    access = create_access_token(payload)
    refresh = create_refresh_token(payload)

    token_hash = hashlib.sha256(refresh.encode()).hexdigest()
    db.add(RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        tenant_id=tenant.id,
        token_hash=token_hash,
    ))
    db.commit()

    # Send welcome email (non-blocking — never fail registration if email fails)
    try:
        from app.services.email_service import send_welcome_email
        await send_welcome_email(to_email=user.email, name=user.name, tenant_name=tenant.name)
    except Exception as exc:
        log.warning("welcome_email_failed", email=user.email, error=str(exc))

    return LoginResponse(
        access_token=access,
        refresh_token=refresh,
        user={"id": user.id, "name": user.name, "email": user.email, "role": user.role.value, "tenant_id": tenant.id},
    )


def _user_token(user_id: str) -> str:
    """Hash a user_id for safe log correlation. Never log raw PII/identifiers at INFO."""
    return hashlib.sha256(user_id.encode()).hexdigest()[:12]


def _as_aware(dt):
    """Postgres returns tz-aware datetimes for TIMESTAMPTZ columns; SQLite
    (used in tests) always returns naive ones. Normalize to UTC-aware so
    subtracting against datetime.now(timezone.utc) never raises."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# Reuse of an already-rotated refresh token within this window is treated as a
# race between concurrent requests (dashboard pages fire several in parallel;
# two can each decide to proactively refresh the same stale token at once) and
# is answered with the successor token that rotation already produced, rather
# than as theft. Reuse after this window has elapsed is treated as genuine
# token theft: the user's entire refresh-token family is revoked.
_REFRESH_GRACE_WINDOW_SECONDS = 60


@router.post("/refresh")
def refresh_token(body: dict, db: Session = Depends(get_db)):
    token = body.get("refresh_token", "")
    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "refresh":
        log.info("refresh_outcome", outcome="invalid_token")
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_tok = _user_token(decoded.get("sub", ""))
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    stored = db.query(RefreshToken).filter_by(token_hash=token_hash).first()

    if not stored:
        log.info("refresh_outcome", outcome="not_found", user=user_tok)
        raise HTTPException(status_code=401, detail="Token revoked or not found")

    now = datetime.now(timezone.utc)
    created_at = _as_aware(stored.created_at)
    seconds_since_issued = (now - created_at).total_seconds() if created_at else None

    if not stored.is_revoked:
        # Happy path: first (and so far only) presentation of this token — rotate.
        stored.is_revoked = True
        stored.revoked_at = now
        new_payload = {"sub": decoded["sub"], "tenant_id": decoded["tenant_id"], "role": decoded.get("role")}
        new_access = create_access_token(new_payload)
        new_refresh = create_refresh_token(new_payload)

        new_hash = hashlib.sha256(new_refresh.encode()).hexdigest()
        stored.replaced_by_token_hash = new_hash
        db.add(RefreshToken(
            id=str(uuid.uuid4()),
            user_id=decoded["sub"],
            tenant_id=decoded["tenant_id"],
            token_hash=new_hash,
        ))
        db.commit()

        log.info("refresh_outcome", outcome="rotated", user=user_tok, seconds_since_issued=seconds_since_issued)
        return {"access_token": new_access, "refresh_token": new_refresh, "token_type": "bearer"}

    # Token was already rotated. Distinguish a same-client race from reuse.
    revoked_at = _as_aware(stored.revoked_at)
    age_since_revoked = (now - revoked_at).total_seconds() if revoked_at else None

    if (
        stored.replaced_by_token_hash
        and age_since_revoked is not None
        and age_since_revoked <= _REFRESH_GRACE_WINDOW_SECONDS
    ):
        # Race: within the grace window and we know this token's rotation
        # already produced a successor (a concurrent request got there
        # first). We can't hand back that successor's raw value -- only its
        # hash was ever stored -- so mint another valid access+refresh pair
        # instead of erroring. Both this pair and the earlier successor stay
        # valid; whichever the client uses next rotates normally. Returning
        # a null/absent refresh_token here would make the client's
        # `data.refresh_token ?? <old token>` fallback re-present the
        # already-revoked token on its next refresh, which would eventually
        # fall outside the grace window and trip false reuse-detection.
        successor = db.query(RefreshToken).filter_by(
            token_hash=stored.replaced_by_token_hash, is_revoked=False
        ).first()
        if successor:
            new_payload = {"sub": decoded["sub"], "tenant_id": decoded["tenant_id"], "role": decoded.get("role")}
            new_access = create_access_token(new_payload)
            new_refresh = create_refresh_token(new_payload)
            new_hash = hashlib.sha256(new_refresh.encode()).hexdigest()
            db.add(RefreshToken(
                id=str(uuid.uuid4()),
                user_id=decoded["sub"],
                tenant_id=decoded["tenant_id"],
                token_hash=new_hash,
            ))
            db.commit()
            log.info(
                "refresh_outcome", outcome="race_reissued", user=user_tok,
                seconds_since_issued=seconds_since_issued, age_since_revoked=age_since_revoked,
            )
            return {"access_token": new_access, "refresh_token": new_refresh, "token_type": "bearer"}

    # Reuse outside the grace window (or no known successor) — genuine reuse
    # of a dead token. Treat as theft: kill every active refresh token for
    # this user, forcing a full re-login on all devices/tabs.
    revoked_count = (
        db.query(RefreshToken)
        .filter_by(user_id=decoded["sub"], is_revoked=False)
        .update({"is_revoked": True, "revoked_at": now})
    )
    append_audit(
        db,
        tenant_id=decoded["tenant_id"],
        action="auth.refresh_token_reuse_detected",
        actor_user_id=decoded.get("sub"),
        target_type="user",
        target_id=decoded.get("sub"),
        payload={"revoked_count": revoked_count, "age_since_revoked": age_since_revoked},
    )
    db.commit()

    log.info(
        "refresh_outcome", outcome="reuse_detected", user=user_tok,
        seconds_since_issued=seconds_since_issued, age_since_revoked=age_since_revoked,
        revoked_count=revoked_count,
    )
    raise HTTPException(status_code=401, detail="Token revoked or not found")


@router.post("/logout")
def logout(body: dict, db: Session = Depends(get_db)):
    token = body.get("refresh_token", "")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    stored = db.query(RefreshToken).filter_by(token_hash=token_hash).first()
    if stored:
        stored.is_revoked = True
        stored.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"status": "logged_out"}


# ─── /auth/me ────────────────────────────────────────────────────────────────

@router.get("/me")
def get_me(token: str = Depends(_oauth2_scheme), db: Session = Depends(get_db)):
    """Return current user + tenant info (used by Next-Auth authorize callback)."""
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    decoded = decode_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter_by(id=decoded["sub"], is_deleted=False).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()

    # Derive onboarding_step — prefer what's saved, but auto-complete for
    # existing accounts that were created before the onboarding wizard existed.
    # "Existing account" = tenant has a name set AND has ≥1 property in the DB.
    raw_step = int((tenant.brand_config or {}).get("onboarding_step", 0)) if tenant else 0
    if raw_step < 9:
        try:
            from app.models.property import Property
            has_properties = db.query(Property).filter_by(
                tenant_id=user.tenant_id
            ).limit(1).count() > 0
        except Exception:
            has_properties = False
        # If the tenant already has properties, they're set up — mark complete
        if has_properties:
            raw_step = 9
            # Persist so subsequent logins don't recompute this every time
            if tenant:
                cfg = dict(tenant.brand_config or {})
                if cfg.get("onboarding_step", 0) < 9:
                    cfg["onboarding_step"] = 9
                    tenant.brand_config = cfg
                    db.commit()

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "tenant_id": user.tenant_id,
        "is_mfa_enabled": user.is_mfa_enabled,
        "onboarding_step": raw_step,
        "tenant": {
            "id": tenant.id if tenant else None,
            "name": tenant.name if tenant else None,
            "slug": tenant.slug if tenant else None,
            "config": tenant.brand_config if tenant else {},
        },
    }


# ─── MFA ─────────────────────────────────────────────────────────────────────

class MFASetupResponse(BaseModel):
    secret: str
    qr_data_uri: str   # base64 PNG data URI for QR code


class MFAVerifyRequest(BaseModel):
    code: str          # 6-digit TOTP


@router.post("/mfa/setup", response_model=MFASetupResponse)
def mfa_setup(token: str = Depends(_oauth2_scheme), db: Session = Depends(get_db)):
    """Generate a new TOTP secret and return the QR code for enrollment."""
    if not _PYOTP_AVAILABLE:
        raise HTTPException(status_code=501, detail="pyotp not installed")
    decoded = decode_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter_by(id=decoded["sub"], is_deleted=False).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    secret = pyotp.random_base32()
    user.mfa_secret = secret
    db.commit()

    totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.email, issuer_name="HAIP"
    )

    # Generate QR code PNG as base64 data URI
    img = qrcode.make(totp_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    return MFASetupResponse(secret=secret, qr_data_uri=data_uri)


@router.post("/mfa/verify")
def mfa_verify(
    req: MFAVerifyRequest,
    token: str = Depends(_oauth2_scheme),
    db: Session = Depends(get_db),
):
    """Verify a TOTP code. On success: enable MFA on the account (if not yet) and return fresh tokens."""
    if not _PYOTP_AVAILABLE:
        raise HTTPException(status_code=501, detail="pyotp not installed")
    decoded = decode_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter_by(id=decoded["sub"], is_deleted=False).first()
    if not user or not user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA not set up for this account")

    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(req.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    # Enable MFA flag if this is first successful verification
    if not user.is_mfa_enabled:
        user.is_mfa_enabled = True
        db.commit()

    # Issue fresh tokens now that MFA is confirmed
    payload = {"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value, "mfa": True}
    access = create_access_token(payload)
    refresh = create_refresh_token(payload)

    token_hash = hashlib.sha256(refresh.encode()).hexdigest()
    db.add(RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        tenant_id=user.tenant_id,
        token_hash=token_hash,
    ))
    db.commit()

    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "mfa_enabled": True}


@router.get("/invitation/{token}")
def preview_invitation(token: str, db: Session = Depends(get_db)):
    """Return invitation details (name, email, role, tenant) — no auth required.
    Used by the /join page so invitees can see who invited them before accepting."""
    invitation = db.query(UserInvitation).filter_by(token=token, is_accepted=False, is_revoked=False).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")
    if datetime.now(timezone.utc) > invitation.expires_at:
        raise HTTPException(status_code=400, detail="Invitation has expired")

    tenant = db.query(Tenant).filter_by(id=invitation.tenant_id).first()
    return {
        "email": invitation.email,
        "name": invitation.name,
        "role": invitation.role.value if hasattr(invitation.role, "value") else invitation.role,
        "tenant_name": tenant.name if tenant else None,
    }


def _get_redis():
    """Lazy Redis connection — avoids import-time failure if Redis is down."""
    try:
        import redis as redis_lib
        from app.core.config import settings
        return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as exc:
        log.warning("redis_unavailable", error=str(exc))
        return None


@router.post("/accept-invitation", response_model=LoginResponse)
def accept_invitation(body: dict, db: Session = Depends(get_db)):
    """Accept a workspace invitation and set a password to activate the account."""
    token = body.get("token", "")
    password = body.get("password", "")
    if not token or not password:
        raise HTTPException(status_code=400, detail="token and password are required")

    invitation = db.query(UserInvitation).filter_by(token=token, is_accepted=False, is_revoked=False).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")

    if datetime.now(timezone.utc) > invitation.expires_at:
        raise HTTPException(status_code=400, detail="Invitation has expired")

    # Check if user already exists in this tenant (created at invite time)
    user = db.query(User).filter_by(email=invitation.email, tenant_id=invitation.tenant_id).first()
    if not user:
        # Create new user
        user = User(
            id=str(uuid.uuid4()),
            tenant_id=invitation.tenant_id,
            name=invitation.name,
            email=invitation.email,
            role=invitation.role,
            is_active=True,
        )
        db.add(user)

    user.hashed_password = get_password_hash(password)
    user.is_active = True
    invitation.is_accepted = True

    payload = {"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value}
    access = create_access_token(payload)
    refresh = create_refresh_token(payload)

    token_hash = hashlib.sha256(refresh.encode()).hexdigest()
    db.add(RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        tenant_id=user.tenant_id,
        token_hash=token_hash,
    ))
    db.commit()

    return LoginResponse(
        access_token=access,
        refresh_token=refresh,
        user={"id": user.id, "name": user.name, "email": user.email, "role": user.role.value, "tenant_id": user.tenant_id},
    )


@router.post("/mfa/disable")
def mfa_disable(
    req: MFAVerifyRequest,
    token: str = Depends(_oauth2_scheme),
    db: Session = Depends(get_db),
):
    """Disable MFA after verifying the current TOTP code."""
    if not _PYOTP_AVAILABLE:
        raise HTTPException(status_code=501, detail="pyotp not installed")
    decoded = decode_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter_by(id=decoded["sub"], is_deleted=False).first()
    if not user or not user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA not set up")

    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(req.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    user.is_mfa_enabled = False
    user.mfa_secret = None
    db.commit()
    return {"status": "mfa_disabled"}


# ─── Forgot / Reset Password ──────────────────────────────────────────────────

_RESET_TTL = 3600  # 1 hour


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


async def issue_password_reset_email(user: "User") -> bool:
    """Generate a reset token + email it to the user. Shared by the
    self-service /forgot-password (below) and the owner/manager-triggered
    admin endpoint (users.py's POST /users/{id}/send-password-reset) --
    same token/link mechanism either way. Returns True if the email was
    actually sent, False if Redis is unavailable or the send failed --
    callers decide how to surface that (forgot_password stays silent to
    avoid enumeration; the admin endpoint surfaces a real error)."""
    r = _get_redis()
    if r is None:
        log.warning("password_reset_redis_unavailable", user_id=user.id)
        return False

    reset_token = secrets.token_urlsafe(32)
    redis_key = f"pwd_reset:{reset_token}"
    r.setex(redis_key, _RESET_TTL, user.id)

    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"

    try:
        from app.services.email_service import send_password_reset_email
        await send_password_reset_email(
            to_email=user.email,
            name=user.name,
            reset_link=reset_link,
        )
        log.info("password_reset_email_sent", user_id=user.id)
        return True
    except Exception as exc:
        log.error("password_reset_email_failed", user_id=user.id, error=str(exc))
        return False


@router.post("/forgot-password", status_code=200)
async def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Send a password-reset link to the given email.
    Always returns 200 — never reveals whether the email exists (prevents enumeration).
    """
    _GENERIC_RESPONSE = {"message": "If that email is registered, you'll receive a reset link shortly."}

    user = db.query(User).filter_by(email=req.email, is_deleted=False).first()
    if not user:
        return _GENERIC_RESPONSE

    await issue_password_reset_email(user)
    return _GENERIC_RESPONSE


@router.post("/reset-password", status_code=200)
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    """
    Validate reset token and update the user's password.
    Token is single-use and expires after 1 hour.
    """
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    r = _get_redis()
    if r is None:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable. Please try again shortly.")

    redis_key = f"pwd_reset:{req.token}"
    user_id = r.get(redis_key)
    if not user_id:
        raise HTTPException(status_code=400, detail="Reset link is invalid or has expired. Please request a new one.")

    user = db.query(User).filter_by(id=user_id, is_deleted=False).first()
    if not user or not user.is_active:
        r.delete(redis_key)
        raise HTTPException(status_code=404, detail="Account not found.")

    # Update password
    user.hashed_password = get_password_hash(req.new_password)

    # Revoke all existing refresh tokens for security
    db.query(RefreshToken).filter_by(user_id=user.id, is_revoked=False).update({"is_revoked": True})
    db.commit()

    # Consume token — single use
    r.delete(redis_key)

    log.info("password_reset_success", user_id=user.id)
    return {"message": "Password updated successfully. Please sign in with your new password."}
