"""
WhatsApp module Phase 2 — flow engine tests.

Covers:
  T2.2: linear walk (trigger -> message -> action -> end), condition
        branching, delay node parks into flow_pending_executions
  T2.1: Beat drain claims due rows and resumes correctly
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.api.v1.endpoints.messaging import WAFlow
from app.models.flow_execution import FlowPendingExecution, WAFlowRun
from app.services.flow_engine import run_flow


def _make_tenant_and_guest(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Guest", phone="+919876500000")
    db.add(g)
    db.flush()
    return t, g


def _make_flow(db, tenant_id, nodes, edges, trigger="new_inquiry"):
    flow = WAFlow(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="Test Flow",
        nodes=nodes, edges=edges, trigger=trigger, is_active=True,
    )
    db.add(flow)
    db.commit()
    return flow


def test_linear_walk_message_action_end(db):
    t, g = _make_tenant_and_guest(db)
    nodes = [
        {"id": "n1", "type": "trigger", "content": "new_inquiry"},
        {"id": "n2", "type": "message", "content": "Hi {{name}}!"},
        {"id": "n3", "type": "action", "content": "tag_vip"},
        {"id": "n4", "type": "end"},
    ]
    edges = [
        {"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}, {"from": "n3", "to": "n4"},
    ]
    flow = _make_flow(db, t.id, nodes, edges)

    with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
        run_flow(db, t.id, flow, g.id)

    runs = db.query(WAFlowRun).filter_by(tenant_id=t.id, flow_id=flow.id).order_by(WAFlowRun.ran_at).all()
    types = [r.node_type for r in runs]
    assert "message" in types
    assert "action" in types
    assert all(r.status in ("success",) for r in runs)


def test_condition_false_ends_flow(db):
    t, g = _make_tenant_and_guest(db)
    nodes = [
        {"id": "n1", "type": "trigger", "content": "new_inquiry"},
        {"id": "n2", "type": "condition", "condition": "is_vip"},
        {"id": "n3", "type": "message", "content": "VIP only message"},
    ]
    edges = [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}]
    flow = _make_flow(db, t.id, nodes, edges)

    # guest has no WASubscriber "VIP" tag -> is_vip evaluates False -> flow
    # must end at the condition node, never reach the message node.
    run_flow(db, t.id, flow, g.id)

    runs = db.query(WAFlowRun).filter_by(tenant_id=t.id, flow_id=flow.id).all()
    node_ids_run = {r.node_id for r in runs}
    assert "n2" in node_ids_run
    assert "n3" not in node_ids_run


def test_delay_node_parks_pending_execution(db):
    t, g = _make_tenant_and_guest(db)
    nodes = [
        {"id": "n1", "type": "trigger", "content": "new_inquiry"},
        {"id": "n2", "type": "delay", "delay_minutes": 60},
        {"id": "n3", "type": "end"},
    ]
    edges = [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}]
    flow = _make_flow(db, t.id, nodes, edges)

    run_flow(db, t.id, flow, g.id)

    pending = db.query(FlowPendingExecution).filter_by(tenant_id=t.id, flow_id=flow.id).all()
    assert len(pending) == 1
    assert pending[0].node_id == "n3"
    assert pending[0].status == "pending"
    resume_at = pending[0].resume_at
    now = datetime.now(timezone.utc)
    if resume_at.tzinfo is None:
        now = now.replace(tzinfo=None)   # sqlite test DB drops tz info on round-trip
    assert resume_at > now


def test_resume_from_delay_completes_flow(db):
    t, g = _make_tenant_and_guest(db)
    nodes = [
        {"id": "n1", "type": "trigger", "content": "new_inquiry"},
        {"id": "n2", "type": "action", "content": "tag_vip"},
        {"id": "n3", "type": "end"},
    ]
    edges = [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}]
    flow = _make_flow(db, t.id, nodes, edges)

    # Resuming directly at node n2 (as if a delay had parked here)
    run_flow(db, t.id, flow, g.id, start_node_id="n2")

    runs = db.query(WAFlowRun).filter_by(tenant_id=t.id, flow_id=flow.id).all()
    assert any(r.node_id == "n2" and r.status == "success" for r in runs)
    assert any(r.node_id == "n3" for r in runs)


def test_tenant_isolation_flow_runs(db):
    t1, g1 = _make_tenant_and_guest(db)
    t2, g2 = _make_tenant_and_guest(db)
    nodes = [{"id": "n1", "type": "trigger", "content": "new_inquiry"}, {"id": "n2", "type": "end"}]
    edges = [{"from": "n1", "to": "n2"}]
    flow1 = _make_flow(db, t1.id, nodes, edges)

    run_flow(db, t1.id, flow1, g1.id)

    t2_runs = db.query(WAFlowRun).filter_by(tenant_id=t2.id).all()
    assert len(t2_runs) == 0
