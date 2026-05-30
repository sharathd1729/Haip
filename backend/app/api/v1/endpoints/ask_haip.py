"""
Ask HAIP endpoint — POST /analytics/ask

Receives a natural language question from a hospitality operator,
routes it through the intelligence analyst pipeline, and returns
structured findings with evidence, impact, and recommendations.
"""

from __future__ import annotations

from typing import Optional, List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.services.ask_haip_service import ask_haip, run_agents, detect_intent
from app.services.ask_haip_steps import execute_step, execute_all_paths
from app.services.ask_haip_rca import get_finding_history
from app.services.ask_haip_reports import generate_report, save_report, list_reports, REPORT_TYPES
from app.core.cache import cache_key, get_cached, set_cached

router = APIRouter(prefix="/analytics", tags=["ask-haip"])


# ─── Request / Response Schemas ──────────────────────────────────────────────

class AskHaipRequest(BaseModel):
    question: str
    range_days: int = 30
    property_ids: Optional[List[str]] = None
    path: Optional[str] = None  # specific path to run, null = auto


class EvidenceBullet(BaseModel):
    text: str


class ImpactModel(BaseModel):
    revenue_loss: float = 0.0
    currency: str = "INR"
    severity: str = "medium"  # high | medium | low


class RecommendationModel(BaseModel):
    action: str
    expected_impact: str = ""
    module: str = ""
    href: str = ""


class FindingModel(BaseModel):
    title: str
    evidence: List[str] = []
    impact: ImpactModel = ImpactModel()
    root_cause: str = ""
    recommendations: List[RecommendationModel] = []


class PathStep(BaseModel):
    step: int
    label: str
    description: str
    status: str = "pending"
    data: Optional[dict] = None


class InvestigationPath(BaseModel):
    id: str
    name: str
    icon: str = ""
    domains: List[str] = []
    steps: List[PathStep] = []
    snapshot: dict = {}


class AgentKPI(BaseModel):
    label: str
    value: Any
    prev: Optional[Any] = None
    delta_pct: Optional[float] = None
    trend: str = "flat"
    unit: str = ""
    severity: str = "normal"


class AgentOutputModel(BaseModel):
    agent: str
    domain: str
    status: str = "ok"
    kpis: List[AgentKPI] = []
    findings: List[str] = []
    top_concern: Optional[str] = None
    top_positive: Optional[str] = None
    summary: str = ""
    charts: List[dict] = []
    metadata: dict = {}


class SignalModel(BaseModel):
    message: str
    severity: str = "info"    # critical | warning | info | positive
    domains: List[str] = []


