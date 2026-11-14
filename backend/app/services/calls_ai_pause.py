"""Pause call transcription + AI analysis for ONE workspace (`tenants.brand_config["calls_ai_paused"] = true`).

The global switch (settings.TRANSCRIPTION_PAUSED) stops every workspace; this stops one, e.g. while it is onboarding
and should not spend on speech-to-text and model calls yet. Calls and recordings keep arriving and are stored as
usual; only the AI work waits. Checked where a call is queued for transcription (call_ingest), inside the transcribe
and analysis tasks themselves (so anything already queued stops too), and by the recovery sweeps (which skip a paused
workspace instead of re-queuing it). Resuming: the transcription sweep picks up calls still waiting from the last 2
days (TRANSCRIBE_LOOKBACK). Set with scripts/pause_calls_ai.py (audited).
"""

from __future__ import annotations

KEY = "calls_ai_paused"


def is_paused(db, tenant_id: str) -> bool:
    from app.models.tenant import Tenant

    t = db.query(Tenant).filter_by(id=tenant_id).first()
    return bool(t and (t.brand_config or {}).get(KEY))
