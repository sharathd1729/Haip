"""
Follow-up Task endpoints (HAIP Inbox prototype-wiring plan, ticket 1).
Any authenticated tenant user can create/list/toggle -- same trust level as
the inbox's other agent-facing actions (approve draft, add note); the real
control here is tenant scoping, matching conversations.py's approve/reject
endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.schemas.task import TaskCreateRequest, TaskOut
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    body: TaskCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = task_service.create_task(
        db,
        tenant_id=current_user.tenant_id,
        title=body.title,
        created_by=current_user.id,
        due_date=body.due_date,
        priority=body.priority,
        guest_id=body.guest_id,
        inquiry_id=body.inquiry_id,
        conversation_id=body.conversation_id,
        assigned_to=body.assigned_to,
    )
    return task


@router.get("", response_model=list[TaskOut])
def list_tasks(
    guest_id: str | None = Query(default=None),
    inquiry_id: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return task_service.list_tasks(
        db,
        tenant_id=current_user.tenant_id,
        guest_id=guest_id,
        inquiry_id=inquiry_id,
        conversation_id=conversation_id,
        assigned_to=assigned_to,
    )


@router.patch("/{task_id}", response_model=TaskOut)
def toggle_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = task_service.toggle_task(db, tenant_id=current_user.tenant_id, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
