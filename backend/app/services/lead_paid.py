"""Paid vs organic, per lead (CRM reporting, 22 Oct 2026). Derived on read; stored sources are never changed.

  paid      an ad referral was recorded for the lead (``lead_attribution.source_type == 'ad'``; older rows with no
            source_type but an ad id count too), or the enquiry came in as Click-to-WhatsApp with an ad referral on the
            guest's conversation
  organic   a referral was recorded but it was a post / story, or the enquiry's own source is a non-ad channel the guest
            reached by themselves (direct WhatsApp, website, Google, walk-in, referral, organic call ...)
  unknown   nothing says either way -- a plain inbound call, a manual lead with no source, an OTA. Calls stay unknown unless
            an attribution row ties them to an ad.

``ad_attribution_sql`` is the ONE "this referral was an ad" test: the owner dashboard's Meta-ads block uses it too, so an
organic post referral is never counted as an ad lead.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry, InquirySource
from app.models.lead_attribution import LeadAttribution

PAID, ORGANIC, UNKNOWN = "paid", "organic", "unknown"
VALUES = (PAID, ORGANIC, UNKNOWN)

# A guest who reached us on their own through these channels, with no ad behind it.
ORGANIC_SOURCES = {"wa_direct", "website", "google", "walk_in", "referral", "email", "organic_call", "meta_ig", "meta_fb", "web_chat"}


def ad_attribution_sql():
    return or_(LeadAttribution.source_type == "ad",
               and_(LeadAttribution.source_type.is_(None), LeadAttribution.ad_id.isnot(None)))


def _src(inq: Inquiry) -> str:
    return str(getattr(inq.source, "value", inq.source) or "").lower()


def classify(db: Session, tenant_id: str, inquiries: Iterable[Inquiry]) -> dict[str, str]:
    """{inquiry_id: paid | organic | unknown}. Two queries for the whole page (attribution rows by enquiry, then by the
    guests of the enquiries with none), none per lead."""
    inqs = [i for i in inquiries if i is not None]
    if not inqs:
        return {}
    ids = [i.id for i in inqs]
    rows = db.query(LeadAttribution.inquiry_id, LeadAttribution.guest_id, LeadAttribution.source_type, LeadAttribution.ad_id).filter(
        LeadAttribution.tenant_id == tenant_id,
        or_(LeadAttribution.inquiry_id.in_(ids), LeadAttribution.guest_id.in_([i.guest_id for i in inqs if i.guest_id]))).all()
    by_inq: dict[str, set] = {}
    by_guest: dict[str, set] = {}
    for inquiry_id, guest_id, source_type, ad_id in rows:
        kind = PAID if (source_type == "ad" or (source_type is None and ad_id)) else ORGANIC
        if inquiry_id:
            by_inq.setdefault(inquiry_id, set()).add(kind)
        elif guest_id:
            by_guest.setdefault(guest_id, set()).add(kind)
    out = {}
    for i in inqs:
        kinds = by_inq.get(i.id)
        if not kinds and _src(i) == InquirySource.CLICK_TO_WA.value and PAID in by_guest.get(i.guest_id, set()):
            kinds = {PAID}   # a Click-to-WhatsApp enquiry whose ad referral landed on the guest's chat before the lead existed
        if kinds:
            out[i.id] = PAID if PAID in kinds else ORGANIC
        elif _src(i) in ORGANIC_SOURCES:
            out[i.id] = ORGANIC
        else:
            out[i.id] = UNKNOWN
    return out


def filter_sql(db: Session, tenant_id: str, value: str):
    """A WHERE clause on Inquiry for the Leads/report filter "Came from". Mirrors ``classify``."""
    from sqlalchemy import exists, select
    ad = exists(select(LeadAttribution.id).where(LeadAttribution.tenant_id == tenant_id, LeadAttribution.inquiry_id == Inquiry.id,
                                                  ad_attribution_sql()))
    ad_guest = and_(Inquiry.source == InquirySource.CLICK_TO_WA, exists(select(LeadAttribution.id).where(
        LeadAttribution.tenant_id == tenant_id, LeadAttribution.inquiry_id.is_(None), LeadAttribution.guest_id == Inquiry.guest_id,
        ad_attribution_sql())))
    any_row = exists(select(LeadAttribution.id).where(LeadAttribution.tenant_id == tenant_id, LeadAttribution.inquiry_id == Inquiry.id))
    paid = or_(ad, ad_guest)
    organic_src = [s for s in InquirySource if s.value in ORGANIC_SOURCES]
    if value == PAID:
        return paid
    if value == ORGANIC:
        return and_(~paid, or_(any_row, Inquiry.source.in_(organic_src)))
    return and_(~paid, ~any_row, or_(Inquiry.source.is_(None), Inquiry.source.notin_(organic_src)))
