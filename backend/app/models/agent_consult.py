"""The AI asking a person before it answers a guest ("Ask a manager", migration 168).

A consult opens when a deterministic trigger (services/agent_escalation_rules.py) fires in the reply path BEFORE anything is
sent: the guessed answer is held (it becomes ``proposed_answer``), the guest gets ONE honest holding reply, and the team is
asked. One OPEN consult per conversation (partial unique index); a later trigger on the same thread appends its reasons.

status:  open        waiting for a person
         answered    a person answered; the text went to the guest (or, with the 24 h window closed, a task was raised)
         taken_over  a person took the conversation themselves (they reply in the Inbox)
         expired     nobody answered after the last level; a callback task was raised
level:   agent -> manager -> owner (agent_consult_notify.escalate climbs it when the SLA passes)
"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String, Text, text

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid

STATUSES = ("open", "answered", "taken_over", "expired")
LEVELS = ("agent", "manager", "owner")


class AgentConsult(Base, TimestampMixin, TenantMixin):
    __tablename__ = "agent_consults"
    __table_args__ = (
        Index("ix_agent_consults_tenant_status", "tenant_id", "status"),
        Index("uq_agent_consults_open_conversation", "tenant_id", "conversation_id", unique=True,
              postgresql_where=text("status = 'open'"), sqlite_where=text("status = 'open'")),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    guest_id = Column(String, nullable=True, index=True)
    inquiry_id = Column(String, nullable=True, index=True)
    message_id = Column(String, nullable=True)                # the guest message that raised it
    draft_message_id = Column(String, nullable=True)          # the held AI draft (pending, never sent by itself)
    holding_message_id = Column(String, nullable=True)        # the "let me check with the team" reply, when one went out
    channel = Column(String(20), nullable=True)
    reason_codes = Column(JSON, nullable=False, default=list)  # stable codes, agent_escalation_rules.REASONS
    question = Column(Text, nullable=False)                   # what the guest asked, in their words
    proposed_answer = Column(Text, nullable=True)             # the AI's draft (may be empty)
    options = Column(JSON, nullable=True)                     # [{"id", "text"}] a person may pick from
    evidence = Column(JSON, nullable=False, default=dict)     # sources / flags / intent the rules saw
    status = Column(String(12), nullable=False, default="open")
    level = Column(String(10), nullable=False, default="agent")
    assigned_to = Column(String, nullable=True)
    sla_due_at = Column(DateTime(timezone=True), nullable=False)
    escalated_at = Column(DateTime(timezone=True), nullable=True)
    answered_by = Column(String, nullable=True)
    answer_mode = Column(String(20), nullable=True)           # approve_proposed | edited | option | take_over | expired
    answer_text = Column(Text, nullable=True)
    answered_at = Column(DateTime(timezone=True), nullable=True)
    delivery = Column(String(20), nullable=True)              # queued | window_closed_task | not_sent
    answer_message_id = Column(String, nullable=True)
    task_id = Column(String, nullable=True)                   # "Reply needed" / callback task, when one was raised
    saved_to_kb_entry_id = Column(String, nullable=True)
