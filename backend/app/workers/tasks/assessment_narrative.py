"""Property assessment write-up (assessment_narrative service).

  assessment.narrative   one LLM call via the router ("assessment_narrative"); the reply is kept only if every number
                         in it is one the engine computed. Not retried: a failed write-up is simply not shown.
"""
from app.core.database import SessionLocal
from app.workers.celery_app import celery_app


@celery_app.task(name="assessment.narrative")
def write_narrative(lead_id: str):
    from app.services import assessment_narrative
    db = SessionLocal()
    try:
        return assessment_narrative.write(db, lead_id)
    finally:
        db.close()
