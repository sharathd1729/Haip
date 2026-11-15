"""Tracked WhatsApp campaign links (services/wa_campaign_money.py): GET /api/v1/c/{code} records the first tap and
redirects to the campaign's link. Public (it is what a guest's phone opens); only stored codes resolve, so it can't be
used as an open redirect."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(tags=["whatsapp-links"])


@router.get("/c/{code}", include_in_schema=False)
def follow_campaign_link(code: str, db: Session = Depends(get_db)):
    from app.services import wa_campaign_money

    if not code or len(code) > 16:
        raise HTTPException(status_code=404, detail="Link not found")
    target = wa_campaign_money.follow(db, code)
    if not target:
        raise HTTPException(status_code=404, detail="Link not found")
    return RedirectResponse(target, status_code=302)
