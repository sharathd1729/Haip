"""Ops files, villa pack (phase 4): the steps only a villa stay has. Shared steps (checklist, settle, close, money, report)
stay in ops_files.py. Every answer is the full file (ops_files._full).

POST   /ops/files/{id}/people                 caretaker, cook, cleaner            ops.write
POST   /ops/files/{id}/check-in               keys + deposit (a person's tap)     ops.manage
POST   /ops/files/{id}/check-out              opens the inspection                ops.write
POST   /ops/files/{id}/meals                  add a meal                          ops.write
DELETE /ops/files/{id}/meals/{meal_id}                                            ops.write
POST   /ops/files/{id}/meals/confirm          {meal_ids} marked confirmed         ops.write
POST   /ops/files/{id}/meals/send             unconfirmed meals to the cook       ops.write
POST   /ops/files/{id}/cleaning/{job_id}/done                                     ops.write
POST   /ops/files/{id}/deposit                refund, or keep part with a reason  ops.manage
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.v1.endpoints.ops_files import _done, _file, _manage, _write
from app.core.database import get_db
from app.models.ops_files import OpsFile
from app.models.user import User
from app.schemas.ops_files import CheckInIn, DepositDecisionIn, MealIn, PeopleIn
from app.services import ops_stay_meals as meals
from app.services import ops_stay_service as stays

router = APIRouter(prefix="/ops/files", tags=["operations"])


class MealIdsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meal_ids: list[str] = Field(min_length=1, max_length=200)


def _stay(db: Session, user: User, file_id: str) -> OpsFile:
    f = _file(db, user, file_id)
    if f.pack != stays.PACK:
        raise HTTPException(status_code=409, detail="This step is for villa stays only.")
    return f


@router.post("/{file_id}/people")
def people(file_id: str, body: PeopleIn, user: User = Depends(_write), db: Session = Depends(get_db)):
    return _done(db, stays.set_people(db, _stay(db, user, file_id), body, user.id))


@router.post("/{file_id}/check-in")
def check_in(file_id: str, body: CheckInIn, user: User = Depends(_manage), db: Session = Depends(get_db)):
    return _done(db, stays.check_in(db, _stay(db, user, file_id), body, user.id))


@router.post("/{file_id}/check-out")
def check_out(file_id: str, user: User = Depends(_write), db: Session = Depends(get_db)):
    return _done(db, stays.check_out(db, _stay(db, user, file_id), user.id))


@router.post("/{file_id}/meals", status_code=201)
def add_meal(file_id: str, body: MealIn, user: User = Depends(_write), db: Session = Depends(get_db)):
    f = _stay(db, user, file_id)
    meals.add_meal(db, f, body, user.id)
    return _done(db, f)


@router.post("/{file_id}/meals/confirm")
def confirm_meals(file_id: str, body: MealIdsIn, user: User = Depends(_write), db: Session = Depends(get_db)):
    f = _stay(db, user, file_id)
    meals.confirm_meals(db, f, body.meal_ids, user.id)
    return _done(db, f)


@router.post("/{file_id}/meals/send")
def send_meals(file_id: str, user: User = Depends(_write), db: Session = Depends(get_db)):
    f = _stay(db, user, file_id)
    meals.send_meals(db, f, user.id)
    return _done(db, f)


@router.delete("/{file_id}/meals/{meal_id}")
def remove_meal(file_id: str, meal_id: str, user: User = Depends(_write), db: Session = Depends(get_db)):
    f = _stay(db, user, file_id)
    meals.remove_meal(db, f, meal_id, user.id)
    return _done(db, f)


@router.post("/{file_id}/cleaning/{job_id}/done")
def cleaning_done(file_id: str, job_id: str, user: User = Depends(_write), db: Session = Depends(get_db)):
    f = _stay(db, user, file_id)
    stays.finish_cleaning(db, f, job_id, actor_id=user.id)
    return _done(db, f)


@router.post("/{file_id}/deposit")
def deposit(file_id: str, body: DepositDecisionIn, user: User = Depends(_manage), db: Session = Depends(get_db)):
    f = _stay(db, user, file_id)
    stays.decide_deposit(db, f, body, user.id)
    return _done(db, f)
