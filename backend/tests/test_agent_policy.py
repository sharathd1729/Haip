"""Who may decide what (brand_config.agent_policy): defaults, the owner-only audited endpoint, and enforcement in the reply path
(through the real concierge task) and in the sales agent's holds."""
from app.models.agent_consult import AgentConsult
from app.models.audit_event import AuditEvent
from app.models.conversation import Message
from app.models.user import UserRole
from app.services import agent_policy
from tests.test_increment1_defect_specs import _h, _tenant, _user
from tests.workers.test_agent_consult_flow import run_turn, setup_thread

P = "/api/v1/ai/agent-policy"


class _T:
    def __init__(self, cfg):
        self.brand_config = cfg


def test_defaults_follow_the_price_disclosure():
    handoff = agent_policy.get(_T({}))
    assert handoff["answer_faq"] == "autonomous" and handoff["suggest_kit"] == "autonomous"
    assert handoff["quote_published_price"] == "consult"
    assert handoff["send_payment_link"] == "draft_for_approval" and handoff["hold_dates"] == "draft_for_approval"
    for k in ("discount", "custom_route", "b2b", "cancellation_refund", "complaint"):
        assert handoff[k] == "consult"
    assert agent_policy.get(_T({"price_disclosure": "grounded"}))["quote_published_price"] == "autonomous"
    assert agent_policy.get(_T({"agent_policy": {"modes": {"discount": "nonsense"}}}))["discount"] == "consult"


def test_apply_keeps_drops_or_adds_reasons():
    t = _T({"agent_policy": {"modes": {"discount": "autonomous"}}})
    assert agent_policy.apply(t, "general", "Sure.", ["discount_request"]) == ([], False, [])
    t = _T({"agent_policy": {"modes": {"discount": "draft_for_approval"}}})
    reasons, hold, _ = agent_policy.apply(t, "general", "Sure.", ["discount_request"])
    assert reasons == [] and hold is True
    t = _T({"agent_policy": {"modes": {"answer_faq": "consult"}}})
    assert agent_policy.apply(t, "faq_answer", "We leave at 9.", [])[0] == ["policy_consult"]
    # A guard reason that no class owns always stays.
    assert agent_policy.apply(_T({}), "general", "x", ["wants_human"])[0] == ["wants_human"]


def test_owner_changes_the_policy_audited(client, db):
    t = _tenant(db)
    owner, mgr, foh = (_user(db, t.id, r) for r in (UserRole.OWNER, UserRole.MANAGER, UserRole.FOH))
    got = client.get(P, headers=_h(mgr)).json()
    assert got["modes"]["discount"] == "consult" and len(got["classes"]) == 10
    assert client.put(P, json={"modes": {"discount": "autonomous"}}, headers=_h(mgr)).status_code == 403
    assert client.get(P, headers=_h(foh)).status_code == 403
    res = client.put(P, json={"modes": {"discount": "draft_for_approval"}}, headers=_h(owner))
    assert res.status_code == 200 and res.json()["changed"] == {"discount": {"from": "consult", "to": "draft_for_approval"}}
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="ai.agent_policy_changed").count() == 1
    assert client.put(P, json={"modes": {"teleport": "consult"}}, headers=_h(owner)).status_code == 422
    assert client.put(P, json={"modes": {"discount": "maybe"}}, headers=_h(owner)).status_code == 422
    other = _tenant(db)
    other_owner = _user(db, other.id, UserRole.OWNER)
    assert client.get(P, headers=_h(other_owner)).json()["modes"]["discount"] == "consult"


def test_the_reply_path_obeys_the_policy(db):
    # Owner lets the AI discuss discounts: no consult, the reply goes.
    t, g, c, m = setup_thread(db, "Any discount for a weekday trip?")
    t.brand_config = {"agent_policy": {"modes": {"discount": "autonomous"}}}
    db.commit()
    tid, cid = t.id, c.id
    sent, _ = run_turn(db, t, c, m, reply="Weekdays are our quietest days, so it's a lovely time to go.")
    assert db.query(AgentConsult).filter_by(tenant_id=tid).count() == 0 and len(sent) == 1

    # Draft for approval: held for a person, but no consult and no holding reply.
    t, g, c, m = setup_thread(db, "Any discount for a weekday trip?")
    t.brand_config = {"agent_policy": {"modes": {"discount": "draft_for_approval"}}}
    db.commit()
    tid, cid = t.id, c.id
    sent, _ = run_turn(db, t, c, m, reply="Let me see what I can do.")
    assert sent == [] and db.query(AgentConsult).filter_by(tenant_id=tid).count() == 0
    draft = db.query(Message).filter_by(conversation_id=cid, is_ai_generated=True).one()
    assert draft.was_approved is None and "needs approval" in draft.ai_needs_human_reason

    # Owner wants a person on every answer: an ordinary question becomes a consult.
    t, g, c, m = setup_thread(db, "What time do we leave?")
    t.brand_config = {"agent_policy": {"modes": {"answer_faq": "consult"}}}
    db.commit()
    tid = t.id
    run_turn(db, t, c, m, reply="Trips leave at 9 am.", intent={"intent": "faq_answer"})
    assert db.query(AgentConsult).filter_by(tenant_id=tid).one().reason_codes == ["policy_consult"]
