from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from app.core.database import get_db
from app.core.security import (
    verify_password, get_password_hash,
    create_access_token, create_refresh_token, decode_token,
)
from app.models.user import User, RefreshToken, UserInvitation, UserRole
from app.models.tenant import Tenant
import uuid, hashlib, secrets, random
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


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=req.email, is_deleted=False).first()
    if not user or not verify_password(req.password, user.hashed_password or ""):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

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
def register(req: RegisterRequest, db: Session = Depends(get_db)):
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
    )
    db.add(tenant)
    db.flush()

    from app.models.user import UserRole
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        name=req.name,
        email=req.email,
        hashed_password=get_password_hash(req.password),
        role=UserRole.OWNER,
        is_active=True,
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

    return LoginResponse(
        access_token=access,
        refresh_token=refresh,
        user={"id": user.id, "name": user.name, "email": user.email, "role": user.role.value, "tenant_id": tenant.id},
    )


@router.post("/refresh")
def refresh_token(body: dict, db: Session = Depends(get_db)):
    token = body.get("refresh_token", "")
    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    stored = db.query(RefreshToken).filter_by(token_hash=token_hash, is_revoked=False).first()
    if not stored:
        raise HTTPException(status_code=401, detail="Token revoked or not found")

    # Rotate: revoke old, issue new
    stored.is_revoked = True
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

    return {"access_token": new_access, "refresh_token": new_refresh, "token_type": "bearer"}


