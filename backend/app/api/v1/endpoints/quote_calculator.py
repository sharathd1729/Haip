"""Rate calculator (/dashboard/quotes and the "Send quote" sheet). Services: quote_calc_service, quote_calc_leads,
rate_calculator, quote_calc_catalog.

GET  /quote-calculator/setup               packages by route (published only), custom-trip rules, add-ons, tax/advance defaults
POST /quote-calculator/price               price + availability + the exact message; NO writes
POST /quote-calculator/quotes              save to a lead, then send / copy / save only (a lowered price may wait for an OK)
GET  /quote-calculator/quotes/{id}         one saved calculator quote (the approval link opens it)
POST /quote-calculator/quotes/{id}/share   send or copy a saved quote (after approval)
POST /quote-calculator/quotes/{id}/approve owner / manager; never your own quote unless you are the owner
GET  /quote-calculator/leads?q=            "Send to" picker: one row per lead, open leads first, "Add as new lead" for a new number
POST /quote-calculator/leads               add a lead from a phone number (identity_service: no duplicate person)
GET  /quote-calculator/context             prefill when opened from a lead / chat / call / phone number (read-only)
GET|PUT /quote-calculator/settings         tax, advance, validity and approval-limit defaults (owner / manager)

Everything needs `quotes.write` and is scoped to the caller's tenant and lead visibility.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.api.v1.deps import get_current_user
from app.core.audit import append_audit
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.quote_calculator import CalcIn, CalcSaveIn, NewLeadIn, QuoteSettingsIn, ShareIn
from app.services import business_data_service as bds
from app.services import quote_calc_catalog as cat
from app.services import quote_calc_leads as leads
from app.services import quote_calc_service as svc
from app.services import quote_service as qs
from app.services.authz_service import require_capability

router = APIRouter(prefix="/quote-calculator", tags=["quote-calculator"])
_write = Depends(require_capability("quotes.write"))


def _err(exc) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def _owner_or_manager(user: User) -> None:
    if user.role not in (UserRole.OWNER, UserRole.MANAGER):
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Only the owner or a manager can change this."})


@router.get("/setup")
def setup(current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    from app.services.quote_builder_service import _send_setup
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    today = bds.tenant_today(db, tenant.id)
    s = cat.settings(db, tenant, today)
    return {
        "today": today.isoformat(), "brand": tenant.brand_name or tenant.name, "settings": cat.settings_out(s),
        "gst_slabs": list(cat.GST_SLABS), "discount_options": cat.discount_options(s),
        **cat.packages(db, tenant.id, today), "custom": cat.custom_rules_out(cat.custom_rules(db, tenant, today)),
        "addons": cat.addon_defaults(db, tenant, today), "send_setup": _send_setup(db, tenant.id),
        "permissions": {"user_id": current_user.id, "privileged": svc.privileged(current_user),
                        "is_owner": current_user.role == UserRole.OWNER, "can_manage": svc.privileged(current_user)},
        "lead_sources": list(leads.SOURCE_MAP),
    }


@router.post("/price")
def price(body: CalcIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    return svc.price(db, current_user, body)                 # reads only; nothing is committed


@router.post("/quotes", status_code=201)
def save(body: CalcSaveIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    try:
        return svc.save(db, current_user, body)
    except qs.QuoteError as exc:
        raise _err(exc)


@router.get("/quotes/{quote_id}")
def get_quote(quote_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    try:
        return svc.view(db, current_user, quote_id)
    except qs.QuoteError as exc:
        raise _err(exc)


@router.post("/quotes/{quote_id}/share")
def share(quote_id: str, body: ShareIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    try:
        return svc.share(db, current_user, quote_id, body.action)
    except qs.QuoteError as exc:
        raise _err(exc)


@router.post("/quotes/{quote_id}/approve")
def approve(quote_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    try:
        return svc.approve(db, current_user, quote_id)
    except qs.QuoteError as exc:
        raise _err(exc)


@router.get("/leads")
def find_leads(q: str = Query("", max_length=80), current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
               _cap=_write):
    return leads.search(db, current_user, q)


@router.post("/leads", status_code=201)
def add_lead(body: NewLeadIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    try:
        return leads.create_lead(db, current_user, body.phone, body.name, body.source)
    except leads.LeadError as exc:
        raise _err(exc)


@router.get("/context")
def context(inquiry_id: Optional[str] = Query(None, max_length=64), guest_id: Optional[str] = Query(None, max_length=64),
            conversation_id: Optional[str] = Query(None, max_length=64), call_id: Optional[str] = Query(None, max_length=64),
            phone: Optional[str] = Query(None, max_length=32), current_user: User = Depends(get_current_user),
            db: Session = Depends(get_db), _cap=_write):
    today = bds.tenant_today(db, current_user.tenant_id)
    try:
        return leads.context(db, current_user, inquiry_id=inquiry_id, guest_id=guest_id, conversation_id=conversation_id,
                             call_id=call_id, phone=phone, today=today,
                             packages=cat.packages(db, current_user.tenant_id, today)["packages"])
    except leads.LeadError as exc:
        raise _err(exc)


@router.get("/settings")
def get_settings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    _owner_or_manager(current_user)
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    return cat.settings_out(cat.settings(db, tenant))


@router.put("/settings")
def put_settings(body: QuoteSettingsIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    _owner_or_manager(current_user)
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    cfg = dict(tenant.brand_config or {})
    before = dict(cfg.get("quotes") or {})
    new = {**before, **body.model_dump(mode="json")}
    cfg["quotes"] = new
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, actor_user_id=current_user.id, action="settings.quotes_changed", target_type="tenant",
                 target_id=tenant.id, payload={"before": before, "after": new})
    db.commit()
    return cat.settings_out(cat.settings(db, tenant))
