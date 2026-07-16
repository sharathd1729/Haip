"""
Leads360 chat auto-create -- turns the first inbound message of a new
WhatsApp/Instagram conversation into an inquiry, routed by tenant-tagged
pipeline stages (migration 048).

Business rules (confirmed by user, see LEADS360_RESTRUCTURE_PLAN.md follow-up):
  - Collab-keyword match (collab, collaboration, B2B, partnership, UGC,
    content creator, etc.) -> the tenant's is_collab_entry stage
    (category="marketing").
  - Otherwise, a phone number is present -- always true on WhatsApp (the
    channel identity itself is a phone number); detected via regex in the
    message text on Instagram -- -> the tenant's is_valid_lead_entry stage
    (category="valid").
  - Otherwise -> the tenant's is_default_entry stage (category="invalid",
    e.g. "General Enquiry").
  - No further automatic stage movement after creation -- agents move
    leads through subsequent stages manually.

Only fires on the guest's first message in a channel (i.e. when no
conversation already existed before this message) -- callers pass
`is_new_conversation`; repeat messages on an existing conversation never
re-trigger this.
"""
from __future__ import annotations
import re
from typing import Optional
from sqlalchemy.orm import Session

from app.models.pipeline_stage import PipelineStage

_COLLAB_KEYWORDS = [
    "collab", "collaboration", "collaborate", "b2b", "partnership", "partner",
    "ugc", "content creator", "content creators", "creator", "creators",
    "content",
]
_COLLAB_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _COLLAB_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Loose international-friendly phone match: 7-15 digits, optional +/spaces/dashes.
_PHONE_RE = re.compile(r"(\+?\d[\d\-\s]{6,14}\d)")


def is_collab_message(text: str) -> bool:
    if not text:
        return False
    return bool(_COLLAB_RE.search(text))


def text_contains_phone(text: str) -> bool:
    if not text:
        return False
    return bool(_PHONE_RE.search(text))


def resolve_entry_stage_id(
    db: Session, tenant_id: str, *, is_collab: bool, has_phone: bool,
) -> Optional[str]:
    """
    Pick the pipeline_stages.id a freshly auto-created inquiry should land
    in, per the routing rules above. Falls back to the tenant's
    is_default_entry stage, then None (caller's own default) if the
    tenant hasn't tagged any stage yet.
    """
    stages = db.query(PipelineStage).filter_by(tenant_id=tenant_id).all()
    by_flag = {
        "collab": next((s for s in stages if s.is_collab_entry), None),
        "valid": next((s for s in stages if s.is_valid_lead_entry), None),
        "default": next((s for s in stages if s.is_default_entry), None),
    }

    if is_collab and by_flag["collab"]:
        return by_flag["collab"].id
    if has_phone and by_flag["valid"]:
        return by_flag["valid"].id
    if by_flag["default"]:
        return by_flag["default"].id
    return None
