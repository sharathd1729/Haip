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
    (category="valid", e.g. "General Enquiry").
  - Otherwise -> the tenant's is_default_entry stage (category="invalid",
    e.g. "Unqualified" -- doesn't count as a lead in dashboards/metrics
    until an agent moves it, or a phone signal gets added later).
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

def is_collab_message(text: str) -> bool:
    if not text:
        return False
    return bool(_COLLAB_RE.search(text))


# A business asking on behalf of its clients (lead_types.B2B). Whole words / phrases only, so "agency" never matches inside
# another word and "event" alone (a guest's own birthday event) never counts. Plural forms listed explicitly.
_B2B_KEYWORDS = [
    "wedding planner", "wedding planners", "event planner", "event planners", "event management", "event company",
    "travel agent", "travel agents", "travel agency", "tour operator", "tour operators", "dmc", "reseller", "resellers",
    "agency", "agencies", "b2b",
]
_B2B_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in _B2B_KEYWORDS) + r")\b", re.IGNORECASE)


def lead_type_for_message(text: str) -> str:
    """The lead type a fresh chat enquiry starts with: b2b when the collaboration routing fires or a trade word appears in the
    guest's OWN message, else guest. Read from the message text only, never from a name."""
    if text and (is_collab_message(text) or _B2B_RE.search(text)):
        return "b2b"
    return "guest"


# A number without a country code is read as Indian unless the caller passes the workspace's own region (every chat path
# did this before phone_identity.find_phones existed; kept so nothing that worked stops working).
DEFAULT_REGION = "IN"


def text_contains_phone(text: str, region: Optional[str] = DEFAULT_REGION) -> bool:
    """True only when the text holds a usable phone number -- the SAME rule extract_phone() uses.

    This used to be a loose digit regex (7-15 digits with spaces/dashes). A date such as "24-10-2026 to 26-10-2026" matched
    it, so a first DM with dates and no number routed the new enquiry into the valid-lead entry stage ("General Enquiry")
    while no phone was ever captured: the team's lists then showed an Instagram lead with dates and "no number on file".
    Routing and capture now agree."""
    return bool(extract_phone(text, region))


def extract_phone(text: str, region: Optional[str] = DEFAULT_REGION) -> Optional[str]:
    """The first usable phone number in message text, as E.164, or None (phone_identity.find_phones).

    Strict on purpose: the result becomes an identity signal, and a phone is a high-confidence signal that can merge two
    guests, so a date, price, pincode or booking reference must never come back as a "phone". Only the first number is
    returned -- a second number in the same message is often someone else's (a driver, a spouse)."""
    from app.services.phone_identity import find_phones
    found = find_phones(text, region)
    return found[0] if found else None


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


def resolve_call_entry_stage_id(
    db: Session, tenant_id: str, *, answered: bool,
) -> Optional[str]:
    """
    Call-specific entry-stage routing. No transcript exists yet at
    call-ingest time, so there's no collab-keyword/phone-text signal to
    evaluate the way resolve_entry_stage_id() does for chat -- the call
    itself already establishes the guest's phone, and the immediate
    answered/unanswered signal (available from the IVR webhook before
    transcription ever runs) is the routing input instead:
      - unanswered -> the tenant's "rnr" stage (falls back to the
        default-entry stage if the tenant renamed/removed RNR)
      - answered -> the tenant's valid-lead-entry stage (same landing
        zone WhatsApp/Instagram use for a phone-present message)
    """
    stages = db.query(PipelineStage).filter_by(tenant_id=tenant_id).all()
    by_key = {s.key: s for s in stages}
    default_entry = next((s for s in stages if s.is_default_entry), None)
    valid_entry = next((s for s in stages if s.is_valid_lead_entry), None)

    if not answered:
        rnr = by_key.get("rnr")
        if rnr:
            return rnr.id
        return default_entry.id if default_entry else None

    if valid_entry:
        return valid_entry.id
    return default_entry.id if default_entry else None
