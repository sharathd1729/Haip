"""The ops WhatsApp template pack (docs/ops/OPS_MODULE_PLAN.md §5).

Every tenant sends from its OWN WhatsApp Business Account, so each tenant has to get these approved by Meta before alerts can
go out on WhatsApp. POST /ops/templates/install creates them as local drafts; they are then submitted with the existing template
editor (POST /messaging/templates/{id}/submit). Until a template is APPROVED, alerts that need it fail loudly and fall back to push.

Body variables (same order for both):
  {{1}} severity label   {{2}} item title   {{3}} property   {{4}} details   {{5}} respond-by time
Buttons: quick replies "Acknowledge" (index 0) and "Can't take it" (index 1); the per-send payload identifies the alert.
A wording change = a new template name (_v2), never an edit of an approved one.

Trip messages (phase 2, ops_auto_messages; no buttons; used only when the 24-hour window is closed, else the same words go
as plain text):
  ops_crew_brief_v1     driver + helper, 72 h before: {{1}} vehicle {{2}} pickup {{3}} route + stops {{4}} guest first name
                        {{5}} guests {{6}} special requests
  ops_helper_chase_v1   helper, 24 h before: {{1}} vehicle {{2}} pickup {{3}} checklist photos still missing
  ops_guest_pretrip_v1  the guest, 24 h before: {{1}} first name {{2}} vehicle {{3}} driver {{4}} reporting time
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


def _trip(text: str, example: list[str]) -> dict:
    return {
        "category": "UTILITY",
        "components": [{"type": "BODY", "text": text, "example": {"body_text": [example]}}],
    }


PACK |= {
    "ops_crew_brief_v1": _trip(
        "Trip brief for {{1}}.\nPickup: {{2}}\nRoute: {{3}}\nGuest: {{4}} ({{5}})\nRequests: {{6}}\n"
        "Send checklist photos with the check's name, for example: ac.",
        ["Ratha 1", "Sat 1 Nov, 7:00 am", "Bangalore - Coorg - Bangalore", "Asha", "6 adults + 2 kids", "Birthday cake"],
    ),
    "ops_helper_chase_v1": _trip(
        "Reminder: {{1}} leaves {{2}}. Checklist photos still needed: {{3}}. Send each photo with its name, for example: ac.",
        ["Ratha 1", "Sat 1 Nov, 7:00 am", "AC, Water, Safety"],
    ),
    "ops_guest_pretrip_v1": _trip(
        "Hello {{1}}, your {{2}} is ready.\nDriver: {{3}}\nReporting time: {{4}}\nSafe travels!",
        ["Asha", "Ratha 1", "Ravi", "Sat 1 Nov, 7:00 am"],
    ),
}

ACK_INDEX, DECLINE_INDEX = 0, 1
