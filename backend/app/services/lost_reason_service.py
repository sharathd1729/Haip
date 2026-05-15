"""Weekly lost-reason clustering — groups free-text notes into themes."""
from typing import List
from sqlalchemy.orm import Session
from app.models.inquiry import Inquiry, InquiryStage
import structlog

log = structlog.get_logger()


def get_lost_inquiries(db: Session, tenant_id: str, days: int = 90) -> List[dict]:
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = (
        db.query(Inquiry)
        .filter_by(tenant_id=tenant_id, stage=InquiryStage.LOST)
        .filter(Inquiry.updated_at >= since)
        .all()
    )
    return [
        {"id": r.id, "reason": r.lost_reason, "note": r.lost_note}
        for r in rows if r.lost_reason
    ]


def cluster_themes(lost_inquiries: List[dict]) -> List[dict]:
    """
    Simple frequency count for known reason taxonomy.
    Phase 2+: replace with Claude embedding clustering.
    """
    from collections import Counter
    counts = Counter(r["reason"] for r in lost_inquiries if r["reason"])
    total = len(lost_inquiries) or 1
    return [
        {
            "reason": reason,
            "count": count,
            "percentage": round(count / total * 100, 1),
            "example_notes": [
                r["note"] for r in lost_inquiries
                if r["reason"] == reason and r["note"]
            ][:3],
        }
        for reason, count in counts.most_common(10)
    ]
