"""Tax invoices, payment receipts and their number series (migration 141).

An issued document never changes: its lines, totals, seller and buyer are snapshots taken when it was issued. A
correction is a NEW document with a new number ("Reissue"); the old one is marked superseded. Numbers come from
``invoice_sequences`` (one row per tenant, financial year and prefix), advanced with a single guarded UPDATE inside the
issuing transaction, so two writers can never get the same number and a rolled-back issue gives its number back.
"""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class Invoice(Base, TimestampMixin, TenantMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_invoices_tenant_number"),
        Index("ix_invoices_tenant_stay", "tenant_id", "stay_id"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    # SET NULL, not CASCADE: GST law requires keeping issued invoices, so a DPDP erasure of the booking detaches them.
    stay_id = Column(String, ForeignKey("stays.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(12), nullable=False, default="invoice")          # invoice | receipt | credit_note
    number = Column(String(40), nullable=False)                           # INV/2026-27/0001
    financial_year = Column(String(7), nullable=False)                    # 2026-27
    status = Column(String(12), nullable=False, default="issued")         # issued | superseded | void
    currency = Column(String(3), nullable=False, default="INR")
    gst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    taxable_value = Column(Numeric(12, 2), nullable=False, default=0)
    cgst = Column(Numeric(12, 2), nullable=False, default=0)
    sgst = Column(Numeric(12, 2), nullable=False, default=0)
    igst = Column(Numeric(12, 2), nullable=False, default=0)
    total = Column(Numeric(12, 2), nullable=False, default=0)             # invoice: booking total incl. GST; receipt: amount received
    amount_received = Column(Numeric(12, 2), nullable=False, default=0)   # received to date when issued
    balance_due = Column(Numeric(12, 2), nullable=False, default=0)
    place_of_supply = Column(String(2), nullable=True)
    lines = Column(JSON, nullable=False, default=list)                    # [{description, detail, quantity, amount, taxable}]
    seller = Column(JSON, nullable=False, default=dict)                   # snapshot of brand_config.invoice_profile
    buyer = Column(JSON, nullable=False, default=dict)                    # snapshot of the guest (name, phone, email, gstin)
    booking_ref = Column(String(40), nullable=True)
    pdf_media_key = Column(String(300), nullable=True)                    # set by the invoices.render_pdf task
    supersedes_id = Column(String, nullable=True, index=True)
    invoice_id = Column(String, nullable=True)                            # receipt: the invoice it is against
    payment_id = Column(String, nullable=True, index=True)                # the StayPayment that triggered it (receipt: that it records)
    notes = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)
    issued_at = Column(DateTime(timezone=True), nullable=False)


class InvoiceSequence(Base, TimestampMixin, TenantMixin):
    __tablename__ = "invoice_sequences"
    __table_args__ = (UniqueConstraint("tenant_id", "financial_year", "prefix", name="uq_invoice_sequences_series"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    financial_year = Column(String(7), nullable=False)
    prefix = Column(String(10), nullable=False)
    next_number = Column(Integer, nullable=False, default=1)
