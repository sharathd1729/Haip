"""The name HAIP greets a guest by ("Namaskara Chandu", not "Namaskara there").

A guest created from a booking form or a phone call often has no name, or a placeholder ("Unknown", the phone number),
while the same person's WhatsApp chat carries their profile name. Rules, in order:
  1. the guest's own name, when it is a real name (not empty, not "Unknown"/"Guest", not a phone number);
  2. the newest real name on another guest record with the SAME exact phone or WhatsApp number (same person by the
     lead rule in CLAUDE.md: exact normalised phone, never a name match);
  3. "there".
`fill_from_profile` keeps the guest's own record right: an inbound WhatsApp profile name fills a missing/placeholder name
(never overwrites a real one a person typed).
"""
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity

FALLBACK = "there"
_PLACEHOLDERS = {"unknown", "guest", "there", "customer", "user", "na", "n/a", "none", "null", "-"}
_PHONEISH = re.compile(r"^[+\d][\d\s().-]{5,}$")


def real_name(name: Optional[str]) -> Optional[str]:
    """The name, trimmed, or None when it is empty, a placeholder or a phone number."""
    n = (name or "").strip()
    if not n or n.lower() in _PLACEHOLDERS or _PHONEISH.match(n) or not any(ch.isalpha() for ch in n):
        return None
    return n


def first_name(name: Optional[str]) -> str:
    n = real_name(name)
    return n.split()[0] if n else FALLBACK


def best_first_name(db: Session, tenant_id: str, guest: Optional[Guest]) -> str:
    if guest is None:
        return FALLBACK
    own = real_name(guest.name)
    if own:
        return own.split()[0]
    numbers = {v for (v,) in db.query(GuestIdentity.identity_value).filter(
        GuestIdentity.tenant_id == tenant_id, GuestIdentity.guest_id == guest.id,
        GuestIdentity.identity_type.in_(("phone", "whatsapp_number"))).all() if v}
    if guest.phone:
        from app.services.guest_service import normalize_phone
        numbers.add(normalize_phone(guest.phone))
    if not numbers:
        return FALLBACK
    # A number is held by one guest per signal type (unique index), so the same person can be a "phone" guest from a booking
    # and a "whatsapp_number" guest from the chat; the guest's own phone column is checked too.
    by_signal = (db.query(Guest.name, Guest.updated_at)
                 .join(GuestIdentity, (GuestIdentity.guest_id == Guest.id) & (GuestIdentity.tenant_id == Guest.tenant_id))
                 .filter(Guest.tenant_id == tenant_id, Guest.id != guest.id,
                         GuestIdentity.identity_type.in_(("phone", "whatsapp_number")), GuestIdentity.identity_value.in_(numbers)))
    by_phone = db.query(Guest.name, Guest.updated_at).filter(Guest.tenant_id == tenant_id, Guest.id != guest.id, Guest.phone.in_(numbers))
    same = sorted(set(by_signal.all()) | set(by_phone.all()), key=lambda r: r[1] or 0, reverse=True)
    for name, _ in same:
        n = real_name(name)
        if n:
            return n.split()[0]
    return FALLBACK


def fill_from_profile(guest: Optional[Guest], profile_name: Optional[str]) -> bool:
    """Set a missing / placeholder guest name from the WhatsApp profile name. True when it changed."""
    n = real_name(profile_name)
    if guest is None or n is None or real_name(guest.name):
        return False
    guest.name = n[:255]
    return True
