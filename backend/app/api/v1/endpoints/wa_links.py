"""Tracked WhatsApp campaign links (services/wa_campaign_money.py): GET /api/v1/c/{code} records the first tap and
redirects to the campaign's link. Public (it is what a guest's phone opens); only stored codes resolve, so it can't be
used as an open redirect."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
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


# ─── click-to-chat entry links (services/wa_entry_links.py) ─────────────────────
# Public: a QR code, a website button or a bio link opens these. Only stored, switched-on codes resolve; the target is
# always wa.me with the workspace's own number.

def _entry_link(db: Session, code: str):
    from app.models.wa_entry_link import WaEntryLink

    link = db.query(WaEntryLink).filter_by(code=code, active=True).first() if code and len(code) <= 16 else None
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    return link


@router.get("/w/{code}", include_in_schema=False)
def follow_entry_link(code: str, db: Session = Depends(get_db)):
    from app.services import wa_entry_links

    target = wa_entry_links.follow(db, code) if code and len(code) <= 16 else None
    if not target:
        raise HTTPException(status_code=404, detail="Link not found")
    return RedirectResponse(target, status_code=302)


@router.get("/w/{code}/qr.svg", include_in_schema=False)
def entry_link_qr(code: str, request: Request, db: Session = Depends(get_db)):
    from app.core.config import settings
    from app.services import wa_entry_links

    link = _entry_link(db, code)
    base = (settings.API_BASE_URL or str(request.base_url)).rstrip("/")
    return Response(wa_entry_links.qr_svg(f"{base}/api/v1/w/{link.code}"), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/w/{code}/widget.js", include_in_schema=False)
def entry_link_widget(code: str, request: Request, label: str = "Chat with us", db: Session = Depends(get_db)):
    from app.core.config import settings
    from app.services import wa_entry_links

    link = _entry_link(db, code)
    base = (settings.API_BASE_URL or str(request.base_url)).rstrip("/")
    return Response(wa_entry_links.widget_js(f"{base}/api/v1/w/{link.code}", label[:40]), media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=3600"})
