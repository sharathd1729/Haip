"""Brand review of a draft (agency M1): the gate between the copywriter and the approval inbox.

  * Deterministic checks (marketing_lint) against the same facts the copywriter was given. Only these can be `high`,
    and a high finding blocks the AGENCY from sending the draft for approval (a person can still send it; the approver
    sees every finding next to the preview). For a version a person wrote, an unknown number is advice, not a block.
  * The AI brand editor (task `marketing_review`, prompt marketing-review-v2) adds advice only: voice, unsupported
    claims, clarity, the ask. Its findings are capped at medium. It never runs in a request handler.
  * The same call is the critic (agency M3): 1-5 scores on hook, specificity, voice, clarity and the ask. Below the bar
    (`weak_points`) the agency rewrites the draft once; the scores never block a person.
One row per (content item, text hash): a version that changes only photos or the look keeps its review.
"""
import hashlib
from typing import Optional

import structlog
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.prompt_versions import get_version
from app.models.marketing import MarketingCompetitor, MarketingContent, MarketingReview
from app.models.tenant import Tenant
from app.schemas.marketing import AIBrandReview, ReviewFinding, text_of
from app.services import marketing_ai_service as ai
from app.services import marketing_content_service as content_svc
from app.services import marketing_context, marketing_lint
from app.services import marketing_prompts as prompts
from app.services import usage_service

log = structlog.get_logger()


def text_sha(payload: dict) -> str:
    return hashlib.sha256(text_of(payload or {}).encode("utf-8")).hexdigest()


def facts_text(db: Session, tenant: Tenant, item: MarketingContent) -> str:
    """Everything the copywriter was shown, flattened: what a number in the draft may come from."""
    return f"{ai._facts(db, tenant, item.property_id)}\n{marketing_context.build(db, tenant.id, item)}\n{item.title}"


def competitor_names(db: Session, tenant_id: str) -> list[str]:
    rows = db.query(MarketingCompetitor.handle, MarketingCompetitor.display_name).filter_by(tenant_id=tenant_id).all()
    return [x for row in rows for x in row if x]


def deterministic(db: Session, tenant: Tenant, item: MarketingContent, payload: dict, *, origin: str) -> list[dict]:
    return marketing_lint.check(item.kind, payload, facts_text=facts_text(db, tenant, item),
                                competitors=competitor_names(db, tenant.id), strict_numbers=origin == "ai")


def current(db: Session, tenant: Tenant, item: MarketingContent) -> Optional[MarketingReview]:
    """The stored review for the current version's text, refreshed with today's deterministic findings."""
    version = content_svc.get_version(db, tenant.id, item.current_version_id)
    if version is None:
        return None
    sha = text_sha(version.payload)
    row = db.query(MarketingReview).filter_by(tenant_id=tenant.id, content_id=item.id, text_sha=sha).first()
    findings = deterministic(db, tenant, item, version.payload, origin=version.origin)
    if row is None:
        row = MarketingReview(tenant_id=tenant.id, content_id=item.id, version_id=version.id, text_sha=sha,
                              findings=findings, blocking=marketing_lint.blocking(findings), ai_status="skipped")
        db.add(row)
    else:
        row.findings, row.blocking = findings, marketing_lint.blocking(findings)
    db.flush()
    return row


SCORE_BAR = 3.5        # the average a draft needs
SCORE_FLOOR = 2        # any single mark at or below this fails the draft


def weak_points(scores: Optional[dict]) -> list[str]:
    """The marks to fix when a draft is below the bar ([] when it passes, or when there are no scores)."""
    if not isinstance(scores, dict) or not scores:
        return []
    marks = {k: v for k, v in scores.items() if isinstance(v, int)}
    if not marks or (sum(marks.values()) / len(marks) >= SCORE_BAR and min(marks.values()) > SCORE_FLOOR):
        return []
    return sorted((k for k, v in marks.items() if v <= 3), key=lambda k: marks[k])


def _labelled(kind: str, payload: dict) -> str:
    return "\n".join(f"[{where}] {text}" for where, text in marketing_lint.segments(kind, payload))


