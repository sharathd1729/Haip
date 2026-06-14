"""
Ask HAIP endpoint — POST /analytics/ask

Receives a natural language question from a hospitality operator,
routes it through the intelligence analyst pipeline, and returns
structured findings with evidence, impact, and recommendations.
"""

from __future__ import annotations

from typing import Any, Optional, List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_module, get_workspace_context
from app.models.user import User
from fastapi.responses import StreamingResponse
from app.services.ask_haip_service import ask_haip, run_agents, detect_intent
from app.services.ask_haip_steps import execute_step, execute_all_paths
from app.services.ask_haip_rca import get_finding_history, build_correlations, calculate_confidence, run_enhanced_rca
from app.services.ask_haip_reports import generate_report, save_report, list_reports, REPORT_TYPES
from app.services.ask_haip_memory import (
    load_memory, save_memory, update_memory,
    resolve_context, build_context_note, generate_suggestions,
)
from app.services.ask_haip_agents import process_agents
from app.core.cache import cache_key, get_cached, set_cached

router = APIRouter(prefix="/analytics", tags=["ask-haip"])


# ─── Request / Response Schemas ──────────────────────────────────────────────

class AskHaipRequest(BaseModel):
    question: str
    range_days: int = 30
    property_ids: Optional[List[str]] = None
    path: Optional[str] = None
    session_id: Optional[str] = None    # Phase 6: pass for conversation memory


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
    compare_mode: bool = False
    agents: dict = {}
    suggestions: List[dict] = []         # Phase 6: proactive follow-up questions
    context_note: str = ""               # Phase 6: memory context injected


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post("/ask", response_model=AskHaipResponse)
async def ask_haip_endpoint(
    body: AskHaipRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("ask_haip")),
    workspace_ctx=Depends(get_workspace_context),
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

    question = body.question.strip()

    # Phase 6: Load conversation memory
    mem_session_id = body.session_id or str(current_user.id)
    memory = load_memory(current_user.tenant_id, mem_session_id)
    ctx    = resolve_context(question, memory)

    # Apply memory context to request params
    effective_range_days   = ctx.get("range_days", body.range_days)
    effective_property_ids = body.property_ids   # explicit wins over memory

    from app.services.workspace_context import available_metrics_for_context
    available_metrics = available_metrics_for_context(db, workspace_ctx)

    result = await ask_haip(
        question=question,
        tenant_id=current_user.tenant_id,
        user_id=str(current_user.id),
        token=token,
        base_url=internal_base,
        range_days=effective_range_days,
        property_ids=effective_property_ids,
        db=db,
        active_modules=workspace_ctx.active_modules,
        available_metrics=available_metrics,
    )

    # Phase 6: Update memory + generate suggestions
    memory  = update_memory(memory, question, result)
    save_memory(current_user.tenant_id, mem_session_id, memory)
    suggestions = generate_suggestions(result, memory)

    result["suggestions"]  = suggestions
    result["context_note"] = build_context_note(memory, question)

    return result


# ─── Phase 6: SSE Streaming Endpoint ────────────────────────────────────────

class StreamRequest(BaseModel):
    question: str
    range_days: int = 30
    property_ids: Optional[List[str]] = None
    session_id: Optional[str] = None


