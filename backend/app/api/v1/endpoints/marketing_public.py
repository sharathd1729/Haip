"""Public (no login) Marketing Studio pages: email unsubscribe (agency M3).

GET  /api/v1/public/email/unsubscribe/{token}   a small page with an Unsubscribe button (a GET never unsubscribes:
                                                mail scanners open links)
POST /api/v1/public/email/unsubscribe/{token}   unsubscribes (the form, and one-click List-Unsubscribe-Post)
The token is signed (marketing_newsletter.unsubscribe_token) and carries no email address.
"""
import html

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import marketing_newsletter as newsletter

router = APIRouter(prefix="/public/email", tags=["marketing-public"])

_PAGE = ('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
         '<meta name="robots" content="noindex"><title>{title}</title></head>'
         '<body style="font:16px/1.5 Arial,sans-serif;max-width:480px;margin:48px auto;padding:0 16px;color:#1f2937">'
         '{body}</body></html>')
_HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
            "Cache-Control": "no-store"}


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe_page(token: str):
    if newsletter.read_token(token) is None:
        return HTMLResponse(_PAGE.format(title="Link not valid", body="<p>This unsubscribe link is not valid.</p>"),
                            status_code=404, headers=_HEADERS)
    body = (f'<h1 style="font-size:22px">Stop marketing emails?</h1><p>You will not get these newsletters any more.</p>'
            f'<form method="post" action="{html.escape(token)}"><button type="submit" style="font-size:16px;padding:12px 20px;'
            f'border-radius:999px;border:0;background:#1E7A5A;color:#fff">Unsubscribe</button></form>')
    return HTMLResponse(_PAGE.format(title="Unsubscribe", body=body), headers=_HEADERS)


@router.post("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    ok = newsletter.unsubscribe(db, token)
    if not ok:
        return HTMLResponse(_PAGE.format(title="Link not valid", body="<p>This unsubscribe link is not valid.</p>"),
                            status_code=404, headers=_HEADERS)
    db.commit()
    return HTMLResponse(_PAGE.format(title="Unsubscribed", body="<h1 style=\"font-size:22px\">You are unsubscribed.</h1>"
                                     "<p>You will not get marketing emails from us any more.</p>"), headers=_HEADERS)
