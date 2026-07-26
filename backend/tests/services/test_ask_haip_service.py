"""
Regression test for the ask_haip() persistence bug (WS2 of the M5+ overhaul):
the finding-persist block referenced an undefined `agent_data` variable
(should have been `agent_outputs`), so every call silently failed to save
its findings — swallowed by a bare `except Exception` around the whole
persist block, so no test or log ever surfaced it.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_ask_haip_persists_finding_with_correct_agents_used():
    """After a full ask_haip() call, the persisted AskHaipFinding.agents_used
    must reflect the domains that actually produced agent output — not raise
    a NameError that gets silently swallowed."""
    from app.services import ask_haip_service as svc

    db = MagicMock()

    fake_raw_data = {"/analytics/executive": {"revenue": 100}}
    fake_agent_outputs = {"revenue": {"summary": "ok"}, "guest": {"summary": "ok"}}

    with patch.object(svc, "get_cached", return_value=None), \
         patch.object(svc, "detect_intent", new=AsyncMock(return_value={"domains": ["revenue", "guest"], "type": "diagnostic"})), \
         patch.object(svc, "run_agents", new=AsyncMock(return_value=(fake_raw_data, fake_agent_outputs))), \
         patch.object(svc, "generate_paths", return_value=[]), \
         patch.object(svc, "build_correlations", return_value=[]), \
         patch.object(svc, "correlations_to_strings", return_value=[]), \
         patch.object(svc, "calculate_confidence", return_value=MagicMock(score=0.8, label="high", data_completeness=1.0, missing_domains=[])), \
         patch.object(svc, "is_comparative_question", return_value=False), \
         patch.object(svc, "run_enhanced_rca", new=AsyncMock(return_value={
             "findings": [], "summary": "", "root_cause_chain": "",
             "confidence": 0.8, "investigation_paths_used": ["revenue", "guest"],
         })):
        result = await svc.ask_haip(
            question="Why did revenue drop?",
            tenant_id="tenant-1",
            user_id="user-1",
            token="tok",
            base_url="http://testserver",
            db=db,
        )

    assert result["session_id"]
    # db.add called twice: AskHaipSession, then AskHaipFinding
    assert db.add.call_count == 2
    finding = db.add.call_args_list[1].args[0]
    assert set(finding.agents_used) == {"revenue", "guest"}
    db.commit.assert_called_once()
    db.rollback.assert_not_called()
