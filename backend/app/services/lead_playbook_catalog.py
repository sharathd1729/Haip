"""The ready-made lead playbooks: what each one watches for, what it does, when it stops, and its default settings.

Playbooks are code, not data: an owner switches one on or off and changes its timings (lead_playbook_settings), but cannot
invent a new trigger or action. That keeps every automatic message reviewable and guarded (lead_playbook_guards).

``built`` says whether this release runs the playbook. The Workflows page lists the others as "coming next" so the owner
sees the whole plan; their switches are refused until they ship.
"""
from __future__ import annotations

MISSED_INBOUND_CALL = "missed_inbound_call"
UNANSWERED_OUTBOUND = "unanswered_outbound"
CALLBACK_REQUESTED = "callback_requested"
NEW_LEAD_ALERT = "new_lead_alert"
SLA_ESCALATION = "sla_escalation"
PROPOSAL_FOLLOWUP = "proposal_followup"
QUIET_LEAD_NURTURE = "quiet_lead_nurture"
LOST_REENGAGE = "lost_reengage"

FOLLOWUP_MODES = ("tasks", "drafts", "autopilot")      # "off" is the playbook's own switch

CATALOG: list[dict] = [
    {
        "key": MISSED_INBOUND_CALL, "code": "P1", "built": True, "kind": "guest_message",
        "name": "Missed call: WhatsApp the guest",
        "trigger": "A guest calls and nobody picks up.",
        "actions": ["WhatsApp the guest within a minute: sorry we missed you, reply here, we'll call back",
                    "Add a callback task for the lead's owner (due in 15 minutes, or 9:30 am if after hours)",
                    "Push the lead's owner (or the team when nobody owns it)"],
        "stops": "Someone already called back or messaged the guest, the guest is booked or the lead is closed.",
        "template": "haip_missed_call_v1",
        "defaults": {"enabled": False, "delay_seconds": 45, "callback_minutes": 15},
    },
    {
        "key": UNANSWERED_OUTBOUND, "code": "P2", "built": True, "kind": "guest_message",
        "name": "No answer: WhatsApp the guest",
        "trigger": "An agent calls a lead and nobody picks up.",
        "actions": ["WhatsApp the guest: we tried calling, we can share the details and proposal here",
                    "Keep the existing 'Call back' reminder for the agent"],
        "stops": "The guest picked up a later call or replied, someone messaged them, booked or closed.",
        "template": "haip_tried_calling_v1",
        "defaults": {"enabled": False, "delay_seconds": 45},
    },
    {
        "key": CALLBACK_REQUESTED, "code": "P7", "built": True, "kind": "task",
        "name": "Guest asks for a call back",
        "trigger": "The guest taps 'Call me back' on one of these WhatsApps.",
        "actions": ["Reply 'Sure, we'll call you shortly'", "Add a high-priority callback task due in 15 minutes",
                    "Push the lead's owner, and WhatsApp them when team alerts are set up"],
        "stops": "Runs once per tap.",
        "template": None,
        "defaults": {"enabled": True, "callback_minutes": 15},
    },
    {
        "key": NEW_LEAD_ALERT, "code": "P3", "built": True, "kind": "alert",
        "name": "New lead not contacted: alert the team",
        "trigger": "A new lead nobody has contacted yet (My day 'New lead').",
        "actions": ["Late (15 min): push + WhatsApp the lead's owner (managers when nobody owns it)",
                    "Urgent (1 h): the managers", "Critical (4 h): the owners",
                    "Buttons on the WhatsApp: Acknowledge, or I'll take it (the lead becomes yours)"],
        "stops": "A person contacts the guest.",
        "template": "haip_staff_lead_alert_v1",
        "defaults": {"enabled": False},
    },
    {
        "key": SLA_ESCALATION, "code": "P4", "built": True, "kind": "alert",
        "name": "Waiting too long: escalate",
        "trigger": "A lead waiting for a reply (30 min) or a missed call to return (30 min) is still waiting.",
        "actions": ["Late: the lead's owner", "Urgent (2 h): the managers", "Critical (8 h): the owners",
                    "Same WhatsApp buttons: Acknowledge, or I'll take it"],
        "stops": "The item leaves My day.",
        "template": "haip_staff_escalation_v1",
        "defaults": {"enabled": False},
    },
    {
        "key": PROPOSAL_FOLLOWUP, "code": "P5", "built": True, "kind": "followup",
        "name": "Proposal follow-up",
        "trigger": "A quote is shared with the guest.",
        "actions": ["6 h with no reply: a follow-up (a task, an AI draft to approve, or sent automatically, by mode)",
                    "Day 3: a call task for the lead's owner", "Day 7: a last-call message (valid until ...)",
                    "Day 8: a task to decide won or lost (with the reason)"],
        "stops": "The guest replies, books, or the lead is lost or paused.",
        "template": "haip_quote_followup_v1",
        "defaults": {"enabled": False, "mode": "drafts"},
    },
    {
        "key": QUIET_LEAD_NURTURE, "code": "P6", "built": True, "kind": "followup",
        "name": "Quiet lead follow-up",
        "trigger": "We wrote last and the guest has been quiet for a day (no quote yet).",
        "actions": ["Day 1: a follow-up (a task, an AI draft to approve, or sent automatically, by mode)",
                    "Day 3: a check-in message", "Day 7: a task to decide: still interested, or lost (with the reason)"],
        "stops": "The guest replies or the lead is closed.",
        "template": "haip_checkin_v1",
        "defaults": {"enabled": False, "mode": "drafts"},
    },
    {
        "key": LOST_REENGAGE, "code": "P8", "built": True, "kind": "followup",
        "name": "Win back lost leads",
        "trigger": "45 days after a lead was lost, only if the guest agreed to offers.",
        "actions": ["One offer message (a MARKETING template), at most every 90 days per guest"],
        "stops": "Any reply or a new enquiry.",
        "template": "haip_reengage_v1",
        "defaults": {"enabled": False, "mode": "autopilot"},
    },
]

BY_KEY = {p["key"]: p for p in CATALOG}
BUILT = {p["key"] for p in CATALOG if p["built"]}

# Each playbook guest WhatsApp counts toward one shared cap per guest, so a guest who misses two calls in a row gets one
# message, not two.
GUEST_MESSAGE_PLAYBOOKS = (MISSED_INBOUND_CALL, UNANSWERED_OUTBOUND, CALLBACK_REQUESTED)

# Defaults for the workspace-wide part of the settings.
WORKSPACE_DEFAULTS = {"enabled": True, "guest_cap_hours": 4, "daily_cap": 150, "bridge_quiet_minutes": 120,
                      # Team alerts (P3/P4/P7): WhatsApp to staff who opted in, held during quiet hours (local time) and
                      # sent as one morning summary instead.
                      "staff_whatsapp": True, "quiet_start_hour": 22, "quiet_end_hour": 8}

FOLLOWUP_PLAYBOOKS = (PROPOSAL_FOLLOWUP, QUIET_LEAD_NURTURE, LOST_REENGAGE)

ALERT_PLAYBOOKS = {NEW_LEAD_ALERT: ("new_lead",), SLA_ESCALATION: ("reply", "callback")}
