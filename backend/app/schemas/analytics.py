from pydantic import BaseModel
from typing import Optional, List, Any


class OwnerDailyStats(BaseModel):
    date: str
    calls_today: int = 0
    open_inquiries: int = 0
    response_p95_sec: Optional[float] = None
    qa_avg_score: Optional[float] = None
    wa_messages_today: int = 0
    top_objections: List[str] = []
    lost_reason_summary: List[Any] = []
    occupancy_rate: Optional[float] = None


class PersonalScorecard(BaseModel):
    user_id: str
    user_name: str
    period: str   # "this_week" | "last_week" | "this_month"
    calls_handled: int = 0
    avg_qa_score: Optional[float] = None
    conversion_rate: Optional[float] = None
    avg_response_time_sec: Optional[float] = None
    score_trend: List[Any] = []


class LostReasonTheme(BaseModel):
    reason: str
    count: int
    percentage: float
    example_notes: List[str] = []
