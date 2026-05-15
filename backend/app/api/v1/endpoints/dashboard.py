"""Dashboard summary endpoint — real numbers per tenant."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone, timedelta
from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.call import Call, CallDisposition
from app.models.guest import Guest
from app.models.score import CallScore

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = current_user.tenant_id
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # ── Counts ────────────────────────────────────────────────────────────────
    total_calls = db.query(func.count(Call.id)).filter_by(tenant_id=tid).scalar() or 0
    calls_this_week = (
        db.query(func.count(Call.id))
        .filter(Call.tenant_id == tid, Call.created_at >= week_ago)
        .scalar() or 0
    )
    total_guests = db.query(func.count(Guest.id)).filter_by(tenant_id=tid).scalar() or 0

    # ── QA avg ────────────────────────────────────────────────────────────────
    scored_calls = (
        db.query(func.count(Call.id))
        .filter(Call.tenant_id == tid, Call.ai_score_status == "done", Call.ai_score.isnot(None))
        .scalar() or 0
    )
    avg_qa_row = (
        db.query(func.avg(Call.ai_score))
        .filter(Call.tenant_id == tid, Call.ai_score.isnot(None))
        .scalar()
    )
    avg_qa_score = float(avg_qa_row) if avg_qa_row else None

    # ── Recent calls (last 20) ────────────────────────────────────────────────
    recent_raw = (
        db.query(Call)
        .filter_by(tenant_id=tid)
        .order_by(Call.created_at.desc())
        .limit(20)
        .all()
    )

    # Guest name lookup (batch)
    guest_ids = [c.guest_id for c in recent_raw if c.guest_id]
    guests = {g.id: g for g in db.query(Guest).filter(Guest.id.in_(guest_ids)).all()}

    recent_calls = []
    for c in recent_raw:
        g = guests.get(c.guest_id)
        disp = c.human_disposition or c.ai_disposition
        recent_calls.append({
            "id": c.id,
            "guest_phone": c.from_number,
            "guest_name": g.name if g else None,
            "qa_score": float(c.ai_score) if c.ai_score else None,
            "disposition": disp.value if hasattr(disp, "value") else (disp or "pending"),
            "started_at": c.started_at,
            "duration_seconds": c.duration_seconds or 0,
        })

    return {
        "total_calls": total_calls,
        "calls_this_week": calls_this_week,
        "total_guests": total_guests,
        "active_inquiries": 0,        # placeholder — inquiry module M4
        "open_conversations": 0,      # placeholder — inbox module M3
        "scored_calls": scored_calls,
        "avg_qa_score": avg_qa_score,
        "recent_calls": recent_calls,
    }
