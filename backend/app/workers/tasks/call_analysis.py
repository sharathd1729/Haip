"""tasks.analyze_call: ONE AI read per transcribed call (AI cost audit, 8 Nov 2026), then the after-call effects.

transcribe -> analyze_call. It replaced the classify -> judge -> wrap_up chain (three LLM calls on the full transcript,
plus a deep_reason re-judge on most calls); the read itself is services/call_analysis.py. The old task names
(tasks.classify / tasks.judge / tasks.wrap_up) stay as thin wrappers so messages already queued at deploy still work.

Statuses (calls.ai_score_status): skipped_no_transcript (no Transcript row, or nobody said anything: no model call),
processing (the model is being asked; ai_score_attempts counts starts), done, failed (call_recovery resumes it).
A retry (and a recovery run) re-uses the model's kept answer, so only a model failure asks the model again; the
writes are idempotent (one call_scores row per call per prompt version). The effects below run once, after the
commit, and never trigger a retry.
"""

import json
from datetime import UTC, datetime, timedelta

import structlog
from celery.exceptions import MaxRetriesExceededError

from app.adapters.llm.scope import scoped_task
from app.core.database import SessionLocal, set_tenant_context
from app.core.prompt_versions import stamp
from app.models.call import Call, CallDirection, CallDisposition
from app.models.property import Property
from app.models.transcript import Transcript
from app.models.user import User
from app.services import call_analysis as analysis
from app.workers.celery_app import celery_app

log = structlog.get_logger()

# A guest who asked for a callback is due sooner than call_ingest's outbound-no-answer reminder: higher intent.
_CALLBACK_REQUESTED_WINDOW = timedelta(hours=1)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60, name="tasks.analyze_call")
@scoped_task("calls", ref_type="call", ref_arg="call_id", prompt_key="call_analysis")
def analyze_call(self, call_id: str, tenant_id: str):
    db = SessionLocal()
    try:
        done = _analyse(self, db, call_id, tenant_id)
        if done is not None:
            after_analysis(db, tenant_id, *done)
    finally:
        db.close()


def _analyse(task, db, call_id: str, tenant_id: str):
    """(call, disposition) once the read is stored; None when skipped or failed for good. Raises Retry to retry."""
    call = None
    try:
        set_tenant_context(db, tenant_id)
        call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
        if not call:
            log.error("call_analysis_missing_call", call_id=call_id)
            return None
        transcript = db.query(Transcript).filter_by(call_id=call_id, tenant_id=tenant_id).first()
        turns = json.loads(transcript.turns or "[]") if transcript else []
        if not transcript or not analysis.has_speech(turns):
            # No model call: a score or summary of nothing is noise. Leaving it "pending" made call_recovery re-send
            # it every 30 minutes (Ratha, Oct 2026). A skip is not an attempt.
            call.ai_score_status = "skipped_no_transcript"
            db.commit()
            log.info("call_analysis_skipped_no_transcript", call_id=call_id, has_row=bool(transcript))
            return None

        _clear_unconfirmed_agent(call, turns)
        call.ai_score_status = "processing"
        call.ai_score_attempts = (call.ai_score_attempts or 0) + 1
        db.commit()

        from app.models.guest import Guest
        from app.services.qa_service import ensure_default_rubric

        rubric = ensure_default_rubric(db, tenant_id)
        prop = (
            db.query(Property).filter_by(id=call.property_id, tenant_id=tenant_id).first() if call.property_id else None
        )
        agent = db.query(User).filter_by(id=call.agent_id, tenant_id=tenant_id).first() if call.agent_id else None
        guest = db.query(Guest).filter_by(id=call.guest_id, tenant_id=tenant_id).first() if call.guest_id else None
        system, user = analysis.build_prompts(
            rubric=rubric,
            call=call,
            turns=turns,
            language=transcript.language,
            property_name=prop.name if prop else "(unknown)",
            agent_name=agent.name if agent else "(unknown)",
            guest_name=guest.name if guest and guest.name and guest.name != "Unknown Guest" else None,
        )
        result = analysis.analyse(
            tenant_id=tenant_id, call_id=call_id, system=system, user=user, rubric_criteria=rubric.criteria or []
        )

        disposition = analysis.apply_result(db, call=call, tenant_id=tenant_id, rubric=rubric, result=result)
        call.ai_score_status = "done"
        db.commit()
        log.info(
            "call_analysis_done",
            call_id=call_id,
            score=float(call.ai_score or 0),
            disposition=disposition,
            rechecked=bool(result.get("rechecked")),
            **stamp("call_analysis", model=result.get("model_used")),
        )
        return call, disposition
    except Exception as exc:
        try:
            # Half-written changes (or a failed flush) must not be committed with the "failed" status.
            if db.new or db.dirty or db.deleted or not db.is_active:
                db.rollback()
            if call is not None:
                call.ai_score_status = "failed"
                db.commit()
        except Exception:  # noqa: BLE001
            pass
        log.error("call_analysis_failed", call_id=call_id, error=str(exc)[:300])
        # The model's answer (if it came) is kept, so this retry -- and call_recovery after the retries run out --
        # writes it again without a second model call.
        try:
            raise task.retry(exc=exc)
        except MaxRetriesExceededError:
            log.error("call_analysis_retries_exhausted", call_id=call_id)
        return None


