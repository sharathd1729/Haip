"""AI Executive E4: what it learns per workspace and detector. Rejections make a detector stricter and pause it, "not now"
counts for nothing, fixes that worked make it more sensitive, a worse outcome raises it and stops autopilot; outcomes are
checked 14 days on; equal-severity findings rank by confidence; autopilot is offered only after 5 internal fixes that
worked and starts only when an owner opts in; owners reset a detector; everything stays inside its tenant."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.models.audit_event import AuditEvent
from app.models.chief import ChiefDetectorTuning, ChiefProposal
from app.models.insight import Insight
from app.services.chief import detectors, findings, outcomes, plans, tuning
from app.services.chief.steps import step
from tests.analyst_world import world
from tests.test_increment1_defect_specs import _h

R = "/api/v1/chief"
ON = {"chief": {"enabled": True}}
PUSH = "app.services.push_service.send_to_tenant"


def _finding(db, w, code="SA1", numbers=None, resolved=False, severity="high"):
    row = Insight(
        tenant_id=w.t.id,
        category_code=code,
        category="urgency",
        role="sales_manager",
        severity=severity,
        title=f"{code} finding",
        body="body",
        numbers=numbers or {"waiting": 10},
        evidence=[],
        is_auto_resolved=resolved,
    )
    db.add(row)
    db.commit()
    return row


def _done(db, w, code, *, numbers_before, finding, days_ago=15, tier="R1", outcome=None):
    p = ChiefProposal(
        tenant_id=w.t.id,
        finding_id=finding.id,
        code=code,
        title="t",
        why="w",
        risk_tier=tier,
        preview=[],
        steps=[step("reviews.draft_replies", "x", tier, review_ids=[])],
        plan_sha="s" * 64,
        status="done",
        step_index=1,
        decided_by=w.owner.id,
        baseline={"numbers": numbers_before},
        finished_at=datetime.now(UTC) - timedelta(days=days_ago),
        check_due_at=datetime.now(UTC) - timedelta(days=days_ago - 14),
        outcome=outcome,
    )
    db.add(p)
    db.commit()
    return p


def test_three_rejections_raise_the_threshold_and_pause_the_detector(db):
    w = world(db, brand_config=ON)
    for _ in range(2):
        tuning.on_decision(db, w.t.id, "SA1", "rejected", "not_worth_it")
    tuning.on_decision(db, w.t.id, "SA1", "rejected", "not_now")  # a snooze, not a judgement
    t = tuning.get(db, w.t.id, "SA1")
    assert t.rejected == 2 and t.step == tuning.DEFAULT_STEP and not tuning.muted(t)
    tuning.on_decision(db, w.t.id, "SA1", "rejected", "wrong")
    db.commit()
    assert t.step == 2 and tuning.muted(t) and "3 times" in t.last_reason
    ctx = detectors.Ctx(db, w.t)
    assert ctx.level("SA1", 3) == tuning.LADDERS["SA1"][2]
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.tuning_changed").count() == 1
    out = findings.run(db, w.t, "urgent")
    assert "SA1" in out["muted"]


def test_mostly_turned_down_also_raises(db):
    w = world(db, brand_config=ON)
    tuning.on_decision(db, w.t.id, "SA2", "approved")
    for reason in ("wrong", "too_risky"):
        tuning.on_decision(db, w.t.id, "SA2", "rejected", reason)
    tuning.on_decision(db, w.t.id, "SA2", "approved")
    for _ in range(4):
        tuning.on_decision(db, w.t.id, "SA2", "dismissed", "wrong")
    for reason in ("wrong", "too_risky"):
        tuning.on_decision(db, w.t.id, "SA2", "rejected", reason)
    t = tuning.get(db, w.t.id, "SA2")
    assert t.step > tuning.DEFAULT_STEP and tuning.muted(t)


def test_outcomes_improved_make_it_more_sensitive_and_worse_raises_it(db):
    w = world(db, brand_config=ON)
    for _ in range(3):
        f = _finding(db, w, resolved=True)
        _done(db, w, "SA1", numbers_before={"waiting": 10}, finding=f)
    with patch(PUSH):
        assert outcomes.check_tenant(db, w.t)["checked"] == 3
    db.commit()
    t = tuning.get(db, w.t.id, "SA1")
    assert t.improved == 3 and t.step == 0 and "worked" in t.last_reason
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.outcome_recorded").count() == 3
    with patch(PUSH):
        assert outcomes.check_tenant(db, w.t)["checked"] == 0  # each proposal is judged once
    f = _finding(db, w, numbers={"waiting": 20})
    _done(db, w, "SA1", numbers_before={"waiting": 10}, finding=f)
    with patch(PUSH):
        outcomes.check_tenant(db, w.t)
    assert t.worse == 1 and t.step == 1


def test_verdict_rules():
    assert tuning.verdict("SA1", {"waiting": 10}, {"waiting": 7}, False) == "improved"
    assert tuning.verdict("SA1", {"waiting": 10}, {"waiting": 9}, False) == "no_change"
    assert tuning.verdict("WB1", {"enquiries": 10, "visits": 1}, {"enquiries": 6, "visits": 1}, False) == "worse"
    assert tuning.verdict("SA1", {"waiting": 0}, {"waiting": 3}, False) == "too_few"
    assert tuning.verdict("SA1", {}, {}, True) == "improved"


def test_equal_severity_ranks_by_confidence(db):
    w = world(db, brand_config=ON)
    _finding(db, w, code="SA2", severity="medium")
    _finding(db, w, code="SA8", severity="medium")
    for _ in range(3):
        tuning.on_decision(db, w.t.id, "SA8", "approved")
    db.commit()
    codes = [f["code"] for f in findings.list_findings(db, w.t.id)]
    assert codes.index("SA8") < codes.index("SA2")
    sa8 = next(f for f in findings.list_findings(db, w.t.id) if f["code"] == "SA8")
    assert sa8["learning"]["history"] == "You approved 3 of 3 like this." and sa8["learning"]["confidence"] > 0.25


def test_autopilot_offered_after_five_internal_fixes_then_owner_opt_in(client, db):
    w = world(db, brand_config=ON)
    for _ in range(5):
        f = _finding(db, w, code="MK7", numbers={"reviews": 3, "low_rated": 0}, resolved=True)
        _done(db, w, "MK7", numbers_before={"reviews": 3, "low_rated": 0}, finding=f)
    assert client.put(f"{R}/autopilot/MK7", json={"on": True}, headers=_h(w.owner)).status_code == 422  # not judged yet
    with patch(PUSH) as push:
        out = outcomes.check_tenant(db, w.t)
    db.commit()
    assert out["offered"] == ["MK7"] and push.called
    assert client.put(f"{R}/autopilot/MK7", json={"on": True}, headers=_h(w.mgr)).status_code == 403
    got = client.put(f"{R}/autopilot/MK7", json={"on": True}, headers=_h(w.owner))
    assert got.status_code == 200 and got.json()["autopilot"] is True
    other = world(db, brand_config=ON)
    assert (
        next(r for r in client.get(f"{R}/learning", headers=_h(other.owner)).json() if r["code"] == "MK7")["autopilot"]
        is False
    )

    # the next MK7 plan is approved by the owner's standing OK and queued, without asking
    row = Insight(
        tenant_id=w.t.id,
        category_code="MK7",
        category="quality",
        role="guest_relations",
        severity="medium",
        title="reviews",
        body="b",
        numbers={"reviews": 1},
        evidence=[{"type": "google_review", "id": str(uuid.uuid4())}],
    )
    db.add(row)
    db.commit()
    new = plans.propose_for_tenant(db, w.t)
    db.commit()
    p = next(x for x in new if x.finding_id == row.id)
    assert p.status == "approved" and p.decided_via == "autopilot" and p.decided_by == w.owner.id
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.proposal_auto_approved").count() == 1
    assert tuning.get(db, w.t.id, "MK7").approved == 0  # a standing OK is not a new approval


def test_r2_plans_never_graduate_and_paused_stops_autopilot(db):
    w = world(db, brand_config=ON)
    for _ in range(5):
        f = _finding(db, w, code="SA1", resolved=True)
        _done(db, w, "SA1", numbers_before={"waiting": 10}, finding=f, tier="R2", outcome={"verdict": "improved"})
    assert tuning.eligible(db, w.t.id, "SA1") is False
    try:
        tuning.start_autopilot(db, w.t.id, "SA1", w.owner.id)
        raise AssertionError("an R2 plan graduated")
    except ValueError:
        pass
    t = ChiefDetectorTuning(
        tenant_id=w.t.id,
        code="MK7",
        step=1,
        approved=0,
        rejected=0,
        dismissed=0,
        improved=5,
        no_change=0,
        worse=0,
        rejections_in_row=0,
        wins_in_row=0,
        autopilot_by=w.owner.id,
    )
    db.add(t)
    w.t.brand_config = {"chief": {"enabled": True, "paused": True}}
    db.commit()
    from app.services.chief import executor

    p = ChiefProposal(
        tenant_id=w.t.id,
        finding_id=_finding(db, w, code="MK7").id,
        code="MK7",
        title="t",
        why="w",
        risk_tier="R1",
        preview=[],
        steps=[step("reviews.draft_replies", "x", "R1", review_ids=[])],
        plan_sha="s" * 64,
        status="awaiting_approval",
        step_index=0,
    )
    db.add(p)
    db.commit()
    assert executor.auto_approve(db, w.t, p, w.owner.id) is False and p.status == "awaiting_approval"


def test_worse_outcome_switches_autopilot_off(db):
    w = world(db, brand_config=ON)
    t = ChiefDetectorTuning(
        tenant_id=w.t.id,
        code="MK7",
        step=1,
        approved=0,
        rejected=0,
        dismissed=0,
        improved=0,
        no_change=0,
        worse=0,
        rejections_in_row=0,
        wins_in_row=0,
        autopilot_by=w.owner.id,
        autopilot_at=datetime.now(UTC),
    )
    db.add(t)
    db.commit()
    tuning.on_outcome(db, w.t.id, "MK7", "worse")
    db.commit()
    assert t.autopilot_by is None and "worse" in t.last_reason
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.autopilot_off").count() == 1


def test_dismissing_counts_half_and_reset_is_owner_only(client, db):
    w = world(db, brand_config=ON)
    row = _finding(db, w, code="SA2")
    got = client.post(f"{R}/findings/{row.id}/dismiss", json={"reason": "wrong"}, headers=_h(w.mgr)).json()
    assert got["learning"]["counts"]["dismissed"] == 1
    assert client.post(f"{R}/tuning/SA2/reset", headers=_h(w.mgr)).status_code == 403
    assert client.post(f"{R}/tuning/NOPE/reset", headers=_h(w.owner)).status_code == 404
    assert client.post(f"{R}/tuning/SA2/reset", headers=_h(w.owner)).json()["counts"]["dismissed"] == 0
    assert tuning.get(db, w.t.id, "SA2") is None
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="chief.tuning_reset").count() == 1
    assert client.get(f"{R}/learning", headers=_h(w.foh)).status_code == 403


def test_learning_stays_in_its_tenant(db):
    a, b = world(db, brand_config=ON), world(db, brand_config=ON)
    for _ in range(3):
        tuning.on_decision(db, a.t.id, "SA1", "rejected", "wrong")
    db.commit()
    assert tuning.muted(tuning.get(db, a.t.id, "SA1")) and tuning.get(db, b.t.id, "SA1") is None
    assert detectors.Ctx(db, b.t).level("SA1", 3) == 3
