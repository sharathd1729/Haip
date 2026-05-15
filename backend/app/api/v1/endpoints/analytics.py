from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone, timedelta
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.call import Call
from app.models.inquiry import Inquiry, InquiryStage
from app.models.conversation import Message
from app.models.score import CallScore
from app.schemas.analytics import OwnerDailyStats, PersonalScorecard, LostReasonTheme
from app.services.lost_reason_service import get_lost_inquiries, cluster_themes
from typing import List

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/owner-daily", response_model=OwnerDailyStats)
def owner_daily(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    today = datetime.now(timezone.utc).date().isoformat()
    tid = current_user.tenant_id

    calls_today = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tid,
        Call.started_at >= today,
    ).scalar() or 0

    open_inquiries = db.query(func.count(Inquiry.id)).filter(
        Inquiry.tenant_id == tid,
        Inquiry.stage.in_([InquiryStage.NEW, InquiryStage.RESPONDING, InquiryStage.QUOTED]),
    ).scalar() or 0

    qa_avg = db.query(func.avg(Call.ai_score)).filter(
        Call.tenant_id == tid, Call.ai_score.isnot(None)
    ).scalar()

    return OwnerDailyStats(
        date=today,
        calls_today=calls_today,
        open_inquiries=open_inquiries,
        qa_avg_score=float(qa_avg) if qa_avg else None,
    )


@router.get("/personal-scorecard", response_model=PersonalScorecard)
def personal_scorecard(
    period: str = Query(default="this_week"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tid = current_user.tenant_id
    uid = current_user.id

    calls_handled = db.query(func.count(Call.id)).filter_by(tenant_id=tid, agent_id=uid).scalar() or 0
    avg_score = db.query(func.avg(Call.ai_score)).filter(
        Call.tenant_id == tid, Call.agent_id == uid, Call.ai_score.isnot(None)
    ).scalar()

    return PersonalScorecard(
        user_id=uid,
        user_name=current_user.name,
        period=period,
        calls_handled=calls_handled,
        avg_qa_score=float(avg_score) if avg_score else None,
    )


@router.get("/lost-reasons", response_model=List[LostReasonTheme])
def lost_reasons(
    days: int = Query(default=90, le=365),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    lost = get_lost_inquiries(db, current_user.tenant_id, days=days)
    themes = cluster_themes(lost)
    return [LostReasonTheme(**t) for t in themes]
