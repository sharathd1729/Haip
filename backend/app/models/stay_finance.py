"""Money and extras attached to a booking (Stay).

A booking's amount owed is the stay charge (Stay.total_amount, unchanged so
existing revenue reports keep their meaning) plus its add-on lines. What has
been received is the ledger of StayPayment rows, so "paid / outstanding" is
computed from recorded payments, never guessed from the booking status.
"""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class StayAddOn(Base, TimestampMixin, TenantMixin):
    """One add-on line on a booking. Name and price are copied from the property's
    catalog (PropertyAddOn) when added, so later catalog edits never rewrite an
    existing booking. addon_id is NULL for a one-off custom line."""
    __tablename__ = "stay_addons"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    stay_id = Column(String, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False, index=True)
    addon_id = Column(String, nullable=True)
    name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Numeric(10, 2), nullable=False, default=0)
    notes = Column(Text, nullable=True)


class StayPayment(Base, TimestampMixin, TenantMixin):
    """A payment received (kind="payment") or money returned (kind="refund")."""
    __tablename__ = "stay_payments"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    stay_id = Column(String, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(10), nullable=False, default="payment")        # payment | refund
    amount = Column(Numeric(12, 2), nullable=False)                     # always positive
    method = Column(String(20), nullable=False, default="upi")         # cash | upi | card | bank_transfer | razorpay | other
    reference = Column(String(120), nullable=True)                     # UTR / receipt no.
    # Provider payment id (Razorpay pay_xxx) for payments recorded by a webhook;
    # the unique (tenant_id, external_id) index makes webhook retries idempotent.
    external_id = Column(String(64), nullable=True)
    paid_on = Column(Date, nullable=False)
    notes = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)


class StayPaymentLink(Base, TimestampMixin, TenantMixin):
    """A hosted payment link sent to the guest (Razorpay Payment Link). When the
    guest pays, the provider webhook marks it paid and records a StayPayment."""
    __tablename__ = "stay_payment_links"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    stay_id = Column(String, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(20), nullable=False, default="razorpay")
    external_id = Column(String(64), nullable=False)                   # plink_xxx
    short_url = Column(String(300), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(20), nullable=False, default="created")     # created | paid | expired | cancelled
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String, nullable=True)
