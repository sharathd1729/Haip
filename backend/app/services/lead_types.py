"""Lead type (migration 169): who the enquiry is from, so guest KPIs count guests (CRM reporting, 22 Oct 2026).

  guest     a traveller asking for themselves (default; every enquiry before 22 Oct 2026)
  b2b       a business buying for its clients: wedding/event planner, travel agent, tour operator, DMC, reseller, agency.
            Set automatically at chat auto-create from the MESSAGE text (lead_auto_create.lead_type_for_message: the
            collaboration keywords, or the trade words below); never from a name. Staff can change it on the lead page.
  partner   a collaboration / creator / supplier contact (staff set it)

Only ``guest`` enquiries count in the guest lead KPIs (lead_metrics.people, kpi_metrics.lead_filters, the work queue's
new_lead, the dashboard funnel, report totals). A person counts as a guest lead unless EVERY enquiry they have is non-guest.
"""
from __future__ import annotations

from sqlalchemy import func

GUEST, B2B, PARTNER = "guest", "b2b", "partner"
LEAD_TYPES = (GUEST, B2B, PARTNER)
LABELS = {GUEST: "Guest", B2B: "B2B / trade", PARTNER: "Partner"}


def is_guest_sql(column):
    """A NULL type is a guest (rows written before the column, or by raw SQL)."""
    return func.coalesce(column, GUEST) == GUEST


def is_guest(value) -> bool:
    return (value or GUEST) == GUEST
