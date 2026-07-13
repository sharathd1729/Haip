from datetime import timedelta
from app.services.date_presets import resolve_preset, resolve_range, today_ist


def test_last_7d_inclusive_of_today():
    d_from, d_to = resolve_preset("last_7d")
    today = today_ist()
    assert d_to == today
    assert d_from == today - timedelta(days=6)
    assert (d_to - d_from).days == 6


def test_next_14d_inclusive_of_today():
    d_from, d_to = resolve_preset("next_14d")
    today = today_ist()
    assert d_from == today
    assert d_to == today + timedelta(days=13)


def test_custom_and_none_return_none():
    assert resolve_preset(None) == (None, None)
    assert resolve_preset("custom") == (None, None)


def test_resolve_range_prefers_preset_over_explicit():
    d_from, d_to = resolve_range("last_7d", "2020-01-01", "2020-01-02")
    assert d_from != "2020-01-01"


def test_resolve_range_passes_through_explicit_when_no_preset():
    d_from, d_to = resolve_range(None, "2020-01-01", "2020-01-02")
    assert (d_from, d_to) == ("2020-01-01", "2020-01-02")
