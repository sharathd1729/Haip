"""Concierge prompt v11: departure point, adults-only capacity, no invented rules.

All three confirmed live on one Ratha thread: a guest proposing a start
other than Bengaluru was told that was fine; 8 adults + a toddler was told
the limit was "8 in total, regardless of age, for travel safety" -- a policy
and a reason that exist nowhere in the knowledge base.
"""
import uuid
from types import SimpleNamespace

from app.models.property import Property
from app.models.tenant import Tenant
from app.services import price_policy
from app.workers.tasks.concierge_draft import _jinja_env, _known_home_bases


def _render(grounded_facts):
    tpl = _jinja_env.get_template("concierge_reply.jinja")
    return tpl.render(
        tenant=SimpleNamespace(brand_name="Rathaa", brand_config={}, name="Rathaa"),
        guest=SimpleNamespace(name="G", language_pref="en", total_stays=0,
                              predicted_csat=None, vip_tier=None, tags=[]),
        inquiry=None,
        recent_messages=[], call_summaries=[], kb_snippets=[],
        grounded_facts=price_policy.redact_price_facts(grounded_facts),
        tone=None, guest_missing_phone=False, missing_details=[], qualified=False,
    )


# ── prompt ───────────────────────────────────────────────────────────────────

def test_departure_point_renders_as_a_hard_constraint():
    out = _render([{"tool": "home_base", "result": ["Bengaluru"]}])
    assert "DEPARTURE POINT" in out
    assert "Every trip starts from Bengaluru" in out
    assert "do NOT agree to it" in out


def test_no_departure_section_without_home_base():
    """Villa tenants have no home_base -- they must not get a travel rule."""
    out = _render([{"tool": "check_availability", "args": {}, "result": [],
                    "max_capacity_note": 4}])
    assert "DEPARTURE POINT" not in out


def test_multiple_bases_are_all_named():
    out = _render([{"tool": "home_base", "result": ["Bengaluru", "Mysuru"]}])
    assert "Bengaluru or Mysuru" in out


def test_capacity_is_stated_as_adults_only():
    out = _render([])
    assert "CAPACITY -- ADULTS ONLY" in out
    assert "toddlers are not counted" in out


def test_invented_rules_and_reasons_are_forbidden():
    out = _render([])
    assert "NEVER INVENT A RULE OR A REASON" in out
    assert "for travel safety" in out  # named explicitly as a forbidden justification


def test_home_base_fact_survives_price_redaction():
    """Facts pass through redact_price_facts before rendering."""
    facts = price_policy.redact_price_facts([{"tool": "home_base", "result": ["Bengaluru"]}])
    assert facts == [{"tool": "home_base", "result": ["Bengaluru"]}]


# ── data ─────────────────────────────────────────────────────────────────────

def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.commit()
    return t


def _vehicle(db, t, base, active=True):
    db.add(Property(
        id=str(uuid.uuid4()), tenant_id=t.id, name=f"Caravan {base}",
        slug=f"c-{uuid.uuid4().hex[:6]}", type="caravan", max_adults=8,
        home_base=base, is_active=active,
    ))
    db.commit()


def test_home_bases_are_distinct_across_a_fleet(db):
    t = _tenant(db)
    _vehicle(db, t, "Bengaluru")
    _vehicle(db, t, "bengaluru")  # same city, different case
    assert _known_home_bases(db, t.id) == ["Bengaluru"]


def test_inactive_and_blank_home_bases_are_ignored(db):
    t = _tenant(db)
    _vehicle(db, t, "Bengaluru")
    _vehicle(db, t, "Mysuru", active=False)
    _vehicle(db, t, None)
    _vehicle(db, t, "  ")
    assert _known_home_bases(db, t.id) == ["Bengaluru"]


def test_home_bases_are_tenant_scoped(db):
    a, b = _tenant(db), _tenant(db)
    _vehicle(db, a, "Bengaluru")
    _vehicle(db, b, "Goa")
    assert _known_home_bases(db, a.id) == ["Bengaluru"]
    assert _known_home_bases(db, b.id) == ["Goa"]


def test_tenant_without_vehicles_has_no_home_base(db):
    assert _known_home_bases(db, _tenant(db).id) == []
