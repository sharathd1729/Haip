"""AI mode resolution + kill switch tests."""
from app.services import ai_mode_service as ams


class _T:
    def __init__(self, wa="shadow", ig="shadow", wa_thr=0.78, ig_thr=0.78, kill=False):
        self.wa_ai_mode_default, self.ig_ai_mode_default = wa, ig
        self.wa_ai_confidence_threshold, self.ig_ai_confidence_threshold = wa_thr, ig_thr
        self.ai_kill_switch = kill


class _C:
    def __init__(self, channel="whatsapp", ai_mode="shadow", human_owned=False):
        self.channel, self.ai_mode, self.human_owned = channel, ai_mode, human_owned


# ─── kill switch ─────────────────────────────────────────────────────────────

def test_kill_switch_forces_shadow_over_autonomous():
    assert ams.resolve_mode(_T(wa="autonomous", kill=True), _C()) == "shadow"


def test_kill_switch_applies_to_every_channel():
    t = _T(wa="autonomous", ig="autonomous", kill=True)
    assert ams.resolve_mode(t, _C("whatsapp")) == "shadow"
    assert ams.resolve_mode(t, _C("instagram")) == "shadow"


def test_kill_switch_downgrades_to_shadow_not_off():
    """Pulling the switch stops guests receiving AI messages; it must not
    take away the drafting assist agents are relying on."""
    assert ams.resolve_mode(_T(wa="autonomous", kill=True), _C()) != "off"


def test_no_kill_switch_leaves_autonomous_intact():
    assert ams.resolve_mode(_T(wa="autonomous", kill=False), _C()) == "autonomous"


# ─── per-channel resolution ──────────────────────────────────────────────────

def test_channels_resolve_independently():
    t = _T(wa="autonomous", ig="off")
    assert ams.resolve_mode(t, _C("whatsapp")) == "autonomous"
    assert ams.resolve_mode(t, _C("instagram")) == "off"


def test_threshold_is_per_channel():
    """WhatsApp drafts previously used the *Instagram* confidence threshold."""
    t = _T(wa_thr=0.9, ig_thr=0.6)
    assert ams.resolve_threshold(t, _C("whatsapp")) == 0.9
    assert ams.resolve_threshold(t, _C("instagram")) == 0.6


def test_tenant_policy_beats_stale_conversation_snapshot():
    """conversations.ai_mode is a creation-time snapshot; the tenant's
    current setting is the real policy."""
    assert ams.resolve_mode(_T(wa="autonomous"), _C(ai_mode="shadow")) == "autonomous"


def test_per_conversation_off_wins_over_tenant():
    """Muting one thread is an explicit decision and must stick."""
    assert ams.resolve_mode(_T(wa="autonomous"), _C(ai_mode="off")) == "off"


def test_unknown_channel_never_defaults_to_autonomous():
    assert ams.resolve_mode(_T(wa="autonomous"), _C(channel="webchat")) == "shadow"


def test_invalid_mode_falls_back_to_shadow():
    assert ams.resolve_mode(_T(wa="banana"), _C()) == "shadow"


def test_missing_tenant_is_safe():
    assert ams.resolve_mode(None, _C()) == "shadow"


# ─── human_owned (auto-shadow on handoff) ─────────────────────────────────────

def test_human_owned_forces_shadow_over_autonomous_default():
    t = _T(wa="autonomous")
    assert ams.resolve_mode(t, _C(human_owned=True)) == "shadow"


def test_human_owned_false_leaves_autonomous_default_intact():
    t = _T(wa="autonomous")
    assert ams.resolve_mode(t, _C(human_owned=False)) == "autonomous"


def test_explicit_off_still_wins_over_human_owned():
    """Muting a thread is a stronger, more explicit decision than the
    implicit "a human replied once" signal -- off must still win."""
    t = _T(wa="autonomous")
    assert ams.resolve_mode(t, _C(ai_mode="off", human_owned=True)) == "off"


def test_kill_switch_still_wins_over_human_owned():
    t = _T(wa="autonomous", kill=True)
    assert ams.resolve_mode(t, _C(human_owned=True)) == "shadow"


def test_human_owned_defaults_false_for_objects_without_the_attribute():
    """Safety net for any caller passing an older/partial conversation
    object that predates this column."""
    class _Bare:
        channel, ai_mode = "whatsapp", "shadow"
    assert ams.resolve_mode(_T(wa="autonomous"), _Bare()) == "autonomous"


def test_kill_switch_defaults_to_off_on_a_fresh_tenant(db):
    """Regression: the column was declared server_default="false" (a plain
    string), which SQLite stores as a non-empty string and reads back as
    True -- every tenant would have started with the AI killed. Postgres
    coerces it, so this only showed up on the test database."""
    from app.models.tenant import Tenant
    t = Tenant(name="Fresh", slug="fresh-kill-default")
    db.add(t)
    db.commit()
    db.refresh(t)
    assert bool(t.ai_kill_switch) is False
    assert ams.resolve_mode(t, _C()) != "off"
