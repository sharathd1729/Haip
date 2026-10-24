"""Learning loop: catalogue guardrails, deterministic 50/50 assignment, the evaluator's decisions (keep / roll back / stop), the
autonomy check + bench gate, one test per control, the kill switch, Undo, the resolver hook, endpoints, proposals."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.analyst import AgentExperiment, AgentExperimentAssignment, AgentLesson
from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.services import agent_policy, sales_playbook
from app.services.learning import catalogue, experiments, proposals, resolver
from app.services.learning import evaluate as ev
from tests.analyst_world import world
from tests.test_increment1_defect_specs import _h

PASS = lambda treated, scenarios: [{"id": "x", "passed": True, "failed": []}]          # noqa: E731
FAIL = lambda treated, scenarios: [{"id": "x", "passed": False, "failed": [{"check": "no_unsupported_figure_sent"}]}]  # noqa: E731
WORDING = {"field": "opening_line", "value": "Tell us your dates and we will plan the whole trip with you."}


def _allow(db, w, **areas):
    w.t.brand_config = {**(w.t.brand_config or {}), "learning": {"experiments_allowed": True, "areas": {**areas}}}
    db.commit()


def _conv(db, w, *, created=None, guest=None, lead=False):
    g = guest or Guest(id=str(uuid.uuid4()), tenant_id=w.t.id, name="Asha Rao", phone="+919845611111" if lead else "",
                       lead_identified_at=datetime.now(timezone.utc) if lead else None)
    if guest is None:
        db.add(g)
        db.flush()
    else:   # a guest has at most ONE open WhatsApp thread (partial unique index, enforced on PostgreSQL): close the earlier ones
        db.query(Conversation).filter_by(tenant_id=w.t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)             .update({"is_open": False})
    c = Conversation(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True,
                     created_at=created or datetime.now(timezone.utc))
    db.add(c)
    db.flush()
    return c, g


# ── catalogue ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_catalogue_refuses_anything_that_would_widen_a_guardrail(db):
    w = world(db)
    for diff, code in (({"field": "opening_line", "value": "Only Rs 9,999 today!"}, "figure_in_wording"),
                       ({"field": "opening_line", "value": "Ask us for a discount"}, "discount_in_wording"),
                       ({"field": "follow_up_style", "value": "Send https://pay.me"}, "link_in_wording"),
                       ({"field": "rules", "value": "x"}, "bad_field")):
        with pytest.raises(catalogue.ChangeRefused) as e:
            catalogue.validate(db, w.t, "playbook_wording", diff)
        assert e.value.code == code
    with patch.object(catalogue, "published", return_value={"coorg-48": "Coorg 48 hours"}):
        assert catalogue.validate(db, w.t, "price_disclosure_per_package", {"packages": ["coorg-48"]}) == {"packages": ["coorg-48"]}
        with pytest.raises(catalogue.ChangeRefused):
            catalogue.validate(db, w.t, "price_disclosure_per_package", {"packages": ["b2b-base"]})     # unpublished / b2b
        with pytest.raises(catalogue.ChangeRefused):
            catalogue.validate(db, w.t, "route_suggestion", {"ask": "Goa", "route_key": "goa-beach"})
    for hours in (1, 72):
        with pytest.raises(catalogue.ChangeRefused):
            catalogue.validate(db, w.t, "followup_timing", {"first_hours": hours})
    with pytest.raises(catalogue.ChangeRefused):
        catalogue.validate(db, w.t, "consult_threshold", {"above_inr": 10})
    with pytest.raises(catalogue.ChangeRefused):
        catalogue.validate(db, w.t, "change_the_price", {})


# ── assignment ────────────────────────────────────────────────────────────────────────────────────────────────

def test_hash_assignment_is_deterministic_and_about_half_and_half():
    ids = [f"conv-{i}" for i in range(4000)]
    arms = [resolver.arm_by_hash("exp-1", c) for c in ids]
    assert arms == [resolver.arm_by_hash("exp-1", c) for c in ids]
    share = arms.count("treatment") / len(arms)
    assert 0.46 < share < 0.54
    assert [resolver.arm_by_hash("exp-2", c) for c in ids] != arms            # a new experiment re-splits


def _running(db, w, change_type="playbook_wording", diff=None, started=None, **kw):
    exp = AgentExperiment(tenant_id=w.t.id, change_type=change_type, area=catalogue.TYPES[change_type].area,
                          control=catalogue.TYPES[change_type].control, title="t", diff=diff if diff is not None else WORDING,
                          target_metric=kw.get("metric", "dm_to_lead"), status="running",
                          started_at=started or datetime.now(timezone.utc) - timedelta(days=1),
                          min_sample_per_arm=kw.get("min_sample", 40), max_days=kw.get("max_days", 14),
                          stop_loss={"relative": 0.3, "p": 0.1, "keep_p": 0.05}, assignment_rule={"split": 0.5})
    db.add(exp)
    db.commit()
    return exp


def test_only_new_conversations_take_part_and_a_guest_keeps_their_arm(db):
    w = world(db)
    exp = _running(db, w)
    old, _ = _conv(db, w, created=exp.started_at - timedelta(hours=2))
    assert resolver.assign(db, exp, old, old.guest_id) is None
    c1, g = _conv(db, w)
    arm = resolver.assign(db, exp, c1, g.id)
    assert arm in ("control", "treatment") and resolver.assign(db, exp, c1, g.id) == arm
    for _ in range(6):                                                          # later conversations of the same guest
        c, _ = _conv(db, w, guest=g)
        assert resolver.assign(db, exp, c, g.id) == arm
    assert db.query(AgentExperimentAssignment).filter_by(experiment_id=exp.id).count() == 7


def test_resolver_applies_the_treatment_only_to_its_arm_and_the_kill_switch_wins(db):
    w = world(db)
    exp = _running(db, w)
    seen = {}
    for _ in range(30):
        c, _ = _conv(db, w)
        eff = resolver.for_conversation(db, w.t, c)
        seen.setdefault(eff.arms[exp.id], eff.playbook["opening_line"])
    assert seen["treatment"] == WORDING["value"] and seen["control"] == ""
    w.t.brand_config = {**w.t.brand_config, "learning": {"paused": True}}
    db.commit()
    c, _ = _conv(db, w)
    assert resolver.for_conversation(db, w.t, c).arms == {}


def test_price_mode_for_turn_only_shows_listed_published_packages():
    eff = resolver.Effective(price_packages={"coorg-48"}, consult_price_above=100000)
    assert resolver.price_mode_for_turn("handoff", eff, "coorg-48", 60000) == "grounded"
    assert resolver.price_mode_for_turn("handoff", eff, "kerala", 60000) == "handoff"
    assert resolver.price_mode_for_turn("handoff", eff, "coorg-48", 150000) == "handoff"     # big quote: a person talks price
    assert resolver.price_mode_for_turn("grounded", eff, None, 150000) == "handoff"
    assert resolver.price_mode_for_turn("handoff", resolver.Effective(), "coorg-48", 1) == "handoff"


# ── the decision rule ─────────────────────────────────────────────────────────────────────────────────────────

D = dict(min_sample=40, max_days=14, stop_loss_relative=0.3, stop_loss_p=0.1, keep_p=0.05)


def test_decide_keep_rollback_stop_continue():
    assert ev.decide((12, 60), (30, 60), elapsed_days=5, **D)["result"] == "keep"
    assert ev.decide((30, 60), (12, 60), elapsed_days=5, **D)["result"] == "rollback"
    early = ev.decide((12, 25), (3, 25), elapsed_days=2, **D)                  # stop-loss before the full sample
    assert early["result"] == "rollback" and early["reason"].startswith("stop-loss")
    assert ev.decide((20, 60), (22, 60), elapsed_days=14, **D) == {**ev.decide((20, 60), (22, 60), elapsed_days=14, **D),
                                                                       "result": "stop", "reason": "no clear difference"}
    assert ev.decide((2, 8), (3, 8), elapsed_days=15, **D)["reason"] == "too few conversations to judge"
    assert ev.decide((20, 60), (22, 60), elapsed_days=3, **D)["result"] == "continue"


def _seed_arm(db, w, exp, arm, n, x):
    """n conversations assigned to ``arm``, x of whose guests became leads (dm_to_lead)."""
    for i in range(n):
        c, g = _conv(db, w)
        db.add(AgentExperimentAssignment(tenant_id=w.t.id, experiment_id=exp.id, conversation_id=c.id, guest_id=g.id, arm=arm,
                                         guest_was_lead=False, assigned_at=datetime.now(timezone.utc) - timedelta(hours=5)))
        if i < x:
            g.phone, g.lead_identified_at = f"+9198456{uuid.uuid4().int % 10**5:05d}", datetime.now(timezone.utc)
    db.commit()


def test_evaluate_keeps_writes_a_lesson_and_undo_restores(db, client):
    w = world(db)
    exp = _running(db, w)
    _seed_arm(db, w, exp, "control", 50, 10)
    _seed_arm(db, w, exp, "treatment", 50, 30)
    out = experiments.evaluate_one(db, w.t, exp)
    db.commit()
    assert out["result"] == "keep" and exp.status == "kept" and exp.decided_by == "system"
    assert sales_playbook.get(w.t).opening_line == WORDING["value"] and exp.applied_before["opening_line"] == ""
    lesson = db.query(AgentLesson).filter_by(tenant_id=w.t.id).one()
    assert "60% with it vs 20% without (100 conversations)" in lesson.text and lesson.status == "active"
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="learning.experiment_kept").count() == 1
    from app.services.learning import lessons
    assert lessons.prompt_lines(db, w.t) == [lesson.text]
    r = client.post(f"/api/v1/learning/experiments/{exp.id}/undo", headers=_h(w.mgr))
    assert r.status_code == 200 and r.json()["undo_available"] is False
    db.expire_all()
    assert sales_playbook.get(w.t).opening_line == "" and db.query(AgentLesson).filter_by(tenant_id=w.t.id).one().status == "retired"
    assert client.post(f"/api/v1/learning/experiments/{exp.id}/undo", headers=_h(w.mgr)).status_code == 409


def test_undo_refuses_when_the_setting_changed_since(db):
    w = world(db)
    exp = _running(db, w)
    _seed_arm(db, w, exp, "control", 50, 10)
    _seed_arm(db, w, exp, "treatment", 50, 30)
    experiments.evaluate_one(db, w.t, exp)
    from app.schemas.sales_playbook import SalesPlaybook
    sales_playbook.update(db, w.t, w.owner.id, SalesPlaybook(opening_line="Owner wrote this"))
    db.commit()
    with pytest.raises(experiments.ExperimentError) as e:
        experiments.undo(db, w.t, exp.id, w.owner)
    assert e.value.code == "changed_since"


def test_evaluate_rolls_back_on_stop_loss(db):
    w = world(db)
    exp = _running(db, w)
    _seed_arm(db, w, exp, "control", 25, 12)
    _seed_arm(db, w, exp, "treatment", 25, 3)
    assert experiments.evaluate_one(db, w.t, exp)["result"] == "rollback" and exp.status == "rolled_back"
    assert sales_playbook.get(w.t).opening_line == ""                         # base untouched


def test_evaluate_stops_at_max_duration_with_no_clear_difference(db):
    w = world(db)
    exp = _running(db, w, started=datetime.now(timezone.utc) - timedelta(days=15))
    _seed_arm(db, w, exp, "control", 45, 20)
    _seed_arm(db, w, exp, "treatment", 45, 21)
    assert experiments.evaluate_one(db, w.t, exp)["reason"] == "no clear difference" and exp.status == "stopped"


# ── autonomy + bench gate ─────────────────────────────────────────────────────────────────────────────────────

def test_autonomy_levels_decide_what_starts(db):
    w = world(db)
    e = experiments.propose(db, w.t, "playbook_wording", WORDING, bench_runner=PASS)       # experiments not allowed yet
    assert e.status == "awaiting_approval"
    e.status = "rejected"
    _allow(db, w, replies="act")
    e = experiments.propose(db, w.t, "playbook_wording", WORDING, bench_runner=PASS)
    assert e.status == "running" and e.bench["passed"] and e.decided_by == "system"
    e2 = experiments.propose(db, w.t, "early_package_share", {}, bench_runner=PASS) if catalogue.published(db, w.t.id, "package") \
        else None
    assert e2 is None or e2.status != "running"                                  # same control: waits
    e.status = "stopped"
    db.commit()
    e3 = experiments.propose(db, w.t, "playbook_wording", WORDING, bench_runner=FAIL)
    assert e3.status == "bench_failed" and e3.started_at is None
    _allow(db, w, replies="watch")
    assert experiments.propose(db, w.t, "playbook_wording", WORDING, bench_runner=PASS).status == "proposed"
    _allow(db, w, replies="suggest")
    e4 = experiments.propose(db, w.t, "followup_timing", {"first_hours": 3}, bench_runner=PASS)
    assert e4.status == "awaiting_approval"
    assert experiments.approve(db, w.t, e4.id, w.mgr, bench_runner=PASS).status == "running"


def test_price_changes_need_the_owner(db):
    w = world(db)
    _allow(db, w, prices="suggest")
    e = experiments.propose(db, w.t, "consult_threshold", {"above_inr": 150000}, bench_runner=PASS)
    with pytest.raises(experiments.ExperimentError) as err:
        experiments.approve(db, w.t, e.id, w.mgr, bench_runner=PASS)
    assert err.value.status == 403
    assert experiments.approve(db, w.t, e.id, w.owner, bench_runner=PASS).status == "running"


def test_one_running_test_per_control(db):
    w = world(db)
    _allow(db, w, replies="act")
    first = experiments.propose(db, w.t, "playbook_wording", WORDING, bench_runner=PASS)
    second = experiments.propose(db, w.t, "kit_before_discount", {"segments": []}, bench_runner=PASS)
    assert first.status == "running" and second.status != "running" and "waiting" in second.decision["reason"]


def test_kill_switch_stops_every_running_test(client, db):
    w = world(db)
    exp = _running(db, w)
    body = {"paused": True}
    assert client.put("/api/v1/ai/learning-settings", json=body, headers=_h(w.mgr)).status_code == 403
    r = client.put("/api/v1/ai/learning-settings", json=body, headers=_h(w.owner))
    assert r.status_code == 200 and r.json()["settings"]["paused"] is True
    db.expire_all()
    assert db.query(AgentExperiment).filter_by(id=exp.id).one().status == "stopped"
    bad = client.put("/api/v1/ai/learning-settings", json={"areas": {"policy_rules": "act"}}, headers=_h(w.owner))
    assert bad.status_code == 422                                              # a price/policy rule change is never automatic


def test_bench_gate_runs_the_real_pipeline_with_the_treatment(db):
    from app.services.agent_bench import load_scenarios
    from app.services.learning import bench_gate
    w = world(db)
    exp = AgentExperiment(id=str(uuid.uuid4()), tenant_id=w.t.id, change_type="playbook_wording", area="replies",
                          control="sales_playbook", title="t", diff=WORDING, target_metric="dm_to_lead")
    pick = [s for s in load_scenarios() if s["id"] in {"mysuru-1day-grounded", "discount-small-booking"}]
    with patch.object(bench_gate, "scenarios_for", return_value=pick):
        res = bench_gate.check(db, w.t, exp, runner=lambda treated, scenarios: bench_gate.run_with(
            db, _bench_world(db, treated), scenarios))
    assert res["passed"], res
    assert "learning-playbook_wording" in res["scenarios"] and res["ran"] == 3


def _bench_world(db, treated):
    from app.services import agent_bench
    bw = agent_bench.build_world(db, playbook=False)
    bw.tenant.brand_config = {**treated}
    db.commit()
    return bw


# ── policy caps, proposals, endpoints ─────────────────────────────────────────────────────────────────────────

def test_area_levels_cap_agent_policy_never_loosen(db):
    w = world(db, brand_config={"price_disclosure": "grounded", "agent_policy": {"modes": {"send_payment_link": "autonomous"}}})
    assert agent_policy.get(w.t)["quote_published_price"] == "autonomous"
    assert agent_policy.get(w.t)["send_payment_link"] == "autonomous"            # no learning settings: unchanged
    _allow(db, w, prices="watch")
    modes = agent_policy.get(w.t)
    assert modes["quote_published_price"] == "consult" and modes["send_payment_link"] == "draft_for_approval"
    assert modes["discount"] == "consult" and modes["b2b"] == "consult"
    assert agent_policy.get(w.t, "grounded")["answer_faq"] == "autonomous"


def test_report_health_turns_into_a_proposal(db):
    w = world(db)
    report = type("R", (), {"id": "rep-1", "facts": {"health": [{"key": "communication", "status": "red"}], "findings": []},
                            "brief": {}})()
    made = proposals.from_report(db, w.t, report)
    exp = db.query(AgentExperiment).filter_by(id=made[0]).one()
    assert exp.change_type == "playbook_wording" and exp.status == "awaiting_approval" and exp.source_report_id == "rep-1"
    assert proposals.from_report(db, w.t, report) == []                         # one open proposal per type


def test_endpoints_board_roles_and_tenants(client, db):
    w = world(db)
    with patch("app.workers.tasks.learning_tasks.start_experiment.delay") as start:
        _allow(db, w, replies="act")
        r = client.post("/api/v1/learning/experiments", json={"change_type": "playbook_wording", "diff": WORDING}, headers=_h(w.mgr))
        assert r.status_code == 201 and r.json()["status"] == "proposed" and start.call_count == 1
    assert client.post("/api/v1/learning/experiments", json={"change_type": "playbook_wording",
                                                             "diff": {"field": "opening_line", "value": "Rs 500 off"}},
                       headers=_h(w.mgr)).status_code == 422
    board = client.get("/api/v1/learning/board", headers=_h(w.mgr)).json()
    assert board["suggested"][0]["id"] == r.json()["id"]
    assert client.get("/api/v1/learning/board", headers=_h(w.foh)).status_code == 403
    other = world(db)
    assert client.get(f"/api/v1/learning/experiments/{r.json()['id']}", headers=_h(other.owner)).status_code == 404
    assert client.post(f"/api/v1/learning/experiments/{r.json()['id']}/reject", headers=_h(other.owner)).status_code == 404
    assert client.post(f"/api/v1/learning/experiments/{r.json()['id']}/reject", headers=_h(w.mgr)).json()["status"] == "rejected"
    assert client.get("/api/v1/learning/lessons", headers=_h(w.owner)).json() == []


def test_followup_delay_follows_the_guests_arm(db):
    w = world(db)
    exp = _running(db, w, "followup_timing", {"playbook": "proposal_followup", "first_hours": 3.0}, metric="quote_to_won")
    c, g = _conv(db, w)
    arm = resolver.assign(db, exp, c, g.id)
    got = resolver.followup_first_delay(db, w.t, "proposal_followup", g.id, timedelta(hours=6))
    assert got == (timedelta(hours=3) if arm == "treatment" else timedelta(hours=6))


def test_bench_gate_isolated_runner_uses_a_throwaway_database(db):
    """The production runner: in-memory SQLite, every SessionLocal pointed at it, no real model; the test DB is untouched."""
    from app.models.tenant import Tenant
    from app.services.agent_bench import load_scenarios
    from app.services.learning import bench_gate
    before = db.query(Tenant).count()
    pick = [s for s in load_scenarios() if s["id"] == "discount-small-booking"]
    out = bench_gate._isolated_runner({"sales_playbook": {**sales_playbook.get(type("T", (), {"brand_config": {}})()).model_dump(),
                                                          "opening_line": WORDING["value"]}}, pick)
    assert out == [{"id": "discount-small-booking", "passed": True, "failed": []}]
    assert db.query(Tenant).count() == before
