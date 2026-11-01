"""The guest ID form of a trip (port of the Ratha prototype's guestform.ts).

A private link /r/trip/<token>, no login. The token is an HMAC of the form's id + nonce (so the link can be shown again)
and only its SHA-256 is stored; ops_guest_form_lookup (SECURITY DEFINER, migration 180) maps the hash to the tenant on
PostgreSQL. The guest fills names, ages, ID type and number (Aadhaar: only the last 4 digits are kept), an emergency
contact, food notes and requests, types their name to sign and ticks the consent text of a stated version. On submit the
readiness item "guests" turns green. Erased with the guest's bookings (dpdp_erasure_service).
"""

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import set_tenant_context
from app.models.ops_files import OpsFile
from app.models.ops_fleet import OpsGuestForm
from app.schemas.ops_fleet import CONSENT_TEXT, CONSENT_VERSION, ID_TYPES, GuestFormIn
from app.services import ops_money as money
from app.services import ops_trip_service as trips
from app.services.wa_booking_messages import Target

_CTRL = re.compile(r"[\x00-\x1f]")


def _clean(s: str | None, limit: int) -> str:
    return _CTRL.sub(" ", s or "").strip()[:limit]


def token_for(form: OpsGuestForm) -> str:
    mac = hmac.new(settings.SECRET_KEY.encode(), f"ops-guest-form:{form.id}:{form.nonce}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()[:18]).decode().rstrip("=")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def link(form: OpsGuestForm) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/r/trip/{token_for(form)}"


def ensure_form(db: Session, f: OpsFile) -> OpsGuestForm:
    form = db.query(OpsGuestForm).filter_by(tenant_id=f.tenant_id, file_id=f.id).first()
    if form is None:
        form = OpsGuestForm(
            id=str(uuid.uuid4()), tenant_id=f.tenant_id, file_id=f.id, stay_id=f.stay_id, nonce=secrets.token_hex(8)
        )
        form.token_hash = _hash(token_for(form))
        db.add(form)
        db.flush()
    return form


def by_token(db: Session, token: str) -> OpsGuestForm:
    """The form for a link, with the tenant context set. A bad link is a 404 that says nothing more."""
    missing = HTTPException(status_code=404, detail="This link is not valid.")
    if not token or len(token) > 64:
        raise missing
    h = _hash(token)
    if db.bind.dialect.name == "postgresql":
        row = db.execute(text("SELECT form_id, tenant_id FROM ops_guest_form_lookup(:h)"), {"h": h}).first()
        if row is None:
            raise missing
        set_tenant_context(db, row[1])
    form = db.query(OpsGuestForm).filter_by(token_hash=h).first()
    if form is None or not hmac.compare_digest(form.token_hash, h):
        raise missing
    return form


def party_count(adults: int | None, children: int | None) -> int:
    """How many people to ask for: the booking's adults + children, at least 1, at most 12 (prototype partyCount)."""
    return min(12, max(1, (adults or 0) + (children or 0)))


def build(body: GuestFormIn) -> dict:
    """Validate the form; every problem is reported at once (one 422 listing them)."""
    errors: list[str] = []
    guests = []
    for n, g in enumerate(body.guests, start=1):
        who = f"Guest {n}"
        name = _clean(g.name, 80)
        if not name:
            errors.append(f"{who}: name is required")
        id_type = g.id_type if g.id_type in ID_TYPES else None
        if id_type is None:
            errors.append(f"{who}: choose an ID type")
        digits = re.sub(r"[\s-]", "", g.id_number)
        number = re.sub(r"\s+", "", _clean(g.id_number, 30)).upper()
        if id_type == "aadhaar":
            if not re.fullmatch(r"\d{12}", digits):
                errors.append(f"{who}: Aadhaar must be 12 digits")
            number = digits[-4:]  # only the last 4 digits are kept
        elif len(number) < 5:
            errors.append(f"{who}: ID number looks too short")
        age = None
        if g.age.strip():
            try:
                age = int(g.age)
            except ValueError:
                age = -1
            if not 0 <= age <= 110:
                errors.append(f"{who}: age looks wrong")
        guests.append({"name": name, "age": age, "id_type": id_type or "other", "id_number": number})
    phone = re.sub(r"[^\d+]", "", body.emergency_phone)
    if not _clean(body.emergency_name, 80):
        errors.append("Emergency contact name is required")
    if len(re.sub(r"\D", "", phone)) < 10:
        errors.append("Emergency contact phone needs at least 10 digits")
    if not body.agreed:
        errors.append("Please tick the box to accept the booking terms")
    if not _clean(body.signed_name, 80):
        errors.append("Type your full name to sign")
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    return {
        "guests": guests,
        "emergency_name": _clean(body.emergency_name, 80),
        "emergency_phone": phone,
        "food": _clean(body.food, 300),
        "requests": _clean(body.requests, 600),
        "signed_name": _clean(body.signed_name, 80),
    }


def mask_id(g: dict) -> str:
    n = g.get("id_number") or ""
    if g.get("id_type") == "aadhaar":
        return f"XXXX XXXX {n}"
    return "•" * (len(n) - 4) + n[-4:] if len(n) > 4 else n


def public_view(db: Session, form: OpsGuestForm) -> dict:
    stay = money.stay_of(db, db.get(OpsFile, form.file_id))
    first = ((stay.guest.name if stay.guest else "") or "").split(" ")[0] or "there"
    return {
        "guest_first_name": first,
        "check_in": stay.check_in.isoformat(),
        "check_out": stay.check_out.isoformat(),
        "party": party_count(stay.adults, stay.children),
        "submitted": form.submitted_at is not None,
        "id_types": [{"value": k, "label": v} for k, v in ID_TYPES.items()],
        "consent": {"version": CONSENT_VERSION, "text": CONSENT_TEXT},
    }


def submit(db: Session, form: OpsGuestForm, body: GuestFormIn) -> None:
    f = db.get(OpsFile, form.file_id)
    if f is None or f.state in ("closed", "cancelled"):
        raise HTTPException(status_code=409, detail="This trip is no longer open. Please contact us on WhatsApp.")
    data = build(body)
    form.signed_name = data.pop("signed_name")
    form.data, form.consent_version, form.submitted_at = data, CONSENT_VERSION, datetime.now(UTC)
    money.event(
        db, f, f"Guest details form filled for {len(data['guests'])} people (signed {form.signed_name})", auto=True
    )
    if f.state in trips.BEFORE_ROAD and any(i.key == "guests" for i in trips.readiness_items(db, f)):
        trips.set_item(db, f, "guests", "green", "Guest form filled")
    db.flush()


def staff_view(db: Session, f: OpsFile, with_link: bool) -> dict:
    form = db.query(OpsGuestForm).filter_by(tenant_id=f.tenant_id, file_id=f.id).first()
    out: dict = {"submitted_at": None, "guests": [], "link": None}
    if form is None:
        return out
    if with_link:
        out["link"] = link(form)
    if form.submitted_at:
        d = form.data or {}
        out.update(
            {
                "submitted_at": form.submitted_at.isoformat(),
                "guests": [
                    {"name": g["name"], "age": g.get("age"), "id": f"{ID_TYPES.get(g['id_type'], 'ID')} {mask_id(g)}"}
                    for g in d.get("guests", [])
                ],
                "emergency_name": d.get("emergency_name"),
                "emergency_phone": d.get("emergency_phone"),
                "food": d.get("food"),
                "requests": d.get("requests"),
                "signed_name": form.signed_name,
                "consent_version": form.consent_version,
            }
        )
    return out


def send_link(db: Session, f: OpsFile, actor_id: str) -> dict:
    """Send the link as a plain WhatsApp message; only while the guest's 24-hour window is open (no template for it)."""
    from app.services.wa_booking_messages import send_guest_text

    form = ensure_form(db, f)
    stay = money.stay_of(db, f)
    first = ((stay.guest.name if stay.guest else "") or "").split(" ")[0] or "there"
    db.commit()
    body = (
        f"Hello {first}, to get your trip ready please fill in the guest details and ID form for everyone travelling "
        f"(about 2 minutes):\n\n{link(form)}\n\nYour details are kept private and used only to register your trip."
    )
    target = Target("ops_file", f.id, "ops:", {"source": "ops", "ops_file_id": f.id}, "ops_file")
    return send_guest_text(
        db,
        f.tenant_id,
        stay.guest,
        body,
        target=target,
        event=f"guest_form:{form.nonce}",
        actor_user_id=actor_id,
        sender_kind="human",
    )
