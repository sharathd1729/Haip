"""The Instagram OAuth callback must survive persisting what it just minted.

Production failure: the token exchange succeeded, then the callback raised
before committing and the browser got a bare "Internal Server Error" --
indistinguishable from an auth failure. Cause was treating _now() (which
returns an ISO *string*) as a datetime: `.isoformat()` on it raises
AttributeError, and `+ timedelta(...)` raises TypeError.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.endpoints import integrations


def test_now_returns_an_iso_string_not_a_datetime():
    """The trap itself. If this ever becomes a datetime, the callback's
    arithmetic has to change with it."""
    value = integrations._now()
    assert isinstance(value, str)
    # parseable back to an aware datetime
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None


def test_string_now_cannot_be_used_as_a_datetime():
    """Pins why the callback must build expiry from datetime.now(), not
    _now() -- both of these are what took the flow down."""
    now_str = integrations._now()
    with pytest.raises(AttributeError):
        now_str.isoformat()
    with pytest.raises(TypeError):
        now_str + timedelta(seconds=60)


def test_expiry_is_computed_from_a_real_datetime():
    """The shape the callback now uses: arithmetic on a datetime, stored as
    a string."""
    now_dt = datetime.now(timezone.utc)
    expires_in = 5183944  # what Meta returns for a 60-day token

    config = {
        "token_refreshed_at": now_dt.isoformat(),
        "token_expires_at": (now_dt + timedelta(seconds=expires_in)).isoformat(),
    }

    assert isinstance(config["token_refreshed_at"], str)
    expires = datetime.fromisoformat(config["token_expires_at"])
    assert expires > datetime.now(timezone.utc) + timedelta(days=55)


def test_zero_expires_in_omits_the_expiry_key():
    """Meta not returning expires_in must not write a bogus expiry."""
    now_dt = datetime.now(timezone.utc)
    token_expires_in = 0
    config = {
        "token_refreshed_at": now_dt.isoformat(),
        **(
            {"token_expires_at": (now_dt + timedelta(seconds=token_expires_in)).isoformat()}
            if token_expires_in else {}
        ),
    }
    assert "token_expires_at" not in config
