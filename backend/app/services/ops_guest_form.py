"""The guest ID form of a booking's ops file, for every pack (caravan trip, villa stay; port of the Ratha prototype's
guestform.ts, widened in Nov 2026 for stays and guests from abroad).

A private link /r/trip/<token> (caravan) or /r/stay/<token> (villa), no login. The token is an HMAC of the form's id +
nonce (so the link can be shown again) and only its SHA-256 is stored; ops_guest_form_lookup (SECURITY DEFINER, migration
180) maps the hash to the tenant on PostgreSQL. The guest fills names, ages, nationality and ID per person (Aadhaar: only
the last 4 digits are kept), an emergency contact, food notes and requests, types their name to sign and ticks the consent
text of a stated version. On submit the caravan readiness item "guests" turns green.

A guest who is not an Indian citizen also gives passport + visa details and photos (what Form C needs; ops_form_c):
the passport and visa numbers are stored ONLY Fernet-encrypted (`numbers_enc`, core.encryption) with their last 4 digits
for display; photos go to private storage (media_storage.upload_ops_guest_doc) and are read only through the audited
reveal. Everything lives in this one row (`data`) and is erased with the guest's bookings (dpdp_erasure_service).

data before submit: {uploads: {photo_id: {key, kind}}, hint_foreign?}; after: {guests: [...], emergency_*, food, requests,
hint_foreign?, hint_form_c?}. guests[i] = {name, age, nationality, id_type, id_number, foreign?: {...}, form_c?: {...}}.
"""

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import set_tenant_context
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.ops_files import OpsFile
from app.models.ops_fleet import OpsGuestForm
from app.models.property import Property
from app.schemas.ops_fleet import (
    CONSENT_TEXTS,
    CONSENT_VERSION,
    COUNTRIES,
    GUEST_DOC_KINDS,
    ID_TYPES,
    NO_VISA_NEEDED,
    VISA_TYPES,
    GuestEntryIn,
    GuestFormIn,
)
from app.services import ops_money as money
from app.services import ops_pack_catalog as packs
from app.services import ops_trip_service as trips
from app.services.wa_booking_messages import Target

_CTRL = re.compile(r"[\x00-\x1f]")
MAX_UPLOADS = 30  # photos one form may hold before submit (2 per guest x 12, plus a few replacements)


def _clean(s: str | None, limit: int) -> str:
    return _CTRL.sub(" ", s or "").strip()[:limit]


