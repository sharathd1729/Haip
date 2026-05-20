"""
B10 — Per-tenant timezone + business hours helpers.

Usage:
    from app.core.tenant_tz import get_tenant_now, is_within_business_hours

    now_local = get_tenant_now(tenant)          # datetime in tenant's tz
    if is_within_business_hours(tenant):        # True if currently open
        ...
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional, TYPE_CHECKING
import structlog

if TYPE_CHECKING:
    from app.models.tenant import Tenant

log = structlog.get_logger()

# Default business hours: Mon-Fri 9am-9pm, weekends 10am-6pm IST
_DEFAULT_HOURS = {
    0: {"open": "09:00", "close": "21:00", "closed": False},  # Mon
    1: {"open": "09:00", "close": "21:00", "closed": False},  # Tue
    2: {"open": "09:00", "close": "21:00", "closed": False},  # Wed
    3: {"open": "09:00", "close": "21:00", "closed": False},  # Thu
    4: {"open": "09:00", "close": "21:00", "closed": False},  # Fri
    5: {"open": "10:00", "close": "18:00", "closed": False},  # Sat
    6: {"open": "10:00", "close": "14:00", "closed": False},  # Sun
}


def get_tz(tenant: "Tenant") -> ZoneInfo:
    """Return a ZoneInfo object for the tenant's timezone. Falls back to IST."""
    tz_name = getattr(tenant, "timezone", None) or "Asia/Kolkata"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        log.warning("unknown_tenant_timezone", tz=tz_name, tenant_id=tenant.id)
        return ZoneInfo("Asia/Kolkata")


def get_tenant_now(tenant: "Tenant") -> datetime:
    """Return the current datetime in the tenant's local timezone."""
    return datetime.now(timezone.utc).astimezone(get_tz(tenant))


def is_within_business_hours(tenant: "Tenant", dt: Optional[datetime] = None) -> bool:
    """
    Return True if `dt` (default: now) falls within the tenant's configured
    business hours. Uses _DEFAULT_HOURS if not configured.
    """
    tz = get_tz(tenant)
    if dt is None:
        dt = datetime.now(timezone.utc).astimezone(tz)
    else:
        dt = dt.astimezone(tz)

    hours_config: dict = getattr(tenant, "business_hours", None) or {}
    # Normalise keys: JSON deserialises int keys as strings
    hours: dict = {}
    for k, v in _DEFAULT_HOURS.items():
        override = hours_config.get(str(k)) or hours_config.get(k)
        hours[k] = override if override else v

    weekday = dt.weekday()   # 0=Mon, 6=Sun
    day_config = hours.get(weekday, _DEFAULT_HOURS[weekday])

    if day_config.get("closed"):
        return False

    open_h, open_m = map(int, day_config["open"].split(":"))
    close_h, close_m = map(int, day_config["close"].split(":"))

    open_minutes = open_h * 60 + open_m
    close_minutes = close_h * 60 + close_m
    current_minutes = dt.hour * 60 + dt.minute

    return open_minutes <= current_minutes < close_minutes


def business_hours_display(tenant: "Tenant") -> dict:
    """Return the effective business hours config for display in settings."""
    hours_config: dict = getattr(tenant, "business_hours", None) or {}
    result = {}
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for i, name in enumerate(day_names):
        override = hours_config.get(str(i)) or hours_config.get(i)
        config = override if override else _DEFAULT_HOURS[i]
        result[name] = config
    return result
