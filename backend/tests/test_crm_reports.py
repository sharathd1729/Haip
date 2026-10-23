"""GET /reports/daily-validation and /reports/checkin-coverage (lead_daily_report, checkin_coverage; 22 Oct 2026).

Pinned: IST day bounds; per agent and total; the human review is counted apart from the automatic numbers and only from a
person's review; b2b enquiries are left out; coverage counts reviewed-valid apart from stage-valid, never Not valid / Sold,
flags dates and weekends under the target, lists booked vehicles and skips a check-in it cannot read; owner/manager only;
another workspace's data never appears.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.user import UserRole
from app.services import checkin_coverage
from tests.api.test_reports_leads import _headers, _lead, _tenant, _user

DAY = date(2026, 10, 21)


def _ist(day: date, hh: int) -> datetime:
    return datetime(day.year, day.month, day.day, hh, 0, tzinfo=timezone.utc) - timedelta(hours=5, minutes=30)


def _stage(db, tid, key, category, won=False, lost=False):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key=key, label=key.title(), category=category, order=1,
                      is_closed_won=won, is_closed_lost=lost)
    db.add(s); db.flush()
    return s


def test_daily_report_splits_automatic_and_human_numbers_per_agent(client, db):
    t, other = _tenant(db), _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER, "Owner")
    asha = _user(db, t.id, UserRole.CONCIERGE, "Asha")
    active = _stage(db, t.id, "active", "valid")
    a1 = _lead(db, t.id, name="A1", phone="+919800000011", owner=asha, stage=active, created_at=_ist(DAY, 10))
    _lead(db, t.id, name="A2", phone="+919800000012", owner=asha, created_at=_ist(DAY, 23))           # 23:00 IST: same day
    _lead(db, t.id, name="Next day", phone="+919800000013", owner=asha, created_at=_ist(DAY, 23) + timedelta(hours=1, minutes=1))
    _lead(db, t.id, name="Agency", phone="+919800000014", owner=asha, created_at=_ist(DAY, 11), lead_type="b2b")
    _lead(db, other.id, name="Elsewhere", phone="+919800000015", created_at=_ist(DAY, 10))
    a1.validation_status, a1.validated_by, a1.validated_at = "valid", owner.id, _ist(DAY, 12)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=a1.guest_id, inquiry_id=a1.id, channel="whatsapp")
    db.add(conv); db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                   channel="whatsapp", body="Hi", sender_id=asha.id, created_at=_ist(DAY, 10)))
    db.add(Call(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=a1.guest_id, inquiry_id=a1.id, agent_id=owner.id, ivr_provider="vobiz",
                ivr_call_id=uuid.uuid4().hex, direction=CallDirection.OUTBOUND, from_number="x", to_number="y", duration_seconds=60,
                ivr_dial_status="completed", created_at=_ist(DAY, 13)))
    prop = Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:5]}", type="caravan")
    db.add(prop); db.flush()
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=a1.guest_id, property_id=prop.id, inquiry_id=a1.id,
                check_in=DAY + timedelta(days=5), check_out=DAY + timedelta(days=6), status="confirmed", total_amount=30000,
                created_at=_ist(DAY, 14)))
    db.commit()

    res = client.get(f"/api/v1/reports/daily-validation?date={DAY.isoformat()}", headers=_headers(owner))
    assert res.status_code == 200, res.text
    body = res.json()
    rows = {r["name"]: r for r in body["agents"]}
    assert rows["Asha"]["automatic"] == {"received": 2, "handled": 1, "in_valid_stage": 1, "valid_now": 1, "conversions": 1}
    assert rows["Asha"]["human"]["not_yet_reviewed"] == 1
    assert rows["Owner"]["human"] == {"reviewed": 1, "valid": 1, "not_valid": 0, "not_yet_reviewed": 0}
    assert rows["Owner"]["automatic"]["handled"] == 1
    assert body["total"]["automatic"]["handled"] == 1                   # two people on one enquiry = one enquiry
    assert body["total"]["automatic"]["received"] == 2 and body["date"] == "2026-10-21"


def test_daily_report_is_for_owners_and_managers_with_a_clean_date_error(client, db):
    t = _tenant(db)
    concierge = _user(db, t.id, UserRole.CONCIERGE)
    manager = _user(db, t.id, UserRole.MANAGER)
    db.commit()
    assert client.get("/api/v1/reports/daily-validation", headers=_headers(concierge)).status_code == 403
    assert client.get("/api/v1/reports/checkin-coverage", headers=_headers(concierge)).status_code == 403
    assert client.get("/api/v1/reports/daily-validation?date=21-10-2026", headers=_headers(manager)).status_code == 422
    assert client.get("/api/v1/reports/daily-validation", headers=_headers(manager)).status_code == 200


def test_coverage_counts_valid_enquiries_per_date_and_weekend(client, db):
    t, other = _tenant(db), _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER)
    active, sold = _stage(db, t.id, "active", "valid"), _stage(db, t.id, "sold", "valid", won=True)
    general = _stage(db, t.id, "unqualified", "invalid")
    fri, sat = date(2026, 10, 30), date(2026, 10, 31)
    for n in range(5):
        _lead(db, t.id, name=f"Fri {n}", phone=f"+91980000010{n}", stage=active, check_in=fri.isoformat())
    _lead(db, t.id, name="Reviewed", phone="+919800000201", stage=general, check_in=sat.isoformat(), validation_status="valid")
    _lead(db, t.id, name="Said no", phone="+919800000202", stage=active, check_in=sat.isoformat(), validation_status="invalid")
    _lead(db, t.id, name="Sold", phone="+919800000203", stage=sold, check_in=sat.isoformat())
    _lead(db, t.id, name="Not a stage lead", phone="+919800000204", stage=general, check_in=sat.isoformat())
    _lead(db, t.id, name="Trade", phone="+919800000205", stage=active, check_in=sat.isoformat(), lead_type="b2b")
    _lead(db, t.id, name="Odd date", phone="+919800000206", stage=active, check_in="2026-10-3x")
    _lead(db, other.id, name="Elsewhere", phone="+919800000207", check_in=sat.isoformat(), validation_status="valid")
    r1 = Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Ratha 1", slug=f"r1-{uuid.uuid4().hex[:5]}", type="caravan")
    spare = Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Unassigned", slug=f"u-{uuid.uuid4().hex[:5]}", type="caravan")
    db.add_all([r1, spare]); db.flush()
    g = db.query(Inquiry).filter_by(tenant_id=t.id).first().guest_id
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g, property_id=r1.id, check_in=sat, check_out=sat + timedelta(days=2),
                status="confirmed", total_amount=1))
    db.commit()

    res = client.get("/api/v1/reports/checkin-coverage?from=2026-10-29&to=2026-11-02", headers=_headers(owner))
    assert res.status_code == 200, res.text
    body = res.json()
    days = {d["date"]: d for d in body["days"]}
    assert days["2026-10-30"]["valid"] == 5 and days["2026-10-30"]["stage_valid"] == 5 and not days["2026-10-30"]["below_target"]
    assert days["2026-10-31"] == {**days["2026-10-31"], "valid": 1, "reviewed_valid": 1, "stage_valid": 0, "below_target": True,
                                  "booked_vehicles": ["Ratha 1"]}
    assert days["2026-11-02"]["booked_vehicles"] == []                     # checked out that morning
    weekend = body["weekends"][0]
    assert weekend["friday"] == "2026-10-30" and weekend["valid"] == 6 and weekend["below_target"] is False
    assert weekend["booked_vehicles"] == ["Ratha 1"] and body["vehicles"] == ["Ratha 1"]
    assert body["unparsed"] == 1 and body["target"] == 5


def test_coverage_defaults_to_six_weekends_and_refuses_a_long_range(client, db):
    assert checkin_coverage.default_range(date(2026, 10, 22)) == (date(2026, 10, 22), date(2026, 11, 29))   # Thu -> 6th Sunday
    assert checkin_coverage.default_range(date(2026, 10, 25))[1] == date(2026, 11, 29)                     # a Sunday is weekend 1
    t = _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER)
    db.commit()
    assert len(client.get("/api/v1/reports/checkin-coverage", headers=_headers(owner)).json()["weekends"]) >= 6
    assert client.get("/api/v1/reports/checkin-coverage?from=2026-10-01&to=2027-06-01", headers=_headers(owner)).status_code == 422
