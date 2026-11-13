"""Yaad settings (GET/PUT /me/settings): custom words for the workspace, notification and email switches for the person.

Custom words (names, places, brands the transcriber mishears) live in `tenants.brand_config["personal_custom_words"]`
and go into every call read (prompt personal_call.jinja), so the summary spells them as listed. The switches live in
`users.notification_prefs` and default on: `daily_summary_email` (tasks personal.daily_digest) and the phone
notifications the Yaad app asks for (services/personal_notify.py).
"""

from __future__ import annotations

import re

WORDS_KEY = "personal_custom_words"
MAX_WORDS = 100
MAX_WORD_LEN = 40
SWITCHES = {
    "daily_email": "daily_summary_email",
    "notify_summary": "yaad_notify_summary",
    "notify_due": "yaad_notify_due",
    "notify_day": "yaad_notify_day",
}
_BAD = re.compile(r"[\x00-\x1f\x7f]")


def clean_words(words: list) -> list[str]:
    """Trimmed, de-duplicated (case-insensitive), control characters refused; raises ValueError on a bad list."""
    out: list[str] = []
    for w in words or []:
        if not isinstance(w, str):
            raise ValueError("Each word must be text.")
        w = " ".join(w.split())
        if not w:
            continue
        if len(w) > MAX_WORD_LEN or _BAD.search(w):
            raise ValueError(f"Keep each word under {MAX_WORD_LEN} characters.")
        if w.lower() not in {o.lower() for o in out}:
            out.append(w)
    if len(out) > MAX_WORDS:
        raise ValueError(f"Up to {MAX_WORDS} words.")
    return out


def custom_words(tenant) -> list[str]:
    words = (tenant.brand_config or {}).get(WORDS_KEY) if tenant else None
    return [w for w in words if isinstance(w, str)] if isinstance(words, list) else []


def switch_on(user, name: str) -> bool:
    return (user.notification_prefs or {}).get(SWITCHES[name], True) is not False


def get(tenant, user) -> dict:
    return {"custom_words": custom_words(tenant), **{k: switch_on(user, k) for k in SWITCHES}}


def update(db, tenant, user, changes: dict) -> dict:
    """Apply the given fields (others unchanged), audit what changed, commit. Returns the new settings."""
    from app.core.audit import append_audit

    before = get(tenant, user)
    if "custom_words" in changes:
        tenant.brand_config = {**(tenant.brand_config or {}), WORDS_KEY: clean_words(changes["custom_words"])}
    prefs = dict(user.notification_prefs or {})
    for k, key in SWITCHES.items():
        if k in changes:
            prefs[key] = bool(changes[k])
    user.notification_prefs = prefs  # a new dict, so SQLAlchemy sees the change
    after = get(tenant, user)
    diff = {k: {"before": before[k], "after": after[k]} for k in after if before[k] != after[k]}
    if diff:
        append_audit(
            db,
            tenant_id=tenant.id,
            actor_user_id=user.id,
            action="personal.settings_changed",
            target_type="user",
            target_id=user.id,
            payload=diff,
        )
    db.commit()
    return after
