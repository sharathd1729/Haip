"""Shift roster: who is on duty and who each escalation step alerts (roster_service)."""
from app.models.ops import EscalationChain, ShiftOverride
from app.models.user import UserRole
from app.services import roster_service as rs
from tests.ops_helpers import ist, prop, shift, staff, tenant, user

MON = 0


def test_day_shift_covers_inside_hours_only(db):
    t = tenant(db)
    p = prop(db, t.id)
    ravi = staff(db, t.id, "Ravi", "maintenance")
    shift(db, t.id, ravi.id, "maintenance", MON, 8, 20)
    assert [s.name for s in rs.on_shift(db, t.id, "maintenance", p.id, ist(2026, 10, 19, 10))] == ["Ravi"]
    assert rs.on_shift(db, t.id, "maintenance", p.id, ist(2026, 10, 19, 21)) == []
    assert rs.on_shift(db, t.id, "maintenance", p.id, ist(2026, 10, 20, 10)) == []      # Tuesday
    assert rs.on_shift(db, t.id, "housekeeping", p.id, ist(2026, 10, 19, 10)) == []     # other duty


def test_overnight_shift_covers_next_morning_not_same_morning(db):
    t = tenant(db)
    night = staff(db, t.id, "Night", "front_desk")
    shift(db, t.id, night.id, "front_desk", MON, 22, 6)
    assert rs.on_shift(db, t.id, "front_desk", None, ist(2026, 10, 19, 23))            # Mon 23:00
    assert rs.on_shift(db, t.id, "front_desk", None, ist(2026, 10, 20, 2))             # Tue 02:00
    assert rs.on_shift(db, t.id, "front_desk", None, ist(2026, 10, 19, 2)) == []       # Mon 02:00 belongs to Sunday's shift


def test_property_specific_shift_only_matches_its_property(db):
    t = tenant(db)
    r1, r2 = prop(db, t.id, "Ratha 1"), prop(db, t.id, "Ratha 2")
    a = staff(db, t.id, "A", "housekeeping", r1.id)
    b = staff(db, t.id, "B", "housekeeping")
    shift(db, t.id, a.id, "housekeeping", MON, 8, 20, property_id=r1.id)
    shift(db, t.id, b.id, "housekeeping", MON, 8, 20)                                  # every property
    at = ist(2026, 10, 19, 9)
    assert {s.name for s in rs.on_shift(db, t.id, "housekeeping", r1.id, at)} == {"A", "B"}
    assert {s.name for s in rs.on_shift(db, t.id, "housekeeping", r2.id, at)} == {"B"}


def test_leave_swap_and_extra_overrides(db):
    t = tenant(db)
    a = staff(db, t.id, "A", "maintenance")
    b = staff(db, t.id, "B", "maintenance")
    c = staff(db, t.id, "C", "maintenance")
    shift(db, t.id, a.id, "maintenance", MON, 8, 20)
    shift(db, t.id, b.id, "maintenance", MON, 8, 20)
    lo, hi = ist(2026, 10, 19, 8), ist(2026, 10, 19, 20)
    db.add(ShiftOverride(tenant_id=t.id, staff_id=a.id, kind="leave", starts_at=lo, ends_at=hi))
    db.add(ShiftOverride(tenant_id=t.id, staff_id=b.id, kind="swap", starts_at=lo, ends_at=hi, replacement_staff_id=c.id))
    db.commit()
    assert [s.name for s in rs.on_shift(db, t.id, "maintenance", None, ist(2026, 10, 19, 12))] == ["C"]

    d = staff(db, t.id, "D", "maintenance")
    db.add(ShiftOverride(tenant_id=t.id, staff_id=d.id, kind="extra", duty="maintenance",
                         starts_at=ist(2026, 10, 19, 22), ends_at=ist(2026, 10, 20, 2)))
    db.commit()
    assert [s.name for s in rs.on_shift(db, t.id, "maintenance", None, ist(2026, 10, 19, 23))] == ["D"]


