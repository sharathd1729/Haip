"""Each AI draft records what it had from the knowledge base (Message.channel_metadata["kb"]).

Without it nobody could tell afterwards whether the bot missed a passage, the search failed, or nothing matched:
scripts/diagnose_bot_replies.py and the KB health card read it.
"""

import importlib.util
import pathlib
from types import SimpleNamespace
from unittest.mock import patch

from app.models.conversation import Message
from app.services.knowledge_service import SearchOutcome
from app.workers.tasks.concierge_draft import concierge_draft
from tests.workers.test_concierge_draft_grounding import _setup_conversation

HIT = {
    "id": "kb-1",
    "category": "faq",
    "question": "Towels?",
    "content": "Towels are provided.",
    "source": "manual",
    "property_id": None,
    "score": 0.71234,
    "updated_at": "2026-11-01",
}


class _LLM:
    async def complete(self, **kwargs):
        return {
            "tool_use": {
                "intent": "general",
                "reply": "Yes, towels are provided.",
                "confidence": 0.9,
                "citations": [],
                "needs_human": False,
            }
        }


def _draft(db, conv):
    return (
        db.query(Message)
        .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
        .order_by(Message.created_at.desc())
        .first()
    )


def test_the_draft_records_the_search_status_and_passages(db, monkeypatch):
    tenant, guest, conv, inbound = _setup_conversation(db)
    monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", lambda task: _LLM())
    with (
        patch("app.services.knowledge_service.search_detailed", return_value=SearchOutcome(hits=[HIT], status="ok")),
        patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db),
        patch("app.services.push_service.send_to_tenant"),
    ):
        concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)
    assert _draft(db, conv).channel_metadata["kb"] == {"status": "ok", "hits": [{"id": "kb-1", "score": 0.712}]}


def test_a_failed_search_is_recorded_as_such(db, monkeypatch):
    tenant, guest, conv, inbound = _setup_conversation(db)
    monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", lambda task: _LLM())
    with (
        patch(
            "app.services.knowledge_service.search_detailed", return_value=SearchOutcome(status="embedding_unavailable")
        ),
        patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db),
        patch("app.services.push_service.send_to_tenant"),
    ):
        concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)
    assert _draft(db, conv).channel_metadata["kb"] == {"status": "embedding_unavailable", "hits": []}


def test_the_diagnose_script_counts_statuses_and_passages():
    path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "diagnose_bot_replies.py"
    spec = importlib.util.spec_from_file_location("diagnose_bot_replies", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    drafts = [
        SimpleNamespace(channel_metadata={"kb": {"status": "ok", "hits": [{"id": "a"}, {"id": "b"}]}}),
        SimpleNamespace(channel_metadata={"kb": {"status": "ok", "hits": [{"id": "a"}]}}),
        SimpleNamespace(channel_metadata={"kb": {"status": "no_match", "hits": []}}),
        SimpleNamespace(channel_metadata=None),
    ]
    status, used = mod.kb_summary(drafts)
    assert status == {"ok": 2, "no_match": 1, "not recorded": 1}
    assert used == {"a": 2, "b": 1}
