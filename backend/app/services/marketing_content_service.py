"""Marketing content lifecycle: immutable versions, review, approval bound to a version hash.

Rules (docs/marketing-website/PHASE0_AUDIT.md §7.3, owner decision D3):
  * A version is never edited. Any change adds a version and sends the item back to `draft`, voiding an approval.
  * Approval needs `marketing.approve`, the version the reviewer saw (409 if it changed), and a stored hash that still
    matches the payload. Only the owner may approve a version they wrote or asked the AI for.
  * State changes are single guarded UPDATEs, so a double click or two reviewers at once cannot both win.
  * Guest-visible text is checked against the tenant's price policy and the profile's banned words before it is stored.
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.marketing import MarketingApproval, MarketingContent, MarketingContentVersion
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.marketing import CONTENT_KINDS, text_of, validate_content
from app.services import price_policy


class MarketingError(Exception):
    def __init__(self, status: int, code: str, message: str, problems: Optional[list] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.problems = status, code, message, problems or []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sha_of(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _role(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def get_item(db: Session, tenant_id: str, item_id: str) -> MarketingContent:
    item = db.query(MarketingContent).filter_by(id=item_id, tenant_id=tenant_id).first()
    if item is None:
        raise MarketingError(404, "not_found", "No such content in this workspace.")
    return item


def get_version(db: Session, tenant_id: str, version_id: Optional[str]) -> Optional[MarketingContentVersion]:
    if not version_id:
        return None
    return db.query(MarketingContentVersion).filter_by(id=version_id, tenant_id=tenant_id).first()


def check_text(db: Session, tenant_id: str, payload: dict) -> list[str]:
    """Problems that block storing a version: prices when the tenant never shows prices, and the brand's banned words."""
    from app.services.marketing_ai_service import get_profile

    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    text = text_of(payload)
    problems: list[str] = []
    if tenant is not None and price_policy.price_mode(tenant) == "handoff":
        found = price_policy.detect_price(text)
        if found:
            problems.append(f"Mentions a price ({found!r}); this workspace never shows prices in public content.")
    lowered = text.lower()
    for word in get_profile(tenant).get("avoid", []) if tenant is not None else []:
        if word and word.lower() in lowered:
            problems.append(f"Uses {word!r}, which the business profile says to avoid.")
    return problems


def _validated(db: Session, tenant_id: str, kind: str, payload: dict) -> dict:
    try:
        clean = validate_content(kind, payload or {})
    except ValidationError as exc:
        raise MarketingError(422, "invalid_content", "The content does not fit the format.",
                             [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()])
    except ValueError as exc:
        raise MarketingError(422, "invalid_content", str(exc))
    problems = check_text(db, tenant_id, clean)
    if problems:
        raise MarketingError(422, "content_not_allowed", "The content breaks a workspace rule.", problems)
    return clean


def _decision(db: Session, item: MarketingContent, version: MarketingContentVersion, decision: str, actor_id: str, note=None):
    db.add(MarketingApproval(tenant_id=item.tenant_id, content_id=item.id, version_id=version.id, sha256=version.sha256,
                             decision=decision, note=note, actor_user_id=actor_id, created_at=_now()))


def create_item(db: Session, tenant_id: str, *, kind: str, title: str, actor_id: str, payload: Optional[dict] = None,
                property_id: Optional[str] = None, plan_id: Optional[str] = None,
                planned_for: Optional[str] = None) -> MarketingContent:
    if kind not in CONTENT_KINDS:
        raise MarketingError(422, "invalid_kind", f"Kind must be one of {', '.join(CONTENT_KINDS)}.")
    item = MarketingContent(tenant_id=tenant_id, kind=kind, title=title.strip()[:160] or "Untitled", property_id=property_id,
                            plan_id=plan_id, planned_for=planned_for, created_by=actor_id, status="draft")
    db.add(item)
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="marketing.content.created", actor_user_id=actor_id,
                 target_type="marketing_content", target_id=item.id, payload={"kind": kind})
    if payload is not None:
        add_version(db, tenant_id, item.id, payload, origin="human", actor_id=actor_id)
    return item


def add_version(db: Session, tenant_id: str, item_id: str, payload: dict, *, origin: str, actor_id: Optional[str],
                note: Optional[str] = None, prompt_version: Optional[str] = None,
                model: Optional[str] = None) -> MarketingContentVersion:
    item = get_item(db, tenant_id, item_id)
    if item.status == "archived":
        raise MarketingError(409, "archived", "Archived content cannot be changed.")
    clean = _validated(db, tenant_id, item.kind, payload)
    n = (db.query(func.max(MarketingContentVersion.version)).filter_by(content_id=item.id).scalar() or 0) + 1
    version = MarketingContentVersion(tenant_id=tenant_id, content_id=item.id, version=n, payload=clean, sha256=sha_of(clean),
                                      origin=origin, note=note, prompt_version=prompt_version, model=model,
                                      created_by=actor_id, created_at=_now())
    db.add(version)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise MarketingError(409, "concurrent_edit", "Someone saved a new version at the same moment. Reload and try again.")
    previous = item.status
    if previous in ("in_review", "approved"):
        old = get_version(db, tenant_id, item.current_version_id)
        if old is not None:
            _decision(db, item, old, "withdrawn", actor_id or "system", note="Superseded by a new version")
    item.current_version_id = version.id
    item.status = "draft"
    item.approved_version_id = None
    item.approved_sha256 = None
    item.generation_status = "idle"
    item.generation_error = None
    append_audit(db, tenant_id=tenant_id, action="marketing.content.version_created", actor_user_id=actor_id,
                 target_type="marketing_content", target_id=item.id,
                 payload={"version": n, "origin": origin, "sha256": version.sha256, "approval_voided": previous == "approved"})
    return version