@router.post("/ask/stream")
async def ask_haip_stream(
    body: StreamRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Phase 6: SSE streaming version of /analytics/ask.
    Streams pipeline events as they complete so the UI updates progressively.

    Events: intent_detected → agents_running → paths_ready → signals_found
            → rca_complete → suggestions_ready → done
    """
    import json as _json

    base_url   = str(request.base_url).rstrip("/") + "/api/v1"
    auth_header= request.headers.get("Authorization", "")
    token      = auth_header.replace("Bearer ", "").strip()
    question   = body.question.strip()
    tid        = current_user.tenant_id

    # Load memory
    mem_sid = body.session_id or str(current_user.id)
    memory  = load_memory(tid, mem_sid)
    ctx     = resolve_context(question, memory)
    range_days = ctx.get("range_days", body.range_days)

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {_json.dumps(data)}\n\n"

    async def stream_generator():
        try:
            yield _sse("connected", {"status": "starting"})

            # 1. Intent detection
            from app.services.ask_haip_service import detect_intent, DOMAIN_ENDPOINTS
            intent = await detect_intent(question)
            yield _sse("intent_detected", {
                "domains": intent.get("domains", []),
                "type": intent.get("type", "diagnostic"),
                "compare_mode": ctx.get("compare_mode", False),
            })

            # 2. Agents running
            domains = intent.get("domains", [])
            yield _sse("agents_running", {"domains": domains, "count": len(domains)})

            raw_data, agent_outputs = await run_agents(
                domains=domains,
                token=token,
                base_url=base_url,
                range_days=range_days,
                property_ids=body.property_ids,
            )

            # Cache for step execution
            ck = cache_key("ask_step_data", tid, sid=mem_sid, range_days=range_days)
            set_cached(ck, raw_data, ttl=3600)

            yield _sse("agents_complete", {
                "agents": {d: {"status": v.get("status","ok"), "summary": v.get("summary","")}
                           for d, v in agent_outputs.items()}
            })

            # 3. Paths
            from app.services.ask_haip_service import generate_paths
            paths = generate_paths(domains, raw_data)
            yield _sse("paths_ready", {"paths": paths})

            # 4. Correlations + confidence
            signals    = build_correlations(domains, raw_data, agent_outputs)
            confidence = calculate_confidence(domains, agent_outputs,
                                              [s["message"] for s in signals])
            yield _sse("signals_found", {
                "structured_signals": signals,
                "correlations": [s["message"] for s in signals],
                "confidence": confidence.score,
                "confidence_label": confidence.label,
            })

            # 5. RCA
            from app.services.ask_haip_rca import is_comparative_question
            rca = await run_enhanced_rca(
                question=question, intent=intent,
                raw_data=raw_data, agent_outputs=agent_outputs,
                structured_correlations=signals, confidence=confidence,
                range_days=range_days,
                compare_mode=is_comparative_question(question),
            )
            yield _sse("rca_complete", {
                "findings": rca.get("findings", []),
                "summary":  rca.get("summary", ""),
                "root_cause_chain": rca.get("root_cause_chain", ""),
            })

            # 6. Suggestions
            result_stub = {"intent": intent, "structured_signals": signals,
                           "investigation_paths_used": domains,
                           "findings": rca.get("findings", []),
                           "summary": rca.get("summary", "")}
            suggestions = generate_suggestions(result_stub, memory)

            # Update memory
            memory_updated = update_memory(memory, question, result_stub)
            save_memory(tid, mem_sid, memory_updated)

            yield _sse("suggestions_ready", {"suggestions": suggestions})
            yield _sse("done", {"status": "complete"})

        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).error("SSE stream error: %s", e)
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Phase 6: Alert Management Endpoints ────────────────────────────────────

class CreateAlertRequest(BaseModel):
    name: str
    metric: str        # revenue_mtd | occupancy_pct | high_risk_count | ...
    operator: str      # lt | gt | lte | gte
    threshold: float
    notify_email: bool = True


@router.post("/ask/alerts")
def create_alert(
    body: CreateAlertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 6: Create a threshold monitoring alert."""
    from app.models.ask_haip_alert import AskHaipAlert
    from app.models.base import gen_uuid

    valid_metrics   = ["revenue_mtd","occupancy_pct","high_risk_count","budget_objection_pct","sla_compliance_pct","active_inquiries"]
    valid_operators = ["lt","gt","lte","gte"]

    if body.metric not in valid_metrics:
        from fastapi import HTTPException
        raise HTTPException(400, f"Invalid metric. Valid: {valid_metrics}")
    if body.operator not in valid_operators:
        from fastapi import HTTPException
        raise HTTPException(400, f"Invalid operator. Valid: {valid_operators}")

    alert = AskHaipAlert(
        id=gen_uuid(),
        tenant_id=current_user.tenant_id,
        user_id=str(current_user.id),
        name=body.name,
        metric=body.metric,
        operator=body.operator,
        threshold=body.threshold,
        notify_email=body.notify_email,
        is_active=True,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return {"id": str(alert.id), "name": alert.name, "status": "created"}


@router.get("/ask/alerts")
def list_alerts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 6: List all alerts for this tenant."""
    from app.models.ask_haip_alert import AskHaipAlert

    rows = db.query(AskHaipAlert).filter(
        AskHaipAlert.tenant_id == current_user.tenant_id
    ).order_by(AskHaipAlert.created_at.desc()).all()

    return {"alerts": [
        {
            "id": str(r.id),
            "name": r.name,
            "metric": r.metric,
            "operator": r.operator,
            "threshold": float(r.threshold),
            "is_active": r.is_active,
            "trigger_count": r.trigger_count or 0,
            "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]}


@router.delete("/ask/alerts/{alert_id}")
def delete_alert(
    alert_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 6: Deactivate an alert."""
    from app.models.ask_haip_alert import AskHaipAlert
    from fastapi import HTTPException

    alert = db.query(AskHaipAlert).filter(
        AskHaipAlert.id == alert_id,
        AskHaipAlert.tenant_id == current_user.tenant_id,
    ).first()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.is_active = False
    db.commit()
    return {"status": "deactivated"}


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
