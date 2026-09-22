import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.inquiry import Inquiry, InquiryStage
from app.models.conversation import Conversation, Message
from app.schemas.inquiry import InquiryOut, InquiryCreateRequest, InquiryUpdateRequest
from app.services.inquiry_service import get_or_create, update_stage, update_stage_by_id, InvalidStageTransition
from pydantic import BaseModel

class NoteRequest(BaseModel):
    body: str

router = APIRouter(prefix="/inquiries", tags=["inquiries"])


@router.get("", response_model=List[InquiryOut])
def list_inquiries(
    stage: Optional[str] = None,
    guest_id: Optional[str] = None,
    property_id: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Inquiry).filter_by(tenant_id=current_user.tenant_id)
    if stage:
        q = q.filter(Inquiry.stage == stage)
    if guest_id:
        q = q.filter_by(guest_id=guest_id)
    if property_id:
        q = q.filter_by(property_id=property_id)
    return q.order_by(Inquiry.created_at.desc()).offset(offset).limit(limit).all()


@router.post("", response_model=InquiryOut, status_code=201)
def create_inquiry(
    body: InquiryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # An explicit assignee wins; otherwise the tenant's lead-assignment rules
    # decide (lead_assignment_service) once the row exists.
    assigned_to = body.assigned_to if hasattr(body, "assigned_to") and body.assigned_to else None

    inquiry = Inquiry(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        guest_id=body.guest_id,
        property_id=body.property_id,
        source=body.source or "web",
        stage=InquiryStage.NEW,
        check_in=body.check_in,
        check_out=body.check_out,
        adults=body.adults,
        children=body.children,
        occasion=body.occasion,
        budget=body.budget,
        assigned_to=assigned_to,
        assigned_at=datetime.now(timezone.utc) if assigned_to else None,
        assignment_method="manual" if assigned_to else None,
    )
    db.add(inquiry)
    db.flush()
    if not assigned_to:
        from app.services.lead_assignment_service import assign_new_lead
        assign_new_lead(db, inquiry)
    db.commit()
    db.refresh(inquiry)

    # Fire automation trigger (non-blocking)
    try:
        from app.workers.tasks.automation_engine import fire_trigger
        fire_trigger.apply_async(
            kwargs={
                "event": "new_inquiry",
                "tenant_id": current_user.tenant_id,
                "context": {
                    "inquiry_id": inquiry.id,
                    "guest_id": inquiry.guest_id,
                    "source": inquiry.source,
                },
            },
            queue="whatsapp",
        )
    except Exception:
        pass  # never let automation failure block the response

    return inquiry


@router.get("/{inquiry_id}", response_model=InquiryOut)
def get_inquiry(
    inquiry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=current_user.tenant_id).first()
    if not inq:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    return inq


@router.patch("/{inquiry_id}", response_model=InquiryOut)
def update_inquiry(
    inquiry_id: str,
    body: InquiryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=current_user.tenant_id).first()
    if not inq:
        raise HTTPException(status_code=404, detail="Inquiry not found")

    updates = body.model_dump(exclude_none=True)
    reason = updates.pop("reason", None)

    # Stage transitions go through the state-machine service. `stage_id`
    # (Leads360 restructure Phase 1) is preferred and required for any
    # tenant that has added a custom pipeline stage; `stage` (legacy enum
    # key) is kept for existing frontend callers until the Kanban UI is
    # migrated over. Both share the same actor-role/reason backward-move
    # guardrails, just against different underlying data.
    actor_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if "stage_id" in updates:
        try:
            update_stage_by_id(
                db,
                tenant_id=current_user.tenant_id,
                inquiry_id=inquiry_id,
                new_stage_id=updates.pop("stage_id"),
                actor_user_id=current_user.id,
                actor_role=actor_role,
                reason=reason,
            )
        except InvalidStageTransition as e:
            raise HTTPException(status_code=422, detail=e.detail)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    elif "stage" in updates:
        try:
            new_stage = InquiryStage(updates.pop("stage"))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        try:
            update_stage(
                db,
                tenant_id=current_user.tenant_id,
                inquiry_id=inquiry_id,
                new_stage=new_stage,
                actor_user_id=current_user.id,
                actor_role=actor_role,
                reason=reason,
            )
        except InvalidStageTransition as e:
            raise HTTPException(status_code=422, detail=e.detail)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # Apply remaining non-stage field updates
    for k, v in updates.items():
        if hasattr(inq, k):
            setattr(inq, k, v)

    # Assign-to-me visibility fix: this was the ONLY writer of
    # Inquiry.assigned_to (used by _action_assign_to/automation_engine.py
    # and every direct PATCH from GuestPanel.tsx/Profile 360), while every
    # place an agent actually checks "my leads" reads Conversation.assigned_to
    # instead (Inbox's "Assigned to Me" chip, worklist_service.py's
    # scope_user_id filtering). The two columns never synced, so a
    # self-assigned lead was invisible everywhere except a raw
    # GET /leads?assigned_to= query. Keep every conversation on this inquiry
    # in step with it.
    if "assigned_to" in updates:
        # A person chose this owner: record it, and reset the "passed on"
        # counter so the not-contacted timer starts fresh for them.
        inq.assigned_at = datetime.now(timezone.utc)
        inq.assignment_method = "manual"
        inq.assignment_attempts = 0
        db.query(Conversation).filter_by(inquiry_id=inq.id, tenant_id=current_user.tenant_id).update(
            {"assigned_to": updates["assigned_to"]}, synchronize_session=False,
        )

    # Leads360 restructure Phase 4: re-evaluate qualification whenever an
    # inquiry's fields change, since qualification is progressive (a field
    # required_for_lead may have just been filled in). Best-effort -- never
    # block a normal field update over it.
    try:
        from app.services.lead_qualification_service import refresh_qualification_status
        refresh_qualification_status(db, current_user.tenant_id, inq)
    except Exception:
        pass

    db.commit()
    db.refresh(inq)
    return inq


# ── K15: Internal notes per inquiry ─────────────────────────────────────────

def _get_or_create_notes_conversation(db: Session, inquiry: Inquiry, tenant_id: str) -> Conversation:
    """Get or create a special 'notes' conversation for this inquiry."""
    conv = db.query(Conversation).filter_by(
        inquiry_id=inquiry.id,
        tenant_id=tenant_id,
        channel="internal",
    ).first()
    if not conv:
        conv = Conversation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            guest_id=inquiry.guest_id,
            inquiry_id=inquiry.id,
            channel="internal",
            is_open=True,
        )
        db.add(conv)
        db.flush()
    return conv


