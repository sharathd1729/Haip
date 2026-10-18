"""Money and extras attached to a booking (Stay).

A booking's amount owed is the stay charge (Stay.total_amount, unchanged so
existing revenue reports keep their meaning) plus its add-on lines. What has
been received is the ledger of StayPayment rows, so "paid / outstanding" is
computed from recorded payments, never guessed from the booking status.
"""
from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text

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
    # One row per provider payment id (migrations 110 and 141). The Razorpay webhook relies on this index: a retried
    # delivery hits IntegrityError and is answered as a duplicate. Declared here too so create_all builds it.
    __table_args__ = (
        Index("uq_stay_payments_external", "tenant_id", "external_id", unique=True,
              postgresql_where=text("external_id IS NOT NULL"), sqlite_where=text("external_id IS NOT NULL")),
    )

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
    guest pays, the provider webhook hands it to payment_events_service.on_payment_link_paid.

    A link belongs to a booking (stay_id) or, from migration 141, to a quote (inquiry_quote_id, no stay yet). A quote
    link that gets paid does not make a booking by itself: it raises a staff task until the quote builder's
    "create booking from quote" step is wired in (see on_payment_link_paid)."""
    __tablename__ = "stay_payment_links"
    __table_args__ = (CheckConstraint("stay_id IS NOT NULL OR inquiry_quote_id IS NOT NULL", name="ck_stay_payment_links_owner"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    stay_id = Column(String, ForeignKey("stays.id", ondelete="CASCADE"), nullable=True, index=True)
    inquiry_quote_id = Column(String, ForeignKey("inquiry_quotes.id", ondelete="SET NULL"), nullable=True, index=True)
    provider = Column(String(20), nullable=False, default="razorpay")
    external_id = Column(String(64), nullable=False)                   # plink_xxx
    short_url = Column(String(300), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(20), nullable=False, default="created")     # created | paid | expired | cancelled
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String, nullable=True)


class StayInstalment(Base, TimestampMixin, TenantMixin):
    """One step of a booking's payment plan (e.g. 30% advance, balance 7 days
    before check-in). Whether it is paid is derived by applying the booking's
    recorded payments to the instalments in due-date order, so there is no status
    to keep in sync."""
    __tablename__ = "stay_instalments"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    stay_id = Column(String, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(80), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    due_date = Column(Date, nullable=False)


class StayDeposit(Base, TimestampMixin, TenantMixin):
    """Refundable security / damage deposit, one per booking. Deliberately not part
    of the stay total or the payment ledger: it is held, then released (less any
    damage deducted) or forfeited, and never counts as revenue."""
    __tablename__ = "stay_deposits"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    stay_id = Column(String, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False, unique=True)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(12), nullable=False, default="pending")   # pending | held | released | forfeited
    deducted = Column(Numeric(12, 2), nullable=False, default=0)     # damage kept when released
    method = Column(String(20), nullable=True)
    collected_on = Column(Date, nullable=True)
    resolved_on = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)


class StayServiceRequest(Base, TimestampMixin, TenantMixin):
    """A thing the team must do for this booking (extra bed, late checkout, cab).
    Mirrored as a Task so it shows on the assignee's My Day; task_id links them."""
    __tablename__ = "stay_service_requests"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    stay_id = Column(String, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    notes = Column(Text, nullable=True)
    status = Column(String(10), nullable=False, default="open")      # open | done
    assigned_to = Column(String, nullable=True)
    due_date = Column(Date, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    task_id = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