def run_ai(db: Session, tenant: Tenant, item_id: str) -> Optional[MarketingReview]:
    """Deterministic findings + the AI editor's advice for the current text. Celery / agency step only.
    A transient provider error raises ai.LLMTransientError; anything else is recorded on the row."""
    item = content_svc.get_item(db, tenant.id, item_id)
    row = current(db, tenant, item)
    if row is None:
        return None
    version = content_svc.get_version(db, tenant.id, item.current_version_id)
    profile = ai.get_profile(tenant)
    labels = [w for w, _ in marketing_lint.segments(item.kind, version.payload)]
    user = (f"Brand voice: {profile.get('voice') or '(not set: judge against the overall tone)'}\n"
            f"Overall tone: {profile.get('tone') or '(not set)'}\n"
            f"Instagram tone: {(profile.get('channel_tone') or {}).get('instagram') or '(not set)'}\n"
            f"Avoid: {profile.get('avoid') or []}\n\nBusiness facts:\n{ai._facts(db, tenant, item.property_id)}\n\n"
            f"Labels: {labels}\nDraft ({item.kind}):\n{_labelled(item.kind, version.payload)}")
    row.prompt_version = get_version("marketing_review")
    try:
        data, raw, provider = ai._call("marketing_review", tenant.id, ai._system(prompts.REVIEW_SYSTEM, tenant), user,
                                       prompts.REVIEW_TOOL)
        usage_service.record_llm(db, tenant.id, ai.MODULE, raw, provider=provider, ref_type="marketing_review", ref_id=row.id)
        review = AIBrandReview.model_validate(data)
        advice = []
        for f in review.findings:
            where = f.where if f.where in labels else (labels[0] if labels else "draft")
            advice.append(ReviewFinding(rule="editor", severity=f.severity, where=where, message=f.issue,
                                        quote=f.quote, suggestion=f.suggestion).model_dump())
        row.advice, row.summary, row.model, row.ai_status, row.ai_error = advice, review.summary, raw.get("model"), "ready", None
        row.scores = review.scores.model_dump() if review.scores else None
    except ValidationError as exc:
        row.ai_status, row.ai_error = "failed", f"The AI editor's answer did not fit the format: {ai._errors(exc)}"[:2000]
    except ValueError as exc:
        row.ai_status, row.ai_error = "failed", str(exc)[:2000]
    return row


def as_dict(row: Optional[MarketingReview]) -> dict:
    """`status` is the AI editor's: skipped (not asked yet) | pending | ready | failed. Findings are always current."""
    if row is None:
        return {"status": "none", "blocking": False, "findings": [], "advice": [], "summary": None, "error": None,
                "scores": None, "weak": []}
    return {"status": row.ai_status, "blocking": row.blocking, "findings": row.findings or [], "advice": row.advice or [],
            "summary": row.summary, "error": row.ai_error, "updated_at": row.updated_at, "scores": row.scores,
            "weak": weak_points(row.scores)}


_WEAK_HINT = {"hook": "the first line is flat; open with the most surprising true detail",
              "specificity": "it could describe any resort; use details only this place has",
              "voice": "it does not sound like the brand voice",
              "clarity": "a guest would not follow it on one read",
              "ask": "the next step is missing or unclear; give exactly one"}


def fix_brief(idea: str, findings: list[dict], *, weak: Optional[list[str]] = None,
              advice: Optional[list[dict]] = None) -> str:
    """The one rewrite request: the original idea, each high finding quoted, then the critic's weak marks and the
    editor's medium advice. High findings first, so the 1,000-character cut drops polish, never a blocker."""
    def line(f):
        return (f"- {f['where']}: {f['message']}" + (f" (\"{f['quote']}\")" if f.get("quote") else "")
                + (f" Fix: {f['suggestion']}" if f.get("suggestion") else ""))
    lines = [line(f) for f in findings if f["severity"] == "high"]
    lines += [f"- {k}: {_WEAK_HINT.get(k, 'weak')}" for k in (weak or [])]
    lines += [line(f) for f in (advice or []) if f.get("severity") == "medium"][:3]
    return (f"{idea}\n\nYour previous draft had problems. Write it again without them:\n" + "\n".join(lines))[:1000]


def request_ai(db: Session, tenant: Tenant, item: MarketingContent) -> Optional[MarketingReview]:
    """Store the deterministic findings now and queue the AI editor (Celery `marketing_studio.review_content`).
    Commits. If the queue is down the row says so; the deterministic findings still stand."""
    row = current(db, tenant, item)
    if row is None:
        return None
    row.ai_status, row.ai_error = "pending", None
    db.commit()
    try:
        from app.workers.tasks.marketing_studio import review_content
        review_content.delay(tenant.id, item.id)
    except Exception as exc:  # noqa: BLE001
        log.warning("marketing_review_queue_failed", tenant_id=tenant.id, item_id=item.id, error=str(exc))
        row.ai_status, row.ai_error = "failed", "Could not start the AI editor (queue unavailable). Try again."
        db.commit()
    return row
