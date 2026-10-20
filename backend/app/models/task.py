"""
Task model (HAIP Inbox prototype-wiring plan, ticket 1). No Task model
existed anywhere in HAIP before this -- this was also the gap that blocked
the schedule_followup_call action flagged during the AI Autonomy Plan Phase 2
work. A task is always tied to at least one of guest_id/inquiry_id/
conversation_id so it can be listed from any of those surfaces (Leads360,
Guest 360, Inbox).
"""
from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class Task(Base, TimestampMixin, TenantMixin):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=gen_uuid)

    title = Column(String(255), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    priority = Column(String(10), nullable=False, default="medium")  # high | medium | low

    is_done = Column(Boolean, nullable=False, default=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # At least one of these is expected to be set -- enforced in
    # task_service.create_task(), not at the DB level, since a task can be
    # scoped to any single one of these without the others.
    guest_id = Column(String, ForeignKey("guests.id"), nullable=True, index=True)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=True, index=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=True, index=True)

    assigned_to = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    # Lead workflows (migration 152): what the task is for (followup | call | decide ...) and the playbook run that
    # made it. NULL on older tasks and on tasks people create.
    kind = Column(String(30), nullable=True)
    playbook_run_id = Column(String, nullable=True, index=True)
