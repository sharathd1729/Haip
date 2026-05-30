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


# ── Executive Dashboard ───────────────────────────────────────────────────────

class RevenueChartPoint(BaseModel):
    date: str           # YYYY-MM-DD
    confirmed: float = 0.0   # revenue from confirmed+checked_in stays
    quoted: float = 0.0      # revenue from quoted stays/inquiries


class FunnelStage(BaseModel):
    stage: str          # NEW | RESPONDING | QUOTED | SITE_VISIT | BOOKED | LOST | GHOSTED
    count: int
    pct: float = 0.0    # % of total inquiries this period


class ChannelMixPoint(BaseModel):
    source: str         # WHATSAPP | WEBSITE | GOOGLE | etc.
    count: int
    pct: float = 0.0


class OccupancyHeatPoint(BaseModel):
    property_id: str
    property_name: str
    pct: float          # 0–100


class ExecutiveDashboardStats(BaseModel):
    # 6 KPI cards
    revenue_mtd: float = 0.0
    revenue_mtd_prev: float = 0.0
    occupancy_pct: float = 0.0
    occupancy_prev: float = 0.0
    active_inquiries: int = 0
    active_inquiries_prev: int = 0
    qa_avg_score: float = 0.0
    qa_prev: float = 0.0
    sla_compliance_pct: float = 0.0
    sla_prev: float = 0.0
    ai_draft_rate_pct: float = 0.0
    ai_draft_prev: float = 0.0
    # Chart datasets
    revenue_chart: List[RevenueChartPoint] = []
    funnel: List[FunnelStage] = []
    channel_mix: List[ChannelMixPoint] = []
    occupancy_heatmap: List[OccupancyHeatPoint] = []


# ── Insights Panel ────────────────────────────────────────────────────────────

class InsightItem(BaseModel):
    id: str
    category_code: str      # "A1", "B2", etc.
    category: str           # "urgency" | "occupancy" | "revenue" | "quality"
    severity: str           # "critical" | "high" | "medium" | "low" | "info"
    title: str
    body: Optional[str] = None
    cta_label: Optional[str] = None
    cta_href: Optional[str] = None
    detected_at: str        # ISO datetime


class InsightList(BaseModel):
    items: List[InsightItem] = []
    total: int = 0
