"""
Weekly lost-reason clustering task — runs every Sunday at 23:00 IST.
"""
import asyncio
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.services.lost_reason_service import get_lost_inquiries, cluster_themes
from app.adapters.llm import get_llm_adapter


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)
import structlog

log = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))

CLUSTER_TOOL = {
    "name": "cluster_lost_reasons",
    "description": "Return clustered lost-reason themes",
    "input_schema": {
        "type": "object",
        "properties": {
            "themes": {"type": "array"},
            "executive_summary": {"type": "string"},
        },
        "required": ["themes", "executive_summary"],
    },
}


@celery_app.task(name="tasks.lost_reason_cluster")
def lost_reason_cluster():
    """Process all active tenants and cluster their lost inquiry reasons."""
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).filter_by(is_active=True).all()
        for tenant in tenants:
            _process_tenant(db, tenant.id)
    finally:
        db.close()


def _process_tenant(db, tenant_id: str):
    lost = get_lost_inquiries(db, tenant_id=tenant_id, days=90)
    if len(lost) < 3:
        return  # Not enough data

    themes = cluster_themes(lost)
    log.info("lost_reason_cluster_done", tenant_id=tenant_id, themes=len(themes), lost_count=len(lost))

    # Store summary in tenant config for dashboard display
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    if tenant:
        config = tenant.brand_config or {}
        config["lost_reason_themes"] = themes
        tenant.brand_config = config
        db.commit()
