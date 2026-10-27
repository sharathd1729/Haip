"""The ops WhatsApp template pack (docs/ops/OPS_MODULE_PLAN.md §5).

Every tenant sends from its OWN WhatsApp Business Account, so each tenant has to get these approved by Meta before alerts can
go out on WhatsApp. POST /ops/templates/install creates them as local drafts; they are then submitted with the existing template
editor (POST /messaging/templates/{id}/submit). Until a template is APPROVED, alerts that need it fail loudly and fall back to push.

Body variables (same order for both):
  {{1}} severity label   {{2}} item title   {{3}} property   {{4}} details   {{5}} respond-by time
Buttons: quick replies "Acknowledge" (index 0) and "Can't take it" (index 1); the per-send payload identifies the alert.
A wording change = a new template name (_v2), never an edit of an approved one.
"""

from __future__ import annotations

_BUTTONS = {
    "type": "BUTTONS",
    "buttons": [
        {"type": "QUICK_REPLY", "text": "Acknowledge"},
        {"type": "QUICK_REPLY", "text": "Can't take it"},
    ],
}
_EXAMPLE = [
    [
        "HIGH",
        "AC not working",
        "Ratha 1",
        "Guest reports the AC stopped at 9:40 pm",
        "10:05 pm, 18 Oct",
    ]
]

PACK: dict[str, dict] = {
    "ops_alert_v1": {
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": "Ops alert ({{1}}): {{2}} at {{3}}.\nDetails: {{4}}\nPlease respond by {{5}}.",
                "example": {"body_text": _EXAMPLE},
            },
            {"type": "FOOTER", "text": "Tap a button to respond"},
            _BUTTONS,
        ],
    },
    "ops_escalation_v1": {
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": "Escalated ({{1}}): {{2}} at {{3}} was not picked up in time.\nDetails: {{4}}\nPlease respond by {{5}}.",
                "example": {"body_text": _EXAMPLE},
            },
            {"type": "FOOTER", "text": "Tap a button to respond"},
            _BUTTONS,
        ],
    },
}

ACK_INDEX, DECLINE_INDEX = 0, 1
