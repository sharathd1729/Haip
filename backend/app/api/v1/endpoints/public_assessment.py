"""Property assessment + ROI tool (HAIP's own public website, page /assess).

Public (no login, rate-limited per IP by RateLimitMiddleware tier /api/v1/public/):
  GET  /public/assessment/options                  the answers the active benchmark set knows (labels only)
  POST /public/assessment/estimate                 free summary (headline range), no writes
  GET  /public/assessment/{lead_id}/report?token=  the full report a visitor unlocked (POST /public/leads kind=assessment)
  GET  /public/assessment/{lead_id}/report.pdf?token=

Owner of HAIP's sales workspace only (versioned benchmarks, audited):
  GET  /roi-benchmarks  ·  GET /roi-benchmarks/{version}  ·  POST /roi-benchmarks  ·  POST /roi-benchmarks/{version}/activate
"""
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.v1.endpoints.public_leads import body_size_cap, require_sales_workspace_owner
from app.core.database import get_db
from app.models.platform_lead import PlatformLead
from app.models.user import User
from app.schemas.assessment import AssessmentInput, BenchmarkCreate
from app.services import assessment_benchmarks, assessment_engine, platform_lead_service

log = structlog.get_logger()
router = APIRouter(tags=["assessment"])

_TOKEN = Query(..., min_length=8, max_length=64)


@router.get("/public/assessment/options")
def assessment_options(db: Session = Depends(get_db)):
    b = assessment_benchmarks.active(db)

    def labels(section: str) -> list[dict]:
        return [{"key": k, "label": v["label"]} for k, v in b[section].items()]
    return {
        "benchmark_version": b["version"], "benchmark_label": b["label"], "sample": b["sample"], "region": b["region"],
        "property_types": labels("property_types"), "amenities": labels("amenities"), "experiences": labels("experiences"),
        "seasonality": labels("seasonality"), "landmarks": labels("landmarks"),
        "competitor_density": labels("competitor_density"), "segments": b["segments"],
    }


@router.post("/public/assessment/estimate", dependencies=[Depends(body_size_cap)])
def estimate(body: AssessmentInput, db: Session = Depends(get_db)):
    try:
        result = assessment_engine.project(assessment_benchmarks.active(db), body)
    except assessment_engine.AssessmentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"summary": assessment_engine.summary(result)}


def _lead_for_report(db: Session, lead_id: str, token: str) -> PlatformLead:
    """404 for an unknown id, a wrong token, or a spam row: never says which."""
    if not platform_lead_service.verify_report_token(lead_id, token):
        raise HTTPException(status_code=404, detail="Report not found.")
    lead = db.query(PlatformLead).filter_by(id=lead_id, kind="assessment").first()
    if lead is None or lead.is_spam or not lead.assessment:
        raise HTTPException(status_code=404, detail="Report not found.")
    return lead


@router.get("/public/assessment/{lead_id}/report")
def get_report(lead_id: str, token: str = _TOKEN, db: Session = Depends(get_db)):
    lead = _lead_for_report(db, lead_id, token)
    return {"id": lead.id, "report": lead.assessment["result"], "input": lead.assessment.get("input"),
            "narrative": lead.narrative if lead.narrative_status == "done" else None,
            "narrative_status": lead.narrative_status, "created_at": lead.created_at.isoformat() if lead.created_at else None}


@router.get("/public/assessment/{lead_id}/report.pdf")
def get_report_pdf(lead_id: str, token: str = _TOKEN, db: Session = Depends(get_db)):
    lead = _lead_for_report(db, lead_id, token)
    from app.services import assessment_pdf
    pdf = assessment_pdf.render(lead.assessment["result"],
                                narrative=lead.narrative if lead.narrative_status == "done" else None,
                                prepared_for=lead.company or lead.name)
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": 'attachment; filename="haip-property-assessment.pdf"', "Cache-Control": "private, no-store"})


# ── Benchmarks (HAIP admins = owner of the sales workspace) ──────────────────

@router.get("/roi-benchmarks")
def list_benchmarks(current_user: User = Depends(require_sales_workspace_owner), db: Session = Depends(get_db)):
    return {"items": assessment_benchmarks.list_versions(db), "active": assessment_benchmarks.active(db)["version"]}


@router.get("/roi-benchmarks/{version}")
def get_benchmarks(version: str, current_user: User = Depends(require_sales_workspace_owner), db: Session = Depends(get_db)):
    data = assessment_benchmarks.get_version(db, version)
    if data is None:
        raise HTTPException(status_code=404, detail="Unknown benchmark version.")
    return data


@router.post("/roi-benchmarks", status_code=201)
def create_benchmarks(body: BenchmarkCreate, current_user: User = Depends(require_sales_workspace_owner),
                      db: Session = Depends(get_db)):
    try:
        row = assessment_benchmarks.create_version(db, body.data, notes=body.notes, actor_user_id=current_user.id,
                                                   tenant_id=current_user.tenant_id)
    except assessment_benchmarks.VersionExists as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"version": row.version, "is_active": row.is_active}


@router.post("/roi-benchmarks/{version}/activate")
def activate_benchmarks(version: str, current_user: User = Depends(require_sales_workspace_owner),
                        db: Session = Depends(get_db)):
    try:
        active = assessment_benchmarks.activate(db, version, actor_user_id=current_user.id, tenant_id=current_user.tenant_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Unknown benchmark version.")
    return {"active": active}
