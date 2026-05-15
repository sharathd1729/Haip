"""Attribution service — stub for Phase 2 ROAS tracking."""
from sqlalchemy.orm import Session


def get_channel_attribution(db: Session, tenant_id: str, days: int = 30) -> dict:
    """Phase 2: compute ROAS by source channel. Returns empty structure for now."""
    return {
        "period_days": days,
        "channels": [],
        "note": "Attribution reporting available in Phase 2",
    }