@router.post("/logout")
def logout(body: dict, db: Session = Depends(get_db)):
    token = body.get("refresh_token", "")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    stored = db.query(RefreshToken).filter_by(token_hash=token_hash).first()
    if stored:
        stored.is_revoked = True
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
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "tenant_id": user.tenant_id,
        "is_mfa_enabled": user.is_mfa_enabled,
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
    try:
        expires = datetime.fromisoformat(str(invitation.expires_at).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires:
            raise HTTPException(status_code=400, detail="Invitation has expired")
    except (ValueError, TypeError):
        pass

    tenant = db.query(Tenant).filter_by(id=invitation.tenant_id).first()
    return {
        "email": invitation.email,
        "name": invitation.name,
        "role": invitation.role.value if hasattr(invitation.role, "value") else invitation.role,
        "tenant_name": tenant.name if tenant else None,
    }


# ─── O7: Phone + OTP Login ────────────────────────────────────────────────────

_OTP_TTL = 300        # 5 minutes
_OTP_RATE_WINDOW = 600  # 10 minutes
_OTP_RATE_MAX = 3     # max sends per phone per window
_OTP_MAX_ATTEMPTS = 3 # max verify attempts per code


def _get_redis():
    """Lazy Redis connection — avoids import-time failure if Redis is down."""
    try:
        import redis as redis_lib
        from app.core.config import settings
        return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as exc:
        log.warning("redis_unavailable", error=str(exc))
        return None


class OtpSendRequest(BaseModel):
    phone: str  # E.164 format e.g. +919876543210


class OtpVerifyRequest(BaseModel):
    phone: str
    code: str  # 6-digit OTP


@router.post("/otp/send")
def otp_send(req: OtpSendRequest, db: Session = Depends(get_db)):
    """
    O7 — Send a 6-digit OTP to the given phone number via WhatsApp.

    Rate limit: 3 sends per phone per 10 minutes.
    OTP TTL: 5 minutes.
    """
    # Normalise phone — must be E.164
    phone = req.phone.strip()
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Phone must be in E.164 format (e.g. +919876543210)")

    # User must already exist with this phone
    user = db.query(User).filter_by(phone=phone, is_deleted=False).first()
    if not user:
        # Return generic message to avoid phone enumeration
        return {"message": "If this number is registered, you will receive an OTP shortly."}

    r = _get_redis()
    if r is None:
        raise HTTPException(status_code=503, detail="OTP service temporarily unavailable. Please use email login.")

    rate_key = f"otp:rate:{phone}"
    send_count = r.get(rate_key)
    if send_count and int(send_count) >= _OTP_RATE_MAX:
        raise HTTPException(
            status_code=429,
            detail=f"Too many OTP requests. Please wait 10 minutes before trying again."
        )

    # Generate and store OTP
    code = f"{random.randint(100000, 999999)}"
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    otp_key = f"otp:code:{phone}"

    r.setex(otp_key, _OTP_TTL, f"{code_hash}:0")  # value = hash:attempts

    # Update rate counter
    pipe = r.pipeline()
    pipe.incr(rate_key)
    pipe.expire(rate_key, _OTP_RATE_WINDOW)
    pipe.execute()

    # Send via WhatsApp (use Meta Cloud API if available, else log)
    _dispatch_otp(phone, code, user.name or "")

    log.info("otp_sent", phone=phone, user_id=user.id)
    return {"message": "OTP sent to your WhatsApp number.", "expires_in": _OTP_TTL}


def _dispatch_otp(phone: str, code: str, name: str) -> None:
    """Send OTP via WhatsApp utility template. Falls back to log if not configured."""
    try:
        from app.models.integration import Integration
        from app.core.database import SessionLocal
        from app.core.encryption import decrypt_credentials

        # Look up any tenant's WhatsApp config — OTP is cross-tenant (phone-keyed)
        # In production, use a dedicated system-level WABA
        db = SessionLocal()
        try:
            wa = db.query(Integration).filter_by(kind="whatsapp_meta", status="connected").first()
            if not wa:
                log.warning("otp_wa_not_configured", phone=phone)
                log.info("otp_code_fallback", phone=phone, code=code)  # dev only
                return

            creds = decrypt_credentials(wa.credentials_enc)
            import httpx
            resp = httpx.post(
                f"https://graph.facebook.com/v19.0/{creds.get('phone_number_id')}/messages",
                headers={"Authorization": f"Bearer {creds.get('access_token')}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": phone.lstrip("+"),
                    "type": "template",
                    "template": {
                        "name": "otp",
                        "language": {"code": "en"},
                        "components": [{"type": "body", "parameters": [{"type": "text", "text": code}]}],
                    },
                },
                timeout=10,
            )
            if resp.status_code != 200:
                log.warning("otp_wa_send_failed", phone=phone, status=resp.status_code, body=resp.text[:200])
                log.info("otp_code_fallback", phone=phone, code=code)  # dev only
        finally:
            db.close()
    except Exception as exc:
        log.warning("otp_dispatch_error", phone=phone, error=str(exc))
        log.info("otp_code_fallback", phone=phone, code=code)  # dev only — remove in prod


@router.post("/otp/verify", response_model=LoginResponse)
def otp_verify(req: OtpVerifyRequest, db: Session = Depends(get_db)):
    """
    O7 — Verify OTP and return access/refresh tokens on success.
    Max 3 attempts per OTP. OTP is single-use.
    """
    phone = req.phone.strip()
    code = req.code.strip()

    r = _get_redis()
    if r is None:
        raise HTTPException(status_code=503, detail="OTP service temporarily unavailable.")

    otp_key = f"otp:code:{phone}"
    stored = r.get(otp_key)
    if not stored:
        raise HTTPException(status_code=400, detail="OTP expired or not found. Please request a new one.")

    code_hash_stored, attempts_str = stored.split(":")
    attempts = int(attempts_str)

    if attempts >= _OTP_MAX_ATTEMPTS:
        r.delete(otp_key)
        raise HTTPException(status_code=400, detail="Too many invalid attempts. Please request a new OTP.")

    code_hash = hashlib.sha256(code.encode()).hexdigest()
    if not secrets.compare_digest(code_hash, code_hash_stored):
        # Increment attempts
        r.setex(otp_key, r.ttl(otp_key), f"{code_hash_stored}:{attempts + 1}")
        remaining = _OTP_MAX_ATTEMPTS - attempts - 1
        raise HTTPException(status_code=401, detail=f"Invalid OTP. {remaining} attempt(s) remaining.")

    # Valid — consume OTP
    r.delete(otp_key)

    user = db.query(User).filter_by(phone=phone, is_deleted=False).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account not found or disabled.")

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

    log.info("otp_login_success", phone=phone, user_id=user.id)

    return LoginResponse(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        user={
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role.value,
            "tenant_id": user.tenant_id,
            "onboarding_step": user.onboarding_step,
        },
    )


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

    # Check expiry
    try:
        expires = datetime.fromisoformat(invitation.expires_at.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires:
            raise HTTPException(status_code=400, detail="Invitation has expired")
    except ValueError:
        pass

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
