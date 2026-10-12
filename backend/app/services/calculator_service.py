"""
Rate Calculator Service.

Resolves rates for properties + caravans given dates, guests, and tenant.
Rate priority:
  1. SeasonalRate (date range match, highest priority wins)
  2. SeasonalRate.occupancy_pricing override within matched range
  3. RatePlan base_price_per_night
  4. Property.price_per_day (caravans)

For channel-manager properties: attempts live rate fetch first, falls back to HAIP rates.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.property import Property, PropertyAddOn, RatePlan, SeasonalRate
from app.models.property import Stay, BlockedDate

log = logging.getLogger(__name__)

GST_RATE = Decimal("0.12")  # 12% GST on accommodation


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class AddOnItem:
    id: str
    name: str
    description: str
    category: str
    price: Decimal
    price_type: str          # per_stay | per_night | per_person | per_unit
    currency: str = "INR"
    quantity: int = 1        # for per_unit items
    selected: bool = False

    def total(self, nights: int, guests: int) -> Decimal:
        if self.price_type == "per_night":
            return self.price * nights * self.quantity
        if self.price_type == "per_person":
            return self.price * guests * self.quantity
        return self.price * self.quantity  # per_stay or per_unit


@dataclass
class PropertyRate:
    property_id: str
    property_name: str
    property_type: str
    city: str
    address: str
    bedrooms: int
    bathrooms: int
    max_adults: int
    photos: list
    amenities: list
    available: bool
    nights: int
    guests: int
    price_per_night: Decimal
    subtotal_accommodation: Decimal
    currency: str = "INR"
    rate_source: str = "manual"      # manual | seasonal | channel_manager
    rate_name: str = ""              # e.g. "Christmas Peak"
    min_nights: int = 1
    addons: list[AddOnItem] = field(default_factory=list)

    # Caravan specific
    is_caravan: bool = False
    vehicle_name: str = ""
    vehicle_type: str = ""
    home_base: str = ""


@dataclass
class QuoteBreakdown:
    property_rate: PropertyRate
    selected_addons: list[AddOnItem]
    subtotal: Decimal
    gst: Decimal
    total: Decimal
    advance_amount: Decimal          # 30% default
    advance_percent: int = 30
    currency: str = "INR"

    def whatsapp_message(
        self,
        checkin: str,
        checkout: str,
        guest_name: str = "",
    ) -> str:
        """Generate formatted WhatsApp message."""
        pr = self.property_rate
        stay_label = f"{pr.nights} Night{'s' if pr.nights > 1 else ''} Stay" if pr.nights > 0 else "Same-Day Experience"
        accommodation_label = (
            f"{pr.nights} × ₹{int(pr.price_per_night):,}" if pr.nights > 0
            else f"Same-day rate: ₹{int(pr.price_per_night):,}"
        )
        lines = [
            f"*{pr.property_name} — {stay_label}* 🏡",
            "",
            f"📅 Check-in: {checkin}  |  Check-out: {checkout}",
            f"👥 {pr.guests} Guest{'s' if pr.guests > 1 else ''}",
            "",
            "*Rate Breakdown:*",
            f"🏠 Accommodation ({accommodation_label})  =  ₹{int(pr.subtotal_accommodation):,}",
        ]

        emoji_map = {
            "meal": "🍽️",
            "transfer": "🚗",
            "experience": "✨",
            "stay": "🛏️",
            "other": "📦",
        }
        for addon in self.selected_addons:
            em = emoji_map.get(addon.category, "•")
            addon_total = addon.total(pr.nights, pr.guests)
            lines.append(f"{em} {addon.name:<30} ₹{int(addon_total):,}")

        lines += [
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"Subtotal        ₹{int(self.subtotal):,}",
            f"GST (12%)       ₹{int(self.gst):,}",
            f"*Total          ₹{int(self.total):,}* ✨",
            "",
            f"*Advance ({self.advance_percent}%)*  =  *₹{int(self.advance_amount):,}*",
            "",
        ]
        if guest_name:
            lines.append(f"To confirm your dates, {guest_name.split()[0]}, reply *YES* 🙏")
        else:
            lines.append("To confirm your dates, reply *YES* 🙏")

        return "\n".join(lines)


# ── Core service ──────────────────────────────────────────────────────────────

class CalculatorService:

    def search(
        self,
        db: Session,
        tenant_id: str,
        checkin: str,           # YYYY-MM-DD
        checkout: str,          # YYYY-MM-DD
        adults: int,
        children: int = 0,
        city: str | None = None,
        property_id: str | None = None,
        property_type: str | None = None,   # villa | caravan | hotel | apartment
    ) -> list[PropertyRate]:
        """
        Return all properties matching the search criteria with resolved rates.
        """
        checkin_date = date.fromisoformat(checkin)
        checkout_date = date.fromisoformat(checkout)
        nights = (checkout_date - checkin_date).days
        # nights == 0 (checkin == checkout) is a real product for caravans --
        # Ratha's Full Day / Sunset + Dinner / Sunrise formats are same-
        # calendar-day. Only reject genuinely inverted ranges here; villas
        # still can't resolve a same-day "stay" (_resolve_rate rejects
        # nights <= 0 for non-caravan properties below), so this is a no-op
        # for every non-caravan tenant.
        if nights < 0:
            return []

        # Adults and children are limited separately -- Property carries both
        # max_adults and max_children. Lumping them into one total made
        # max_adults mean "max people", so a party of 8 adults + 1 toddler was
        # refused by an 8-adult caravan. Confirmed live on Ratha: a guest
        # asking about 8 adults plus a toddler was told the limit was "8 in
        # total, regardless of age".
        #
        # max_children == 0 is the column default and reads as "not
        # configured" rather than "children forbidden", so it is not enforced;
        # a property that genuinely caps children sets a real number.
        total_guests = adults + children

        # Build property query
        q = db.query(Property).filter_by(tenant_id=tenant_id, is_active=True)
        if property_id:
            q = q.filter(Property.id == property_id)
        if property_type:
            q = q.filter(Property.type == property_type)
        if city:
            q = q.filter(Property.city.ilike(f"%{city}%"))

        properties = q.all()
        results: list[PropertyRate] = []

        for prop in properties:
            # Capacity check -- adults against max_adults, children against
            # max_children (only when that is actually configured).
            if adults > (prop.max_adults or 0):
                continue
            if prop.max_children and children > prop.max_children:
                continue

            rate = self._resolve_rate(
                db=db,
                prop=prop,
                checkin=checkin,
                checkout=checkout,
                checkin_date=checkin_date,
                nights=nights,
                guests=total_guests,
            )
            if rate is None:
                continue

            # Availability check: skip if a confirmed booking overlaps the dates.
            # (Channel-manager properties already validated live above; we still
            #  double-check the HAIP stays table in case of local bookings too.)
            if not self._is_available(db, str(prop.id), tenant_id, checkin, checkout):
                continue

            # Load add-ons
            addons = self._load_addons(db, prop.id, tenant_id)

            price_per_night, rate_source, rate_name, min_nights = rate
            # A same-day product (nights == 0) still bills one unit, not
            # zero -- `nights` itself is left as the real value (0) below
            # so callers can tell a same-day quote apart from an overnight
            # one (see PropertyRate.nights / whatsapp_message()'s label).
            subtotal = price_per_night * max(nights, 1)

            results.append(PropertyRate(
                property_id=str(prop.id),
                property_name=prop.name,
                property_type=prop.type or "villa",
                city=prop.city or "",
                address=prop.address or "",
                bedrooms=prop.bedrooms or 0,
                bathrooms=prop.bathrooms or 0,
                max_adults=prop.max_adults or 2,
                photos=prop.photos or [],
                amenities=prop.amenities or [],
                available=True,
                nights=nights,
                guests=total_guests,
                price_per_night=price_per_night,
                subtotal_accommodation=subtotal,
                currency="INR",
                rate_source=rate_source,
                rate_name=rate_name,
                min_nights=min_nights,
                addons=addons,
                is_caravan=(prop.type == "caravan"),
                vehicle_name=prop.vehicle_name or "",
                vehicle_type=prop.vehicle_type or "",
                home_base=prop.home_base or "",
            ))

        # Sort: available first, then by price ascending
        results.sort(key=lambda r: r.price_per_night)
        return results

    def build_quote(
        self,
        db: Session,
        tenant_id: str,
        property_id: str,
        checkin: str,
        checkout: str,
        adults: int,
        children: int = 0,
        selected_addon_ids: list[str] | None = None,
        advance_percent: int = 30,
    ) -> QuoteBreakdown | None:
        """Build a full quote with selected add-ons and tax breakdown."""
        results = self.search(
            db=db, tenant_id=tenant_id,
            checkin=checkin, checkout=checkout,
            adults=adults, children=children,
            property_id=property_id,
        )
        if not results:
            return None

        pr = results[0]
        nights = pr.nights
        guests = pr.guests
        selected_ids = set(selected_addon_ids or [])

        selected_addons = []
        for addon in pr.addons:
            if addon.id in selected_ids:
                addon.selected = True
                selected_addons.append(addon)

        addons_total = sum(a.total(nights, guests) for a in selected_addons)
        subtotal = pr.subtotal_accommodation + addons_total
        gst = (subtotal * GST_RATE).quantize(Decimal("1"))
        total = subtotal + gst
        advance = (total * Decimal(advance_percent) / 100).quantize(Decimal("1"))

        return QuoteBreakdown(
            property_rate=pr,
            selected_addons=selected_addons,
            subtotal=subtotal,
            gst=gst,
            total=total,
            advance_amount=advance,
            advance_percent=advance_percent,
            currency="INR",
        )

    def build_route_quote(
        self,
        db: Session,
        tenant_id: str,
        property_id: str,
        from_city: str,
        to_city: str,
    ) -> dict | None:
        """
        Distance/route-based quote for caravan properties (Ratha), separate
        from build_quote()'s per-night model -- search()/build_quote() only
        ever price caravans per-night despite carrying an is_caravan flag
        (verified: no existing code path does km-based pricing). Looks up
        the matching entry in Property.routes ([{"from","to","km"}]) and
        prices it at Property.price_per_km, same GST/advance shape as
        build_quote() for a consistent guest-facing breakdown.

        Returns None if the property isn't a caravan, has no matching route,
        or has no price_per_km set.
        """
        from app.models.property import Property

        prop = db.query(Property).filter_by(id=property_id, tenant_id=tenant_id).first()
        if not prop or prop.type != "caravan" or not prop.price_per_km:
            return None

        route = next(
            (
                r for r in (prop.routes or [])
                if str(r.get("from", "")).strip().lower() == from_city.strip().lower()
                and str(r.get("to", "")).strip().lower() == to_city.strip().lower()
            ),
            None,
        )
        if not route or not route.get("km"):
            return None

        km = Decimal(str(route["km"]))
        subtotal = (km * prop.price_per_km).quantize(Decimal("1"))
        gst = (subtotal * GST_RATE).quantize(Decimal("1"))
        total = subtotal + gst
        advance = (total * Decimal(30) / 100).quantize(Decimal("1"))

        return {
            "property_id": str(prop.id), "property_name": prop.name,
            "from_city": from_city, "to_city": to_city, "km": route["km"],
            "price_per_km": prop.price_per_km,
            "subtotal": subtotal, "gst": gst, "total": total,
            "advance_amount": advance, "advance_percent": 30, "currency": "INR",
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _is_available(
        self,
        db: Session,
        property_id: str,
        tenant_id: str,
        checkin: str,
        checkout: str,
    ) -> bool:
        """
        Return True if no confirmed/checked-in stay OR active manual block
        overlaps the requested [checkin, checkout) window.
        Overlap condition: start < checkout AND end > checkin
        """
        # Check stays table
        conflict = (
            db.query(Stay)
            .filter(
                Stay.property_id == property_id,
                Stay.tenant_id == tenant_id,
                Stay.status.in_(["confirmed", "checked_in"]),
                Stay.check_in < checkout,
                Stay.check_out > checkin,
            )
            .first()
        )
        if conflict:
            return False

        # Check manual blocks
        blocked = (
            db.query(BlockedDate)
            .filter(
                BlockedDate.property_id == property_id,
                BlockedDate.tenant_id == tenant_id,
                BlockedDate.is_active == True,
                BlockedDate.blocked_from < checkout,
                BlockedDate.blocked_to > checkin,
            )
            .first()
        )
        if blocked is not None:
            return False

        # Vehicles sharing a calendar: bookings that have no vehicle yet use up one of them.
        from app.services import vehicle_pool
        try:
            return not vehicle_pool.shortage_days(db, tenant_id, property_id, date.fromisoformat(checkin), date.fromisoformat(checkout))
        except ValueError:
            return True

    def _resolve_rate(
        self,
        db: Session,
        prop: Property,
        checkin: str,
        checkout: str,
        checkin_date: date,
        nights: int,
        guests: int,
    ) -> tuple[Decimal, str, str, int] | None:
        """
        Returns (price_per_night, source, rate_name, min_nights) or None if no rate.
        Priority: SeasonalRate > RatePlan > property.price_per_day
        """

        # Same-day (nights == 0) is only a valid request for caravans (Full
        # Day / Sunset + Dinner / Sunrise formats). A villa "stay" with no
        # nights isn't a real booking -- reproduces the exact pre-existing
        # behaviour (search()'s old `nights <= 0: return []` bail) for every
        # non-caravan property now that search() itself allows nights == 0
        # through to here.
        if prop.type != "caravan" and nights <= 0:
            return None

        # 1. Try channel manager live rates (RentalWise)
        if prop.channel_source == "retalwise" and prop.hostaway_listing_id:
            try:
                live = self._fetch_channel_rate(prop, checkin, checkout, guests)
                if live:
                    return live
            except Exception as exc:
                log.warning("channel_rate_fetch_failed prop=%s err=%s", prop.id, exc)

        # 2. Seasonal rates (date range match)
        seasonal = (
            db.query(SeasonalRate)
            .filter_by(tenant_id=prop.tenant_id, property_id=prop.id, is_active=True)
            .filter(SeasonalRate.date_from <= checkin)
            .filter(SeasonalRate.date_to >= checkin)
            .order_by(SeasonalRate.priority.desc())
            .first()
        )
        if seasonal:
            # Check occupancy-based override
            price = Decimal(str(seasonal.price_per_night))
            if seasonal.occupancy_pricing and isinstance(seasonal.occupancy_pricing, dict):
                for threshold_str, override_price in sorted(
                    seasonal.occupancy_pricing.items(), key=lambda x: int(x[0])
                ):
                    if guests >= int(threshold_str):
                        price = Decimal(str(override_price))
            return price, "seasonal", seasonal.name, seasonal.min_nights

        # 3. Active rate plan
        rate_plan_query = db.query(RatePlan).filter_by(
            tenant_id=prop.tenant_id, property_id=prop.id, is_active=True,
        )
        if prop.type == "caravan":
            # Caravans carry several plans for different products (day /
            # overnight / multi-day) on the SAME property -- match the one
            # for what was actually asked, instead of grabbing whichever
            # row Postgres returns first (confirmed live bug: no ordering
            # meant any of the 3 Ratha plans, including a ₹0 one, could win
            # for any quote). No match for this bucket -> fall through to
            # step 4 (price_per_day) rather than use an unrelated plan.
            duration_type = "same_day" if nights <= 0 else "overnight" if nights == 1 else "multiday"
            rate_plan = rate_plan_query.filter_by(duration_type=duration_type).first()
        else:
            rate_plan = rate_plan_query.first()
        if rate_plan:
            # Check seasonal_pricing JSON overrides within the plan
            price = Decimal(str(rate_plan.base_price_per_night))
            for sp in (rate_plan.seasonal_pricing or []):
                if sp.get("from", "") <= checkin <= sp.get("to", ""):
                    price = Decimal(str(sp["price"]))
                    break
            return price, "manual", rate_plan.name, rate_plan.min_nights

        # 4. Caravan price_per_day
        if prop.price_per_day:
            return Decimal(str(prop.price_per_day)), "manual", "Base rate", 1

        return None  # No rate configured

    def _fetch_channel_rate(
        self, prop: Property, checkin: str, checkout: str, guests: int
    ) -> tuple[Decimal, str, str, int] | None:
        """Attempt live rate fetch from RentalWise."""
        from app.core.database import SessionLocal
        from app.models.integration import Integration
        from app.core.encryption import decrypt_credentials
        from app.adapters.pms.retalwise import RentalwiseAdapter

        db = SessionLocal()
        try:
            integration = db.query(Integration).filter_by(
                tenant_id=prop.tenant_id, kind="retalwise", status="active"
            ).first()
            if not integration or not integration.credentials_kms_blob:
                return None

            creds = decrypt_credentials(integration.credentials_kms_blob)
            config = integration.config or {}
            adapter = RentalwiseAdapter(
                api_token=creds.get("api_token", ""),
                username=creds.get("username", ""),
                password=creds.get("password", ""),
                base_url=config.get("base_url", "https://app.rentalwise.io/rest"),
            )
            # Extract numeric ID from "rw_123" format
            rw_id = (prop.hostaway_listing_id or "").replace("rw_", "")
            if not rw_id:
                return None

            rates = adapter.get_availability(rw_id, checkin, checkout)
            if rates and isinstance(rates, list):
                prices = [
                    Decimal(str(r["rate"]))
                    for r in rates
                    if r.get("rate") and r.get("is_available")
                ]
                if prices:
                    avg_price = sum(prices) / len(prices)
                    return avg_price, "channel_manager", "Live rate (RentalWise)", 1
        except Exception as exc:
            log.warning("retalwise_rate_fetch err=%s", exc)
        finally:
            db.close()
        return None

    def _load_addons(
        self, db: Session, property_id: str, tenant_id: str
    ) -> list[AddOnItem]:
        rows = (
            db.query(PropertyAddOn)
            .filter_by(property_id=property_id, tenant_id=tenant_id, is_active=True)
            .order_by(PropertyAddOn.sort_order)
            .all()
        )
        return [
            AddOnItem(
                id=str(r.id),
                name=r.name,
                description=r.description or "",
                category=r.category or "experience",
                price=Decimal(str(r.price)),
                price_type=r.price_type or "per_stay",
                currency=r.currency or "INR",
            )
            for r in rows
        ]


# Singleton
calculator_service = CalculatorService()