class AskHaipResponse(BaseModel):
    session_id: str
    question: str
    intent: dict
    paths: List[InvestigationPath] = []
    correlations: List[str] = []
    structured_signals: List[SignalModel] = []   # Phase 4: severity-tagged
    findings: List[FindingModel] = []
    summary: str = ""
    root_cause_chain: str = ""                   # Phase 4: signal→cause→impact→action
    confidence: float = 0.0
    confidence_label: str = "low"                # Phase 4: high | medium | low
    data_completeness: str = "partial"
    missing_domains: List[str] = []              # Phase 4: domains with no data
    investigation_paths_used: List[str] = []
    compare_mode: bool = False                   # Phase 4: comparative analysis
    agents: dict = {}   # domain → AgentOutputModel


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post("/ask", response_model=AskHaipResponse)
async def ask_haip_endpoint(
    body: AskHaipRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ask HAIP — Hospitality Intelligence Analyst

    Submit any business question in natural language:
    - "Why did revenue drop this month?"
    - "Which properties are underperforming?"
    - "What objections are increasing?"
    - "Which channel converts best?"

    Returns structured findings with evidence, impact (₹), and
    actionable recommendations with module deep-links.
    """
    # Build base URL for internal agent calls
    base_url = str(request.base_url).rstrip("/")
    api_prefix = "/api/v1"
    internal_base = f"{base_url}{api_prefix}"

    # Extract JWT for internal agent calls
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()

    result = await ask_haip(
        question=body.question.strip(),
        tenant_id=current_user.tenant_id,
        user_id=str(current_user.id),
        token=token,
        base_url=internal_base,
        range_days=body.range_days,
        property_ids=body.property_ids,
        db=db,
    )

    return result


# ─── Step Execution Endpoint (Phase 3) ──────────────────────────────────────

class StepRequest(BaseModel):
    session_id: str
    path_id: str          # revenue | inquiry | channel | objection | guest | property | intent | campaign
    step: int             # 1 | 2 | 3
    range_days: int = 30
    property_ids: Optional[List[str]] = None


@router.post("/ask/step")
async def execute_path_step(
    body: StepRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Phase 3: Execute a specific step in an investigation path.

    Returns cumulative step data (steps 1..N for step N).
    Caches raw agent data per session for fast step navigation.
    """
    # Cache key for agent raw data (fetched once per session)
    ck_data = cache_key("ask_step_data", current_user.tenant_id,
                        sid=body.session_id, range_days=body.range_days)

    raw_data = get_cached(ck_data)
    if raw_data is None:
        # Need to re-fetch agent data — requires all domain endpoints
        from app.services.ask_haip_service import DOMAIN_ENDPOINTS
        base_url = str(request.base_url).rstrip("/") + "/api/v1"
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()

        all_domains = list(DOMAIN_ENDPOINTS.keys())
        raw_data, _ = await run_agents(
            domains=all_domains,
            token=token,
            base_url=base_url,
            range_days=body.range_days,
            property_ids=body.property_ids,
        )
        set_cached(ck_data, raw_data, ttl=3600)

    result = await execute_step(
        path_id=body.path_id,
        step=body.step,
        raw_data=raw_data,
    )
    return result


class RunAllRequest(BaseModel):
    session_id: str
    domains: List[str]
    range_days: int = 30
    property_ids: Optional[List[str]] = None


@router.post("/ask/run-all")
async def run_all_paths(
    body: RunAllRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Phase 3: Execute ALL investigation paths to Step 3 in parallel.
    Returns a dict of path_id → cumulative step results.
    """
    ck_data = cache_key("ask_step_data", current_user.tenant_id,
                        sid=body.session_id, range_days=body.range_days)

    raw_data = get_cached(ck_data)
    if raw_data is None:
        base_url = str(request.base_url).rstrip("/") + "/api/v1"
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()

        from app.services.ask_haip_service import DOMAIN_ENDPOINTS
        all_domains = list(DOMAIN_ENDPOINTS.keys())
        raw_data, _ = await run_agents(
            domains=all_domains,
            token=token,
            base_url=base_url,
            range_days=body.range_days,
            property_ids=body.property_ids,
        )
        set_cached(ck_data, raw_data, ttl=3600)

    results = await execute_all_paths(raw_data, body.domains)
    return {"paths": results, "domains_run": list(results.keys())}


# ─── Findings History Endpoint (Phase 4) ────────────────────────────────────

@router.get("/ask/history")
# ─── Report Endpoints (Phase 5) ─────────────────────────────────────────────
def ask_history(
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Phase 4: Return recent Ask HAIP findings for this tenant.
    Used to populate the history panel in the frontend.
    """
    return {
        "history": get_finding_history(
            db=db,
            tenant_id=current_user.tenant_id,
            limit=min(limit, 50),
        )
    }


# ─── Report Endpoints (Phase 5) ──────────────────────────────────────────────

class GenerateReportRequest(BaseModel):
    report_type: str       # executive | weekly | monthly | property | guest | revenue | inquiry
    range_days: int = 30
    property_ids: Optional[List[str]] = None
    send_email: bool = False


@router.post("/reports/generate")
async def generate_report_endpoint(
    body: GenerateReportRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Phase 5: Generate an on-demand report for the current tenant.
    Fetches live analytics data, renders HTML, saves to DB.
    Optionally emails to the requesting user.
    """
    if body.report_type not in REPORT_TYPES:
        from fastapi import HTTPException
        raise HTTPException(400, f"Invalid report_type. Valid: {REPORT_TYPES}")

    # Fetch analytics data (reuse step data cache or fetch fresh)
    ck_data = cache_key("ask_step_data", current_user.tenant_id,
                        sid="report", range_days=body.range_days)
    raw_data = get_cached(ck_data)

    if raw_data is None:
        base_url = str(request.base_url).rstrip("/") + "/api/v1"
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()

        from app.services.ask_haip_service import DOMAIN_ENDPOINTS
        all_domains = list(DOMAIN_ENDPOINTS.keys())
        raw_data, _ = await run_agents(
            domains=all_domains,
            token=token,
            base_url=base_url,
            range_days=body.range_days,
            property_ids=body.property_ids,
        )
        set_cached(ck_data, raw_data, ttl=3600)

    result = await generate_report(
        report_type=body.report_type,
        raw_data=raw_data,
        range_days=body.range_days,
    )

    # Save to DB
    report = save_report(
        db=db,
        tenant_id=current_user.tenant_id,
        report_type=body.report_type,
        title=result["title"],
        html=result["html"],
        range_days=body.range_days,
    )

    # Optional email
    if body.send_email and current_user.email:
        from app.services.ask_haip_reports import send_report_email
        await send_report_email(
            to_email=current_user.email,
            to_name=getattr(current_user, "full_name", "") or current_user.email,
            report_type=body.report_type,
            title=result["title"],
            html=result["html"],
        )

    return {
        "id": str(report.id),
        "title": result["title"],
        "report_type": body.report_type,
        "html": result["html"],   # frontend renders this in an iframe
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/reports")
def list_reports_endpoint(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 5: List recent reports for this tenant."""
    return {"reports": list_reports(db, current_user.tenant_id, limit=min(limit, 50))}


@router.get("/reports/{report_id}/html")
def get_report_html(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 5: Get the full HTML content of a specific report."""
    from fastapi import HTTPException
    from fastapi.responses import HTMLResponse
    from app.models.ask_haip import AskHaipReport

    report = db.query(AskHaipReport).filter(
        AskHaipReport.id == report_id,
        AskHaipReport.tenant_id == current_user.tenant_id,
    ).first()

    if not report:
        raise HTTPException(404, "Report not found")

    return HTMLResponse(content=report.html_content or "<p>No content</p>")
