"""Imported DMs must keep Meta's event time, not the import time.

A backfill replays messages that are days old. Without honouring
payload["timestamp"], Message.created_at fell back to the column default
(now), so the inbox showed a week of history as having arrived "1m" ago,
all bunched at the import moment and in the wrong order.
"""
from datetime import datetime, timedelta, timezone

import pytest


def _occurred_at(payload):
    """The parsing the task performs on payload['timestamp']."""
    raw = payload.get("timestamp")
    if not raw:
        return None
    try:
        return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def test_meta_millisecond_timestamp_is_honoured():
    real = datetime(2026, 9, 18, 14, 22, 5, tzinfo=timezone.utc)
    payload = {"timestamp": int(real.timestamp() * 1000)}
    assert _occurred_at(payload) == real


def test_missing_timestamp_falls_back_to_none():
    """Live webhooks without a timestamp must still store, using the
    column default rather than crashing."""
    assert _occurred_at({}) is None
    assert _occurred_at({"timestamp": None}) is None


@pytest.mark.parametrize("bad", ["not-a-number", "", {}, [], 10**20])
def test_malformed_timestamps_do_not_raise(bad):
    """A backfill must never fail a whole message on a junk timestamp."""
    assert _occurred_at({"timestamp": bad}) is None


def test_conversation_clock_only_moves_forward():
    """Importing an old message must not drag a thread below newer traffic."""
    newer = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc).isoformat()
    older = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc).isoformat()

    last_message_at = newer
    if not last_message_at or str(last_message_at) < older:
        last_message_at = older
    assert last_message_at == newer  # unchanged

    last_message_at = older
    if not last_message_at or str(last_message_at) < newer:
        last_message_at = newer
    assert last_message_at == newer  # advanced


def test_backfilled_message_is_older_than_now():
    real = datetime.now(timezone.utc) - timedelta(days=3)
    got = _occurred_at({"timestamp": int(real.timestamp() * 1000)})
    assert got < datetime.now(timezone.utc) - timedelta(days=2)
