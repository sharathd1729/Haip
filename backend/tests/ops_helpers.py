"""Shared builders for the operations-module tests."""

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.core.security import get_password_hash
from app.models.ops import ShiftPattern, StaffDuty, StaffProfile
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import User, UserRole

IST = ZoneInfo("Asia/Kolkata")


def ist(y, mo, d, h, mi=0) -> datetime:
    """An IST wall-clock time as an aware UTC datetime. 2026-10-19 is a Monday."""
    return datetime(y, mo, d, h, mi, tzinfo=IST).astimezone(UTC)


def tenant(db) -> Tenant:
    t = Tenant(
        id=str(uuid.uuid4()),
        name="Ops T",
        slug=f"ops-{uuid.uuid4().hex[:8]}",
        plan="growth",
    )
    db.add(t)
    db.commit()
    return t


def prop(db, tenant_id, name="Ratha 1") -> Property:
    p = Property(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=name,
        slug=f"p-{uuid.uuid4().hex[:6]}",
    )
    db.add(p)
    db.commit()
    return p


_n = [0]


def phone() -> str:
    _n[0] += 1
    return f"+9198450{(uuid.uuid4().int + _n[0]) % 100000:05d}"


def staff(db, tenant_id, name, duty=None, property_id=None, opted_in=True, user_id=None) -> StaffProfile:
    s = StaffProfile(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=name,
        phone_e164=phone(),
        user_id=user_id,
        active=True,
        whatsapp_opt_in_at=datetime.now(UTC) if opted_in else None,
    )
    db.add(s)
    db.flush()
    if duty:
        db.add(StaffDuty(tenant_id=tenant_id, staff_id=s.id, duty=duty, property_id=property_id))
    db.commit()
    return s


def shift(db, tenant_id, staff_id, duty, weekday, start, end, property_id=None) -> ShiftPattern:
    p = ShiftPattern(
        tenant_id=tenant_id,
        staff_id=staff_id,
        duty=duty,
        property_id=property_id,
        weekday=weekday,
        start_minute=start * 60,
        end_minute=end * 60,
        active=True,
    )
    db.add(p)
    db.commit()
    return p


def user(db, tenant_id, role=UserRole.MANAGER, phone_number=None) -> User:
    u = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=f"{role.value} user",
        email=f"{role.value}-{uuid.uuid4().hex[:6]}@t.com",
        hashed_password=get_password_hash("pw"),
        role=role,
        is_active=True,
        phone=phone_number,
    )
    db.add(u)
    db.commit()
    return u
