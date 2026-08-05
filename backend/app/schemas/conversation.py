from pydantic import BaseModel
from typing import Optional, List, Union
from datetime import datetime


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    direction: str
    channel: str
    body: Optional[str] = None
    media_url: Optional[str] = None
    is_ai_generated: bool = False
    ai_confidence: Optional[float] = None
    was_approved: Optional[bool] = None
    sender_name: Optional[str] = None
    sender_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    delivery_state: Optional[str] = None
    delivery_error: Optional[str] = None
    is_internal: bool = False
    replied_to_message_id: Optional[str] = None
    scheduled_for: Optional[str] = None
    # Accept either datetime (Postgres/SQLite ORM result) or ISO string (legacy)
    created_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: str
    tenant_id: str
    guest_id: str
    inquiry_id: Optional[str] = None
    channel: str
    is_open: bool = True
    ai_mode: Optional[str] = "shadow"
    last_message_at: Optional[datetime] = None
    last_inbound_at: Optional[datetime] = None  # D9: last inbound message timestamp (computed)
    snoozed_until: Optional[Union[datetime, str]] = None
    guest_name: Optional[str] = None
    last_message: Optional[str] = None
    ad_title: Optional[str] = None  # T0.5: set when the conversation originated from a Click-to-Instagram ad

    # HAIP Inbox UI-fidelity pass, ticket 2: lead owner/stage/score/SLA were
    # already joined in memory (Conversation.assigned_to, Conversation.inquiry)
    # but never serialized -- this is what the prototype's left-list card and
    # Guest Overview panel actually need.
    assigned_to: Optional[str] = None  # raw user id -- for "assigned to me" comparison client-side
    assigned_owner_name: Optional[str] = None
    stage_key: Optional[str] = None
    stage_label: Optional[str] = None
    profile_completeness_pct: Optional[int] = None
    is_waiting_reply: bool = False
    sla_status: Optional[str] = None  # "on_time" | "warning" | "breached" | None (no open inquiry)

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    body: str
    media_url: Optional[str] = None
    is_internal: bool = False
    replied_to_message_id: Optional[str] = None
    scheduled_for: Optional[str] = None  # W4: ISO datetime


class AIDraftRequest(BaseModel):
    """Ask the AI concierge to draft a reply for a conversation."""
    context_hint: Optional[str] = None  # optional instruction override
    # AI Autonomy Plan Phase 2: matches AIDraftPanel.tsx's AiTone type. Was
    # captured in frontend state but never sent to the backend at all --
    # the tone chips were fully wired UI with no effect on the actual draft.
    tone: Optional[str] = None  # "warm" | "formal" | "brief" | "persuasive"


class RewriteDraftRequest(BaseModel):
    """HAIP Inbox prototype-wiring plan, ticket 3: real translate/tone-fix
    of an existing pending AI draft. At least one of tone/target_language
    is expected -- validated in the endpoint, not here, since "polish only"
    (both absent) is a legitimate no-op-instructions case the task handles."""
    tone: Optional[str] = None
    target_language: Optional[str] = None


class ComposerRewriteRequest(BaseModel):
    """HAIP Inbox full-parity pass, ticket 5: Translate/Tone-Fix on the
    composer's free-typed text -- no Message row exists yet for this text."""
    text: str
    tone: Optional[str] = None
    target_language: Optional[str] = None


class SendTemplateRequest(BaseModel):
    """T3.2: send an approved WhatsApp template -- required when the 24h
    service window is closed, since Meta rejects free-form messages then."""
    template_id: str
    variables: Optional[list[str]] = None


class ApproveDraftRequest(BaseModel):
    """Approve an AI draft, optionally with edited text. `text` omitted or
    equal to the stored draft means sent verbatim; a different value means
    the agent edited it before sending -- distinguishing the two is the
    whole point of this endpoint accepting a body at all."""
    text: Optional[str] = None
