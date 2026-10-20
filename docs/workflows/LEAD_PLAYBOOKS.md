# Lead workflows: the playbooks

Ready-made automations that make sure no lead goes unnoticed. Owners and managers switch them on in
**More → Lead workflows** (`/dashboard/workflows`). **Every playbook is off until switched on.** Settings live in
`tenants.brand_config.lead_playbooks` and every change is audited (`workflows.settings_changed`).

Code: `backend/app/services/lead_playbook_*.py`, `lead_alert_*.py`, `lead_followup_*.py`, `lead_journey_tracker.py`,
`wa_lead_pack.py`, `workflow_report_service.py`; Celery `backend/app/workers/tasks/lead_playbooks.py`.

## The playbooks

| # | Playbook | Trigger | What it does | Stops / skips when |
|---|---|---|---|---|
| P1 | Missed call: WhatsApp the guest | A guest calls and nobody picks up | ~45 s later: WhatsApp (text inside the 24 h window, else `haip_missed_call_v1`); high-priority callback task (15 min in business hours, else 09:30); push the owner | someone already called back or messaged, booked, closed |
| P2 | No answer: WhatsApp the guest | An agent's call is not picked up | ~45 s later: "we tried calling" (`haip_tried_calling_v1`); the existing "Call back" reminder stays | the guest picked up a later call or replied, booked, closed |
| P7 | Guest asks for a call back | Tap on "Call me back" / "Call me later" on a P1/P2 message | Short reply, callback task, push + WhatsApp to the owner | once per tap |
| P3 | New lead not contacted | My day "New lead" | Team alert ladder: late (15 min) owner → urgent (1 h) managers → critical (4 h) owners | a person contacts the guest |
| P4 | Waiting too long | My day "Reply" / "Callback" | Same ladder at 30 min / 2 h / 8 h | the item leaves My day |
| P5 | Proposal follow-up | A quote is shared | 6 h message · day 3 call task · day 7 last call · day 8 decide task | the guest replied or spoke on a call, booked, lost, paused |
| P6 | Quiet lead follow-up | My day "No reply" (we wrote last, 24 h silent, no quote) | day 1 follow-up · day 3 check-in · day 7 decide task | same as P5; never while P5 runs for the person |
| P8 | Win back lost leads | Lost 45-60 days ago, guest agreed to offers | One MARKETING message, at most once in 90 days | any reply |

The thresholds of P3/P4 are the work queue's own (`work_queue_service.SLA_MINUTES`): alerts never use a second rule.

## Follow-up modes (P5, P6, P8)

* **Tasks only**: a task for the lead's owner and a push. Nothing goes to the guest.
* **AI drafts** (default): inside the 24 h window an AI-drafted follow-up waits in the inbox for a person to approve
  (router task `lead_followup_draft`, prompt `lead-followup-draft-v1`; a reply with a price, an empty reply or a provider
  error is replaced by the fixed wording), plus a task. Window closed: a task naming the template to send from the inbox.
* **Automatic**: the fixed wording goes by itself (text in the window, else the approved template). Never AI text. At least
  20 h between automatic messages to the same guest. No approved template = a task instead.

Messages to guests from P5/P6/P8 only go between 09:30 and 20:00 local time.

## Safety rules (every guest message)

Checked when the step fires, not when it was scheduled (`lead_playbook_guards.check`):

* the workspace switch and the playbook are on; no old automation rule also messages after calls (conflict shown on the page)
* the lead is not paused (Journey card switch, `POST /leads/{id}/playbooks/pause`)
* a valid WhatsApp number that is not a team member's; the guest did not say STOP
* not booked, lead not closed; nobody contacted the guest since the trigger
* at most one automatic WhatsApp per guest in 4 h (P1/P2/P7) and the workspace's daily cap (default 150)
* never into a personal-WhatsApp chat the agent used in the last 2 hours
* one run per trigger (unique key), one message per run step (idempotency key `pb:{run}:{step}`), approved templates only
* automatic messages carry `messages.sender_kind = "playbook"` and `sent_autonomously`, so they never count as a person's
  contact (the lead stays on My day until a person really reaches them)

## Team alerts (P3, P4, P7)

Everyone gets the app notification. A WhatsApp from the business number goes only to people who turned on
**Lead alerts on my WhatsApp** in their Profile (with a phone on the profile), with the buttons **Acknowledge** and
**I'll take it** (the lead becomes theirs, audited). A tap counts only from the number the alert went to. Messages from an
opted-in staff number are never treated as a guest. Quiet hours (default 22:00-08:00) hold alerts and send one morning
summary per person instead.

## Templates (the "lead pack")

**Create templates** on the Workflows page adds them as drafts; the owner submits each to Meta from the template editor.
A wording change needs a new name (`_v2`).

| Template | Category | To | Buttons |
|---|---|---|---|
| `haip_missed_call_v1` | Utility | guest | Call me back · Share details here |
| `haip_tried_calling_v1` | Utility | guest | Share details here · Call me later |
| `haip_quote_followup_v1` | Utility | guest | I have a question · Call me back |
| `haip_quote_final_v1` | Utility | guest | Yes, hold them · Not now |
| `haip_checkin_v1` | Utility | guest | Still planning · Not now |
| `haip_reengage_v1` | Marketing | guest (offers consent only) | Show me options · Stop promotions |
| `haip_staff_lead_alert_v1` | Utility | team | Acknowledge · I'll take it |
| `haip_staff_escalation_v1` | Utility | team | Acknowledge · I'll take it |
| `haip_staff_digest_v1` | Utility | team | (none) |

No team template carries a guest's phone number.

## Tracking: the journey and the report

Every enquiry has a journey (`lead_journeys`): received, team notified, seen, called, spoke, first contact (and channel),
proposal (sent or copied, delivered, read), follow-ups and the outcome. It shows on the lead page (Journey card) and feeds
the **Report** tab (funnel + one row per team member). Definitions: `docs/analytics/KPI_METRIC_CATALOGUE.md`, section 16.
For leads from before 20 Oct 2026 run `scripts/backfill_lead_journeys.py --tenant-slug <slug>` (dry run, then `--apply`);
"seen" and "team notified" cannot be rebuilt for them.

## Switching on (owner checklist)

1. Workflows → **Create templates**; submit the ones you will use to Meta and wait for approval.
2. Each team member: Profile → add a phone number → turn on **Lead alerts on my WhatsApp** (for team alerts).
3. Switch on the playbooks one by one; watch the **Activity** tab for what went out or was skipped, and why.
