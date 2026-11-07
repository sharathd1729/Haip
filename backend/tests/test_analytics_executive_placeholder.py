"""Executive dashboard: the "Unassigned" holder is not a property (D-32), and every KPI says what it measures.

Last month is used for the numbers because it is always a whole month (month to date is empty on the 1st)."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.guest import Guest
from app.models.property import Property, Stay
from app.models.tenant import Tenant

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

URL = "/api/v1/analytics/executive"


@pytest.fixture(autouse=True)
def _entitle(db, tenant_and_user):
    from app.models.module import Module, WorkspaceModule
    tid = tenant_and_user["tenant"].id
    mod = db.query(Module).filter_by(code="analytics").first()
    if mod is None:
        mod = Module(id=str(uuid.uuid4()), code="analytics", name="Analytics")
        db.add(mod)
        db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=tid, module_id=mod.id, enabled=True))
    db.commit()


def _last_month():
    first = datetime.now(timezone.utc).date().replace(day=1)
    prev_first = (first - timedelta(days=1)).replace(day=1)
    return prev_first, first, (first - prev_first).days


def _prop(db, tid, name):
    p = Property(id=str(uuid.uuid4()), tenant_id=tid, name=name, slug=f"p-{uuid.uuid4().hex[:8]}",
                 type="caravan", is_active=True)
    db.add(p)
    db.flush()
    return p


def _stay(db, tid, prop, check_in: date, check_out: date):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Guest")
    db.add(g)
    db.flush()
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, property_id=prop.id, check_in=check_in,
                check_out=check_out, status="confirmed", total_amount=1000))
    db.flush()


def _get(client, tenant_and_user):
    r = client.get(URL, headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_unassigned_holder_is_not_capacity_but_its_nights_count(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    start, end, days = _last_month()
    r1, _r2 = _prop(db, tid, "Ratha 1"), _prop(db, tid, "Ratha 2")
    holder = _prop(db, tid, "Unassigned (legacy bookings)")
    _stay(db, tid, r1, start, end)                          # Ratha 1 full last month
    _stay(db, tid, holder, start, start + timedelta(days=10))  # 10 nights sold without a vehicle
    db.commit()

    data = _get(client, tenant_and_user)
    assert data["occupancy_prev"] == round((days + 10) / (2 * days) * 100, 1)   # two vehicles, not three
    assert holder.id not in {h["property_id"] for h in data["occupancy_heatmap"]}
    assert len(data["occupancy_heatmap"]) == 2


def test_overflow_on_the_holder_never_reads_above_100(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    start, end, _ = _last_month()
    for name in ("Ratha 1", "Ratha 2", "Unassigned"):
        _stay(db, tid, _prop(db, tid, name), start, end)
    db.commit()
    assert _get(client, tenant_and_user)["occupancy_prev"] == 100.0


def test_a_business_without_a_holder_is_unchanged(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    start, end, _ = _last_month()
    v1, v2 = _prop(db, tid, "Villa A"), _prop(db, tid, "Villa B")
    _stay(db, tid, v1, start, end)
    db.commit()
    data = _get(client, tenant_and_user)
    assert data["occupancy_prev"] == 50.0
    assert {h["property_id"] for h in data["occupancy_heatmap"]} == {v1.id, v2.id}


def test_another_workspace_never_counts(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    start, end, _ = _last_month()
    mine = _prop(db, tid, "Ratha 1")
    _stay(db, tid, mine, start, end)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(other)
    db.flush()
    for name in ("Elsewhere 1", "Elsewhere 2", "Unassigned"):
        _stay(db, other.id, _prop(db, other.id, name), start, end)
    db.commit()
    data = _get(client, tenant_and_user)
    assert data["occupancy_prev"] == 100.0                                     # one property of mine, full
    assert [h["property_id"] for h in data["occupancy_heatmap"]] == [mine.id]


def test_every_card_says_what_it_measures_and_the_sla_is_a_person(client, tenant_and_user):
    labels = _get(client, tenant_and_user)["labels"]
    assert labels["sla_compliance_pct"].startswith("Replies by a person within 15 min")
    assert "AI replies are not counted" in labels["sla_compliance_pct"]
    assert "last 30 days" in labels["sla_compliance_pct"]
    assert "month to date" in labels["occupancy_pct"]
    assert {"revenue_mtd", "occupancy_pct", "active_inquiries", "qa_avg_score", "sla_compliance_pct",
            "ai_draft_rate_pct"} <= set(labels)


def test_capacity_units_leaves_the_holder_out_for_this_workspace_only(db, tenant_and_user):
    from app.services import kpi_metrics
    tid = tenant_and_user["tenant"].id
    r1 = _prop(db, tid, "Ratha 1")
    _prop(db, tid, "Ratha 2")
    holder = _prop(db, tid, "Unassigned (vehicle not chosen yet)")
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(other)
    db.flush()
    _prop(db, other.id, "Elsewhere")
    db.commit()
    assert kpi_metrics.capacity_units(db, tid) == 2
    assert kpi_metrics.capacity_units(db, tid, property_ids=[r1.id, holder.id]) == 1
    assert kpi_metrics.capacity_units(db, other.id) == 1


def test_ask_haip_occupancy_uses_the_same_units(db, tenant_and_user):
    from app.services import ask_haip_kpi
    from app.services.date_presets import resolve_preset
    tid = tenant_and_user["tenant"].id
    d_from, d_to = resolve_preset("last_month")
    r1 = _prop(db, tid, "Ratha 1")
    _prop(db, tid, "Ratha 2")
    _prop(db, tid, "Unassigned")
    _stay(db, tid, r1, d_from, d_to + timedelta(days=1))   # Ratha 1 the whole month
    db.commit()
    rows = {r["metric"]: r["value"] for r in ask_haip_kpi.answer(db, tid, "occupancy last month")["rows"]}
    assert rows["stays.occupancy_pct"] == "50.0%"                                # two caravans, not three
