from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


# ─── Room ─────────────────────────────────────────────────────────────────────

class RoomOut(BaseModel):
    id: str
    tenant_id: str
    property_id: str
    room_number: str
    room_type: str = "standard"
    floor: Optional[int] = None
    capacity: int = 2
    amenities: List[Any] = []
    is_active: bool = True

    class Config:
        from_attributes = True


class RoomCreateRequest(BaseModel):
    room_number: str
    room_type: Optional[str] = "standard"
    floor: Optional[int] = None
    capacity: Optional[int] = 2
    amenities: Optional[List[str]] = []


class RoomUpdateRequest(BaseModel):
    room_number: Optional[str] = None
    room_type: Optional[str] = None
    floor: Optional[int] = None
    capacity: Optional[int] = None
    amenities: Optional[List[str]] = None
    is_active: Optional[bool] = None


# ─── Property ─────────────────────────────────────────────────────────────────

class PropertyOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    slug: str
    type: Optional[str] = "villa"
    is_active: bool = True
    city: Optional[str] = None
    state: Optional[str] = None
    address: Optional[str] = None
    max_adults: int = 2
    max_children: int = 0
    bedrooms: int = 1
    bathrooms: int = 1
    description: Optional[str] = None
    brand_voice: Optional[str] = None
    amenities: List[Any] = []
    photos: List[Any] = []

    # Caravan fields
    vehicle_name: Optional[str] = None
    vehicle_type: Optional[str] = None
    home_base: Optional[str] = None
    routes: List[Any] = []
    price_per_day: Optional[float] = None
    price_per_km: Optional[float] = None
    driver_included: bool = True
    seats: Optional[int] = None

    # Channel manager
    channel_source: Optional[str] = None
    channel_manager_listing_id: Optional[str] = None

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PropertyCreateRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    type: Optional[str] = "villa"
    city: Optional[str] = None
    state: Optional[str] = None
    address: Optional[str] = None
    max_adults: Optional[int] = 2
    max_children: Optional[int] = 0
    bedrooms: Optional[int] = 1
    bathrooms: Optional[int] = 1
    description: Optional[str] = None

    # Caravan fields
    vehicle_name: Optional[str] = None
    vehicle_type: Optional[str] = None
    home_base: Optional[str] = None
    routes: Optional[List[Any]] = []
    price_per_day: Optional[float] = None
    price_per_km: Optional[float] = None
    driver_included: Optional[bool] = True
    seats: Optional[int] = None


class PropertyUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None
    max_adults: Optional[int] = None
    max_children: Optional[int] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    description: Optional[str] = None
    brand_voice: Optional[str] = None

    # Caravan fields
    vehicle_name: Optional[str] = None
    vehicle_type: Optional[str] = None
    home_base: Optional[str] = None
    routes: Optional[List[Any]] = None
    price_per_day: Optional[float] = None
    price_per_km: Optional[float] = None
    driver_included: Optional[bool] = None
    seats: Optional[int] = None
