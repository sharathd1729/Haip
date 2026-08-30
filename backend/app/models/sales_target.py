"""Sales targets — the revenue number a tenant, property, or agent is aiming at.

Deliberately stores ONLY the monthly figure. The daily target (and
target-till-date) is derived on read by targets_service, never stored:
a month's daily target is monthly / days_in_month, so persisting 31 rows
per target would create 31 chances for the stored copies to drift out of
sync with the monthly number the owner actually edits.

Revenue is NOT stored here. It is read from `stays` at query time --
see sales_performance_service. The link back to who sold it is
Stay.inquiry_id -> Inquiry.assigned_to, which inquiry_service already
populates when a lead is moved to a closed-won stage.
"""
from sqlalchemy import Column, String, ForeignKey, Numeric, Date, UniqueConstraint, Index

from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


# scope_type values
SCOPE_TENANT = "tenant"      # whole business
SCOPE_PROPERTY = "property"  # one caravan / villa
SCOPE_AGENT = "agent"        # one salesperson

SCOPE_TYPES = (SCOPE_TENANT, SCOPE_PROPERTY, SCOPE_AGENT)


class SalesTarget(Base, TimestampMixin, TenantMixin):
    __tablename__ = "sales_targets"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    scope_type = Column(String(20), nullable=False)
    # properties.id when scope_type='property', users.id when 'agent',
    # NULL when 'tenant'. Not a real FK because it points at two different
    # tables depending on scope_type -- validated in the service layer.
    scope_id = Column(String, nullable=True, index=True)

    # First day of the month this target covers. Always day 1 -- the month
    # is the unit; storing a full range invites half-month targets that the
    # daily-division maths has no sane answer for.
    period_month = Column(Date, nullable=False, index=True)

    target_amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="INR")

    created_by = Column(String, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        # One target per scope per month. Re-setting a target updates this
        # row rather than accumulating a history of stale numbers that
        # reports would have to guess between.
        UniqueConstraint(
            "tenant_id", "scope_type", "scope_id", "period_month",
            name="uq_sales_target_scope_month",
        ),
        Index("ix_sales_targets_tenant_month", "tenant_id", "period_month"),
    )
