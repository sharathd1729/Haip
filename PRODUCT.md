# HAIP: Product context for design work

Read this with `docs/DESIGN.md` and `HAIP_UI_Redesign_Plan.md` before any UI work. Source of truth for what the product is: root `CLAUDE.md`.

## In one line
HAIP is the AI intelligence and communication layer for Indian luxury hospitality: pre-call prep, post-call analysis, AI-drafted WhatsApp replies, and one record of every guest across every touchpoint.

## What it is not
Not a PMS, not a softphone, not a channel manager, not a booking engine. Hostaway/eZee stay the source of truth for inventory. HAIP is where the team works the conversation and the sale.

## Who uses it, and for how long each day
| Role | Lives in | What they need at a glance |
|---|---|---|
| Owner | Dashboard, Reports, Targets | Is revenue on track? What is leaking? Who needs help? |
| Manager | Dashboard, Leads, Team | Who is waiting on us, who is overdue, how is each agent doing |
| Reservations / sales agent | Inbox, Leads, Calls, My day | **Who is waiting on me right now**, then the guest's whole story in one place |
| Concierge / FOH | Bookings, My day | Today's arrivals, requests, deposits, notes for the on-site team |
| Marketing | Messaging, Campaigns | Audience, template status, send results |
| Compliance | Compliance Center | Consent, deletion requests, audit trail |

Agents work in Inbox, Leads and Calls all day, mostly on laptops, often on a phone between guests (the app is installed as a PWA). Screens are used in short bursts while a guest is waiting.

## Clients today
- **Ratha**: luxury caravan experiences, Bangalore. WhatsApp and Instagram are the main channels; calls through Vobiz.
- **Jade**: pool villas, Bangalore. Calls through Acefone.
Navigation and wording differ by business type (a caravan has no "rooms"); respect `hideForBusinessTypes`.

## The product's point of view
**"Who is waiting on me?"** Everything else is context for answering that. The queue (guests waiting for a reply, missed calls, shared a phone but not called, follow-ups overdue) is the centre of the product, and the design should keep returning to it.

## Principles for the interface
1. **Calm over loud.** Urgency is rare, so it must stay meaningful. One red thing on a screen is a signal; twenty are wallpaper.
2. **One story per guest.** Inquiry, conversation, call, booking and stay read as one timeline wherever a guest appears.
3. **The words carry the meaning.** Colour reinforces a state; it never is the state (colour-blind users, greyscale prints, bright sun on a phone).
4. **Fast beats pretty.** Motion explains a state change or it is removed.
5. **Honest numbers.** Say what a number covers ("7 days" versus "all time"), never show a percentage against nothing, and never truncate a value silently.
6. **Every screen has five states:** loading, empty, error, partial and worst-case data (a 300-character name, 500 conversations, no network).

## Language
Plain, active, specific. Say what a control does ("Send template", then a confirmation that says "Sent"). Errors say what went wrong and how to fix it, without apology. Rupees use lakh/crore grouping (₹6,00,000), dates are day-month-year, time is IST. Phone numbers are masked unless the person is allowed to see them.

## Constraints that shape design
- Mobile first for agents: 44px touch targets, no hover-only controls, 100dvh and safe areas, 16px inputs.
- DPDP: personal data is masked by default and revealed deliberately; destructive actions confirm.
- Per-tenant white-label: colour, radius and font can change per client (`brandTheme.ts`), so styling goes through tokens, never fixed hex.
- Light and dark must both work. Nothing ships without both.

## Anti-goals
- Not a marketing page: the app is a tool, not a showcase. Personality lives in a few signature moments, not in novel layouts for tables and forms.
- No decoration that costs speed on a phone (no WebGPU or heavy effects inside data screens).
- No changes to data behaviour in a visual pass.
