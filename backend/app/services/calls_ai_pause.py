"""Pause call transcription for ONE workspace: Settings > AI "Call transcription" (tenants.ai_features["call_transcription"]
= false, services/ai_features.py). Call analysis has its own switch ("call_analysis") and needs a transcript.

The global switch (settings.TRANSCRIPTION_PAUSED) stops every workspace; this stops one, e.g. while it is onboarding
and should not spend on speech-to-text and model calls yet. Calls and recordings keep arriving and are stored as
usual; only the AI work waits. Checked where a call is queued for transcription (call_ingest), inside the transcribe
and analysis tasks themselves (so anything already queued stops too), and by the recovery sweeps (which skip a paused
workspace instead of re-queuing it). Resuming: the transcription sweep picks up calls still waiting from the last 2
days (TRANSCRIBE_LOOKBACK). Set with scripts/pause_calls_ai.py (audited). Migration 217 moved the old
brand_config["calls_ai_paused"] flag here.
"""

from __future__ import annotations

FEATURE = "call_transcription"


def is_paused(db, tenant_id: str) -> bool:
    from app.services import ai_features

    return not ai_features.enabled(db, tenant_id, FEATURE)
