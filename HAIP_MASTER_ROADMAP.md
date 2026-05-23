# HAIP — Master Product Roadmap
> **Hospitality AI Intelligence Platform**
> **Author:** Sharath D. + Claude
> **Last updated:** 2026-05-24
> **Status:** Active — Source of Truth

---

## Table of Contents

1. [What HAIP Is](#1-what-haip-is)
2. [Current Build State](#2-current-build-state)
3. [Tech Stack](#3-tech-stack)
4. [Core Data Thread](#4-core-data-thread)
5. [Module 1 — Portfolio (Properties)](#5-module-1--portfolio)
6. [Module 2 — Inbox](#6-module-2--inbox)
7. [Module 3 — Call Analysis](#7-module-3--call-analysis)
8. [Module 4 — Guest 360](#8-module-4--guest-360)
9. [Module 5 — Rate Calculator & Quote Generator](#9-module-5--rate-calculator--quote-generator)
10. [Module 6 — WhatsApp Automations](#10-module-6--whatsapp-automations)
11. [Module 7 — AI Layer](#11-module-7--ai-layer)
12. [Module 8 — Dashboards & Reports](#12-module-8--dashboards--reports)
13. [Integrations](#13-integrations)
14. [Build Sequence](#14-build-sequence)
15. [Pricing](#15-pricing)

---

## 1. What HAIP Is

**HAIP is the AI intelligence and operations layer for hospitality businesses in India.**

Built for:
- Villa operators (5–100 properties)
- Boutique hotels
- Caravan / glamping businesses (Ratha)
- Airbnb / OTA-listed properties

**The core promise:**
> Every call, every WhatsApp message, every booking, every complaint — collapsed into one living guest profile. Every interaction becomes structured intelligence that improves revenue decisions.

**What HAIP is NOT:**
- Not a PMS (Hostaway / eZee remain source of truth for bookings)
- Not a channel manager (we sync via RentalWise / Hostaway)
- Not a softphone (agents use their own phones via IVR forwarding)
- Not a booking engine

**Core invariant — never break this:**
```
Inquiry → Conversation → Booking → Stay → Revenue
```

Phone number = identity layer across all systems.

---

## 2. Current Build State

### Done ✅
| Area | What's built |
|---|---|
| Auth | Login, register, refresh, logout, role-based access |
| Multi-tenancy | Tenant isolation, RLS on all tables |
| IVR Webhooks | CallerDesk + Acefone webhook ingestion |
| Call pipeline | Ingest → transcribe → QA score → wrap-up |
| Transcription | Groq Whisper (active), Deepgram, local Whisper, **Sarvam AI (built, awaiting key)** |
| WhatsApp | Meta Cloud API connected, webhook receiving messages |
| Instagram | Webhook receiving DMs |
| Inbox | Conversation list, message thread, SSE real-time updates |
| Properties | List, create, edit, channel manager sync (RentalWise) |
| RentalWise | 63 properties synced, booking query fixed, full adapter |
| Integrations UI | Connect/disconnect WhatsApp, RentalWise — soft validation |
| Dashboard shell | Sidebar, topbar, all page shells |
| Guests | Basic list and upsert by phone |
| Encryption | Fernet AES credentials storage |
| SSE | Real-time events via Redis pub/sub |

### In Progress 🔄
| Area | Status |
|---|---|
| Rate Calculator | Models built (PropertyAddOn, SeasonalRate), service not started |
| Sarvam adapter | Built, waiting for API key approval |
| Call Analysis Layer 2-5 | Layer 1 QA basic scoring done, deeper layers not built |

### Not Started ❌
- Guest 360 full module
- Portfolio section (Calendar, Bookings tab, Check-in Forms, Upsells catalog)
- WhatsApp Automation engine
- Chatbot
- Role-specific dashboards (Daily/Weekly/Monthly/Quarterly)
- Next-Best-Action
- Intent detection
- Sentiment analysis
- Suggest chips
- Auto-tagging

---

## 3. Tech Stack

```
Backend          FastAPI (Python) + SQLAlchemy + Alembic
Database         PostgreSQL (Neon) + pgvector
Cache/Queue      Upstash Redis + Celery
Frontend         Next.js 14 (App Router) + TailwindCSS + TanStack Query v5
Auth             NextAuth v5 + JWT
Storage          Cloudflare R2
AI               Anthropic Claude (Haiku 3.5 + Sonnet 3.5)
Transcription    Sarvam AI (primary) / Groq Whisper (fallback) / Deepgram
WhatsApp         Meta Cloud API
IVR              CallerDesk + Acefone
Channel Manager  RentalWise (+ Hostaway planned)
Deployment       Docker Compose → VPS (72.61.228.243) + Vercel (frontend)
```

**AI Cost estimate:**
| Scale | Claude cost/month |
|---|---|
| 10 clients | ~$4 |
| 100 clients | ~$40 |
| 500 clients | ~$200 |

Stays flat at ~0.8% of revenue regardless of scale.

---

## 4. Core Data Thread

```
Guest (phone = PK)
  └── Inquiry
        ├── Conversation
        │     └── Messages (WhatsApp / IG / Web)
        ├── Calls
        │     ├── Transcript
        │     └── QA Score
        └── Stay (Booking)
              ├── Check-in Form Response
              ├── Service Requests
              ├── Complaints / Damages
              └── Review
```

---

## 5. Module 1 — Portfolio

> Renamed from "Properties" — covers everything a host manages.

### Sub-sections

#### 5.1 Properties
Fields per property:
- Name, type (Villa / Hotel / Apartment / Caravan / Glamping)
- Location: city, state, address, map pin (lat/lng)
- Capacity: max guests, bedrooms, bathrooms
- Min. nights
- Amenities (multi-select tags)
- Photos (gallery)
- Description
- Status: Active / Inactive toggle
- Channel source: RentalWise / Manual / Airbnb / Booking.com
- Brand voice (for AI concierge)
- FAQs

**Caravan-specific:**
- Vehicle name, type (luxury_caravan / campervan / glamping_pod / sleeper_bus)
- Home base city
- Routes: [{from, to, km, price}]
- Price per day / per km
- Driver included (yes/no)
- Seats / passenger capacity

#### 5.2 Calendar (Pricing & Availability)
- Month / week view per property
- Color coded:
  - 🟢 Available
  - 🔴 Booked
  - ⚫ Blocked
  - 🟡 Pending
- Click date range → set:
  - Price per night
  - Min nights
  - Availability status
- Seasonal rate bands visible as overlays
- Sync indicator (last synced from channel manager)
- Manual override always available regardless of channel manager

**Rate logic (priority order):**
1. Seasonal rate (date range match, highest priority wins)
2. RatePlan base price
3. Property default price

**Occupancy-based pricing:**
- Different rate for 2 guests vs 4 vs 6 (stored in SeasonalRate.occupancy_pricing JSON)

#### 5.3 Bookings
- All reservations in one table
- Columns: Guest, Property, Check-in, Check-out, Nights, Guests, Amount, Source, Status, Actions
- Source filter: Direct / Airbnb / RentalWise / Manual
- Status: Confirmed / Checked-in / Checked-out / Cancelled / Pending
- Guest name → click → opens Guest 360
- Quick actions per row:
  - Send confirmation message
  - Send check-in details
  - Share check-in form
  - Add note
  - Mark as paid
- Create manual booking button

#### 5.4 Check-in Forms
**Builder:**
- Drag-and-drop Google Forms-style
- Field types: Text, Number, Dropdown, Date, File upload (ID proof), Phone, Checkbox
- Default fields: Guest name, ID proof upload, arrival time, vehicle number, special requests, dietary needs, emergency contact
- Custom fields per property
- Save as template

**Sharing:**
- One-click → sends WhatsApp message with form link
- Link: `genhaip.com/checkin/{booking_id}`
- Guest fills on mobile browser (no app needed)
- Responses stored against booking + guest profile
- Agent dashboard shows: form sent ✅ / pending ⏳ / completed ✅

**Automation:**
- Auto-send form on booking confirmation (WhatsApp trigger)
- Reminder if not filled 24hrs before check-in

#### 5.5 Upsells & Activities
**Catalog (client-managed):**
- Name, description, price, photo, category
- Price type: per stay / per night / per person / per unit
- Active / Inactive toggle
- Sort order

**Categories:**
- Experience (Bonfire, Sunrise trek, Couples massage, Yoga)
- Meal (Private chef, Breakfast, Candle-lit dinner, BBQ)
- Transfer (Airport pickup, Cab, Bike rental)
- Stay enhancement (Early check-in, Late checkout, Room decoration, Birthday setup)
- Other

**Feeds into:**
- Rate calculator add-ons
- AI concierge upsell suggestions
- WhatsApp pre-arrival upsell automation
- Next-Best-Action engine

---

## 6. Module 2 — Inbox

Unified omnichannel inbox for all guest communications.

### Channels
- WhatsApp
- Instagram DM
- Post-call wrap-ups (linked from call analysis)
- Web chat (Phase 3)

### Layout (3-panel)
```
LEFT PANEL          CENTER PANEL         RIGHT PANEL
────────────────────────────────────────────────────
Conversation list   Message thread       Guest 360 mini
  - Filter by       AI draft (teal)      Insights panel
    channel         Suggest chips        Live sentiment
  - Filter by       Compose bar          Detected intents
    status                               Next-Best-Action
  - Search                               Score / History
  - Tags
  - SLA indicators
```

### Conversation List Features
- Tabs: All / Unassigned / SLA Breach / VIP
- Tags: Honeymoon, Birthday, Corporate, Wedding, Anniversary, In-stay, Stay support
- Score badge per conversation
- AI Handled indicator
- Last message preview
- Time since last message

### Message Thread Features
- Speaker-separated messages
- AI concierge replies (teal background, labeled "HAIP CONCIERGE")
- Tool calls visible: `check_availability`, `get_rates`, `get_villa_info`
- Drafting indicator: "HAIP CONCIERGE — DRAFTING..."
- Guardrail indicator: "handing off to [agent] — [reason] guardrail triggered"
- Suggest chips (context-aware quick actions)

### Right Panel — Insights
- Live sentiment gradient (Started: neutral → Now: very positive)
- Detected intents with confidence %
- Next-Best-Action with upsell suggestion + ARPU lift
- Guest 360 mini-card: first touch, lifetime stays, predicted CSAT, churn risk, language

### Actions (top bar)
- Quote — opens rate calculator
- Take over — agent takes manual control from AI
- Book — create booking directly from conversation

---

## 7. Module 3 — Call Analysis

> The core product. Hospitality-specific, not generic.

### Layer 1 — QA Scoring (Rubric)

10 criteria, each scored 0–10:

| Criterion | What AI checks |
|---|---|
| Opening | Greeted with property name + agent name? |
| Needs discovery | Asked occasion, dates, group size, budget? |
| Property pitch | Described USPs relevant to guest's occasion? |
| Availability check | Checked live availability during call? |
| Rate presentation | Quoted confidently without hesitation? |
| Upsell attempt | Offered experiences / transfers / add-ons? |
| Objection handling | Countered price/comparison objections effectively? |
| Closing attempt | Explicitly asked for the booking? |
| Follow-up commitment | Promised to send quote / WhatsApp? |
| Language match | Switched to Hindi/regional when guest did? |

**Total score: 0–100**
**Model:** Haiku 3.5 (fast), Sonnet 3.5 re-score if confidence < 0.78

### Layer 2 — Intent & Outcome Detection

| Signal | Values |
|---|---|
| Occasion | Honeymoon / Anniversary / Birthday / Corporate / Family / Solo |
| Budget signal | "That's high" / "Okay works" / "Can you do better?" |
| Decision stage | First inquiry / Comparing / Ready to book |
| Competitor mentioned | StayVista / Airbnb / [property name] etc. |
| Conversion probability | 0–100% |
| Lost reason | Price / Dates unavailable / Still comparing / No response / Wrong property |

### Layer 3 — Agent Intelligence

| Metric | Detail |
|---|---|
| Talk ratio | Agent vs guest % (ideal: 40/60) |
| Dead air | Pauses > 3s = agent uncertain |
| Filler words | "Umm", "actually", "basically" count |
| Rate confidence | Hesitation before quoting price |
| Script compliance | Hit all required talking points? |
| Best performing agent | Who converts the most? |

### Layer 4 — Guest Intelligence (feeds Guest 360)

Extracted from every call:
- Guest name, phone, language preference
- Occasion + travel dates + group size
- Budget range (inferred)
- Objections raised
- Decision timeline ("deciding by weekend")
- Referral source (Instagram / Google / Friend)

### Layer 5 — Automated Post-Call Actions

| Trigger | Action |
|---|---|
| Conversion prob > 70% | Auto-draft WhatsApp quote |
| Agent promised follow-up | Create task with deadline |
| Competitor mentioned | Flag for manager review |
| Guest said "too expensive" | Suggest alternative property |
| Score < 60 | Send coaching nudge to agent |
| Lost reason detected | Add to lost-reason cluster |
| Call ended, no booking | Add to follow-up queue |

### Call Detail Page (UI)

```
[Audio player with waveform + seek bar]

Transcript (speaker-separated, click-to-seek)
  AGENT  0:03  "Good morning, Casa Aurora, this is Sneha..."
  GUEST  0:08  "Hi, I wanted to check availability for..."

Score Card
  Opening          9/10  ████████████████████░  Evidence highlight
  Needs discovery  7/10  ██████████████░░░░░░░  "Didn't ask budget"
  Upsell attempt   4/10  ████████░░░░░░░░░░░░░  "No upsell offered"
  ...
  TOTAL           74/100

Wrap-up Panel
  Disposition: [Interested - Quoted] [dropdown]
  AI Summary: "Guest Priya Shenoy inquiring for 3-night honeymoon stay..."
  Detected intent: Honeymoon · Budget: ₹80-90k/night · Dates: 23-26 Dec
  Suggested next action: Send quote + gallery link on WhatsApp
  Lost reason: — (not lost)

[Save wrap-up]  [Send WhatsApp follow-up]
```

---

## 8. Module 4 — Guest 360

> The DNA of the guest. Every touchpoint across the full lifecycle.

### The Full Lifecycle

```
AWARENESS → PRE-BOOKING → BOOKING → PRE-CHECKIN → DURING STAY → CHECKOUT → POST-STAY → REPEAT
```

### Data Structure

```
Guest (phone = PK)
├── Identity
│   ├── name, email, phone
│   ├── language (Hindi / English / Kannada etc.)
│   ├── nationality
│   └── tags [VIP, Repeat, Honeymoon-traveler, Corporate, Price-sensitive, Complainer, Referrer]
│
├── Acquisition
│   ├── first_touch (Instagram / Google / WhatsApp / Referral / OTA)
│   └── first_touch_campaign
│
├── Commercial
│   ├── lifetime_value
│   ├── total_stays
│   ├── total_inquiries
│   └── conversion_rate
│
├── Timeline (every event ever)
│   ├── event_type [inquiry/call/message/booking/checkin/complaint/damage/checkout/review/referral]
│   ├── channel [whatsapp/instagram/call/email/in-person]
│   ├── sentiment [positive/neutral/negative]
│   ├── summary (AI 1-line)
│   └── raw_ref_id → FK to source record
│
├── Per Stay
│   ├── Pre-booking: inquiry, quotes, objections, competitor mentions, days to convert
│   ├── Booking: rate paid, discount, source, special requests
│   ├── Pre-checkin: arrangements confirmed, upsells accepted
│   ├── During stay: service requests, complaints, issues, damages
│   └── Post-stay: NPS, review rating/text/platform, referrals
│
└── AI Intelligence Layer
    ├── budget_range (inferred from calls)
    ├── price_sensitivity (low/medium/high)
    ├── occasion_pattern (always travels for anniversary in October)
    ├── preferred_property_type
    ├── preferred_amenities
    ├── communication_style (formal/casual/hindi/mixed)
    ├── decision_maker (true/false)
    ├── upsell_receptiveness (high/medium/low)
    ├── complaint_tendency (low/medium/high)
    ├── referral_tendency (high = referred 2+ guests)
    ├── predicted_ltv
    ├── churn_risk (low/medium/high)
    ├── next_visit_probability (%)
    ├── next_visit_window (e.g. Oct-Nov based on pattern)
    └── recommended_packages
```

### Guest 360 Page (UI)

```
[Guest avatar]  Priya Shenoy  +91 98765 43210
                Honeymoon-traveler · VIP · English + Hindi

TIMELINE                              GUEST INTELLIGENCE
────────────────────────────────────────────────────────────────
📱 WhatsApp  23 May  Inquiry          Budget        ₹80-90k/night
📞 Call      23 May  Score 91/100     Price sens.   Low
✅ Booking   24 May  ₹2,97,920        Upsell recep. High
📋 Form      25 May  Check-in form ✅  Decision mkr  Yes
🏠 Stay      26 Dec  Casa Aurora      LTV (pred.)   ₹4,50,000
⭐ Review    29 Dec  4.8 · Google      Churn risk    Low
                                      Next visit    Oct-Nov 2026

STAYS (1)                             COMPLAINTS (0)
Casa Aurora  23-26 Dec  ₹2,97,920     —

CONVERSATIONS (3)                     REFERRALS (0)
WhatsApp · Call · Post-call wrap-up   —
```

### Phase-wise Build

| Phase | What |
|---|---|
| 1 | Guest record from first call/WhatsApp, timeline auto-logged |
| 2 | AI extraction from calls + chats (occasion, budget, sentiment) |
| 3 | Complaint/damage tracking, post-stay review ingestion |
| 4 | LTV prediction, churn risk, next visit window, personalized recommendations |

---

## 9. Module 5 — Rate Calculator & Quote Generator

> Agent tool: calculate rates live during a call and share instantly on WhatsApp.

### Flow

```
Agent on call → Opens calculator → Enters dates + guests + property
             → Sees available properties + live rates
             → Adds upsells/add-ons
             → Clicks "Share on WhatsApp"
             → Guest receives formatted rate breakdown
```

### Inputs

| Input | Villa | Caravan |
|---|---|---|
| Check-in date | ✅ | ✅ |
| Check-out date | ✅ | ✅ |
| Adults | ✅ | ✅ |
| Children | ✅ | ✅ |
| Preferred location | City / "any" | Route / home base |
| Occasion | Optional | Optional |
| Budget range | Optional | Optional |

### Rate Resolution Logic

```
For channel-manager properties:
  → Fetch live rates from RentalWise adapter
  → Fall back to HAIP manual rate if adapter fails

For manual properties:
  1. Check SeasonalRate table (date range match, highest priority wins)
  2. Check occupancy_pricing overrides within seasonal rate
  3. Fall back to RatePlan base_price_per_night
  4. Fall back to property default price
```

### Output — Agent View

```
┌─────────────────────────────────────────────────────┐
│  Casa Aurora                    AVAILABLE ✅          │
│  4BHK · Private pool · Hilltop · max 8 guests        │
│                                                      │
│  23–26 Dec (3 nights)  ·  2 adults                   │
│  ₹85,000/night  ×  3  =  ₹2,55,000                  │
│                                                      │
│  Add-ons:                                            │
│  ☑ Candle-lit dinner        ₹8,500  (per stay)       │
│  ☑ Airport transfer         ₹2,500  (per stay)       │
│  ☐ Private chef (3 days)   ₹15,000  (per stay)       │
│  ☐ Early check-in           ₹5,000  (per stay)       │
│                                                      │
│  Subtotal      ₹2,66,000                             │
│  GST 12%       ₹31,920                               │
│  ──────────────────────                              │
│  Total         ₹2,97,920                             │
│  Advance 30%   ₹89,376                               │
│                                                      │
│            [Share on WhatsApp]  [Copy]  [Save Quote] │
└─────────────────────────────────────────────────────┘
```

### WhatsApp Message Format

```
*Casa Aurora — 3 Nights Stay* 🏡

📅 Check-in: 23 Dec | Check-out: 26 Dec
👥 2 Adults

*Rate Breakdown:*
🏠 Accommodation (3 × ₹85,000)  =  ₹2,55,000
🍽️ Candle-lit dinner             =  ₹8,500
🚗 Airport transfer              =  ₹2,500
━━━━━━━━━━━━━━━━━━━━━━
Subtotal        ₹2,66,000
GST (12%)       ₹31,920
*Total          ₹2,97,920* ✨

*Advance (30%)*  =  *₹89,376*

To confirm your dates, reply *YES* 🙏
```

### API Endpoints

```
POST /api/v1/calculator/search    → available properties + rates for dates/guests
POST /api/v1/calculator/quote     → build quote with add-ons, get breakdown
POST /api/v1/calculator/share     → send WhatsApp message to guest phone
GET  /api/v1/calculator/quotes    → saved quotes list
GET  /api/v1/calculator/quotes/{id}
```

---

## 10. Module 6 — WhatsApp Automations

> Trigger-based automation engine. No code required for clients.

### Architecture

```
Trigger (event) → Condition check → Delay → Action (WhatsApp message)
```

### Built-in Trigger Library

| # | Trigger | Condition | Timing | Message |
|---|---|---|---|---|
| 1 | Booking confirmed | Always | Immediate | Booking confirmation + check-in form |
| 2 | Check-in form not filled | Form pending | 24hrs before check-in | Reminder to fill form |
| 3 | Pre-arrival upsell | Upsells exist for property | 3 days before check-in | Activity options with prices |
| 4 | Check-in day | Always | 8am on check-in date | Check-in details (address, code, instructions) |
| 5 | Mid-stay check-in | Stay > 1 night | Day 2 of stay, 10am | "How is everything going?" |
| 6 | Checkout day | Always | 8am on checkout date | Thank you + review request |
| 7 | Review follow-up | No review received | 7 days after checkout | Gentle nudge + Google/Airbnb link |
| 8 | Repeat guest | Stayed before | 60 days no activity | Re-engagement + special offer |
| 9 | Guest birthday | DOB stored | Day of birthday | Birthday wish + exclusive offer |
| 10 | Unanswered quote | Quote sent, no reply | 24hrs after quote | Follow-up nudge |

### Message Template Builder

- Variables: `{guest_name}`, `{property_name}`, `{checkin_date}`, `{checkout_date}`, `{amount}`, `{agent_name}`, `{checkin_instructions}`, `{upsell_list}`, `{review_link}`
- Rich text: bold, emoji, line breaks
- Media: attach property photo, PDF quote
- CTA buttons (WhatsApp template buttons): "Confirm Booking", "Fill Check-in Form", "View Gallery"

### Automation Builder UI

```
[+ New Automation]

Trigger:    [Booking confirmed ▼]
Condition:  [Always ▼]
Delay:      [Immediately ▼]
Action:     [Send WhatsApp message ▼]
Template:   [Booking Confirmation ▼]  [Edit template]

[Save]  [Test send]  [Activate]
```

---

## 11. Module 7 — AI Layer

### 7.1 Concierge (Auto-draft replies)

- Drafts WhatsApp/Instagram replies using property context + guest history
- Tools it calls: `check_availability`, `get_rates`, `get_villa_info`, `propose_experience`
- Modes:
  - **Shadow** (default): Always draft, agent approves before sending
  - **Autonomous**: Auto-send if confidence > threshold AND KB size ≥ 10 snippets
- Guardrails — always hand off to human when:
  - Complaint detected
  - Birthday/anniversary special request
  - Price negotiation > 15% discount asked
  - Legal/safety issue

### 7.2 Intent Detection

Real-time classification per message:
- Booking inquiry
- Price query
- Availability query
- Experience interest
- Special occasion
- Complaint
- Check-in query
- Post-stay feedback
- Cancellation request

### 7.3 Sentiment Analysis

- Live tracking per conversation
- Scale: Very negative → Negative → Neutral → Positive → Very positive
- Alert when sentiment drops to negative mid-conversation
- Stored per message + aggregated per conversation

### 7.4 Next-Best-Action

Recommendation engine:
- UPSELL: "Surprise birthday package — 87% of similar guests accept. ARPU lift: ₹4,500–₹8,500"
- FOLLOW-UP: "Quote sent 26hrs ago — send reminder"
- ESCALATE: "Sentiment dropped — assign senior agent"
- BOOK: "Conversion probability 78% — ask for booking now"

### 7.5 Suggest Chips

Context-aware quick-action buttons under compose bar:
- "Confirm dinner + breakfast package"
- "Surprise cake + flowers (₹4,500)"
- "Send payment link"
- "Check availability for alternate dates"
- "Send gallery"

Generated dynamically by AI based on conversation context.

### 7.6 Auto-tagging

Automatically tags conversations with:
- Occasion: Honeymoon / Birthday / Anniversary / Corporate / Wedding / Family / Solo
- Status: Hot lead / Warm / Cold / Booked / In-stay / Post-stay
- Issue: Complaint / Damage / Cancellation / Dispute
- Priority: VIP / High value / Repeat guest

### 7.7 Lost Reason Clustering (Weekly batch)

- Clusters all lost inquiries from past 7 days
- Groups by theme: price, availability, competition, no response
- Generates insight: "38% of losses this week were price objections on 2BHK properties — consider reviewing monsoon rates"
- Shows in Weekly Dashboard

---

## 12. Module 8 — Dashboards & Reports

> Not generic. Insight-driven. Every number suggests an action.

### Access by Role

| Dashboard | Owner/GM | Manager | Agent | Property Mgr |
|---|---|---|---|---|
| Daily | Full | Ops only | Personal only | Property only |
| Weekly | Full | Full | Personal only | Property only |
| Monthly | Full | Full | Personal only | — |
| Quarterly | Full | Summary | — | — |

---

### Daily Dashboard

**Owner view — "What needs my attention today?"**

```
TODAY AT A GLANCE
Check-ins today     3      Check-outs today    2
New inquiries       8      Open conversations  12
Revenue today   ₹85,000    Pending quotes       4
SLA breaches        1 🔴   Unanswered > 2hrs    3

URGENT ACTIONS
🔴 Rohan Mehta — no check-in form received (arriving 4pm)
🟡 Priya Shenoy — quote sent 26hrs ago, no reply
🟡 SLA breach — Anjali Kapoor WA unanswered 3hrs

PROPERTIES TODAY
Casa Aurora    Checked in ✅      Jade Villa    Checking out 2pm
Sunset Bay     Available          Ratha #1      On route → Coorg
```

**Agent view — personal only**
```
MY DAY
Open conversations    6
Calls to follow up    3
Quotes pending reply  2
My QA score today    87/100
Tasks due today       4
```

---

### Weekly Dashboard

**"How did this week perform vs last week?"**

```
WEEK PERFORMANCE              vs Last Week   vs Last Year
Revenue             ₹4,20,000    ▲ 12%          ▲ 34%
New bookings                7    ▲ 2             ▲ 3
Inquiry → Booking       16.6%    ▲ 2.1%
Avg response time         18min  ▼ 4min ✅
New guests                  6    Repeat           1

TOP PROPERTY      Casa Aurora  (3 bookings, ₹2,55,000)
TOP AGENT         Sneha R.  (conv. rate 24%)
TOP CHANNEL       Instagram DM  (18 inquiries)

LOST REASONS THIS WEEK
Price too high        8   38%   ████████░░
Dates unavailable     6   28%   ██████░░░░
Still comparing       4   19%   ████░░░░░░
No response           3   14%   ███░░░░░░░

UPSELL PERFORMANCE
Sent 14 · Accepted 6 · Revenue ₹38,500
```

---

### Monthly Dashboard

**"Is the business growing? Where are the gaps?"**

```
KEY METRICS               vs Last Month   vs Last Year
Total Revenue  ₹18,40,000    ▲ 8%            ▲ 41%
Occupancy           73%      ▲ 4%
ADR             ₹78,000      ▲ 3%
RevPAR          ₹56,940      ▲ 7%
Bookings             31      ▲ 3
Cancellations         3      ▼ 1 ✅
Repeat Guest %      22%      ▲ 4%
Avg NPS            8.6       ▲ 0.3
Review Rating      4.7 ★

REVENUE BY PROPERTY (bar chart)
REVENUE BY CHANNEL (pie: Direct 48% / Airbnb 31% / RentalWise 14% / Booking 7%)

CALL QA AVERAGE     74/100
TOP OBJECTION       "Price too high" (31 times) → Action: Review 2BHK rates

GUEST SATISFACTION
5-star reviews    8
Complaints        2  → avg resolved in 1.4hrs
NPS               8.6
```

---

### Quarterly Dashboard

**"Is my business healthy? What's the trend?"**

```
Q2 2026 (Apr–Jun)             vs Q1      vs Q2 2025
Total Revenue    ₹52,40,000    ▲ 14%       ▲ 67%
Total Bookings          94     ▲ 11
New Guests              71     Repeat       23 (24%)
Avg LTV (repeat)  ₹1,84,000
Occupancy              68%     ▲ 6%

REVENUE TREND
Apr  ₹16,20,000  ████████████████
May  ₹18,40,000  ██████████████████
Jun  ₹17,80,000  █████████████████ (projected)

AGENT LEADERBOARD (Q2)
1. Sneha R.    Conv. 28%  QA 91  Revenue ₹18,40,000
2. Karan M.    Conv. 19%  QA 78  Revenue ₹12,10,000
3. Divya S.    Conv. 14%  QA 72  Revenue ₹8,80,000

GUEST RETENTION
Returned this quarter    23
Revenue from repeat   ₹14,20,000  (27% of total)
At churn risk             8  → trigger re-engagement campaign

TOP LOST REASON (quarter)  Price objection 34%
AI RECOMMENDATION →  Review rate strategy for 2BHK properties
```

---

### Metrics Master List

**Revenue:** MRR, ARR, ADR, RevPAR, occupancy rate, revenue by property/channel/agent, outstanding payments, cancellation revenue lost

**Bookings:** New bookings, cancellations, conversion rate, inquiry→quote→booking funnel, avg days to convert, avg lead time

**Guests:** New vs repeat, NPS, review scores, repeat rate, avg LTV, churn risk count, top guests by revenue

**Team:** Agent leaderboard (conversion, QA score, revenue), avg response time, SLA breach count, calls handled, messages handled

**Properties:** Occupancy per property, revenue per property, avg stay duration, top objections per property

**AI:** Concierge draft acceptance rate, upsell conversion rate, chatbot deflection rate, transcription accuracy

---

## 13. Integrations

### Active
| Integration | Type | Status |
|---|---|---|
| RentalWise | Channel Manager / PMS | ✅ Connected |
| WhatsApp Meta Cloud | Messaging | ✅ Connected |
| CallerDesk | IVR | ✅ Webhook live |
| Acefone | IVR | ✅ Webhook live |
| Groq Whisper | Transcription | ✅ Active |
| Anthropic Claude | AI | ✅ Active |

### In Progress
| Integration | Type | Status |
|---|---|---|
| Sarvam AI | Transcription (Hindi/Indic) | 🔄 Adapter built, key pending |

### Planned
| Integration | Type | Priority |
|---|---|---|
| Hostaway | Channel Manager | High |
| Instagram DM | Messaging | High |
| Deepgram | Transcription (fallback) | Medium |
| Google Reviews | Review ingestion | Medium |
| Razorpay | Payments | Medium |
| Airbnb | OTA sync | Low |
| Booking.com | OTA sync | Low |

---

## 14. Build Sequence

### Phase 1 — Foundation Complete (Now → 2 weeks)
**Goal: Daily-use product for existing clients (Kiwistays)**

1. Rate Calculator + Quote Generator (backend service + API + frontend widget)
2. Portfolio section rename + Calendar view
3. Upsells catalog (CRUD)
4. Bookings tab in Portfolio
5. Call Analysis Layer 2 (intent + outcome detection)
6. WhatsApp Automation — 3 core triggers (booking confirmation, check-in day, checkout)

### Phase 2 — Guest Intelligence (2–6 weeks)
**Goal: Every agent knows the guest before picking up the phone**

1. Guest 360 Phase 1 (timeline, per-stay record)
2. Call Analysis Layer 3 (agent intelligence — talk ratio, dead air, filler words)
3. AI post-call actions (auto-draft quote, create follow-up task)
4. Intent detection + auto-tagging on all messages
5. Sentiment analysis live tracking
6. Daily + Weekly dashboards (owner + agent views)

### Phase 3 — Automation & Intelligence (6–12 weeks)
**Goal: Platform runs most interactions autonomously**

1. Full WhatsApp automation engine (all 10 triggers)
2. Check-in form builder + auto-share
3. Concierge shadow mode → autonomous mode
4. Next-Best-Action engine
5. Suggest chips
6. Monthly + Quarterly dashboards
7. Guest 360 Phase 2 (AI intelligence layer)
8. Chatbot (inbound intent → auto-reply)

### Phase 4 — Scale & Retention (12–18 weeks)
**Goal: Clients can't leave**

1. Guest 360 Phase 3 (LTV prediction, churn risk, next visit window)
2. Lost reason clustering (weekly batch)
3. Re-engagement campaigns
4. Hostaway integration
5. Google Reviews ingestion
6. Razorpay payment links in quotes
7. Mobile-optimized agent dashboard

---

## 15. Pricing

| Plan | Price/month | For |
|---|---|---|
| Starter | ₹3,999 | Up to 5 properties, 1 user |
| Growth | ₹6,999 | Up to 20 properties, 5 users, automations |
| Pro | ₹9,999 | Unlimited properties, 15 users, full AI |
| Enterprise | Custom | 50+ properties, dedicated support |

**AI cost as % of revenue:** ~0.8% at all scales (negligible)

---

## Appendix — Key Design Principles

1. **Insight, not data** — Every metric has context and an action prompt
2. **Phone = identity** — Always the primary key across all systems
3. **Never break the thread** — Inquiry → Conversation → Booking → Stay → Revenue
4. **Multi-tenant by default** — Every row has tenant_id, RLS on all tables
5. **Mobile-first for agents** — Daily dashboard and inbox work on phone
6. **AI assists, human decides** — Shadow mode default, autonomous only when earned
7. **Build for hospitality, not generic** — Every rubric, every tag, every automation is hospitality-specific
8. **BYOC** — Clients pay their own IVR/WhatsApp bills, HAIP holds the integration

---

*This document supersedes HAIP_FULL_BUILD_PLAN.md, HAIP-V2-PRD.md, and HAIP_Engineering_Ticket_Plan.md*
*Last updated: 2026-05-24*