def test_inactive_staff_never_on_duty(db):
    t = tenant(db)
    a = staff(db, t.id, "A", "maintenance")
    shift(db, t.id, a.id, "maintenance", MON, 0, 24)
    a.active = False
    db.commit()
    assert rs.on_shift(db, t.id, "maintenance", None, ist(2026, 10, 19, 12)) == []


def test_default_chain_skips_empty_steps_and_reaches_manager(db):
    t = tenant(db)
    mgr = user(db, t.id, UserRole.MANAGER, phone_number="+919845012345")
    res, skipped = rs.first_step_with_recipients(db, t.id, "maintenance", None, 0, at=ist(2026, 10, 19, 3))
    assert skipped == [0, 1]                       # nobody on shift, no ops manager on shift
    assert res.step == 2 and [r.user_id for r in res.recipients] == [mgr.id]
    assert res.recipients[0].whatsapp_ok and res.recipients[0].phone == "+919845012345"


def test_custom_chain_always_ends_with_owner(db):
    t = tenant(db)
    db.add(EscalationChain(tenant_id=t.id, duty="housekeeping", property_id=None, steps=[{"type": "on_shift"}]))
    db.commit()
    steps = rs.chain_for(db, t.id, "housekeeping", None)
    assert steps[-1] == {"type": "role", "role": "owner"}
    assert len(steps) == 2


def test_property_chain_beats_tenant_chain(db):
    t = tenant(db)
    p = prop(db, t.id)
    db.add(EscalationChain(tenant_id=t.id, duty="maintenance", property_id=None, steps=[{"type": "duty"}]))
    db.add(EscalationChain(tenant_id=t.id, duty="maintenance", property_id=p.id, steps=[{"type": "role", "role": "owner"}]))
    db.commit()
    assert rs.chain_for(db, t.id, "maintenance", p.id) == [{"type": "role", "role": "owner"}]
    assert rs.chain_for(db, t.id, "maintenance", None)[0] == {"type": "duty"}


def test_critical_step_zero_includes_ops_manager_on_shift(db):
    t = tenant(db)
    tech = staff(db, t.id, "Tech", "maintenance")
    boss = staff(db, t.id, "Boss", "ops_manager")
    shift(db, t.id, tech.id, "maintenance", MON, 0, 24)
    shift(db, t.id, boss.id, "ops_manager", MON, 0, 24)
    at = ist(2026, 10, 19, 12)
    assert {r.name for r in rs.recipients_for_step(db, t.id, "maintenance", None, 0, "critical", at).recipients} == {"Tech", "Boss"}
    assert {r.name for r in rs.recipients_for_step(db, t.id, "maintenance", None, 0, "high", at).recipients} == {"Tech"}


def test_staff_without_opt_in_cannot_get_whatsapp(db):
    t = tenant(db)
    a = staff(db, t.id, "A", "maintenance", opted_in=False)
    shift(db, t.id, a.id, "maintenance", MON, 0, 24)
    r = rs.recipients_for_step(db, t.id, "maintenance", None, 0, at=ist(2026, 10, 19, 12)).recipients[0]
    assert not r.whatsapp_ok


def test_roster_is_tenant_isolated(db):
    t1, t2 = tenant(db), tenant(db)
    other = staff(db, t2.id, "Other", "maintenance")
    shift(db, t2.id, other.id, "maintenance", MON, 0, 24)
    at = ist(2026, 10, 19, 12)
    assert rs.on_shift(db, t1.id, "maintenance", None, at) == []
    assert rs.duty_holders(db, t1.id, "maintenance", None, at) == []
    user(db, t2.id, UserRole.OWNER)
    res, _ = rs.first_step_with_recipients(db, t1.id, "maintenance", None, 0, at=at)
    assert res is None                              # t1 has no owner user: nobody, and never t2's people
