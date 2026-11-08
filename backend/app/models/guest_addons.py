"""Guest add-ons bought from a private link (migration 192; services/guest_addons.py)."""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Numeric, String, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class GuestAddonLink(Base, TimestampMixin, TenantMixin):
    """One private add-ons link per stay. Only the token's SHA-256 is stored; the token is an HMAC of id + nonce."""

    __tablename__ = "guest_addon_links"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    stay_id = Column(String, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False)
    nonce = Column(String(32), nullable=False)
    token_hash = Column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("stay_id", name="uq_guest_addon_links_stay"),
        UniqueConstraint("token_hash", name="uq_guest_addon_links_token"),
    )


class GuestAddonOrder(Base, TimestampMixin, TenantMixin):
    """What a guest picked. status: awaiting_approval -> awaiting_payment -> paid; or declined / cancelled.
    items = [{addon_id, name, quantity, unit_price, line_total, category, needs_approval, stay_change}]."""

    __tablename__ = "guest_addon_orders"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    stay_id = Column(String, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False)
    items = Column(JSON, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String(20), nullable=False)
    payment_link_id = Column(String, ForeignKey("stay_payment_links.id", ondelete="SET NULL"), nullable=True)
    ops_item_id = Column(String, nullable=True)
    decided_by = Column(String, nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decline_reason = Column(String(200), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("payment_link_id", name="uq_guest_addon_orders_link"),)
