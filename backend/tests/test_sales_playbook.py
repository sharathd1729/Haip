"""The owner's sales playbook: owner-only audited endpoint, rendered into the concierge prompt (and nothing when empty), the
follow-up draft's style line, and Rathaa's seed."""
import importlib.util
import pathlib
from unittest.mock import patch

from app.models.audit_event import AuditEvent
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import lead_followup_draft, sales_playbook
from app.workers.tasks.concierge_draft import concierge_draft
from tests.test_increment1_defect_specs import _h, _tenant, _user
from tests.workers.test_agent_consult_flow import setup_thread

P = "/api/v1/ai/sales-playbook"


def _seed_module():
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "seed_ratha_playbook.py"
    spec = importlib.util.spec_from_file_location("seed_ratha_playbook", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_owner_writes_the_playbook_audited(client, db):
    t = _tenant(db)
    owner, mgr = _user(db, t.id, UserRole.OWNER), _user(db, t.id, UserRole.MANAGER)
    assert client.get(P, headers=_h(mgr)).json()["empty"] is True
    body = {"opening_line": "A retreat that travels with you.", "qualification_questions": ["When?", "How many?"],
            "never_say_no": True}
    assert client.put(P, json=body, headers=_h(mgr)).status_code == 403
    res = client.put(P, json=body, headers=_h(owner))
    assert res.status_code == 200 and set(res.json()["changed"]) == {"opening_line", "qualification_questions", "never_say_no"}
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="ai.sales_playbook_changed").count() == 1
    assert client.put(P, json={"made_up": 1}, headers=_h(owner)).status_code == 422
    assert client.put(P, json={"rules": ["x" * 301]}, headers=_h(owner)).status_code == 422
    other = _tenant(db)
    assert client.get(P, headers=_h(_user(db, other.id, UserRole.OWNER))).json()["empty"] is True


class _Recorder:
    def __init__(self):
        self.prompts = []

    async def complete(self, **kwargs):
        self.prompts.append(kwargs.get("system_prompt") or "")
        if any(t.get("name") == "classify_and_extract" for t in kwargs.get("tools") or []):
            return {"tool_use": {"intent": "general"}}
        return {"tool_use": {"reply": "Hello!", "confidence": 0.95, "citations": [], "needs_human": False}}


def _prompt(db, t, c, m):
    rec = _Recorder()
    with patch("app.workers.tasks.concierge_draft.get_llm", lambda task: rec), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.services.push_service.send_to_tenant"), patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
        concierge_draft.run(message_id=m.id, conversation_id=c.id, tenant_id=t.id)
    return rec.prompts[-1]


def test_the_playbook_reaches_the_reply_prompt_and_only_when_set(db):
    t, g, c, m = setup_thread(db, "Hi, what is Rathaa?")
    assert "SALES PLAYBOOK" not in _prompt(db, t, c, m)
    seed = _seed_module()
    t, g, c, m = setup_thread(db, "Hi, what is Rathaa?")
    sales_playbook.update(db, t, None, seed.RATHA_PLAYBOOK, actor="test")
    db.commit()
    prompt = _prompt(db, t, c, m)
    assert "SALES PLAYBOOK" in prompt and "Rathaa can go where the room can't go" in prompt
    assert "never open by asking their budget" in prompt and "Recommend ONE itinerary" in prompt
    assert "Reply in the language of the guest's latest message" in prompt


def test_the_seed_is_valid_and_figure_free():
    seed = _seed_module()
    pb = seed.RATHA_PLAYBOOK
    assert len(pb.qualification_questions) == 10 and pb.add_value_before_discount and pb.never_say_no
    from app.services.price_policy import detect_price
    assert not any(detect_price(a) for a in pb.objection_answers.values())       # the price guard would block a figure


def test_follow_up_drafts_carry_the_owners_style(db):
    t = _tenant(db)
    assert lead_followup_draft._style(db, t.id) == ""
    sales_playbook.update(db, t, None, _seed_module().RATHA_PLAYBOOK)
    db.commit()
    assert "never 'any update?'" in lead_followup_draft._style(db, db.get(Tenant, t.id).id)
