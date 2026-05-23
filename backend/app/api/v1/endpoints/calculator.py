"""
Rate Calculator & Quote Generator API.

Endpoints:
  POST /calculator/search          → available properties + rates
  POST /calculator/quote           → full quote with add-ons + tax
  POST /calculator/share           → send WhatsApp quote message
  GET  /calculator/addons/{prop}   → add-ons for a property
  POST /properties/{id}/addons     → create add-on
  PATCH /properties/{id}/addons/{aid}
  DELETE /properties/{id}/addons/{aid}
  GET  /properties/{id}/rates      → seasonal rates
  POST /properties/{id}/rates      → create seasonal rate
  PATCH /properties/{id}/rates/{rid}
  DELETE /properties/{id}/rates/{rid}
"""
from __future__ import annotations

import uuid
import logging
from decimal import Decimal
from typing import List, Optional, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.property import Property, PropertyAddOn, SeasonalRate
from app.models.user import User, UserRole
from app.services.calculator_service import calculator_service

log = logging.getLogger(__name__)
router = APIRouter(tags=["calculator"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    checkin: str                          # YYYY-MM-DD
    checkout: str                         # YYYY-MM-DD
    adults: int
    children: int = 0
    city: Optional[str] = None
    property_id: Optional[str] = None
    property_type: Optional[str] = None  # villa | caravan | hotel | apartment


class QuoteRequest(BaseModel):
    property_id: str
    checkin: str
    checkout: str
    adults: int
    children: int = 0
    selected_addon_ids: List[str] = []
    advance_percent: int = 30


class ShareRequest(BaseModel):
    property_id: str
    checkin: str
    checkout: str
    adults: int
    children: int = 0
    selected_addon_ids: List[str] = []
    guest_phone: str                      # E.164 format: +919876543210
    guest_name: str = ""
    advance_percent: int = 30


class AddOnCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    category: str = "experience"          # experience|meal|transfer|stay|other
    price: float
    price_type: str = "per_stay"          # per_stay|per_night|per_person|per_unit
    currency: str = "INR"
    sort_order: int = 0


class AddOnUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    price_type: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class AddOnOut(BaseModel):
    id: str
    property_id: str
    name: str
    description: Optional[str] = None
    category: str
    price: float
    price_type: str
    currency: str
    is_active: bool
    sort_order: int

    class Config:
        from_attributes = True


class SeasonalRateCreateRequest(BaseModel):
    name: str
    date_from: str                        # YYYY-MM-DD
    date_to: str                          # YYYY-MM-DD
    price_per_night: float
    min_nights: int = 1
    currency: str = "INR"
    priority: int = 0
    occupancy_pricing: dict = {}          # {4: 95000, 6: 110000}


class SeasonalRateUpdateRequest(BaseModel):
    name: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    price_per_night: Optional[float] = None
    min_nights: Optional[int] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    occupancy_pricing: Optional[dict] = None


class SeasonalRateOut(BaseModel):
    id: str
    property_id: str
    name: str
    date_from: str
    date_to: str
    price_per_night: float
    min_nights: int
    currency: str
    priority: int
    is_active: bool
    occupancy_pricing: Any = {}

    class Config:
        from_attributes = True


# ── Search ────────────────────────────────────────────────────────────────────

@router.post("/calculator/search")
def search_properties(
    body: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search available properties with resolved rates for given dates + guests."""
    results = calculator_service.search(
        db=db,
        tenant_id=current_user.tenant_id,
        checkin=body.checkin,
        checkout=body.checkout,
        adults=body.adults,
        children=body.children,
        city=body.city,
        property_id=body.property_id,
        property_type=body.property_type,
    )
    return [_rate_to_dict(r) for r in results]


# ── Quote ─────────────────────────────────────────────────────────────────────

@router.post("/calculator/quote")
def build_quote(
    body: QuoteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Build a detailed quote with selected add-ons and tax breakdown."""
    quote = calculator_service.build_quote(
        db=db,
        tenant_id=current_user.tenant_id,
        property_id=body.property_id,
        checkin=body.checkin,
        checkout=body.checkout,
        adults=body.adults,
        children=body.children,
        selected_addon_ids=body.selected_addon_ids,
        advance_percent=body.advance_percent,
    )
    if not quote:
        raise HTTPException(status_code=404, detail="Property not found or no rate configured")
    return _quote_to_dict(quote, body.checkin, body.checkout)


# ── Share via WhatsApp ────────────────────────────────────────────────────────

@router.post("/calculator/share")
def share_quote_whatsapp(
    body: ShareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate and send a formatted WhatsApp quote message."""
    quote = calculator_service.build_quote(
        db=db,
        tenant_id=current_user.tenant_id,
        property_id=body.property_id,
        checkin=body.checkin,
        checkout=body.checkout,
        adults=body.adults,
        children=body.children,
        selected_addon_ids=body.selected_addon_ids,
        advance_percent=body.advance_percent,
    )
    if not quote:
        raise HTTPException(status_code=404, detail="Property not found or no rate configured")

    message = quote.whatsapp_message(
        checkin=body.checkin,
        checkout=body.checkout,
        guest_name=body.guest_name,
    )

    # Send via WhatsApp adapter
    try:
        from app.adapters.whatsapp.meta_cloud import MetaCloudAdapter
        from app.models.integration import Integration
        from app.core.encryption import decrypt_credentials

        integration = db.query(Integration).filter_by(
            tenant_id=current_user.tenant_id, kind="whatsapp_meta", status="active"
        ).first()

        if integration and integration.credentials_kms_blob:
            creds = decrypt_credentials(integration.credentials_kms_blob)
            adapter = MetaCloudAdapter(
                phone_number_id=creds.get("phone_number_id", ""),
                access_token=creds.get("access_token", ""),
            )
            result = adapter.send_text(to=body.guest_phone, text=message)
            return {
                "status": "sent",
                "message_preview": message[:200],
                "whatsapp_message_id": result.get("messages", [{}])[0].get("id"),
            }
        else:
            # WhatsApp not configured — return message for manual copy
            return {
                "status": "not_sent",
                "reason": "WhatsApp integration not connected",
                "message": message,
            }
    except Exception as exc:
        log.error("whatsapp_share_failed err=%s", exc)
        return {
            "status": "error",
            "reason": str(exc),
            "message": message,
        }


# ── Add-ons CRUD ──────────────────────────────────────────────────────────────

@router.get("/properties/{property_id}/addons", response_model=List[AddOnOut])
def list_addons(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_property(db, property_id, current_user.tenant_id)
    return db.query(PropertyAddOn).filter_by(
        property_id=property_id, tenant_id=current_user.tenant_id
    ).order_by(PropertyAddOn.sort_order).all()


@router.post("/properties/{property_id}/addons", response_model=AddOnOut, status_code=201)
def create_addon(
    property_id: str,
    body: AddOnCreateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    _check_property(db, property_id, current_user.tenant_id)
    addon = PropertyAddOn(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        property_id=property_id,
        **body.model_dump(),
    )
    db.add(addon)
    db.commit()
    db.refresh(addon)
    return addon


@router.patch("/properties/{property_id}/addons/{addon_id}", response_model=AddOnOut)
def update_addon(
    property_id: str,
    addon_id: str,
    body: AddOnUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    addon = db.query(PropertyAddOn).filter_by(
        id=addon_id, property_id=property_id, tenant_id=current_user.tenant_id
    ).first()
    if not addon:
        raise HTTPException(status_code=404, detail="Add-on not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(addon, k, v)
    db.commit()
    db.refresh(addon)
    return addon


@router.delete("/properties/{property_id}/addons/{addon_id}", status_code=204)
def delete_addon(
    property_id: str,
    addon_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    addon = db.query(PropertyAddOn).filter_by(
        id=addon_id, property_id=property_id, tenant_id=current_user.tenant_id
    ).first()
    if not addon:
        raise HTTPException(status_code=404, detail="Add-on not found")
    addon.is_active = False
    db.commit()


# ── Seasonal Rates CRUD ───────────────────────────────────────────────────────

@router.get("/properties/{property_id}/rates", response_model=List[SeasonalRateOut])
def list_seasonal_rates(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_property(db, property_id, current_user.tenant_id)
    return db.query(SeasonalRate).filter_by(
        property_id=property_id, tenant_id=current_user.tenant_id, is_active=True
    ).order_by(SeasonalRate.date_from).all()


@router.post("/properties/{property_id}/rates", response_model=SeasonalRateOut, status_code=201)
def create_seasonal_rate(
    property_id: str,
    body: SeasonalRateCreateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    _check_property(db, property_id, current_user.tenant_id)
    rate = SeasonalRate(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        property_id=property_id,
        **body.model_dump(),
    )
    db.add(rate)
    db.commit()
    db.refresh(rate)
    return rate


@router.patch("/properties/{property_id}/rates/{rate_id}", response_model=SeasonalRateOut)
def update_seasonal_rate(
    property_id: str,
    rate_id: str,
    body: SeasonalRateUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    rate = db.query(SeasonalRate).filter_by(
        id=rate_id, property_id=property_id, tenant_id=current_user.tenant_id
    ).first()
    if not rate:
        raise HTTPException(status_code=404, detail="Rate not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(rate, k, v)
    db.commit()
    db.refresh(rate)
    return rate


@router.delete("/properties/{property_id}/rates/{rate_id}", status_code=204)
def delete_seasonal_rate(
    property_id: str,
    rate_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    rate = db.query(SeasonalRate).filter_by(
        id=rate_id, property_id=property_id, tenant_id=current_user.tenant_id
    ).first()
    if not rate:
        raise HTTPException(status_code=404, detail="Rate not found")
    rate.is_active = False
    db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_property(db: Session, property_id: str, tenant_id: str) -> Property:
    prop = db.query(Property).filter_by(id=property_id, tenant_id=tenant_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


def _rate_to_dict(r) -> dict:
    return {
        "property_id": r.property_id,
        "property_name": r.property_name,
        "property_type": r.property_type,
        "city": r.city,
        "address": r.address,
        "bedrooms": r.bedrooms,
        "bathrooms": r.bathrooms,
        "max_adults": r.max_adults,
        "photos": r.photos[:3],
        "amenities": r.amenities[:10],
        "available": r.available,
        "nights": r.nights,
        "guests": r.guests,
        "price_per_night": float(r.price_per_night),
        "subtotal_accommodation": float(r.subtotal_accommodation),
        "currency": r.currency,
        "rate_source": r.rate_source,
        "rate_name": r.rate_name,
        "min_nights": r.min_nights,
        "is_caravan": r.is_caravan,
        "vehicle_name": r.vehicle_name,
        "addons": [
            {
                "id": a.id,
                "name": a.name,
                "description": a.description,
                "category": a.category,
                "price": float(a.price),
                "price_type": a.price_type,
            }
            for a in r.addons
        ],
    }


def _quote_to_dict(q, checkin: str, checkout: str) -> dict:
    return {
        "property": _rate_to_dict(q.property_rate),
        "selected_addons": [
            {
                "id": a.id,
                "name": a.name,
                "category": a.category,
                "price": float(a.price),
                "price_type": a.price_type,
                "total": float(a.total(q.property_rate.nights, q.property_rate.guests)),
            }
            for a in q.selected_addons
        ],
        "breakdown": {
            "subtotal_accommodation": float(q.property_rate.subtotal_accommodation),
            "subtotal_addons": float(
                sum(a.total(q.property_rate.nights, q.property_rate.guests) for a in q.selected_addons)
            ),
            "subtotal": float(q.subtotal),
            "gst": float(q.gst),
            "total": float(q.total),
            "advance_percent": q.advance_percent,
            "advance_amount": float(q.advance_amount),
            "currency": q.currency,
        },
        "whatsapp_message": q.whatsapp_message(checkin, checkout),
    }
