"""Self check-in (Ops 2, gap 7): on a whole_unit property nobody meets the guest, so the property holds the check-in steps.

properties.self_check_in      on/off per property (the vacation_rental pack suggests it: GET /ops/pack self_check_in).
properties.self_check_in_enc  ONE Fernet token (core/encryption, ENCRYPTION_KEY) over {steps, lock_code, key_box}.

Rules: the values are never logged, never put in an audit payload (only which fields changed), and only roles with
ops.manage (owner, manager) see them; everyone else sees whether each is set. for_message() hands them to the pre-arrival
message (card "Ops 2d"). nobody_on_site() raises the priority of guest issues at that property (ops_escalation_service).
Only whole_unit packs offer it: a trip has a driver, a room business a front desk.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.property import Property
from app.services import ops_pack_catalog as packs
from app.services import ops_pack_seed

SECRET_FIELDS = ("steps", "lock_code", "key_box")


def _property(db: Session, tenant_id: str, property_id: str) -> Property:
    p = db.query(Property).filter_by(id=property_id, tenant_id=tenant_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return p


def _secrets(p: Property) -> dict:
    if not p.self_check_in_enc:
        return {}
    return decrypt_credentials(p.self_check_in_enc.encode())


def offered(db: Session, tenant_id: str) -> bool:
    """Self check-in is an option for this business: its pack's flow is whole_unit."""
    pack = ops_pack_seed.business_pack(db, tenant_id)
    return pack is not None and packs.flow_of(pack) == "whole_unit"


def view(db: Session, tenant_id: str, property_id: str, *, reveal: bool) -> dict:
    """What a screen may show. reveal=False (no ops.manage): only whether each value is set."""
    p = _property(db, tenant_id, property_id)
    s = _secrets(p)
    out = {
        "property_id": p.id,
        "offered": offered(db, tenant_id),
        "enabled": bool(p.self_check_in),
        "revealed": reveal,
        "set": {k: bool(s.get(k)) for k in SECRET_FIELDS},
    }
    out.update({k: (s.get(k) or None) if reveal else None for k in SECRET_FIELDS})
    return out


def update(db: Session, tenant_id: str, property_id: str, *, enabled: bool | None, values: dict) -> list[str]:
    """Change the switch and/or values (an empty string clears one). Returns the names of what changed (no values)."""
    if not offered(db, tenant_id):
        raise HTTPException(
            status_code=409, detail="Self check-in is for businesses that let the whole place (villas, rentals, homes)."
        )
    p = _property(db, tenant_id, property_id)
    s = _secrets(p)
    changed: list[str] = []
    for key in SECRET_FIELDS:
        if key not in values or values[key] is None:
            continue
        new = values[key].strip()
        if (s.get(key) or "") != new:
            changed.append(key)
            if new:
                s[key] = new
            else:
                s.pop(key, None)
    if changed:
        p.self_check_in_enc = encrypt_credentials(s).decode() if s else None
    if enabled is not None and bool(p.self_check_in) != enabled:
        if enabled and not (s.get("lock_code") or s.get("key_box") or s.get("steps")):
            raise HTTPException(status_code=422, detail="Add the lock code, key box or check-in steps first.")
        p.self_check_in = enabled
        changed.append("enabled")
    db.flush()
    return changed


def for_message(db: Session, tenant_id: str, property_id: str) -> dict | None:
    """The decrypted steps for the pre-arrival message (Ops 2d), or None when the property is not self check-in."""
    p = db.query(Property).filter_by(id=property_id, tenant_id=tenant_id).first()
    if p is None or not p.self_check_in:
        return None
    return {k: v for k, v in _secrets(p).items() if k in SECRET_FIELDS and v}


def nobody_on_site(db: Session, tenant_id: str, property_id: str | None) -> bool:
    if not property_id:
        return False
    return bool(db.query(Property.self_check_in).filter_by(id=property_id, tenant_id=tenant_id).scalar())
