"""Append-only usage metering (models/usage_event.py). Recording must never break the work it measures."""
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.usage_event import UsageEvent

log = structlog.get_logger()


def record(
    db: Session, tenant_id: str, *, module: str, kind: str, units: int = 0,
    provider: Optional[str] = None, model: Optional[str] = None,
    input_units: Optional[int] = None, output_units: Optional[int] = None,
    ref_type: Optional[str] = None, ref_id: Optional[str] = None, meta: Optional[dict] = None,
) -> Optional[UsageEvent]:
    """Add a usage row to the session (caller commits). Returns None instead of raising on bad input."""
    try:
        ev = UsageEvent(
            tenant_id=tenant_id, module=module, kind=kind, units=max(int(units or 0), 0),
            provider=provider, model=model, input_units=input_units, output_units=output_units,
            ref_type=ref_type, ref_id=ref_id, meta=meta,
        )
        db.add(ev)
        return ev
    except Exception as exc:  # noqa: BLE001 -- metering is best-effort by design
        log.warning("usage_record_failed", tenant_id=tenant_id, module=module, kind=kind, error=str(exc))
        return None


def record_llm(db: Session, tenant_id: str, module: str, raw: dict, *, provider: Optional[str], ref_type: str, ref_id: str) -> None:
    """Meter one LLM response dict (adapters return input_tokens / output_tokens / model when the provider reports them)."""
    inp = raw.get("input_tokens") or 0
    out = raw.get("output_tokens") or 0
    total = raw.get("tokens_used") or (inp + out)
    record(db, tenant_id, module=module, kind="llm_tokens", units=total, provider=provider, model=raw.get("model"),
           input_units=inp or None, output_units=out or None, ref_type=ref_type, ref_id=ref_id)
