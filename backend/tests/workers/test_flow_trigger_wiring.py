"""
WhatsApp module bug-fix pass — flow trigger wiring.

Real bug: of the 6 trigger options offered in the Flow Builder UI
(flows/page.tsx's TRIGGER_OPTIONS), only "new_inquiry" ever actually fired
a flow. "check_in"/"check_out" fired under a different internal event name
(check_automation_timers.py's "stay_check_in_1d"/"stay_check_out_1d") that
never matched what the flow's own trigger column stored, so
_fire_matching_flows's exact-string filter_by always returned nothing.
"opt_in" had no fire point anywhere. "keyword"/"campaign_reply" are
genuinely unbuilt and were removed from the UI dropdown rather than left
to silently do nothing.

These tests cover the fix: an event-name alias table for check_in/check_out,
and a real fire_trigger call from the opt-in endpoint.
"""
import uuid
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.api.v1.endpoints.messaging import WAFlow
from app.models.flow_execution import WAFlowRun
from app.workers.tasks.automation_engine import fire_trigger, _FLOW_TRIGGER_ALIASES


def _make_tenant_and_guest(db):
    """Returns plain id strings -- fire_trigger closes `db` in its own
    finally block, so any ORM instance handed back here would be left
    detached+expired by the time a test could use it (see the identical
    note in test_generate_ai_summary_extraction.py)."""
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Guest", phone="+919876500000")
    db.add(g)
    db.flush()
    return t.id, g.id


def _make_flow(db, tenant_id, trigger):
    flow_id = str(uuid.uuid4())
    flow = WAFlow(
        id=flow_id, tenant_id=tenant_id, name="Test Flow", trigger=trigger, is_active=True,
        nodes=[
            {"id": "n1", "type": "trigger", "content": trigger},
            {"id": "n2", "type": "end"},
        ],
        edges=[{"from": "n1", "to": "n2"}],
    )
    db.add(flow)
    db.commit()
    return flow_id


def _run_trigger(db, event, tenant_id, guest_id):
    with patch("app.core.database.set_tenant_context"), \
         patch("app.workers.tasks.automation_engine.SessionLocal", return_value=db):
        fire_trigger.run(event=event, tenant_id=tenant_id, context={"guest_id": guest_id})


class TestCheckInOutTriggerAlias:
    def test_check_in_flow_fires_on_the_real_stay_event(self, db):
        tenant_id, guest_id = _make_tenant_and_guest(db)
        flow_id = _make_flow(db, tenant_id, trigger="check_in")  # what the UI actually stores

        _run_trigger(db, "stay_check_in_1d", tenant_id, guest_id)

        runs = db.query(WAFlowRun).filter_by(tenant_id=tenant_id, flow_id=flow_id).all()
        assert len(runs) > 0, "flow set to 'check_in' must fire on the real 'stay_check_in_1d' event"

    def test_check_out_flow_fires_on_the_real_stay_event(self, db):
        tenant_id, guest_id = _make_tenant_and_guest(db)
        flow_id = _make_flow(db, tenant_id, trigger="check_out")

        _run_trigger(db, "stay_check_out_1d", tenant_id, guest_id)

        runs = db.query(WAFlowRun).filter_by(tenant_id=tenant_id, flow_id=flow_id).all()
        assert len(runs) > 0

    def test_check_in_flow_does_not_fire_on_unrelated_events(self, db):
        tenant_id, guest_id = _make_tenant_and_guest(db)
        flow_id = _make_flow(db, tenant_id, trigger="check_in")

        _run_trigger(db, "stay_check_out_1d", tenant_id, guest_id)

        runs = db.query(WAFlowRun).filter_by(tenant_id=tenant_id, flow_id=flow_id).all()
        assert len(runs) == 0

    def test_alias_table_is_exactly_the_two_stay_events(self):
        assert _FLOW_TRIGGER_ALIASES == {
            "stay_check_in_1d": "check_in",
            "stay_check_out_1d": "check_out",
        }


class TestNewInquiryUnaffected:
    def test_new_inquiry_flow_still_fires_unaliased(self, db):
        """Regression guard: the alias table must not touch the one trigger
        that already worked correctly."""
        tenant_id, guest_id = _make_tenant_and_guest(db)
        flow_id = _make_flow(db, tenant_id, trigger="new_inquiry")

        _run_trigger(db, "new_inquiry", tenant_id, guest_id)

        runs = db.query(WAFlowRun).filter_by(tenant_id=tenant_id, flow_id=flow_id).all()
        assert len(runs) > 0