def _guarded(db: Session, tenant_id: str, item_id: str, *, from_statuses: tuple, seen_version_id: str, values: dict) -> bool:
    n = (db.query(MarketingContent)
         .filter(MarketingContent.id == item_id, MarketingContent.tenant_id == tenant_id,
                 MarketingContent.status.in_(from_statuses), MarketingContent.current_version_id == seen_version_id)
         .update({**values, "updated_at": _now()}, synchronize_session=False))
    return n == 1


def _current_or_409(db: Session, tenant_id: str, item: MarketingContent, seen_version_id: str) -> MarketingContentVersion:
    if not item.current_version_id:
        raise MarketingError(409, "no_version", "There is nothing to review yet.")
    if item.current_version_id != seen_version_id:
        raise MarketingError(409, "version_changed", "A newer version was saved since you opened this. Review the latest one.")
    version = get_version(db, tenant_id, seen_version_id)
    if version is None or sha_of(version.payload) != version.sha256:
        raise MarketingError(409, "integrity_failed", "This version's stored content no longer matches its fingerprint.")
    return version


def submit(db: Session, tenant_id: str, item_id: str, seen_version_id: str, actor: User) -> MarketingContent:
    item = get_item(db, tenant_id, item_id)
    version = _current_or_409(db, tenant_id, item, seen_version_id)
    if not _guarded(db, tenant_id, item.id, from_statuses=("draft", "rejected"), seen_version_id=version.id,
                    values={"status": "in_review"}):
        raise MarketingError(409, "wrong_state", "Only a draft or rejected item can be sent for review.")
    _decision(db, item, version, "submitted", actor.id)
    append_audit(db, tenant_id=tenant_id, action="marketing.content.submitted", actor_user_id=actor.id,
                 target_type="marketing_content", target_id=item.id, payload={"version_id": version.id})
    db.refresh(item)
    return item


def approve(db: Session, tenant_id: str, item_id: str, seen_version_id: str, actor: User, note: Optional[str] = None) -> MarketingContent:
    item = get_item(db, tenant_id, item_id)
    if item.status == "approved" and item.approved_version_id == seen_version_id:
        return item   # double click: already done
    version = _current_or_409(db, tenant_id, item, seen_version_id)
    if _role(actor) != "owner" and version.created_by == actor.id:
        raise MarketingError(403, "self_approval", "You wrote or generated this version, so someone else must approve it.")
    if not _guarded(db, tenant_id, item.id, from_statuses=("in_review",), seen_version_id=version.id,
                    values={"status": "approved", "approved_version_id": version.id, "approved_sha256": version.sha256}):
        raise MarketingError(409, "wrong_state", "Only content that is in review can be approved.")
    _decision(db, item, version, "approved", actor.id, note)
    append_audit(db, tenant_id=tenant_id, action="marketing.content.approved", actor_user_id=actor.id,
                 target_type="marketing_content", target_id=item.id,
                 payload={"version_id": version.id, "sha256": version.sha256})
    db.refresh(item)
    return item


def reject(db: Session, tenant_id: str, item_id: str, seen_version_id: str, actor: User, note: Optional[str] = None) -> MarketingContent:
    item = get_item(db, tenant_id, item_id)
    version = _current_or_409(db, tenant_id, item, seen_version_id)
    if not _guarded(db, tenant_id, item.id, from_statuses=("in_review",), seen_version_id=version.id, values={"status": "rejected"}):
        raise MarketingError(409, "wrong_state", "Only content that is in review can be rejected.")
    _decision(db, item, version, "rejected", actor.id, note)
    append_audit(db, tenant_id=tenant_id, action="marketing.content.rejected", actor_user_id=actor.id,
                 target_type="marketing_content", target_id=item.id, payload={"version_id": version.id, "note": note})
    db.refresh(item)
    return item


def archive(db: Session, tenant_id: str, item_id: str, actor_id: str) -> MarketingContent:
    item = get_item(db, tenant_id, item_id)
    item.status = "archived"
    append_audit(db, tenant_id=tenant_id, action="marketing.content.archived", actor_user_id=actor_id,
                 target_type="marketing_content", target_id=item.id, payload={})
    return item


def approved_payload(db: Session, tenant_id: str, item_id: str) -> dict:
    """What a publisher may send: the approved version, only if it is still current and its hash still matches.
    Phase 4's publisher must call this immediately before any external request."""
    item = get_item(db, tenant_id, item_id)
    if item.status != "approved" or not item.approved_version_id:
        raise MarketingError(409, "not_approved", "This content has not been approved.")
    if item.approved_version_id != item.current_version_id:
        raise MarketingError(409, "approval_stale", "The content changed after it was approved.")
    version = get_version(db, tenant_id, item.approved_version_id)
    if version is None or version.sha256 != item.approved_sha256 or sha_of(version.payload) != version.sha256:
        raise MarketingError(409, "integrity_failed", "The approved content no longer matches what was approved.")
    return version.payload


def history(db: Session, tenant_id: str, item_id: str) -> dict:
    item = get_item(db, tenant_id, item_id)
    versions = (db.query(MarketingContentVersion).filter_by(tenant_id=tenant_id, content_id=item.id)
                .order_by(MarketingContentVersion.version.desc()).all())
    decisions = (db.query(MarketingApproval).filter_by(tenant_id=tenant_id, content_id=item.id)
                 .order_by(MarketingApproval.created_at.desc()).all())
    return {"versions": versions, "decisions": decisions}