@router.get("/{inquiry_id}/notes")
def list_inquiry_notes(
    inquiry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=current_user.tenant_id).first()
    if not inq:
        raise HTTPException(status_code=404, detail="Inquiry not found")

    conv = db.query(Conversation).filter_by(
        inquiry_id=inquiry_id,
        tenant_id=current_user.tenant_id,
        channel="internal",
    ).first()
    if not conv:
        return []

    notes = (
        db.query(Message)
        .filter_by(conversation_id=conv.id, is_internal=True)
        .order_by(Message.created_at.asc())
        .all()
    )
    return [
        {
            "id": n.id,
            "body": n.body,
            "sender_id": n.sender_id,
            "sender_name": None,  # TODO: join user
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notes
    ]


@router.post("/{inquiry_id}/notes", status_code=201)
def add_inquiry_note(
    inquiry_id: str,
    body: NoteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=current_user.tenant_id).first()
    if not inq:
        raise HTTPException(status_code=404, detail="Inquiry not found")

    conv = _get_or_create_notes_conversation(db, inq, current_user.tenant_id)

    note = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        tenant_id=current_user.tenant_id,
        direction="outbound",
        channel="internal",  # messages.channel is NOT NULL; matches the parent conversation's channel
        body=body.body,
        sender_id=current_user.id,
        is_internal=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return {
        "id": note.id,
        "body": note.body,
        "sender_id": note.sender_id,
        "sender_name": current_user.name or current_user.email,
        "created_at": note.created_at.isoformat() if note.created_at else None,
    }
