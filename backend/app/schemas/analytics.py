from pydantic import BaseModel
from typing import Optional, List, Any, Dict


class Objection(BaseModel):
    text: str
    count: int


class LostReasonThemeItem(BaseModel):
    theme: str
    count: int
    root_cause: Optional[str] = None


class CallsWeekPoint(BaseModel):
    date: str
    count: int
    avg_score: float = 0.0


class KPIDelta(BaseModel):
    pct: float          # +12.5 / -8.3
    direction: str      # "up" | "down" | "neutral"


class OwnerDailyStats(BaseModel):
    date: str
    # primary KPIs
    today_queue: int = 0
    calls_today: int = 0
    p95_response_time_seconds: float = 0.0
    qa_avg_score: float = 0.0
    occupancy_rate: Optional[float] = None
    revenue_at_risk: Optional[float] = None
    # series
    calls_week: List[CallsWeekPoint] = []
    top_objections: List[Objection] = []
    lost_reason_themes: List[LostReasonThemeItem] = []
    # comparison deltas (present when compare_to != "none")
    deltas: Optional[Dict[str, KPIDelta]] = None
    # previous period series (present when compare_to != "none")
    calls_week_prev: Optional[List[CallsWeekPoint]] = None


class PersonalScorecard(BaseModel):
    user_id: str
    user_name: str
    period: str   # "this_week" | "last_week" | "this_month"
    calls_handled: int = 0
    avg_qa_score: Optional[float] = None
    conversion_rate: Optional[float] = None
    avg_response_time_sec: Optional[float] = None
    score_trend: List[Any] = []


# Legacy alias kept for backward compat
class LostReasonTheme(BaseModel):
    reason: str
    count: int
    percentage: float
    example_notes: List[str] = []


# ── Drill-down ────────────────────────────────────────────────────────────────

class DrillDownPoint(BaseModel):
    label: str
    value: float
    count: int = 0


class MetricDrillDown(BaseModel):
    metric_key: str
    metric_label: str
    unit: str = ""           # "s" | "%" | "" | "₹"
    by_property: List[DrillDownPoint] = []
    by_agent: List[DrillDownPoint] = []
    by_hour: List[DrillDownPoint] = []
    by_channel: List[DrillDownPoint] = []


# ── Lost-reason inquiry list ──────────────────────────────────────────────────

class LostInquiryRow(BaseModel):
    id: str
    guest_name: Optional[str] = None
    guest_phone: str
    property_name: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    lost_reason: Optional[str] = None
    last_contact: Optional[str] = None
    created_at: str


class LostInquiryPage(BaseModel):
    theme: str
    total: int
    page: int
    per_page: int
    items: List[LostInquiryRow] = []
