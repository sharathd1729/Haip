"""The AI Executive's detector catalogue (code-defined; docs/ai/AI_EXECUTIVE_ROLES.md). One entry per detector: a short
``code`` (the insights row's category_code, <= 10 chars), the role that owns it, its cadence, the insights category it is
shown under, the next step said in plain words, and the rule (services/chief/detectors.py).

Cadence: ``urgent`` runs every 5 minutes and in the daily pass; ``daily`` only in the 06:30 pass (and on "Check now").
The 11 older insight detectors (A1-D4, insight_detector.py, every 15 min) are not re-run here: their rows are shown on the
Executive page under the role in INSIGHT_ROLES.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.services.chief import detectors as d


@dataclass(frozen=True)
class Detector:
    code: str
    role: str
    cadence: str
    category: str  # InsightCategory value
    next_step: str
    rule: Callable


CATALOGUE: tuple[Detector, ...] = (
    Detector(
        "SA1",
        "sales_manager",
        "urgent",
        "urgency",
        "Reply to the people waiting longest, and switch on team WhatsApp alerts so new leads reach the team.",
        d.sales_unattended,
    ),
    Detector(
        "SA2",
        "sales_manager",
        "urgent",
        "urgency",
        "Give each lead an owner, or ask the team to tap Take it.",
        d.sales_unowned,
    ),
    Detector(
        "SA8",
        "sales_manager",
        "daily",
        "revenue",
        "Call these leads today, before they book elsewhere.",
        d.sales_at_risk,
    ),
    Detector(
        "SA6",
        "sales_manager",
        "daily",
        "revenue",
        "Look at the leads lost for this reason and fix what they have in common.",
        d.sales_lost_cluster,
    ),
    Detector(
        "CO5",
        "concierge",
        "urgent",
        "urgency",
        "Answer the waiting questions, complaints first.",
        d.concierge_consults_waiting,
    ),
    Detector(
        "CO2",
        "concierge",
        "daily",
        "quality",
        "Check the inbox more often, or let the AI answer simple questions itself.",
        d.concierge_drafts_expired,
    ),
    Detector(
        "CO4",
        "concierge",
        "urgent",
        "quality",
        "Ask the team member to link their WhatsApp again from the QR screen.",
        d.concierge_bridge_down,
    ),
    Detector(
        "OP2", "ops_manager", "urgent", "urgency", "Open Ops today and sort the red items first.", d.ops_red_needs
    ),
    Detector(
        "OP1",
        "finance",
        "daily",
        "revenue",
        "Send the balance reminder or call the guest before they arrive.",
        d.finance_arrivals_owing,
    ),
    Detector(
        "TE4",
        "it_monitor",
        "urgent",
        "quality",
        "Check the calendar link with the channel and paste a fresh one.",
        d.it_ical_failing,
    ),
    Detector(
        "TE6",
        "it_monitor",
        "urgent",
        "quality",
        "See the failure reasons and fix the template or the numbers.",
        d.it_auto_messages_failing,
    ),
    Detector(
        "MK3",
        "ads_analyst",
        "daily",
        "quality",
        "Replace the token in Meta Business Settings before it ends.",
        d.ads_token_expiring,
    ),
    Detector(
        "MK5",
        "ads_analyst",
        "daily",
        "revenue",
        "Subscribe the Meta app to messaging_referral so every ad chat is traced.",
        d.ads_attribution_gap,
    ),
    Detector(
        "OW3",
        "data_analyst",
        "daily",
        "revenue",
        "Ask the analyst why, then check where leads usually come from.",
        d.owner_leads_down,
    ),
    Detector(
        "OW3B",
        "data_analyst",
        "daily",
        "revenue",
        "Check quotes and follow-ups for the leads of the last two weeks.",
        d.owner_bookings_down,
    ),
)
BY_CODE = {det.code: det for det in CATALOGUE}

# Older insight detectors (insight_detector.py) -> the role that shows them.
INSIGHT_ROLES = {
    "A1": "sales_manager",
    "A2": "sales_manager",
    "A4": "sales_manager",
    "C2": "sales_manager",
    "A3": "guest_relations",
    "C1": "guest_relations",
    "B1": "revenue_manager",
    "B3": "revenue_manager",
    "C3": "revenue_manager",
    "D3": "it_monitor",
    "D4": "hr_coach",
}


def role_of(code: str, stored: str | None = None) -> str:
    if stored:
        return stored
    det = BY_CODE.get(code)
    return det.role if det else INSIGHT_ROLES.get(code, "data_analyst")


def runs_in(det: Detector, cadence: str) -> bool:
    return cadence == "daily" or det.cadence == "urgent"