def _clear_unconfirmed_agent(call: Call, turns: list) -> None:
    """An inbound call attributed to an agent by Vobiz's DialStatus "completed" can be nothing but the greeting and
    hold music ("completed" = connected at SIP level). With no agent speech in the diarized transcript the attribution
    is dropped. Outbound click-to-call attribution comes from the agent's own dial and is never touched."""
    if call.agent_id and call.direction == CallDirection.INBOUND:
        if not any(t.get("speaker") == "agent" and (t.get("text") or "").strip() for t in turns):
            log.info("vobiz_dial_attribution_unconfirmed_no_agent_speech", call_id=call.id, agent_id=call.agent_id)
            call.agent_id = None


def after_analysis(db, tenant_id: str, call: Call, disposition: str) -> None:
    """The effects the old classify/wrap_up ran, once per finished analysis. Each is best-effort and logged."""
    call_id = call.id
    if call.ai_disposition == CallDisposition.CALLBACK:
        try:
            _maybe_create_callback_requested_task(db, tenant_id, call)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.warning("callback_requested_task_failed", call_id=call_id, error=str(exc)[:200])

    # Lead workflows: a call that turns out unanswered gets its missed-call / no-answer WhatsApp now if ingest could
    # not tell (the run's unique key makes a second trigger a no-op).
    try:
        from app.services.lead_playbook_engine import playbook_for_call

        if playbook_for_call(call):
            from app.workers.tasks.lead_playbooks import queue_on_call

            queue_on_call(call.tenant_id, call.id, countdown=5, classified_late=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("playbook_requeue_failed", call_id=call_id, error=str(exc)[:200])

    # Lead autopilot: the call is fully analysed (disposition + outcome), so re-read the lead's stage.
    try:
        from app.services import lead_autopilot_service

        lead_autopilot_service.queue_evaluation(
            call.inquiry_id or lead_autopilot_service.open_inquiry_for_guest(db, tenant_id, call.guest_id),
            tenant_id,
            trigger="call",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("call_analysis_autopilot_enqueue_failed", call_id=call_id, error=str(exc)[:200])

    # Leads360: refresh the linked lead's AI summary (no debounce for calls).
    if call.inquiry_id:
        try:
            from app.services.leads_service import trigger_summary_refresh

            trigger_summary_refresh(db=db, inquiry_id=str(call.inquiry_id), tenant_id=tenant_id, source="call")
        except Exception as exc:  # noqa: BLE001
            log.warning("call_analysis_summary_refresh_skipped", call_id=call_id, error=str(exc)[:200])

    _emit_sse(tenant_id=tenant_id, event="call_processed", call_id=call_id)

    try:
        from app.services.push_service import send_to_tenant

        send_to_tenant(
            db=db,
            tenant_id=tenant_id,
            title="Call summary ready",
            body=call.ai_summary[:80] if call.ai_summary else "AI wrap-up complete.",
            url=f"/dashboard/calls/{call_id}",
            tag="haip-call",
            user_id=call.agent_id or None,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("push_notify_failed", error=str(exc)[:200])

    try:
        from app.workers.tasks.automation_engine import fire_trigger

        fire_trigger.apply_async(
            kwargs={
                "event": "call_completed",
                "tenant_id": tenant_id,
                "context": {"call_id": call_id, "disposition": disposition},
            },
            queue="whatsapp",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("call_completed_trigger_failed", call_id=call_id, error=str(exc)[:200])


def _maybe_create_callback_requested_task(db, tenant_id: str, call: Call) -> None:
    """A guest who asked to be called back (CallDisposition.CALLBACK) is ANSWERED, so the missed-call queue never sees
    them (Ratha, Sep 2026): turn it into a reminder. One open "Callback requested" task per guest, due in an hour,
    plus a push."""
    from app.models.guest import Guest
    from app.models.task import Task

    if not call.guest_id:
        return
    existing = (
        db.query(Task)
        .filter_by(tenant_id=tenant_id, guest_id=call.guest_id, is_done=False)
        .filter(Task.title.ilike("Callback requested — %"))
        .first()
    )
    if existing:
        return

    guest = db.query(Guest).filter_by(id=call.guest_id, tenant_id=tenant_id).first()
    guest_label = (getattr(guest, "name", None) or "").strip() or "this lead"
    task = Task(
        tenant_id=tenant_id,
        title=f"Callback requested — {guest_label}",
        priority="high",
        guest_id=call.guest_id,
        inquiry_id=call.inquiry_id,
        assigned_to=call.agent_id,
        due_date=datetime.now(UTC) + _CALLBACK_REQUESTED_WINDOW,
    )
    db.add(task)
    db.commit()
    log.info("callback_requested_task_created", tenant_id=tenant_id, call_id=call.id, task_id=task.id)

    try:
        from app.services.push_service import send_to_tenant

        send_to_tenant(
            db,
            tenant_id,
            title="Guest asked for a callback",
            body=f"{guest_label} asked to be called back. A reminder has been added.",
            url=f"/dashboard/calls?call={call.id}",
            user_id=call.agent_id or None,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("callback_requested_task_push_failed", tenant_id=tenant_id, error=str(exc)[:200])


def _emit_sse(tenant_id: str, event: str, call_id: str):
    """Publish to Redis pub/sub so the SSE endpoint forwards it to the browser."""
    try:
        import redis

        from app.core.config import settings

        r = redis.from_url(settings.REDIS_URL)
        r.publish(f"sse:{tenant_id}", json.dumps({"event": event, "call_id": call_id}))
    except Exception as exc:  # noqa: BLE001
        log.warning("sse_publish_failed", error=str(exc)[:200])


# ── Old names: messages queued before the deploy, and old callers ─────────────────────────────────────────────────


@celery_app.task(name="tasks.classify")
def classify(call_id: str, tenant_id: str, **_old_kwargs):
    """Was the first of three LLM calls; now hands over to the single analysis."""
    analyze_call.delay(call_id=call_id, tenant_id=tenant_id)


@celery_app.task(name="tasks.judge")
def judge(call_id: str, tenant_id: str, **_old_kwargs):
    """Was the QA re-judge step; now hands over to the single analysis (kept answer = no second model call)."""
    analyze_call.delay(call_id=call_id, tenant_id=tenant_id)


@celery_app.task(name="tasks.wrap_up")
def wrap_up(call_id: str, tenant_id: str, **_old_kwargs):
    """Was the wrap-up step; now hands over to the single analysis."""
    analyze_call.delay(call_id=call_id, tenant_id=tenant_id)
