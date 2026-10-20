"""scripts/repair_autopilot_unsuitable.py: the lead autopilot's moves into Unsuitable (Ratha, 20 Oct 2026) go back to Active
through the audited revert path, tied stage orders are renumbered, a dry run writes nothing, a lead a person has moved
since is left alone, and other workspaces are never touched."""
import importlib.util
from datetime import timedelta
from pathlib import Path

from app.models.audit_event import AuditEvent
from app.models.inquiry_360 import InquiryStageLog
from app.models.lead_autopilot import LeadAutopilotEvent
from app.models.pipeline_stage import PipelineStage
from tests.services._autopilot_fixtures import NOW, lead, tenant

_spec = importlib.util.spec_from_file_location(
    "repair_unsuitable", Path(__file__).resolve().parents[1] / "scripts" / "repair_autopilot_unsuitable.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

RATHA_ORDERS = {"unqualified": 0, "rnr": 1, "general_enquiry": 1, "unsuitable": 3, "active": 3, "lost": 4, "sold": 5,
                "collaboration_engagement": 6}


def _ratha(db):
    t, s = tenant(db)
    for key, order in RATHA_ORDERS.items():
        s[key].order = order
    db.commit()
    return t, s


def _wrongly_moved(db, t, s):
    """A qualified lead the autopilot put in Unsuitable (what production did)."""
    _, inq, _ = lead(db, t.id, s["unsuitable"])
    ev = LeadAutopilotEvent(tenant_id=t.id, inquiry_id=inq.id, from_stage_id=s["general_enquiry"].id,
                            to_stage_id=s["unsuitable"].id, rule="qualified", source="rule", status="applied",
                            mode="autopilot", reason="Phone and requirement captured (dates)", evidence=[],
                            created_at=NOW - timedelta(hours=2))
    db.add(ev)
    db.commit()
    return inq, ev


def test_dry_run_reports_and_writes_nothing(db):
    t, s = _ratha(db)
    inq, ev = _wrongly_moved(db, t, s)
    r = script.repair(db, t.id, apply=False)
    assert [i.id for _, i in r["moves"]] == [inq.id] and r["target"] == "active"
    assert r["order"][:5] == ["0 unqualified", "1 general_enquiry", "2 rnr", "3 active", "4 unsuitable"]
    db.refresh(inq)
    db.refresh(ev)
    assert inq.stage_id == s["unsuitable"].id and ev.status == "applied"
    assert db.query(PipelineStage).filter_by(tenant_id=t.id, key="active").one().order == 3


def test_apply_moves_the_lead_to_active_audited_and_unties_the_order(db):
    t, s = _ratha(db)
    inq, ev = _wrongly_moved(db, t, s)
    r = script.repair(db, t.id, apply=True)
    db.commit()
    assert r["done"] == [inq.id] and r["failed"] == []
    db.refresh(inq)
    db.refresh(ev)
    assert inq.stage_id == s["active"].id
    assert ev.status == "undone" and ev.resolved_by == "repair"
    log = db.query(InquiryStageLog).filter_by(inquiry_id=inq.id).one()
    assert (log.from_stage, log.to_stage) == ("unsuitable", "active") and log.reason.startswith("Repair:")
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="lead_autopilot.repaired", target_id=inq.id).count() == 1
    orders = [st.order for st in db.query(PipelineStage).filter_by(tenant_id=t.id)]
    assert sorted(orders) == list(range(len(orders)))
    again = script.repair(db, t.id, apply=True)                                # a second run changes nothing
    assert again["moves"] == [] and again["order"] == []


def test_a_lead_a_person_moved_since_is_left_alone(db):
    t, s = _ratha(db)
    inq, ev = _wrongly_moved(db, t, s)
    inq.stage_id = s["lost"].id
    db.commit()
    r = script.repair(db, t.id, apply=True)
    db.commit()
    assert r["moves"] == []
    db.refresh(ev)
    assert ev.status == "applied"


def test_other_workspaces_are_never_touched(db):
    t, s = _ratha(db)
    other, os_ = _ratha(db)
    inq, _ = _wrongly_moved(db, other, os_)
    r = script.repair(db, t.id, apply=True)
    db.commit()
    assert r["moves"] == []
    db.refresh(inq)
    assert inq.stage_id == os_["unsuitable"].id
    assert db.query(PipelineStage).filter_by(tenant_id=other.id, key="active").one().order == 3
