"""
Task service (HAIP Inbox prototype-wiring plan, ticket 1). Single write/read
path for the follow-up Task model -- mirrors the identity_service/
next_action_service "one place owns this" convention used elsewhere in HAIP.
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.models.task import Task


def create_task(
    db: Session,
    tenant_id: str,
    title: str,
    created_by: Optional[str] = None,
    due_date=None,
    priority: str = "medium",
    guest_id: Optional[str] = None,
    inquiry_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    assigned_to: Optional[str] = None,
    commit: bool = True,
) -> Task:
    """commit=False adds the task to the caller's transaction (the caller commits)."""
    task = Task(
        tenant_id=tenant_id,
        title=title,
        due_date=due_date,
        priority=priority,
        guest_id=guest_id,
        inquiry_id=inquiry_id,
        conversation_id=conversation_id,
        assigned_to=assigned_to,
        created_by=created_by,
    )
    db.add(task)
    if not commit:
        db.flush()
        return task
    db.commit()
    db.refresh(task)
    return task


def list_tasks(
    db: Session,
    tenant_id: str,
    guest_id: Optional[str] = None,
    inquiry_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    assigned_to: Optional[str] = None,
) -> list[Task]:
    q = db.query(Task).filter_by(tenant_id=tenant_id)
    if guest_id:
        q = q.filter_by(guest_id=guest_id)
    if inquiry_id:
        q = q.filter_by(inquiry_id=inquiry_id)
    if conversation_id:
        q = q.filter_by(conversation_id=conversation_id)
    if assigned_to:
        q = q.filter_by(assigned_to=assigned_to)
    return q.order_by(Task.is_done.asc(), Task.due_date.asc().nullslast(), Task.created_at.desc()).all()


def toggle_task(db: Session, tenant_id: str, task_id: str) -> Optional[Task]:
    task = db.query(Task).filter_by(id=task_id, tenant_id=tenant_id).first()
    if not task:
        return None
    task.is_done = not task.is_done
    task.completed_at = datetime.now(timezone.utc) if task.is_done else None
    db.commit()
    db.refresh(task)
    return task
