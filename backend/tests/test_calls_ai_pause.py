"""Pausing call AI for one workspace (services/calls_ai_pause.py, scripts/pause_calls_ai.py): a paused workspace's calls
are not transcribed or analysed (not even ones already queued) and the sweeps skip it; other workspaces carry on."""
from pathlib import Path

from sqlalchemy.orm import Session as SASession

from app.models.call import Call
from app.models.tenant import Tenant
from app.services import calls_ai_pause
from app.workers.tasks import call_recovery
from tests.test_calls_app_reliability import _stuck_call
from tests.workers import call_analysis_harness as h


def _pause(db, tenant_id):
    t = db.get(Tenant, tenant_id)
    t.brand_config = {**(t.brand_config or {}), calls_ai_pause.KEY: True}
    db.commit()


def test_a_paused_workspace_is_not_transcribed_or_analysed_and_others_are(db, monkeypatch):
    from app.workers.tasks import transcribe

    paused, running = h.tenant(db), h.tenant(db)
    _pause(db, paused.id)
    c = _stuck_call(db, paused.id, status="queued")
    monkeypatch.setattr(transcribe, "SessionLocal", lambda: SASession(bind=db.connection()))
    transcribe.transcribe.run(call_id=c.id, tenant_id=paused.id)        # would fail fetching x.mp3 if it went on
    db.refresh(c)
    assert c.transcription_status == "queued"                           # left waiting for a resume

    a = h.call(db, paused.id)                                           # has a transcript: analysis would call the model
    llm = h.ScriptedLLM(tool_use={})
    h.run(db, paused.id, a.id, llm)
    assert llm.calls == [] and db.get(Call, a.id).ai_score_status != "done"

    b = h.call(db, running.id)
    llm2 = h.ScriptedLLM(tool_use={})
    try:
        h.run(db, running.id, b.id, llm2)
    except Exception:  # noqa: BLE001 -- the scripted answer is empty; all that matters is that the model was asked
        pass
    assert len(llm2.calls) >= 1                                         # the other workspace still gets its read


def test_sweeps_skip_a_paused_workspace(db):
    paused = h.tenant(db)
    _pause(db, paused.id)
    _stuck_call(db, paused.id, status="queued")
    sent = []
    assert call_recovery.requeue_queued_transcriptions(db, paused.id, sent.append) == 0 and sent == []


def test_the_flag_is_per_workspace(db):
    a, b = h.tenant(db), h.tenant(db)
    _pause(db, a.id)
    assert calls_ai_pause.is_paused(db, a.id) is True and calls_ai_pause.is_paused(db, b.id) is False
    script = Path(__file__).resolve().parent.parent / "scripts" / "pause_calls_ai.py"
    assert "--resume" in script.read_text(encoding="utf-8")
