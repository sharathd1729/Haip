"""Ask Yaad chats (services/personal_ask.py): the person's saved questions and answers.

  GET    /me/asks?folder_id=                    chats, newest first (title, folder, turns, updated_at)
  GET    /me/asks/suggestions?folder_id=        starting questions from the person's recent calls (no AI)
  GET    /me/asks/{id}                          one chat with its turns (answer with [n] markers, sources, follow-ups)
  DELETE /me/asks/{id}                          gone for good (audited by id)
  GET    /me/asks/{id}/turns/{turn_id}/pdf      one answer as an editable PDF
Asking (and following up in a chat) is POST /me/ask with `session_id` (endpoints/personal_calls.py).

Personal workspaces only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.v1.endpoints.personal_calls import personal_user
from app.core.audit import append_audit
from app.core.database import get_db
from app.models.user import User
from app.services import personal_ask as svc
from app.services.personal_ask_pdf import render

router = APIRouter(prefix="/me/asks", tags=["personal"])


def _chat(db: Session, user: User, session_id: str):
    a = svc.get_session(db, user.tenant_id, session_id)
    if a is None:
        raise HTTPException(status_code=404, detail="That chat isn't here any more.")
    return a


@router.get("")
def list_chats(
    folder_id: str | None = Query(None, max_length=64),
    user: User = Depends(personal_user),
    db: Session = Depends(get_db),
):
    return {"chats": svc.sessions(db, user.tenant_id, folder_id)}


@router.get("/suggestions")
def suggestions(
    folder_id: str | None = Query(None, max_length=64),
    user: User = Depends(personal_user),
    db: Session = Depends(get_db),
):
    return {"suggestions": svc.suggestions(db, user.tenant_id, folder_id)}


@router.get("/{session_id}")
def get_chat(session_id: str, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    return svc.session_view(_chat(db, user, session_id))


@router.delete("/{session_id}")
def delete_chat(session_id: str, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    a = _chat(db, user, session_id)
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="yaad_ask.deleted",
        actor_user_id=user.id,
        target_type="yaad_ask",
        target_id=a.id,
        payload={"turns": len(a.turns or [])},
    )
    db.delete(a)
    db.commit()
    return {"deleted": True}


@router.get("/{session_id}/turns/{turn_id}/pdf")
def turn_pdf(session_id: str, turn_id: str, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    turn = next((t for t in _chat(db, user, session_id).turns or [] if t.get("id") == turn_id), None)
    if turn is None:
        raise HTTPException(status_code=404, detail="That answer isn't here any more.")
    pdf = render(
        question=turn.get("question") or "",
        answer=turn.get("answer") or "",
        sources=turn.get("sources") or [],
        asked_at=turn.get("at"),
        owner=user.name or "",
    )
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="yaad-answer-{turn_id}.pdf"'},
    )