def token_for(form: OpsGuestForm) -> str:
    mac = hmac.new(settings.SECRET_KEY.encode(), f"ops-guest-form:{form.id}:{form.nonce}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()[:18]).decode().rstrip("=")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def file_word(f: OpsFile | None) -> str:
    """"trip" or "stay": the pack's own word (the link path and the guest-facing wording)."""
    return packs.get(f.pack)["file_word"] if f is not None and f.pack in packs.PACKS else "trip"


def link(form: OpsGuestForm, word: str = "trip") -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/r/{'stay' if word == 'stay' else 'trip'}/{token_for(form)}"


def link_for(f: OpsFile, form: OpsGuestForm) -> str:
    return link(form, file_word(f))


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


def form_of(db: Session, f: OpsFile) -> OpsGuestForm | None:
    return db.query(OpsGuestForm).filter_by(tenant_id=f.tenant_id, file_id=f.id).first()


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


def is_foreign(g: dict) -> bool:
    return (g.get("nationality") or "IN") != "IN"


def expect_foreign(db: Session, tenant_id: str, stay) -> bool:
    """A website booking said the guest is not Indian: make the ops file + form now and remember it, so Form C is raised
    at arrival even if the guest never fills the form (ops_form_c). False when the business has no ops pack (the caller
    then keeps its own reminder task)."""
    with db.begin_nested():
        f = trips.ensure_file(db, tenant_id, stay)
        if f is None:
            return False
        form = ensure_form(db, f)
        form.data = {**(form.data or {}), "hint_foreign": True}
    return True


# ── Validation ──────────────────────────────────────────────────────────────


def _date(raw: str, what: str, errors: list[str], lo: date | None = None, hi: date | None = None,
          required: bool = True, expiry: bool = False) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        if required:
            errors.append(f"{what} is required")
        return None
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        errors.append(f"{what} is not a date")
        return None
    if (lo and d < lo) or (hi and d > hi):
        errors.append(f"{what} has passed" if expiry else f"{what} looks wrong")
        return None
    return d.isoformat()


def _doc_number(raw: str) -> str:
    return re.sub(r"[\s-]", "", raw or "").upper()


def _id(g: GuestEntryIn, who: str, errors: list[str]) -> tuple[str, str]:
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
    return id_type or "other", number


def _photo(photo_id: str, kind: str, uploads: dict, who: str, what: str, errors: list[str], required: bool) -> str | None:
    up = uploads.get(photo_id or "")
    if up is None or up.get("kind") != kind:
        if required:
            errors.append(f"{who}: add a photo of the {what}")
        return None
    return up["key"]


def _foreign(g: GuestEntryIn, cc: str, who: str, uploads: dict, today: date, errors: list[str]) -> tuple[dict, str, str]:
    """Passport, visa and travel details of a guest who is not an Indian citizen. Returns (foreign block, id_type,
    id_number to show). Numbers leave here only encrypted, plus their last 4 digits."""
    free = cc in NO_VISA_NEEDED  # Nepal, Bhutan: no visa, and a passport is optional
    passport = _doc_number(g.passport_number)
    has_passport = bool(passport) or not free
    if has_passport and not re.fullmatch(r"[A-Z0-9]{6,12}", passport):
        errors.append(f"{who}: passport number should be 6 to 12 letters or digits")
    visa_type = g.visa_type if g.visa_type in VISA_TYPES else None
    visa = _doc_number(g.visa_number)
    has_visa = not free or bool(visa or g.visa_type)
    if has_visa and visa_type is None:
        errors.append(f"{who}: choose the visa type")
    if has_visa and not re.fullmatch(r"[A-Z0-9]{4,20}", visa):
        errors.append(f"{who}: {'OCI card' if visa_type == 'oci' else 'visa'} number should be 4 to 20 letters or digits")
    block = {
        "passport_last4": passport[-4:] if has_passport else None,
        "passport_expires_on": _date(g.passport_expires_on, f"{who}: passport expiry", errors, lo=today,
                                     expiry=True)
        if has_passport else None,
        "visa_type": visa_type if has_visa else None,
        "visa_last4": visa[-4:] if has_visa else None,
        "visa_expires_on": _date(g.visa_expires_on, f"{who}: visa expiry", errors, lo=today,
                                 required=visa_type != "oci", expiry=True) if has_visa else None,
        "arrived_india_on": _date(g.arrived_india_on, f"{who}: date of arrival in India", errors,
                                  lo=today - timedelta(days=3650), hi=today + timedelta(days=400)),
        "arrived_from": _clean(g.arrived_from, 80),
        "onward_to": _clean(g.onward_to, 80),
        "passport_photo_key": _photo(g.passport_photo_id, "passport", uploads, who, "passport", errors, has_passport),
        "visa_photo_key": _photo(g.visa_photo_id, "visa", uploads, who,
                                 "OCI card" if visa_type == "oci" else "visa", errors, has_visa),
    }
    if len(block["arrived_from"]) < 2:
        errors.append(f"{who}: say where you arrived in India from (city, country)")
    if len(block["onward_to"]) < 2:
        errors.append(f"{who}: say where you go after this (city, country)")
    secret = {k: v for k, v in (("passport", passport if has_passport else ""), ("visa", visa if has_visa else "")) if v}
    block["numbers_enc"] = encrypt_credentials(secret).decode() if secret else None
    if has_passport:
        return block, "passport", passport[-4:]
    id_type, number = _id(g, who, errors)  # Nepal / Bhutan without a passport: their own ID instead
    return block, id_type, number


def build(body: GuestFormIn, uploads: dict | None = None, today: date | None = None) -> dict:
    """Validate the form; every problem is reported at once (one 422 listing them)."""
    errors: list[str] = []
    uploads, today = uploads or {}, today or datetime.now(UTC).date()
    guests = []
    for n, g in enumerate(body.guests, start=1):
        who = f"Guest {n}"
        name = _clean(g.name, 80)
        if not name:
            errors.append(f"{who}: name is required")
        cc = (g.nationality or "IN").strip().upper()
        if cc not in COUNTRIES:
            errors.append(f"{who}: choose a nationality")
            cc = "IN"
        age = None
        if g.age.strip():
            try:
                age = int(g.age)
            except ValueError:
                age = -1
            if not 0 <= age <= 110:
                errors.append(f"{who}: age looks wrong")
        entry: dict = {"name": name, "age": age, "nationality": cc}
        if cc == "IN":  # Indian citizen: passport and visa fields are ignored, never stored
            entry["id_type"], entry["id_number"] = _id(g, who, errors)
        else:
            entry["foreign"], entry["id_type"], entry["id_number"] = _foreign(g, cc, who, uploads, today, errors)
        guests.append(entry)
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
    if is_foreign(g) and g.get("id_type") == "passport":
        return f"••••{n}"
    return "•" * (len(n) - 4) + n[-4:] if len(n) > 4 else n


def numbers(g: dict) -> dict:
    """The full passport / visa numbers (decrypted). Callers: the audited reveal only."""
    enc = (g.get("foreign") or {}).get("numbers_enc")
    return decrypt_credentials(enc.encode()) if enc else {}


def file_keys(form: OpsGuestForm) -> list[str]:
    """Every stored photo of the form (pending uploads + each guest's passport / visa), for DPDP erasure."""
    d = form.data or {}
    keys = [u.get("key") for u in (d.get("uploads") or {}).values()]
    for g in d.get("guests") or []:
        fb = g.get("foreign") or {}
        keys += [fb.get("passport_photo_key"), fb.get("visa_photo_key")]
    return [k for k in keys if k]


# ── Guest side ──────────────────────────────────────────────────────────────


def public_view(db: Session, form: OpsGuestForm) -> dict:
    f = db.get(OpsFile, form.file_id)
    stay = money.stay_of(db, f)
    first = ((stay.guest.name if stay.guest else "") or "").split(" ")[0] or "there"
    word = file_word(f)
    place = db.query(Property.name).filter_by(id=stay.property_id, tenant_id=stay.tenant_id).scalar()
    return {
        "guest_first_name": first,
        "check_in": stay.check_in.isoformat(),
        "check_out": stay.check_out.isoformat(),
        "party": party_count(stay.adults, stay.children),
        "submitted": form.submitted_at is not None,
        "file_word": word,
        "unit_word": packs.get(f.pack)["unit_word"] if f.pack in packs.PACKS else "property",
        "place": place,
        "guest_from_abroad": bool((form.data or {}).get("hint_foreign")),
        "id_types": [{"value": k, "label": v} for k, v in ID_TYPES.items()],
        "countries": sorted(COUNTRIES),
        "no_visa_needed": sorted(NO_VISA_NEEDED),
        "visa_types": [{"value": k, "label": v} for k, v in VISA_TYPES.items()],
        "photo_kinds": list(GUEST_DOC_KINDS),
        "consent": {"version": CONSENT_VERSION, "text": CONSENT_TEXTS.get(word, CONSENT_TEXTS["trip"])},
    }


def _open_file(db: Session, form: OpsGuestForm) -> OpsFile:
    f = db.get(OpsFile, form.file_id)
    if f is None or f.state in ("closed", "cancelled"):
        word = file_word(f)
        raise HTTPException(status_code=409, detail=f"This {word} is no longer open. Please contact us on WhatsApp.")
    if form.submitted_at is not None:
        raise HTTPException(
            status_code=409, detail="We already have your details. Please message us on WhatsApp to change them."
        )
    return f


def add_photo(db: Session, form: OpsGuestForm, kind: str, raw: bytes, content_type: str) -> str:
    """One passport / visa photo from the guest's page, stored privately before the form is sent. Returns its id."""
    from app.services import media_storage
    from app.services.ops_fleet_service import check_file

    _open_file(db, form)
    if kind not in GUEST_DOC_KINDS:
        raise HTTPException(status_code=422, detail="Choose passport or visa.")
    ext = check_file(raw, content_type)  # the paper scans' limits: JPG / PNG / WebP / PDF, 5 MB, real file
    data = dict(form.data or {})
    uploads = dict(data.get("uploads") or {})
    if len(uploads) >= MAX_UPLOADS:
        raise HTTPException(status_code=422, detail="Too many photos on this form. Please message us on WhatsApp.")
    photo_id = secrets.token_hex(12)
    key = media_storage.upload_ops_guest_doc(form.tenant_id, form.id, photo_id, raw, content_type, ext)
    uploads[photo_id] = {"key": key, "kind": kind}
    data["uploads"] = uploads
    form.data = data
    db.flush()
    return photo_id


def submit(db: Session, form: OpsGuestForm, body: GuestFormIn) -> list[str]:
    """Save the form. Returns the storage keys of photos uploaded but not used (the caller deletes them after commit)."""
    f = _open_file(db, form)
    prior = dict(form.data or {})
    uploads = prior.pop("uploads", None) or {}
    from app.services.booking_agenda_service import tenant_today

    data = build(body, uploads, tenant_today(db, form.tenant_id))  # expiry dates against the workspace's own date
    form.signed_name = data.pop("signed_name")
    form.data = {**prior, **data}
    form.consent_version, form.submitted_at = CONSENT_VERSION, datetime.now(UTC)
    abroad = sum(1 for g in data["guests"] if is_foreign(g))
    money.event(
        db,
        f,
        f"Guest details form filled for {len(data['guests'])} people"
        + (f", {abroad} from abroad (Form C needed)" if abroad else "")
        + f" (signed {form.signed_name})",
        auto=True,
    )
    if f.state in trips.BEFORE_ROAD and any(i.key == "guests" for i in trips.readiness_items(db, f)):
        trips.set_item(db, f, "guests", "green", "Guest form filled")
    db.flush()
    from app.services import ops_form_c

    ops_form_c.sync(db, f)
    used = set(file_keys(form))
    return [u["key"] for u in uploads.values() if u.get("key") and u["key"] not in used]


# ── Staff side ──────────────────────────────────────────────────────────────


def _staff_guest(g: dict) -> dict:
    out = {"name": g["name"], "age": g.get("age"), "nationality": g.get("nationality") or "IN",
           "id": f"{ID_TYPES.get(g['id_type'], 'ID')} {mask_id(g)}"}
    fb = g.get("foreign")
    if fb is not None:
        out["foreign"] = {
            "passport": f"••••{fb['passport_last4']}" if fb.get("passport_last4") else None,
            "passport_expires_on": fb.get("passport_expires_on"),
            "visa_type": VISA_TYPES.get(fb.get("visa_type") or "", None),
            "visa": f"••••{fb['visa_last4']}" if fb.get("visa_last4") else None,
            "visa_expires_on": fb.get("visa_expires_on"),
            "arrived_india_on": fb.get("arrived_india_on"),
            "photos": sum(1 for k in ("passport_photo_key", "visa_photo_key") if fb.get(k)),
        }
        fc = g.get("form_c") or {}
        out["form_c"] = {"due_at": fc.get("due_at"), "submitted_at": fc.get("submitted_at")}
    return out


def staff_view(db: Session, f: OpsFile, with_link: bool) -> dict:
    """What the file page shows: never a full passport / visa number (those need the audited reveal, ops_form_c)."""
    form = form_of(db, f)
    out: dict = {"submitted_at": None, "guests": [], "link": None, "file_word": file_word(f), "from_abroad": 0,
                 "guest_from_abroad": bool(form is not None and (form.data or {}).get("hint_foreign"))}
    if form is None:
        return out
    if with_link:
        out["link"] = link_for(f, form)
    if form.submitted_at:
        d = form.data or {}
        guests = [_staff_guest(g) for g in d.get("guests", [])]
        out.update(
            {
                "submitted_at": form.submitted_at.isoformat(),
                "guests": guests,
                "from_abroad": sum(1 for g in guests if "foreign" in g),
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
    word = file_word(f)
    who = "travelling" if word == "trip" else "staying"
    db.commit()
    body = (
        f"Hello {first}, to get your {word} ready please fill in the guest details and ID form for everyone {who} "
        f"(about 2 minutes):\n\n{link_for(f, form)}\n\nYour details are kept private and used only to register your {word}."
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
