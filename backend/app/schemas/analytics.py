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


# ── Phase 2: Section Schemas ──────────────────────────────────────────────────

# -- Guest Analytics --

class LTVBucket(BaseModel):
    bucket: str          # "<10k" | "10-50k" | "50-200k" | ">200k"
    count: int

class VIPTierRow(BaseModel):
    tier: Optional[str]  # "platinum" | "gold" | "silver" | None
    count: int
    avg_ltv: float = 0.0

class TopCityRow(BaseModel):
    city: str
    count: int
    pct: float = 0.0

class AcquisitionPoint(BaseModel):
    date: str
    new_guests: int

class GuestAnalyticsStats(BaseModel):
    total_guests: int = 0
    total_guests_prev: int = 0
    new_guests: int = 0
    new_guests_prev: int = 0
    repeat_guests_pct: float = 0.0
    repeat_guests_pct_prev: float = 0.0
    avg_ltv: float = 0.0
    avg_ltv_prev: float = 0.0
    avg_stays: float = 0.0
    ltv_distribution: List[LTVBucket] = []
    vip_breakdown: List[VIPTierRow] = []
    top_cities: List[TopCityRow] = []
    acquisition_trend: List[AcquisitionPoint] = []


# -- Channel Analytics --

class ChannelBreakdownRow(BaseModel):
    channel: str
    messages: int = 0
    delivered_pct: float = 0.0
    read_pct: float = 0.0
    ai_gen_pct: float = 0.0

class ResponseTimeRow(BaseModel):
    channel: str
    median_s: float = 0.0
    p95_s: float = 0.0

class AttributionFunnelRow(BaseModel):
    source: str
    inquiries: int = 0
    converted: int = 0
    conversion_pct: float = 0.0

class VolumeTrendPoint(BaseModel):
    date: str
    whatsapp: int = 0
    instagram: int = 0
    voice: int = 0
    webchat: int = 0

class ChannelAnalyticsStats(BaseModel):
    total_messages: int = 0
    total_messages_prev: int = 0
    delivery_rate_pct: float = 0.0
    delivery_rate_prev: float = 0.0
    read_rate_pct: float = 0.0
    read_rate_prev: float = 0.0
    avg_response_time_s: float = 0.0
    avg_response_time_prev: float = 0.0
    ai_acceptance_pct: float = 0.0
    ai_acceptance_prev: float = 0.0
    channel_breakdown: List[ChannelBreakdownRow] = []
    response_time_by_channel: List[ResponseTimeRow] = []
    attribution_funnel: List[AttributionFunnelRow] = []
    volume_trend: List[VolumeTrendPoint] = []


# -- Campaign Analytics --

class CampaignRow(BaseModel):
    id: str
    name: str
    status: str
    sent: int = 0
    delivered: int = 0
    read: int = 0
    failed: int = 0
    delivery_rate: float = 0.0
    read_rate: float = 0.0
    scheduled_at: Optional[str] = None

class TemplatePerformanceRow(BaseModel):
    name: str
    category: str
    status: str
    times_used: int = 0
    avg_delivery_rate: float = 0.0
    avg_read_rate: float = 0.0

class SubscriberTrendPoint(BaseModel):
    date: str
    opted_in: int = 0
    opted_out: int = 0
    cumulative: int = 0

class CampaignAnalyticsStats(BaseModel):
    total_campaigns: int = 0
    active_campaigns: int = 0
    avg_delivery_rate_pct: float = 0.0
    avg_read_rate_pct: float = 0.0
    subscriber_count: int = 0
    subscriber_count_prev: int = 0
    campaigns: List[CampaignRow] = []
    template_performance: List[TemplatePerformanceRow] = []
    subscriber_trend: List[SubscriberTrendPoint] = []


# -- Property Analytics --

class PropertyMatrixRow(BaseModel):
    id: str
    name: str
    type: str
    city: Optional[str] = None
    occupancy_pct: float = 0.0
    revenue_mtd: float = 0.0
    adr: float = 0.0          # avg daily rate
    revpar: float = 0.0       # revenue per available room-night
    total_stays: int = 0
    direct_pct: float = 0.0
    ota_pct: float = 0.0

class PropertyAnalyticsStats(BaseModel):
    total_properties: int = 0
    portfolio_occupancy: float = 0.0
    portfolio_occupancy_prev: float = 0.0
    portfolio_revenue_mtd: float = 0.0
    portfolio_revenue_prev: float = 0.0
    portfolio_adr: float = 0.0
    properties: List[PropertyMatrixRow] = []


# -- Operations Analytics --

class AgentLeaderboardRow(BaseModel):
    id: str
    name: str
    role: str
    calls_handled: int = 0
    avg_qa_score: float = 0.0
    inquiries_handled: int = 0
    sla_compliance_pct: float = 0.0
    avg_response_time_s: float = 0.0
    last_seen_at: Optional[str] = None

class SLATrendPoint(BaseModel):
    date: str
    compliant: int = 0
    breached: int = 0
    compliance_pct: float = 0.0

class IntegrationHealthRow(BaseModel):
    kind: str
    status: str
    last_health_at: Optional[str] = None
    is_healthy: bool = False

class OperationsAnalyticsStats(BaseModel):
    team_size: int = 0
    calls_today: int = 0
    sla_compliance_pct: float = 0.0
    sla_compliance_prev: float = 0.0
    open_conversations: int = 0
    avg_response_time_s: float = 0.0
    avg_response_time_prev: float = 0.0
    agents: List[AgentLeaderboardRow] = []
    sla_trend: List[SLATrendPoint] = []
    integrations: List[IntegrationHealthRow] = []


# -- AI Intelligence Analytics --

class AIAcceptanceTrendPoint(BaseModel):
    date: str
    approved: int = 0
    rejected: int = 0
    edited: int = 0
    total: int = 0

class AICostTrendPoint(BaseModel):
    date: str
    transcription_usd: float = 0.0
    llm_usd: float = 0.0
    total_usd: float = 0.0

class AIAcceptanceByAgentRow(BaseModel):
    agent_name: str
    drafts: int = 0
    approved: int = 0
    rejected: int = 0
    acceptance_pct: float = 0.0

class AIAnalyticsStats(BaseModel):
    total_ai_drafts: int = 0
    total_ai_drafts_prev: int = 0
    acceptance_rate_pct: float = 0.0
    acceptance_rate_prev: float = 0.0
    rejection_rate_pct: float = 0.0
    edit_rate_pct: float = 0.0
    total_cost_mtd_usd: float = 0.0
    total_cost_prev_usd: float = 0.0
    avg_cost_per_call_usd: float = 0.0
    calls_auto_scored_pct: float = 0.0
    pipeline_pending_transcription: int = 0
    pipeline_pending_scoring: int = 0
    pipeline_done_today: int = 0
    pipeline_failed_today: int = 0
    acceptance_trend: List[AIAcceptanceTrendPoint] = []
    cost_trend: List[AICostTrendPoint] = []
    acceptance_by_agent: List[AIAcceptanceByAgentRow] = []
