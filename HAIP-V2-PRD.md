# HAIP V2 — Product Requirements Document

**Hospitality AI Intelligence Platform**
**Version:** 2.0 (Founder-grade PRD)
**Author:** Product / Engineering
**Date:** May 2026
**Status:** Draft for review

---

## How to read this document

This PRD is a single source of truth for HAIP V2 — the next nine months of product strategy. It is written for three audiences simultaneously:

- **Founders & investors** — Parts I and IX (positioning, market, roadmap, metrics)
- **Product & design** — Parts II–VII (module deep dives, UX flows, sub-modules)
- **Engineering** — Parts VI–VIII and Appendix (data model, semantic layer, AI architecture, infra, evals)

Each module section follows the same shape: *Where V1 is today → Pain points → Competitor benchmark → V2 vision → Sub-modules & features → Data model deltas → AI architecture → UX flows → Acceptance criteria*. Skim the headers if you only need a particular slice.

A companion `.docx` of this document is available for sharing.

---

# Table of Contents

**Part I — Strategy**
1. Executive Summary
2. V1 Audit & Maturity Map
3. Strategic Positioning: The HAIP Wedge
4. Competitive Landscape (2026)
5. The Hero Metric

**Part II — Foundation**
6. The Identity & Data Layer (V2 spine)
7. Semantic Layer & Metric Definitions

**Part III — Conversational Intelligence Modules**
8. WhatsApp Intelligence Hub
9. Instagram Intelligence Hub
10. IVR & Call Intelligence 2.0

**Part IV — Lifecycle & Commercial Modules**
11. Lead CRM 2.0
12. Booking, Stay & Revenue
13. Campaign Attribution & Marketing Intelligence

**Part V — The AI Intelligence Layer**
14. The Agent Operating System
15. AI Data Analyst ("Athena")
16. AI Concierge & Guest Agents

**Part VI — Cross-Cutting Concerns**
17. UX / UI Vision & Design System
18. Multi-Tenancy, Branding & White-Labeling
19. Compliance: DPDP, GDPR, TRAI, Meta policy
20. Evals, Guardrails & Production AI hygiene
21. Cost Model & Pricing Strategy

**Part VII — Execution**
22. Phased Roadmap (Q3 2026 → Q2 2027)
23. Success Metrics & North-Star Dashboard
24. Risks & Mitigations

**Appendix**
A. Data model deltas (full)
B. API surface additions
C. New Celery task graph
D. Recommended infrastructure stack
E. Hospitality QA Rubrics (sample)
F. Glossary

---

# PART I — STRATEGY

# 1. Executive Summary

HAIP V1 is a more capable platform than this PRD's brief might suggest. The codebase audit (§2) found a production-grade FastAPI/Next.js stack with multi-tenant Postgres + RLS, working integrations to CallerDesk, Acefone, Meta WhatsApp & Instagram, Hostaway, Anthropic, Gemini, Groq, and Deepgram. Core CRM entities (Guest, Inquiry, Conversation, Message, Call, Stay, Property) are intact, the call intelligence pipeline (ingest → transcribe → classify → judge → wrap-up) is end-to-end, and a Kanban inbox, call player, QA rubric editor, and analytics scaffolding exist in the frontend. Roughly **60% of the platform is built**; the remaining work is less about new plumbing and more about (a) finishing half-shipped flows (campaigns, Instagram inbox, concierge approval), (b) layering advanced AI features that the market now expects as table stakes, and (c) crystallising a defensible product wedge before well-funded generalists (Gupshup, Twilio, Convin) ship hospitality verticals.

The V2 thesis is built on three findings from the 2026 market and domain research:

**Finding 1 — Speed wins hospitality, and the industry is bleeding it.** First-responders capture 35–50% of inquiries; close rates rise 7× when reply happens inside an hour; 74% of operators still miss the 5-minute window. No competitor currently sells a single number — *median time-to-first-response across WhatsApp, Instagram, and phone* — as the hero outcome of their product. This is HAIP's wedge.

**Finding 2 — The data thread is unowned.** WhatsApp BSPs (Wati, AiSensy, Interakt, Gupshup) stop at the message. PMS/channel managers (Hostaway, Cloudbeds, SiteMinder) stop at the reservation. Conversation-intelligence tools (Convin, Gong, Salesken) stop at the call. CRMs (TeleCRM, LeadSquared) ignore the audio. **Nobody** ties *Ad → Inquiry → Conversation → Call → Booking → Stay → Repeat → LTV* into one entity graph keyed off phone-as-identity. The Open Semantic Interchange (OSI) standard (dbt + Snowflake + Salesforce, 2025) and the 83% jump in text-to-SQL accuracy with a semantic layer make this the right moment to ship a hospitality-tuned semantic spine.

**Finding 3 — Agentic AI is the new floor, vertical agents the new ceiling.** Every serious platform now ships *autonomous* agents (Gupshup ACE, Twilio Agentforce, Respond.io, Convin AI Phone, Superfone's 5-agent SKU). Meta's January 2026 policy effectively bans general-purpose third-party AI assistants on WhatsApp while explicitly permitting business-specific bots — a regulatory tailwind for vertical players. HAIP's defensible play is not building a better LLM wrapper; it is building hospitality-tuned QA rubrics, pre-built WhatsApp Flows, fine-tuned classifiers on Indian hospitality conversations, and a property-aware agent runtime — none of which generic platforms can ship in under 18 months.

**V2 is therefore organised around five module upgrades and one new layer:**

1. **WhatsApp Intelligence Hub** — Chatbot builder, Flow Studio, CTWA Ads Manager, AI Agents (Booking, Pre-Arrival, Concierge, Re-engagement), Catalog + Cart, opt-in compliance suite. Finish broadcast logic, add visual flow builder, add CTWA → revenue attribution via Conversions API.
2. **Instagram Intelligence Hub** — Compliant comment-to-DM funnels, story-mention auto-replies, IG Ads → DM lead capture, unified inbox with WhatsApp under a single thread, rate-limit-aware throttling.
3. **IVR & Call Intelligence 2.0** — Real-time agent assist (whisper coaching), property-aware voicebots (Vapi/Retell), paralinguistic sentiment, LLM-as-judge replacing static rubrics, post-call coaching loops, multilingual transcription (12+ Indian languages).
4. **Lead CRM 2.0** — Visual pipeline rules, SLA enforcement, response-time leaderboards, multi-property lead routing, repeat-guest detection at first ring, Inquiry-to-Stay revenue attribution.
5. **Analytics & AI Data Analyst ("Athena")** — Semantic layer (MetricFlow YAML), insights feed (Slack/email/in-app), text-to-SQL chat for owners, anomaly detection, MMM + MTA hybrid attribution, automated cleansing of dirty marketing data.
6. **NEW: The Agent OS** — A property-aware, identity-aware runtime where AI Concierge, AI Data Analyst, AI QA Reviewer, AI Receptionist, and future agents share memory, tools, and a vertical playbook library. Built on LangGraph + pgvector + Claude Sonnet 4.6 with Haiku fallback.

**Phasing** (full detail in §22): Q3 2026 ships the foundation (semantic layer, finish broadcasts, IG inbox, AI Data Analyst MVP). Q4 2026 ships Flow Studio, CTWA, voice agents, advanced QA. Q1 2027 ships the Agent OS, attribution, and the agent marketplace. Q2 2027 hardens for enterprise (white-label, audit, SOC 2 path).

**Success metrics** are deliberately narrow. North-star: median tenant time-to-first-response under five minutes within 90 days of onboarding. Secondary: AI-attributable revenue per tenant per month, repeat-guest share lift, gross margin per agent-minute.

The rest of this document is the *how*.

---

# 2. V1 Audit & Maturity Map

This section is a sober inventory of what exists in `/HAIP` today. It is based on a code-level audit, not on aspirational documentation.

## 2.1 Tech stack inventory

| Layer | Technology | State |
|---|---|---|
| Backend | FastAPI 0.115, SQLAlchemy 2.0, Alembic, Pydantic 2 | Production-grade |
| Database | PostgreSQL 16 + pgvector + Postgres RLS | Production-grade |
| Queues | Redis + Celery + Flower | Production-grade |
| Frontend | Next.js 16 (App Router, RSC), React 19, TypeScript 5, Tailwind 4, shadcn/ui, Zustand, TanStack Query, Socket.io-client | Production-grade |
| Auth | NextAuth 5 + JWT (access + refresh) | Working |
| Storage | AWS S3 / Cloudflare R2 (recordings) | Working |
| Observability | Sentry | Configured |
| AI | Anthropic (Haiku 4.5 + Sonnet 4.6), Gemini (free fallback), Groq Whisper (free), Deepgram Nova-2 (paid fallback) | Production-grade |
| Telephony | CallerDesk, Acefone webhooks | Production-grade |
| Messaging | Meta WhatsApp Cloud API v20, Meta Instagram Graph API v20 | Inbound working; outbound partial |
| PMS | Hostaway (OAuth2 + hourly sync); RentalWise (stub) | Hostaway live; RW stub |

The stack is well chosen. It is the stack this PRD recommends keeping. No language or framework migration is proposed for V2.

## 2.2 Module-by-module maturity

| Module | Status | Coverage |
|---|---|---|
| IVR/Call ingest | ✅ Full | Both providers wired, recordings to S3 |
| Transcription pipeline | ✅ Full | Groq→Deepgram fallback, diarization |
| Call QA / scoring | ✅ Full | Rubric + LLM judge, evidence highlights |
| WhatsApp inbox | 🟡 Partial | Inbound working, outbound + concierge approval not finished |
| WhatsApp campaigns | 🟡 Schema only | Models exist, broadcast logic missing |
| Instagram DMs | 🟡 Partial | Workers exist, UI missing |
| Lead CRM | ✅ Core | Pipeline working, no SLA/auto-assign yet |
| Analytics | 🟡 Partial | Owner-day stats, lost-reason clustering; no cross-source correlation |
| AI intelligence | ✅ Core | Claude/Gemini, prompt cache, model routing |
| PMS sync | 🟡 Partial | Hostaway pulls, no Stay creation hook |
| Audit / compliance | ✅ Core | DPDP, soft deletes, recording consent |
| Multi-tenancy | ✅ Core | RLS + tenant context middleware |

## 2.3 Data model — what is intact

The core thread is wired: `Guest → Inquiry → Conversation → Message`, with `Call → Transcript → CallScore` linked to Inquiry and Guest, and `Property → Stay → RatePlan` modeled. Phone-as-identity is enforced at the Guest level. Consent is captured.

What is **missing** at the data layer for V2 (see §17 and Appendix A):

- No `Campaign` → `Inquiry` foreign key (attribution dead-end)
- No `Booking` entity distinct from `Stay` (channel-manager bookings collapse into Stay, losing OTA commission tracking)
- No `Touchpoint` / event-stream entity (needed for MTA)
- No `LeadScore` / `ChurnRisk` / `LTVForecast` columns on Guest
- No `Flow` execution state (WAFlow has design but no runtime state)
- No `AgentRun` / `AgentToolCall` audit trail (needed for Agent OS)
- No `Insight` entity (needed for the AI Data Analyst feed)
- No `SLA` definition or breach tracking
- No `BrandTheme` / per-tenant asset storage (needed for white-label)

## 2.4 Gaps & technical debt

Critical findings from the audit, prioritized:

1. **Webhook signature verification is skip-on-missing-secret** — security bug; must require META_APP_SECRET in prod.
2. **No inquiry stage transition validation** — leads can jump NEW → BOOKED illegally, breaking funnel reporting.
3. **No retry strategy for Meta API failures** beyond socket timeout.
4. **No rate limiting on API endpoints** — exposed surface area.
5. **Message table has no partition strategy** — unbounded growth will hurt analytics on large tenants.
6. **Lost-reason clustering runs full-table query weekly** — O(n) on every tenant; needs incremental.
7. **No mocks for Meta/Deepgram/Claude in tests** — integration regressions ship blind.
8. **Cron schedules hardcoded to IST** — blocks multi-region tenants.

None of these are blockers for V2 features but they all need fixing before scale.

## 2.5 What V2 keeps, deprecates, or replaces

**Keeps wholesale:**
- The 11+4 entity data model (extended, not replaced)
- Adapter pattern for LLM, transcription, telephony, PMS
- Celery + Redis backbone
- Postgres RLS for multi-tenancy
- pgvector for embeddings
- The Next.js App Router frontend architecture
- shadcn/ui + Tailwind 4 design system

**Replaces:**
- Static QA rubric scoring → **LLM-as-judge** with rubric as prompt context (see §10)
- Regex-based transcript redaction → **NER-based PII detection** (Presidio + custom Indian models)
- Lost-reason static clustering → **Embedding-based + LLM theming** (see §15)
- Single global ALLOWED_ORIGINS → **Per-tenant CORS allowlist**

**Adds (greenfield):**
- Visual WhatsApp Flow Studio
- CTWA Ads Manager + Conversions API integration
- Voicebot orchestration (Vapi or Retell)
- Real-time agent assist
- Semantic layer (MetricFlow YAML)
- Insights feed
- Agent OS runtime (LangGraph)
- White-label asset pipeline

---

# 3. Strategic Positioning: The HAIP Wedge

## 3.1 The problem operators actually have

A villa operator in Goa, a 30-room boutique hotel in Udaipur, or an Airbnb portfolio host in Bangalore all run the same underlying loop:

1. Spend on Instagram/Google/Meta ads (~30–60% of CAC budget).
2. Receive inquiries via WhatsApp, IG DM, IVR, web form, OTA.
3. Reply, send rates, negotiate, follow up.
4. Convert to booking (own engine or OTA).
5. Hand off to operations (PMS) for the stay.
6. Hope for repeat / referral.

In V1 customer interviews, the recurring complaints are not "we need another chatbot." They are:

- *"We lose leads because reps don't reply fast enough at 9pm or on Sundays."*
- *"My WhatsApp, IG, and call data live in three places — I cannot tell which ads worked."*
- *"My agent missed an upsell — I only find out when the guest checks out angry."*
- *"My analyst spends 3 days a month exporting CSVs from Booking, Hostaway, WhatsApp, and the IVR portal to build *one* monthly deck."*
- *"My OTA commissions are eating 18% but I cannot prove direct-booking ROI without a data person."*
- *"Returning guests are treated like strangers because nobody connects the phone number to last stay's history."*

Every one of these is **continuity**. Continuity of identity (phone number), continuity of data (cross-channel), continuity of time (pre-arrival → in-stay → post-stay → next inquiry).

## 3.2 Why generic platforms cannot solve this

A pure WhatsApp platform (Wati, AiSensy, Interakt, Gupshup) cannot solve continuity because it does not own the call audio, the PMS reservation, or the ad data. A pure CPaaS (Twilio, Plivo, Exotel) does not own the CRM pipeline or the WhatsApp template approvals as a daily UX. A pure CRM (TeleCRM, LeadSquared) does not transcribe and judge calls. A pure hospitality CRM (Revinate, Asksuite) does not ingest IVR calls or do conversation intelligence. A pure conversation-intelligence tool (Convin, Gong, Salesken) is contact-center DNA, not hospitality-lifecycle DNA.

To solve continuity, an operator today buys **four to six tools** and either pays a data person to glue them together or runs blind. HAIP V2's positioning is: *the operator buys one product, and the product is the continuity.*

## 3.3 The wedge — three sentences

**HAIP is the response-time and revenue-attribution system of record for hospitality.**
**Every guest interaction — ad click, DM, call, message, booking, stay, review — joins on phone number, lands in one timeline, and feeds an AI Data Analyst that tells the owner what to do, not just what happened.**
**Operators choose HAIP because it pays for itself in one extra booking per property per month and never lets a lead go cold.**

This is the line on the homepage. Every roadmap decision is judged against it.

## 3.4 What HAIP is *not*

To resist scope creep:

- HAIP is **not a PMS**. It integrates with Hostaway, Cloudbeds, eZee, STAAH; it does not run housekeeping or front-office.
- HAIP is **not a channel manager**. It does not push rates/inventory to OTAs.
- HAIP is **not a booking engine** for the website (yet — see §12.4).
- HAIP is **not a generic CRM**. Hospitality verticality is the moat.
- HAIP is **not a CPaaS**. It rides on top of Exotel/Twilio/Plivo and Meta Cloud API.

This list will live in the README and the sales deck.

## 3.5 Target segments in V2

**Tier 1 (V2 primary ICP):**
- Villa operators (5–50 properties), independent boutique hotels (20–80 keys), serviced apartment chains (3–20 buildings) in India + GCC + Southeast Asia.
- Pain: high ad spend, fragmented stack, owner is the analyst.
- ACV target: ₹3L–₹15L per tenant per year (~$3.5K–$18K).

**Tier 2 (V2 secondary):**
- Single-property luxury villas with a small ops team (3–8 people).
- Airbnb professional hosts (50+ listings).
- ACV target: ₹50K–₹2L per year.

**Tier 3 (V3+, not V2 focus):**
- Hotel chains (Marriott, Taj, IHCL) — enterprise sales cycle, RFP-driven.
- Cruise lines, vacation clubs.

V2 ships for Tier 1, with onboarding flows simple enough that a 3-person villa office can self-serve. Tier 3 sales-led RFPs are deferred to V3.

---

# 4. Competitive Landscape (2026)

This section condenses the competitor benchmark research into a tactical view. See competitor research artifact for full sourcing.

## 4.1 Category map

| Category | Players | What they own | What they miss |
|---|---|---|---|
| WhatsApp BSP (SMB) | Wati, AiSensy, Interakt, DoubleTick | Inbox, broadcasts, basic chatbot | No voice, no call QA, no PMS, no MMM |
| WhatsApp Enterprise | Gupshup, Infobip, LivePerson | ACE LLM, agent libraries, scale | SMB UX, vertical depth |
| Omnichannel inbox | Respond.io, Trengo | Multichannel + autonomous agents | No call analytics, no hospitality data |
| CPaaS Voice | Exotel, Plivo, Twilio, MyOperator | IVR, calling, voicebots | Generic, no CRM/Analytics layer |
| SMB Phone+ | Superfone, CallHippo | Bundled WA+Voice+CRM | Thin AI, no hospitality |
| Sales CRM | TeleCRM, LeadSquared | Pipeline, telecaller workflows | No call QA, no conversation intelligence |
| Conv. Intelligence | Convin, Salesken, Gong | LLM-as-judge QA, agent assist | Contact-center DNA, no hospitality lifecycle |
| Hotel CRM | Revinate | Hotel guest data, email/SMS | No call QA, no inquiry pre-stay |
| Hotel Chatbot | Asksuite, HiJiffy | Booking-engine chatbot | Pre-booking only, no post-stay, no calls |
| PMS / Channel | Hostaway, Cloudbeds, eZee, STAAH, SiteMinder | Reservations, distribution | No conversation intelligence |

The empty cell is the bottom-left to top-right diagonal: nobody operates across rows.

## 4.2 Feature parity matrix vs HAIP V2

Y = ships in V2; ✓ = competitor has; — = doesn't have it.

| Feature | HAIP V2 | Wati | AiSensy | Gupshup | Respond.io | Convin | Revinate | Asksuite |
|---|---|---|---|---|---|---|---|---|
| WhatsApp inbox | Y | ✓ | ✓ | ✓ | ✓ | — | — | ✓ |
| Visual flow builder | Y | ✓ | ✓ | ✓ | ✓ | — | — | ✓ |
| WhatsApp Flows (in-chat forms) | Y | ✓ | ✓ | ✓ | ✓ | — | — | — |
| CTWA Ads Manager + CAPI | Y | — | ✓ | ✓ | — | — | — | — |
| WhatsApp Catalog + Cart | Y | ✓ | ✓ | ✓ | ✓ | — | — | — |
| WA Pay (India) | Y | — | ✓ | ✓ | — | — | — | — |
| Instagram DM automation | Y | — | — | ✓ | ✓ | — | — | ✓ |
| IG Comment-to-DM | Y | — | — | — | — | — | — | — |
| IVR ingestion | Y | — | — | ✓ | ✓ (limited) | ✓ | — | — |
| Multilingual transcription | Y (12+) | — | — | — | — | ✓ (70+) | — | — |
| LLM-as-judge call QA | Y | — | — | — | — | ✓ | — | — |
| Real-time agent assist | Y | — | — | — | — | ✓ | — | — |
| Voicebot (Vapi/Retell) | Y | — | — | ✓ | ✓ | ✓ | — | — |
| Property-aware routing | Y | — | — | — | — | — | ✓ | ✓ |
| Inquiry pipeline | Y | partial | partial | partial | ✓ | — | ✓ | — |
| Revenue attribution (MMM + MTA) | Y | — | — | — | — | — | — | — |
| AI Data Analyst (NL → insight) | Y | — | — | — | — | — | — | — |
| Insights feed (push) | Y | — | — | — | — | partial | — | — |
| Cross-source correlation | Y | — | — | — | — | — | — | — |
| PMS integrations (Hostaway/Cloudbeds) | Y | — | — | — | — | — | ✓ | ✓ |
| Hospitality QA rubric library | Y | — | — | — | — | — | — | — |
| DPDP compliance toolkit | Y | partial | partial | ✓ | partial | ✓ | ✓ | — |
| White-label | Y | partial | — | ✓ | partial | ✓ | — | ✓ |

The defensible columns for HAIP are the four at the bottom block — *PMS integration depth + hospitality rubric library + cross-source correlation + property-aware everything*. The rest of the column is parity. We are not betting on parity; we are betting on the diagonal that no one operates.

## 4.3 Pricing benchmark

| Player | Entry tier | Per user / msg | Note |
|---|---|---|---|
| Wati | $59/mo Growth | + per-message markup + add-ons | Real bill 30–50% higher |
| AiSensy | Free → $45/mo | Marketing-heavy |
| Interakt | ₹999/mo | Shopify-tied |
| DoubleTick | ~$141/mo | Sales-team focus |
| Respond.io | $79/mo Starter | MAC-based (balloons fast) |
| Exotel | ₹9,999 / 5mo | Voice + WA + SMS pool |
| Plivo | $0.0085/min outbound | PAYG, dev-only |
| Twilio Flex | $150/user/mo or $1/active-hour | Enterprise |
| Superfone | ₹199–₹999/mo | All-in-one SMB India |
| TeleCRM | ₹799/user/mo + WA add-on ₹200 | 3-user min |
| Convin | Custom | Mid-enterprise contact center |
| Revinate | $4/room/mo min $399 | Hospitality CRM |

**HAIP V2 pricing recommendation** (full model in §21):

- **Spark** — ₹4,999/mo (3 users, 1 property, 2 channels) — solo villa / small B&B
- **Pro** — ₹14,999/mo (10 users, 5 properties, all channels, AI Data Analyst Lite)
- **Scale** — ₹39,999/mo (unlimited users, 25 properties, full Agent OS, white-label)
- **Enterprise** — custom (50+ properties, SLA, dedicated support, SOC 2)

Plus pass-through Meta/IVR/transcription costs at cost + 10% (no hidden markups like Wati).

## 4.4 What we learned about positioning

Three positioning bets:

1. **Lead with response time, not features.** The homepage hero is one number: median seconds to first response. Competitors lead with feature counts; we lead with an outcome.
2. **Own "AI Data Analyst" before generic platforms do.** Gupshup and Twilio will get there in 12–18 months; we need to plant the flag in Q3 2026.
3. **Be the hospitality data layer.** When a Cloudbeds or SiteMinder customer asks "where does my conversation data go?", the answer should be HAIP — not their PMS, not a CDP, not Snowflake.

---

# 5. The Hero Metric

A product needs one number to be famous for. For HAIP V2 that number is:

**Median tenant time-to-first-response (TFR) across all channels, measured weekly.**

## 5.1 Why this metric

- **Customers feel it daily** — every missed lead is a lost booking they can mentally price.
- **Statistically meaningful** — first-responder data shows 35–50% pickup of leads, 7× close rate inside one hour.
- **Falsifiable** — it is a real-world clock; no vanity smoothing.
- **Product-shaped** — it forces the AI Concierge, the Flow Studio, the routing rules, and the SLA module to all align on one outcome.
- **Sales-priceable** — "we will get your median TFR under 5 minutes in 90 days, or you pay nothing this quarter" is a clear guarantee.

## 5.2 What feeds TFR

TFR is the time between *first inbound touch on any channel* and *first meaningful outbound response*. "Meaningful" means: a human or AI reply that addresses content, not a templated auto-acknowledge.

Inputs:
- WhatsApp inbound → human / AI reply
- IG DM inbound → human / AI reply
- IVR call → returned call or WhatsApp follow-up
- Web form / OTA inquiry → first channel response
- After-hours coverage by AI Concierge
- Auto-assignment to available rep
- SLA breach notifications

This metric makes every V2 module accountable. The Concierge exists to drive TFR down. The routing exists to drive TFR down. The Flow Studio is a TFR-bypass (the form replies itself). The Analytics layer is what proves we drove it down.

## 5.3 Secondary metrics

Without losing the hero focus, we instrument:

- **AI-attributable revenue per tenant per month** — bookings that touched an AI surface (Concierge, Flow, agent-assisted call) at any step.
- **Repeat-guest share lift** — % of bookings from returning phone numbers, baseline vs after 6 months.
- **Cost per response-minute** — model + infra cost per AI minute, tracking gross margin.
- **CTWA ROAS** — for tenants who advertise on Meta, dollar revenue per dollar of CTWA spend.
- **Call QA coverage** — % of inbound/outbound calls auto-scored.
- **DPDP compliance score** — auto-generated readiness rating per tenant.

All seven metrics live on the *internal* North-Star Dashboard (§23). Only TFR lives on the customer-facing homepage and sales deck.

---

# PART II — FOUNDATION

# 6. The Identity & Data Layer (V2 spine)

Every V2 module rides on a continuity spine: one identity model, one event stream, one semantic layer. This section defines that spine. Without it, modules optimise locally and the cross-source insight thesis collapses.

## 6.1 Phone number as identity — what V2 enforces

V1 already uses `Guest.phone` as the dedup key. V2 hardens this into a true identity service:

- **E.164 normalisation on every write** — strip whitespace, hyphens; infer country code from tenant default; reject malformed.
- **Alias table** — `GuestAlias` (guest_id, channel, channel_identifier) so the same Guest can join on WhatsApp WA ID, IG IGSID, email, OTA reservation ID, and PMS guest ID without losing primary phone.
- **Merge / split tooling** — UI to merge two Guests when phones overlap, with full audit; UI to split (separate two people sharing a phone, common in family bookings).
- **Identity resolution job** — nightly Celery job that scans for likely-same-person duplicates (Levenshtein on name + phone similarity + last property booked) and surfaces for human review.
- **OTA-aware aliasing** — when Hostaway/Cloudbeds sync delivers a booking with a masked OTA phone (e.g., Booking.com aliases), we keep both alias and real phone (post-checkin) and merge on signal.

## 6.2 The unified Touchpoint event stream

V2 introduces a single append-only event table — `Touchpoint` — that every customer-impacting interaction writes to. This is the join target for attribution, the source for the timeline UI, and the input to the semantic layer.

```python
class Touchpoint:
    id: UUID
    tenant_id: UUID                # multi-tenant RLS
    guest_id: UUID | None          # may be unresolved at creation, backfilled
    inquiry_id: UUID | None
    property_id: UUID | None
    occurred_at: datetime          # event time (not ingest time)
    channel: Enum                  # whatsapp | instagram | voice | email | webform | ota | pms | ad
    event_type: Enum               # impression | click | message_in | message_out | call_in | call_out |
                                   # form_submit | booking | check_in | check_out | review | refund | …
    direction: Enum | None         # inbound | outbound
    actor_type: Enum               # guest | human_agent | ai_agent | system | ad_network
    actor_id: UUID | None
    payload: JSONB                 # channel-specific (message text, call duration, ad campaign, …)
    parent_id: UUID | None         # threading
    metadata: JSONB                # utm_*, ctwa_clid, attribution_window, etc.
    cost_inr: Decimal | None       # ad cost / msg cost (for unit economics)
    revenue_inr: Decimal | None    # for booking touchpoints
```

All existing entities (Message, Call, Stay, Inquiry transitions) continue to live in their typed tables; `Touchpoint` is a *projection* written via SQL triggers or Celery hooks. This preserves V1 query patterns and adds the cross-source projection.

Why an event stream, not a star schema? Hospitality lifecycles have many channels, irregular event shapes, and most analytics questions are sequential ("inquiries that received a voicebot answer before human handoff converted at what rate?"). A projection table with `(tenant_id, guest_id, occurred_at)` BRIN-indexed answers these in milliseconds without a warehouse.

## 6.3 New entities V2 introduces

Full schemas in Appendix A. Summary:

- **Campaign** — ad-level: `(channel, platform, campaign_id, ad_set_id, ad_id, name, spend, impressions, clicks, started_at, ended_at, utm_*, ctwa_clid)`. Synced hourly from Meta Ads, Google Ads, manually entered for offline.
- **Booking** — distinct from `Stay`. A `Booking` is a *commercial commitment* (channel, OTA confirmation code, gross amount, net amount, commission, payment status). A `Stay` is the *fulfilment* (check-in/out, room, services). One Booking → 1+ Stays (multi-room) or 1+ Bookings → 1 Stay (extensions).
- **LeadScore** — `(guest_id, inquiry_id, score, model_version, computed_at, features)` — vector of conversion-likelihood scores. Recomputed on every Touchpoint.
- **ChurnRisk** — same shape, scoped to returning guests (probability of next booking within 12 months).
- **LTVForecast** — `(guest_id, forecast_12m, forecast_60m, model_version, computed_at, confidence_band)`.
- **Flow** — visual flow definition (nodes, edges, version). `FlowRun` — execution state per Guest.
- **AgentRun** — every AI agent invocation: `(agent_type, tenant_id, guest_id, started_at, ended_at, model, tokens_in, tokens_out, cost, status, parent_run_id)`.
- **AgentToolCall** — per-tool-call audit: `(agent_run_id, tool_name, args, result, latency_ms, error)`.
- **Insight** — discovered fact: `(tenant_id, type, severity, title, narrative, evidence_query, suggested_actions[], created_at, resolved_at)`. Powers the insights feed.
- **SLA** — `(tenant_id, channel, business_hours, target_first_response_seconds, escalation_chain[])`.
- **SLABreach** — `(sla_id, inquiry_id, breached_at, breach_minutes, escalated_to_user_id)`.
- **BrandTheme** — `(tenant_id, logo_url, primary_color, secondary_color, font_family, email_signature, whatsapp_display_name, white_label_domain)`.
- **GuestAlias** — described in §6.1.
- **Touchpoint** — described in §6.2.
- **Consent (extended)** — already exists; V2 adds `purpose` (marketing | service | recording | profiling), `expiry`, `proof_url` (screenshot of opt-in).

## 6.4 Multi-property awareness everywhere

In V1 `Property` exists but routing logic ignores it. V2 makes every module property-aware:

- Inbound WA message → if matched template includes `{{property}}`, parse + assign to Property.
- IVR call → DID number → Property mapping (already partial; formalize).
- IG comment-to-DM → IG account → Property mapping (multi-account tenants).
- AI Concierge → context window includes property-specific knowledge base (rate card, amenities, policies).
- Flow runs → property selector node defines which Property is "in scope" for downstream logic.
- Reports → property dimension on every visualization.

## 6.5 Tenant + region awareness

- `Tenant.region` enum: `IN | GCC | SEA | EU | US | ROW`.
- Tenant timezone overrides all cron + business hours math.
- Currency on `Tenant`: `inr | usd | aed | eur | sgd`. All money columns store native; reports convert via daily FX rate.
- Per-tenant Meta WABA, per-tenant IVR DID pool — already supported in V1, extended for IG Business Account ID and Google Ads customer ID.

## 6.6 Backwards compatibility

The V2 spine is additive. V1 tables, endpoints, and frontend pages continue to work. The Touchpoint projection is populated for new events from V2 release date; a one-time backfill job rewrites the last 24 months for each tenant after migration. Endpoints `/v1/...` are frozen and additionally a `/v2/...` surface launches with the new entities. Frontend uses `/v2/...` everywhere; the marketing site can keep linking to V1 documentation until deprecation.

---

# 7. Semantic Layer & Metric Definitions

## 7.1 Why a semantic layer

Research finding: text-to-SQL on raw tables hits ~40% accuracy; with a semantic layer it jumps to ~83%. The 2026 industry has converged: dbt MetricFlow and Cube.dev are the two viable open standards. Snowflake, Salesforce, and dbt Labs are pushing Open Semantic Interchange (OSI) — a YAML format that travels across tools.

HAIP V2 ships a semantic layer because:

1. The AI Data Analyst (§15) cannot answer "what's my CTWA ROAS for villas in Goa last quarter, excluding OTA-fulfilled bookings?" reliably without one.
2. Tenants will export to their own BI tools (Looker, Metabase, Hex) and need consistent definitions of "revenue" and "lead."
3. It's the only durable answer to "what is a conversion?" — a question every operator phrases differently.

## 7.2 Choice: MetricFlow vs Cube

**Recommendation: MetricFlow (dbt)**, with a Cube.dev fallback if dbt-Postgres adapter performance disappoints. Reasoning:

- MetricFlow is the OSI reference implementation; betting on the format that will be supported by Snowflake, Salesforce, etc.
- HAIP already has Postgres + Alembic — a dbt deployment slots in cleanly as a sidecar service.
- We can expose MetricFlow as a `/v2/metrics` JSON API for the frontend + AI Data Analyst without needing a full BI tool.

Cube has better caching and better SQL pre-aggregations but is less aligned with the OSI direction. We will re-evaluate quarterly.

## 7.3 The HAIP canonical model (YAML excerpt)

```yaml
# models/haip_inquiry.yml
semantic_models:
  - name: inquiry
    model: ref('inquiry')
    entities:
      - name: inquiry_id
        type: primary
      - name: guest_id
        type: foreign
      - name: property_id
        type: foreign
      - name: campaign_id
        type: foreign
    dimensions:
      - name: stage
        type: categorical
      - name: source_channel
        type: categorical
      - name: lost_reason
        type: categorical
      - name: created_at
        type: time
        type_params:
          time_granularity: day
    measures:
      - name: inquiries_count
        agg: count
      - name: bookings_count
        agg: count
        expr: case when stage = 'BOOKED' then 1 end
      - name: gross_booking_value
        agg: sum
        expr: booking_gross_inr
      - name: net_booking_value
        agg: sum
        expr: booking_gross_inr - ota_commission_inr - payment_fee_inr

metrics:
  - name: conversion_rate
    type: ratio
    type_params:
      numerator: bookings_count
      denominator: inquiries_count
  - name: time_to_first_response_p50
    type: simple
    type_params:
      measure: time_to_first_response_seconds
      agg: median
```

The full model covers ~25 dimensions and ~40 metrics across `inquiry`, `conversation`, `call`, `message`, `booking`, `stay`, `campaign`, `touchpoint`, `agent_run`. Defined in version-controlled YAML so every change is reviewed.

## 7.4 The Glossary — operator-facing

Each metric has a plain-English definition that appears in tooltips throughout the product *and* is fed to the AI Data Analyst as part of its system prompt:

- **Inquiry** — A first inbound touch from a Guest expressing interest (WA, IG, call, web, OTA, walk-in). Excludes spam and existing-booking service queries.
- **Lead** — Synonym for Inquiry in NEW or RESPONDING stage. Operators use the words interchangeably; we standardize.
- **Booking** — Confirmed commercial commitment with at least one payment milestone (deposit or full).
- **Stay** — Fulfilled booking (Guest arrived).
- **Conversion rate** — Bookings ÷ Inquiries, scoped to a time window of the *inquiry's creation date* (not the booking date), to avoid attribution confusion.
- **Time to First Response (TFR)** — Seconds between first inbound touch and first meaningful outbound response, where "meaningful" means content addressing the inquiry (not a templated auto-acknowledge). Pre-computed nightly + on every Touchpoint write.
- **Direct booking** — Booking with `source = direct | whatsapp | call | webform`. Excludes `booking.com | airbnb | expedia | makemytrip | agoda | …`.
- **Net booking value** — Gross − OTA commission − payment processing fee. Reported per Property.
- **AI-attributable revenue** — Net booking value where any Touchpoint in the inquiry chain has `actor_type = ai_agent`.
- **Repeat guest** — Guest with ≥ 2 bookings whose check-in dates are ≥ 30 days apart.
- **LTV** — Sum of net booking value for a Guest, projected forward 60 months using LTVForecast model.

This list lives in `glossary.yml` and is rendered as `/docs/glossary` in the product.

## 7.5 How metrics get to the UI

```
Postgres (raw tables + Touchpoint projection)
    ↓
dbt models (cleaning, business logic, joins)
    ↓
MetricFlow semantic layer (dimensions + measures + metrics)
    ↓
HAIP Metrics API (`/v2/metrics` — JSON, cache-aware)
    ↓
    ├─ Frontend dashboards (Recharts/Tremor)
    ├─ AI Data Analyst (Athena) — uses metric definitions for text-to-SQL
    ├─ Insights feed (anomaly detection runs on metrics)
    └─ Export endpoints (CSV / Looker / Metabase / Hex)
```

Metric API request example:

```http
POST /v2/metrics/query
{
  "metrics": ["conversion_rate", "time_to_first_response_p50"],
  "dimensions": ["property.region", "created_at__week"],
  "filters": {"property.type": ["villa"]},
  "date_range": {"start": "2026-04-01", "end": "2026-05-15"}
}
```

Response is a structured grid + SQL trace (for AI Data Analyst auditing).

---

# PART III — CONVERSATIONAL INTELLIGENCE MODULES

# 8. WhatsApp Intelligence Hub

## 8.1 Where V1 is today

V1 ships an inbox (inbound message routing, conversation threading), template manager schema, campaign schema (no broadcast logic), subscribers schema, and a flow schema (no runtime). Meta Cloud API v20 adapter is live for receiving and sending text messages. The AI surface includes lead classification, sentiment analysis, lost-reason theming, and a `concierge_draft` task that proposes a reply but has no approval UX. Inbound message → Inquiry creation is wired; inbound → Guest dedup on phone works.

What is missing is everything users see as "WhatsApp marketing": campaign broadcast with rate-limit-aware throttling, visual flow builder, CTWA Ads Manager, Catalog + Cart, WhatsApp Pay checkout, an opt-in compliance suite, and AI agents that can carry a multi-turn conversation autonomously.

## 8.2 Operator pain points (from interviews + research)

- *"My team has eight WhatsApp numbers, and a guest gets replies from three different reps with three different prices."*
- *"I run CTWA ads but I can't tell which ad drove which booking."*
- *"My templates take 4 days to get Meta-approved and I have no preview that matches what the guest sees."*
- *"Wati's chatbot is keyword-based and breaks the moment a guest writes a typo."*
- *"I want to ask guests pre-arrival questions (arrival time, dietary, pickup) without sending a Google Form link."*
- *"Marketing sends a broadcast → 200 people opt out → I have no way to honor that across all channels."*
- *"After-hours inquiries (10pm to 8am, weekends) go cold. I lose half my pipeline to time-of-day."*

## 8.3 V2 vision

The WhatsApp Intelligence Hub is HAIP's busiest surface. It must do five things excellently:

1. **Conversation** — best-in-class shared inbox that handles 10K+ daily messages without lag, threaded by Guest, channel-aware (so the same Guest's WA + IG + email + SMS conversations collapse into one timeline if the operator wants).
2. **Automation** — visual flow builder + WhatsApp Flows (in-chat forms) + AI agents that can autonomously progress a Guest through pre-arrival → check-in → in-stay → post-stay → re-engagement.
3. **Acquisition** — CTWA Ads Manager that ties ad spend to booking revenue, with WhatsApp Catalog + Cart for in-chat conversion and WhatsApp Pay UPI checkout for India.
4. **Compliance** — opt-in suite (with proof-of-consent storage), template lifecycle management, broadcast throttling, quality-rating dashboard.
5. **Intelligence** — every message is classified, sentiment-tagged, and feeds the Inquiry pipeline + AI Data Analyst.

## 8.4 Sub-modules

### 8.4.1 Shared Inbox 2.0

**What ships:**
- Multi-WABA support — a tenant can connect multiple Meta WhatsApp Business Accounts (one per brand/property) into a single inbox with WABA selector.
- Real-time updates via Server-Sent Events (V1 has this; extend for typing indicators, read receipts, message status).
- **Unified Guest view** — a Guest's WA, IG, email, call thread collapses into one chronological timeline with channel-icon decorations. Operator can reply on any channel from one composer.
- **Assignment rules** — round-robin, property-based, language-based, lead-score-based. Visual rules editor.
- **Snooze, pin, internal notes** — internal `@mention`s with audit.
- **AI Draft button** — already in V1; extend to "Draft a reply", "Suggest 3 replies", "Translate this reply", "Make it more formal/casual", with one-click insert.
- **Quick replies** — saved snippets per Property with merge fields ({{guest_name}}, {{villa_name}}, {{check_in}}).
- **Inline media** — image gallery, PDF preview, location pin, contact card.
- **Inline rate quoting** — operator drags a Property + dates into the composer; AI generates a quote message with availability check, rate, and a "Book on WhatsApp" Catalog message.
- **Conversation summary panel** — left rail shows AI-generated summary of the conversation so a new agent picking up an open thread has context in 5 seconds.

**Data model deltas:** none beyond V1; the unified Guest view is a query, not a new table.

### 8.4.2 Template Studio

**What ships:**
- Visual template editor — drag-drop header/body/footer/buttons matching Meta's UI.
- **Live preview** — exact rendering of how it shows on iOS, Android, WA Web.
- **Sample value preview** — fills `{{1}}`, `{{2}}` with realistic Guest data so reviewers see the final text.
- **Variable lineage** — each variable shows its source (Guest field, Inquiry field, Property field, custom). Catches mismatches before Meta submission.
- **Approval status tracking** — Meta status (Pending/Approved/Rejected/Paused/Flagged) syncs via webhook + nightly poll.
- **AI Template Suggester** — operator describes intent in plain English ("welcome message for new guests with a 10% off CTA"), agent drafts 3 candidates that comply with Meta policy.
- **Template library** — pre-built hospitality templates: booking confirmation, pre-arrival, check-in instructions, late checkout offer, review request, NPS, abandoned-quote follow-up. ~30 templates ship for Q3 release.
- **Compliance checks** — pre-submission lint: prohibited terms ("guaranteed", "win"), max length, button placement, category match.

### 8.4.3 Broadcast Engine

**What ships:**
- Audience builder with semantic-layer dimensions (e.g., "Repeat guests in Goa who last stayed >180 days ago, opted in to marketing").
- Throttled send respecting Meta's tier (1K → 10K → 100K → unlimited) — Celery rate-limit aware.
- **Send-time optimisation** — model recommends best 4-hour window per Guest based on their reply history (V2.1).
- A/B test split (template variant A vs B, 10% sample, statistical winner).
- **Quality monitoring** — auto-pause if quality rating drops below "high" or if opt-out rate exceeds threshold.
- **DLT/DPDP-compliant logging** — every send writes a Touchpoint with consent proof reference.
- **Smart suppression** — campaign opt-outs propagate across all channels; campaign suppress list also auto-suppresses unresolved support cases, recently-stayed guests, and a per-tenant DNC list.
- **Cost preview** — pre-send estimate of Meta charges (marketing template per delivery).
- **Result analytics** — per-template reach, read, reply, click, opt-out, booking-attributed revenue.

### 8.4.4 Flow Studio (NEW)

WhatsApp Flows are Meta's in-chat structured forms (dropdowns, date pickers, multi-step). Research shows 158% higher conversion vs web forms and 62–78% completion rates in hospitality use cases.

**What ships:**
- Visual flow designer — drag-drop nodes (Message, Question, Input, Branch, API Call, AI Step, Wait, Tag, Hand-off).
- **Pre-built flow templates** — Pre-arrival info (10 questions: arrival time, pickup needed, dietary, allergies, anniversary?), Booking inquiry (dates, guests, property, budget), Review collection, Cancellation reason, Lost-deposit recovery, Loyalty signup.
- **API Call node** — calls HAIP backend or external (e.g., PMS check availability, push booking to Cloudbeds).
- **AI Step node** — invokes the Agent OS with a defined input/output schema (e.g., "given dietary preferences, generate three personalised menu suggestions").
- **Conditional branching** — if/then on Guest property, response value, language detection.
- **Multilingual flow** — single flow definition, per-language string overrides (V2 ships English, Hindi, Gujarati, Tamil, Marathi, Bengali, Arabic; framework supports any).
- **Run state** — `FlowRun` table tracks per-Guest progress, abandoned-flow recovery (Wait + re-prompt after N hours).
- **Analytics** — funnel chart per node, drop-off heatmap, time-on-node.

**Why this matters:** Flow Studio is the single highest-leverage feature for TFR. A pre-arrival Flow that asks 10 questions runs autonomously at 11pm; the operator wakes up to 100% of pre-arrival data collected and a sorted action list. No competitor in the hospitality vertical ships Flows with API-call + AI-step nodes integrated to a hospitality data model.

### 8.4.5 CTWA Ads Manager (NEW)

Click-to-WhatsApp Ads are the highest-intent Meta ad surface. Research: typical ROAS 3–8x, Indian businesses report 5–15x. The 72-hour free-message window post-CTWA-click means every CTWA conversation is functionally free for the operator until reply runs cold.

**What ships:**
- Direct Meta Ads Manager integration via Marketing API (one-click campaign creation from within HAIP).
- **AI Ad Copy** — operator gives a Property + offer; AI generates 5 ad variants (headline + body + image prompt) with Meta-policy linting.
- **Audience suggester** — pull from semantic layer: lookalike of past-bookers, repeat-guest lookalike, lost-deposit lookalike.
- **Conversions API integration** — every ad-driven WA conversation writes `ctwa_clid` to the Touchpoint, and bookings that descend from it fire `Purchase` events back to Meta (this is the linchpin for ROAS measurement; without CAPI, attribution is broken).
- **CTWA Funnel Dashboard** — Impressions → Clicks → Conversations Started → Replied → Quoted → Booked → Revenue.
- **Revenue-back attribution** — Meta receives ROAS signal, so Advantage+ campaigns can optimise toward booking revenue, not just clicks.
- **Smart pause** — if quality of CTWA conversations drops (no booking signal in 14 days), Agent OS recommends ad pause/refresh.

**Cost model:** Meta's 72-hour free window means HAIP can run a CTWA campaign on behalf of a Property and only pay for the *ad* and the *post-72-hour follow-ups*. We pass this saving to operators as part of the value prop.

### 8.4.6 WhatsApp Catalog + Cart for Hospitality

Rooms-as-products is novel but supported. Operators in V1 have no way to send a Catalog message in-chat.

**What ships:**
- **Catalog sync from Property + RatePlan** — each Property generates a Catalog category; each RatePlan or Room becomes a Product with image, description, price.
- **Dynamic pricing** — Catalog refreshed nightly from PMS rate pulls.
- **In-chat browsing** — operator (or AI Agent) sends "View Rooms" → Catalog message → Guest scrolls products in WhatsApp → adds to Cart.
- **Cart-to-Inquiry** — when Guest submits Cart, a Booking entity is created in DRAFT state and Inquiry advances to QUOTED.
- **WhatsApp Pay (India)** — Razorpay/PayU/BillDesk integration; UPI checkout in-chat; cap ₹1,00,000/txn per NPCI.
- **Confirmation flow** — successful payment → Booking → confirmation template → optional Pre-arrival Flow.

This unlocks "complete the booking inside WhatsApp" for direct guests, which is the most ROI-positive flow because it bypasses OTA commission entirely.

### 8.4.7 AI Agents (the WhatsApp slice of the Agent OS)

The Agent OS is described fully in §14. Here are the WhatsApp-side agents:

1. **AI Concierge** (the default) — answers questions, generates rate quotes, sends Catalog, escalates to human on intent shift.
2. **AI Booking Agent** — focused on conversion: knows live availability, can hold a room (calls PMS via adapter), drives Cart + Pay.
3. **AI Pre-Arrival Agent** — runs the Pre-arrival Flow, collects info, schedules pickup, generates internal ops checklist.
4. **AI Re-engagement Agent** — Re-activates inactive Guests with offers timed to their travel pattern.
5. **AI Support Agent** — handles common service issues (housekeeping requests, Wi-Fi, late checkout) during stay; PMS-aware.
6. **AI QA-Assist Agent** — *not a guest-facing agent*. Audits human-agent WhatsApp replies for tone, accuracy, policy compliance; flags risky drafts before send.

Each agent has:
- A defined system prompt (versioned, eval-tested — see §20).
- A tool whitelist (e.g., Pre-Arrival cannot send rate quotes; Booking cannot delete bookings).
- Memory scoped to Guest + Property + Tenant.
- A handoff policy (when to escalate to a human).

**Approval modes per Property/Tenant:**
- **Full autonomy** — AI sends replies directly.
- **Draft mode** — AI proposes; human approves with one tap.
- **Co-pilot mode** — AI annotates the conversation but does not generate sends.

A tenant can pick mode per agent per channel per business hours (e.g., autonomy 10pm–8am, draft mode during business hours).

### 8.4.8 Opt-in Compliance Suite

- **Consent capture surfaces** — webform widget, QR code, manual entry; every capture writes Consent + Touchpoint with proof.
- **Per-purpose consent** — marketing, service, recording, profiling stored separately.
- **One-tap opt-out** — every marketing template includes opt-out keyword handling; processed within 30 seconds; suppression propagates to broadcast lists immediately.
- **Quality rating dashboard** — Meta's per-WABA quality score with trend; tenant alerts on drop.
- **Audit log** — every send / opt-in / opt-out emits an audit event (existing V1 module).

### 8.4.9 Calling on WhatsApp (NEW, V2.1)

Meta launched the WhatsApp Business Calling API globally July 2025. By V2.1 we wire this for tenants on Pro+:

- Inbound WA call → routed to operator's HAIP web UI (WebRTC) or forwarded to existing IVR DID.
- Outbound WA call from inbox composer.
- WA call recording (with consent prompt) → same transcription + QA pipeline as IVR calls.
- Threading: the call and the chat collapse into the same Conversation.

This is parity with Respond.io + Plivo on WA voice; the differentiator is that the call runs through HAIP's QA pipeline.

## 8.5 Data model deltas (WhatsApp)

```python
class WAFlowRun:
    id: UUID
    tenant_id: UUID
    flow_id: UUID
    guest_id: UUID
    inquiry_id: UUID | None
    state: Enum  # active, completed, abandoned
    started_at, completed_at: datetime
    node_history: JSONB  # [{node_id, entered_at, exited_at, response}]
    collected: JSONB     # final form payload

class WACampaign (extends V1):
    + audience_definition: JSONB  # semantic layer query
    + a_b_variants: list[UUID]   # template ids
    + start_at, scheduled_at: datetime
    + status: Enum  # draft, scheduled, sending, paused, complete, failed
    + auto_pause_rules: JSONB

class CTWACampaign:
    id, tenant_id, property_id
    meta_campaign_id, meta_ad_set_id, meta_ad_ids: list
    spend_inr, impressions, clicks, conversations_started: int
    status: Enum

class WACart:
    id, tenant_id, guest_id, conversation_id
    items: JSONB  # [{property_id, rate_plan_id, qty, price}]
    total_inr: Decimal
    status: Enum  # draft, submitted, paid, abandoned
    payment_intent_id: UUID | None
```

## 8.6 AI architecture (WhatsApp slice)

| Use case | Model | Pattern |
|---|---|---|
| Inbound message classification | Claude Haiku 4.5 | Prompt cache w/ examples (V1 pattern) |
| Reply draft / Concierge | Claude Sonnet 4.6 | RAG over Property KB + Conversation history |
| AI Ad Copy | Claude Sonnet 4.6 | Few-shot with brand voice samples |
| Template suggester | Claude Sonnet 4.6 | Policy-aware constrained generation |
| Flow AI Steps | Claude Haiku/Sonnet (per node) | Schema-constrained JSON output |
| QA-Assist | Claude Sonnet 4.6 (judge mode) | LLM-as-judge with rubric |

Fallback: Gemini Flash for cost-sensitive paths if Anthropic quota exhausts.

## 8.7 UX flows (selected)

**Flow A — Operator sends a rate quote**
1. Operator opens inbox, picks Conversation.
2. Clicks "Rate Quote" button on composer.
3. Modal: pick Property, dates, guests. AI checks availability (PMS adapter) and computes price.
4. AI generates a 3-sentence quote text + a Catalog message with 2 rate options.
5. Operator clicks Send.
6. Touchpoint written; Inquiry → QUOTED stage; SLA stopwatch updated.

**Flow B — A guest clicks a CTWA ad**
1. Meta delivers click, `ctwa_clid` arrives via webhook.
2. WA inbound message lands; HAIP creates/links Guest, creates Inquiry with `campaign_id`, writes Touchpoint with `ctwa_clid`.
3. AI Concierge replies within 8 seconds (target).
4. Conversation progresses; if Booking lands, `Purchase` event fires to Meta CAPI with `ctwa_clid` for attribution.

**Flow C — A pre-arrival Flow runs 48h before check-in**
1. Cron triggers FlowRun creation for upcoming Stays.
2. WA template + Flow attachment sent.
3. Guest fills 6 fields in-chat.
4. FlowRun.completed; data written to Stay (arrival_time, pickup_needed, dietary).
5. Internal ops checklist auto-generated for housekeeping.
6. If Guest doesn't respond in 12h, Wait → re-prompt with simplified question.

## 8.8 Acceptance criteria

- Inbox supports 5K+ open conversations per tenant without UI lag (p95 inbox load <600ms).
- Template submission to Meta and approval round-trip surfaced inside HAIP.
- Broadcast of 50K messages completes within 4 hours on Meta tier 10K with zero quality drop.
- CTWA → Booking attribution end-to-end demonstrable in dogfood tenant within 30 days.
- Pre-arrival Flow completion rate ≥ 60% in beta tenants.
- AI Concierge first-response p95 < 12 seconds (model + Meta latency).
- Per-purpose Consent capture surfaces on all opt-in flows; auto-suppression demonstrated.

---

# 9. Instagram Intelligence Hub

## 9.1 Where V1 is today

V1 has the Meta Instagram Graph API adapter wired (send DM, mark seen, typing indicator), webhook ingest, and Celery worker tasks. The frontend does not yet render an IG inbox; conversations created from IG events are stored but not surfaced. There is no comment-to-DM automation, no story-mention handling, no IG Ads → DM funnel.

## 9.2 Operator pain points

- *"My villas get most discovery on Reels but every IG comment gets the same generic 'DM us' reply, which the algorithm punishes."*
- *"I have to log in to Instagram app on a personal phone to reply to DMs; there's no team inbox."*
- *"My Reels ads send people to DM and then nothing — there's no funnel I can measure."*
- *"Asking guests for a review on IG never lands because there's no story-share automation."*
- *"I keep getting account warnings from Meta because my VA replies to 500 DMs an hour with the same script."*

## 9.3 V2 vision

Instagram becomes a first-class peer to WhatsApp in HAIP. Same inbox, same Inquiry pipeline, same AI Concierge, *with IG-specific superpowers*:

1. **Comment-to-DM automation** — keyword trigger on Reel/post comment auto-DMs the commenter with a personalised hook + optional Flow.
2. **Story-mention auto-response** — when a Guest tags the brand in a Story, auto-DM a thank-you + reshare prompt; if mid-stay, route to Support agent.
3. **IG Ads → DM funnels** — same CTWA-style attribution but for Instagram ad set → DM landing.
4. **Compliance-aware throttling** — respect 200 DM/hour cap, character-diversity (no 25+ identical DMs/hour), warm-up curves for new IG accounts.
5. **Unified Guest** — IG Sender ID stored as `GuestAlias`; the same Guest's WA + IG + call timeline collapses in HAIP.

## 9.4 Sub-modules

### 9.4.1 IG Inbox & Composer

Same shared-inbox UX as WhatsApp, with IG-specific message types: text, image, voice note, story mention, reaction. Single composer per Guest spans WA + IG; operator picks channel per send.

### 9.4.2 Comment-to-DM Engine

- **Trigger rules** — per post / Reel / live, keyword(s), exact-match, or AI-classify (sentiment positive + intent-to-buy).
- **DM template** — message with optional Flow attachment, with private-reply variation (Meta's private-reply API has 1-msg-per-comment-within-7-days cap; HAIP respects this).
- **Audience analytics** — funnel per Reel: comments → matched → DMed → replied → led to Inquiry → led to Booking.
- **Anti-spam controls** — per-account hourly cap, character-diversity randomiser (3 message variants randomised), human-pause if reply rate drops.
- **AI Comment-Classifier** — when "keyword" is too blunt, an LLM classifier decides if the comment merits a DM (filters trolls, repeat commenters, off-topic).

### 9.4.3 Story Mentions & Replies

- Webhook on Story mention → AI generates personalised thank-you DM (e.g., "Loved seeing you at Villa Saffron, Aarav! Hope the rooftop dinner was perfect.").
- Automated reshare consent — opt-in template asking Guest to allow re-share to brand Story; if granted, post a UGC story.
- Mid-stay detection — if Story mention occurs during a known Stay window, route to AI Support Agent for in-stay sentiment capture.

### 9.4.4 IG Ads → DM Attribution

- IG Ads Manager integration similar to CTWA (§8.4.5) but with the IG-specific webhook signal.
- Each DM-driven Inquiry tagged with `campaign_id`, `ad_id`, `ad_creative_id`.
- Revenue-back attribution to Meta CAPI for IG ads driving bookings.

### 9.4.5 Rate-Limit-Aware Throttling

- Token-bucket per IG account at 200/hour, with safety burn-down to 150/hour during warm-up first 30 days.
- Per-day soft cap 600.
- Variation engine — every send body is hashed; if >25 sends in 1 hour share a hash, throttle automatically.
- Auto-pause + Slack notification to operator if Meta returns 429 or quality drop signal.

### 9.4.6 AI Agents on IG

Same agent menu as WhatsApp (Concierge, Booking, Re-engagement, Support), with IG-specific persona variants (more emoji, casual tone — operator can override). Voice replies (audio messages) supported in V2.1 with TTS via ElevenLabs adapter.

## 9.5 Data model deltas

- Extend `Touchpoint.payload` to support IG-specific event types (`story_mention`, `comment`, `reaction`).
- `IGAccount` entity (tenant_id, ig_business_id, ig_user_id, warm_up_started_at, daily_quota, hourly_quota).
- `CommentToDMRule` (account_id, trigger_keywords[], trigger_post_ids[], template_id, flow_id, enabled).

## 9.6 Acceptance criteria

- IG inbox parity with WA inbox UX (same composer, same Guest timeline merge).
- Comment-to-DM funnel demonstrable end-to-end with conversion attribution.
- No tenant IG account triggered Meta rate-limit warning during 60-day beta.
- Story mention auto-response p95 latency < 30 seconds.

---

# 10. IVR & Call Intelligence 2.0

## 10.1 Where V1 is today

This is V1's strongest module. CallerDesk + Acefone webhooks live; recording → S3; Groq Whisper → Deepgram fallback transcription with diarization; LLM-based classification + judgment + wrap-up tasks; CallScore with rubric criteria; Transcript with turn-level diarization; QA UI for rubric editing and human override; call detail page with audio player synced to transcript.

What is missing is the next tier:

- LLM-as-judge replacing the static rubric (industry has moved on from rubric scoring).
- Real-time agent assist (live whisper coaching).
- Voicebots in the IVR tree (Vapi/Retell).
- Paralinguistic sentiment (tone/pitch/energy, not just words).
- Multilingual depth (V1 is English-first; production tenants need Hindi/Marathi/Tamil/Gujarati/Bengali/Kannada/Telugu/Punjabi/Malayalam/Arabic).
- Property-aware routing and post-call coaching loops.
- Repeat-guest recognition at first ring.

## 10.2 Operator pain points

- *"I record 200 calls a day, listen to maybe 5. The rest are dark."*
- *"My junior reps don't know the rate card on the call and quote wrong — I want a whisper coach."*
- *"Out-of-hours calls go to voicemail. Voicemail is a dead end."*
- *"When a returning guest calls, my rep treats them like a stranger because the screen doesn't pop their history."*
- *"My QA rubric scoring people on 'said greeting' is theatre. I want to know if the rep handled the objection well."*

## 10.3 V2 vision

The call surface is the highest-trust channel in hospitality. V2 elevates it from "we record and transcribe" to "we coach in the moment and score against hospitality-specific judgment."

Five pillars:

1. **Property + repeat-guest screen-pop** — phone number → Guest lookup → past stays, F&B preferences, last complaint → on screen before the rep answers.
2. **Voicebot IVR** — first-ring AI receptionist that qualifies, takes booking inquiries, schedules callbacks; integrated to Property knowledge base and live availability.
3. **Real-time agent assist** — live transcription + LLM-based prompts to the rep ("Guest mentioned anniversary — offer the romance package", "rate quoted exceeds Property's floor — confirm", "objection detected: handle with the budget script").
4. **LLM-as-judge QA** — rubric becomes the *prompt* for an evaluator LLM; every call (not a sample) gets a holistic score, criterion breakdown, evidence quotes, suggested coaching action.
5. **Paralinguistic signals** — sentiment from audio (energy, pace, frustration markers) folded into QA + insights feed.

## 10.4 Sub-modules

### 10.4.1 Multilingual Transcription

- Primary: Groq Whisper Large-v3 (free tier 7200s/day) — supports 99 languages with reasonable Indian-language quality.
- Fallback: Deepgram Nova-2 (paid) — best diarization accuracy.
- Tertiary: AssemblyAI Universal-2 — strong in noisy Indian environments.
- **Language detection per call** — first 15 seconds classified; downstream prompts in detected language.
- **Code-switching support** — Hinglish, Tanglish are explicitly handled (Whisper handles natively; we tune diarization for code-switch boundaries).

### 10.4.2 Voicebot IVR (NEW)

V2 supports two patterns:

**Pattern A — Bot-first, human-second.**
- Inbound call hits Vapi (or Retell) voicebot configured for the Property.
- Bot greets, qualifies (existing booking? new inquiry?), pulls Guest history if known, answers ~70% of FAQs against Property KB.
- Booking inquiries → bot collects dates + guests + budget → either books inside the call (PMS adapter, V2.1) or schedules a callback with sales.
- Escalation triggers: confusion (3 consecutive failed turns), explicit ask for human, high-value Guest (LTV > threshold).

**Pattern B — Human-first, bot-after-hours.**
- 9am–9pm routes to human IVR tree (existing).
- 9pm–9am routes to voicebot for triage + callback scheduling.

Vapi is the recommended primary (best latency 500–600ms; transparent pricing; LangChain-aligned). Retell as fallback (lowest latency ~600ms; better English voices). Bland as enterprise fallback.

**Property knowledge** — each Property has a structured KB (amenities, FAQ, rate card, policies, F&B menu, neighbourhood guide) consumed by the voicebot prompt. The KB is editable in HAIP and version-controlled.

### 10.4.3 Real-Time Agent Assist (NEW)

During a live call:

- Browser-based softphone (HAIP web UI integrating with CallerDesk / Acefone WebRTC) — operator answers in-app.
- Streaming transcription via Deepgram streaming API (already supports streaming) — partial transcripts arrive every ~300ms.
- Every 5–10 seconds, the streaming transcript is fed to a Claude Haiku eval prompt with:
  - Property context.
  - Guest history.
  - Sales playbook.
  - Compliance rules (recording disclosure, opt-in language).
- The eval returns: (a) optional whisper prompt (text shown to the rep, e.g., "Mention complimentary breakfast"), (b) compliance flag if needed, (c) deal-risk warning ("Guest just mentioned competitor — propose anchor offer").
- Whispers render in a side panel with one-click "Used / Ignored" buttons (closes the coaching loop).

Cost-control: Haiku 4.5 + prompt caching → ~$0.0003/call-minute; affordable to run on every call by default.

### 10.4.4 LLM-as-Judge QA (replacing rubric scoring)

V1 has a CallScore with criteria — but criteria are evaluated by an LLM call per criterion, which is brittle.

V2 changes the architecture: the rubric becomes a *judge prompt template*. The full transcript + diarization + paralinguistic signals are fed to a Sonnet 4.6 evaluator that returns a structured JSON:

```json
{
  "overall_score": 78,
  "criteria": [
    {"name": "Greeting", "score": 100, "evidence": "turn 1: 'Good evening, welcome to Villa Saffron'"},
    {"name": "Need_Discovery", "score": 60, "evidence": "..."},
    {"name": "Rate_Quote_Accuracy", "score": 80, "evidence": "..."},
    {"name": "Objection_Handling", "score": 75, "evidence": "..."},
    {"name": "Close", "score": 70, "evidence": "..."}
  ],
  "sentiment_trajectory": [
    {"turn": 1, "guest": "neutral", "agent": "warm"},
    {"turn": 14, "guest": "frustrated", "agent": "warm"},
    {"turn": 22, "guest": "neutral", "agent": "warm"}
  ],
  "key_moments": [
    {"turn": 14, "type": "objection", "summary": "Price compared to neighbouring villa"},
    {"turn": 20, "type": "anchor", "summary": "Agent offered 10% off for 4+ nights"}
  ],
  "coaching_action": "Need-discovery was rushed; recommend probing for occasion type before quoting.",
  "compliance_flags": []
}
```

**Hospitality QA rubric library** (V2 ships 6 rubrics):

1. Inbound new inquiry — sales script.
2. Inbound existing guest — service script.
3. Outbound follow-up — chase script.
4. Inbound complaint — service-recovery script.
5. Inbound booking confirmation — compliance + upsell.
6. Outbound win-back — re-activation script.

Tenants can clone and edit rubrics.

### 10.4.5 Paralinguistic Sentiment

Deepgram and AssemblyAI now expose pitch / energy / speaking-rate signals. V2 captures:

- Per-turn agent and guest energy (low / medium / high).
- Sentiment time-series (positive / neutral / negative) folded into the call detail UI.
- Frustration markers (raised energy + interruptions + negative valence) auto-tagged as `key_moment`.

This feeds the insights feed (e.g., "Calls between 7–9pm show 30% more guest frustration — investigate staffing.").

### 10.4.6 Post-Call Coaching Loop

After every scored call:

- If overall score < 60: auto-create a Coaching task assigned to the rep with the call's key moments + recommended action.
- Coaching session view: AI summary + 3 highlight clips + 1 written recommendation.
- Weekly per-rep coaching digest sent via WA + email; tracks trend, top strengths, top growth area.
- Property-level leaderboards.

### 10.4.7 Repeat-Guest & VIP Routing

- Inbound call → phone lookup → if Guest exists: enrich screen-pop with last stay date, last property, F&B preferences, last complaint, LTV bucket, lead score.
- Routing rules: VIPs (high LTV) skip queue → directly to assigned host; complaint history → senior rep; first-time → standard pool.
- Greeting templates per Guest bucket ("Welcome back, Mr Sharma — last with us in March").

## 10.5 Data model deltas

```python
class CallScore (V2 form):
    + judge_prompt_version: str
    + judge_model: str
    + judge_output_json: JSONB    # full structured eval
    + paralinguistic_summary: JSONB
    + coaching_action_id: UUID | None

class CoachingTask:
    id, tenant_id, user_id (rep), call_id, manager_id
    summary, recommendation, evidence_clip_urls
    status: pending | reviewed | resolved
    created_at, resolved_at

class VoicebotSession:
    id, tenant_id, call_id (linked when handover)
    provider: vapi | retell | bland
    transcript: JSONB
    outcome: handled_by_bot | escalated | callback_scheduled | booked
    knowledge_used: JSONB
```

## 10.6 AI architecture

| Use case | Model | Latency target |
|---|---|---|
| Streaming transcription | Deepgram Nova-2 streaming | <300ms partial |
| Streaming agent-assist eval | Claude Haiku 4.5 | <2s suggestion |
| Voicebot turn | Vapi / Retell (orchestrating Sonnet 4.6) | <800ms end-to-end |
| Call QA judge (batch) | Claude Sonnet 4.6 | <30s per call |
| Coaching summary | Claude Haiku 4.5 | <5s |

## 10.7 UX flows (selected)

**Flow D — Returning guest calls at 11pm**
1. Voicebot answers.
2. Caller ID → Guest match → KB context includes last stay.
3. Voicebot greets by name, asks what they need.
4. Guest asks "is the rooftop suite available 12–15 June?" Bot checks Hostaway, replies, asks if they want to hold.
5. If yes: Bot collects deposit intent, schedules a callback for human confirmation in business hours, sends WA message with summary, writes Inquiry + Touchpoint.

**Flow E — Live whisper during a call**
1. Rep answers inbound; transcription streams.
2. At turn 6, transcript contains "your prices are higher than the villa next door."
3. Eval LLM returns: `whisper: "Anchor on amenities — mention private chef and rooftop pool included; offer 4-night discount as fallback."`
4. Whisper text appears in rep's side panel; one-click "Used".
5. After call: judge rates objection handling; rep gets +5 if used.

## 10.8 Acceptance criteria

- 100% of inbound calls auto-scored within 60 seconds of call end.
- Voicebot handles ≥ 50% of after-hours calls without human escalation in pilot tenants.
- Whisper agent-assist returns suggestions with p95 < 2.5 seconds.
- Multilingual transcription WER ≤ 12% for Hindi/Marathi/Tamil at production volume.
- Paralinguistic sentiment time-series renders on call detail UI.
- Coaching task creation triggers automatically on score < 60.

---

# PART IV — LIFECYCLE & COMMERCIAL MODULES

# 11. Lead CRM 2.0

## 11.1 Where V1 is today

The Inquiry pipeline exists: stages NEW → RESPONDING → QUOTED → BOOKED / LOST / GHOSTED, with a Kanban board UI and basic CRUD. Guest entity with phone dedup is intact. Assignment is single-user with no rule engine. There is no SLA logic, no response-time tracking, no auto-routing, no lead-score field, no automation builder.

## 11.2 Operator pain points

- *"My reps cherry-pick easy leads and high-value ones rot."*
- *"There's no SLA enforcement; missed leads have no consequence."*
- *"I can't tell which lead source has the best conversion, even though I have the data."*
- *"Reassignment when a rep is on leave is manual chaos."*
- *"Lost leads are lost forever — no re-engagement workflow."*

## 11.3 V2 vision

The CRM should *manage operators, not just data*. The pipeline becomes opinionated: SLAs are real, routing is automatic, leaderboards are public, and the AI Concierge fills the gaps overnight and weekends.

## 11.4 Sub-modules

### 11.4.1 SLA Engine

- Per-tenant SLA definitions: response-time target by stage, by channel, by Property.
- Stopwatch starts at first inbound Touchpoint; pauses on inbound, resumes on outbound.
- Breach states: warning (50% of target), breach (100%), escalation (200%).
- Escalation chain: rep → team lead → property manager → owner. Each level gets a configurable notification template on each tier.
- SLA breach dashboard with weekly digest.

### 11.4.2 Routing Engine

- Visual rule builder: trigger (channel, property, source, time of day, language detected, lead score) → action (assign to user / team, AI Concierge, queue, escalation).
- Round-robin within team.
- Skill-based (language, property expertise, VIP tier).
- Workload-aware (skip if assignee has >N open inquiries).
- Out-of-office aware (calendar integration deferred to V2.1; for V2 we ship explicit user availability toggle).
- Cherry-pick prevention — reps cannot reassign a lead away from themselves; only managers can.

### 11.4.3 Lead Scoring

- Continuous score 0–100 per Inquiry, recomputed on every Touchpoint.
- Features: source channel (CTWA > Inbound call > Webform > OTA), recency of last message, response speed, sentiment, prior bookings, message length, language match, property fit.
- V2 ships a tuned LightGBM model trained on dogfood data; V2.1 moves to a fine-tuned per-tenant model.
- Score surfaces in inbox, on Kanban cards, in routing rules.

### 11.4.4 Workflow / Automation Builder

Visual workflow editor (similar to Flow Studio but for *internal* automation):

- Triggers: stage transition, time-on-stage, SLA event, Touchpoint event, manual.
- Conditions: any Guest/Inquiry/Property field, lead score, time of day.
- Actions: send WA template, schedule call, assign user, advance stage, tag, create task, trigger Flow, hand to AI Agent, send email.
- Pre-built workflows ship for: 24h follow-up, lost-deposit recovery, post-stay review, anniversary upsell, re-engagement after 90 days idle.

### 11.4.5 Task & Activity System

- Tasks linked to Inquiry / Guest / Property / Call.
- Reminders via WA + email + in-app.
- Activity feed (system events + human notes) on every Guest detail page.

### 11.4.6 Inquiry Detail 2.0

A single screen showing for an Inquiry:
- Header: Guest avatar, name, phone (one-tap call/WA), lead score, stage, assigned rep.
- Timeline (Touchpoint stream): chronological WA / IG / call / email / note / system events with channel icons; expanded view on click.
- Past Stays panel: prior bookings, F&B preferences, complaints, total spend, LTV bucket.
- Property panel: assigned Property, alternates, availability, rate card.
- AI Suggestions panel: 3 next-best-actions ("Send Catalog now, mention rooftop", "Offer 4-night discount", "Forward to senior rep — high LTV").
- Notes (internal collab, @mentions).
- Files / attachments.

This screen is the operator's primary workspace.

### 11.4.7 Kanban + Table + Calendar Views

Three views over the same data:
- **Kanban** — stage columns (existing V1).
- **Table** — power-user view: sortable, filterable, bulk actions, saved views.
- **Calendar** — check-in dates for BOOKED stage; sales reps see deals closing this month.

## 11.5 Data model deltas

```python
class SLA:
    id, tenant_id
    channel: Enum
    property_id: UUID | None  # null = all
    target_first_response_seconds: int
    business_hours: JSONB
    escalation_chain: list[UUID]  # user ids

class SLABreach:
    id, sla_id, inquiry_id
    breached_at, breach_minutes
    notified_users: list[UUID]
    resolved_at: datetime | None

class RoutingRule:
    id, tenant_id, priority
    triggers: JSONB   # match conditions
    actions: JSONB
    enabled: bool

class WorkflowRun:
    id, tenant_id, workflow_id
    inquiry_id, guest_id
    state, current_step, started_at, completed_at
    step_history: JSONB

class LeadScore: see §6.3
```

## 11.6 Acceptance criteria

- SLA stopwatch accuracy ±5s.
- Routing rule changes apply within 60s.
- Kanban supports 5K open cards without UI lag.
- Bulk reassign of 200 leads to a new rep completes in <30s.

---

# 12. Booking, Stay & Revenue

## 12.1 Where V1 is today

`Stay` exists with check-in, check-out, room, revenue fields. `RatePlan` exists. Hostaway sync pulls reservations hourly. There is no distinct `Booking` entity, no commission tracking, no payment milestone, no cancellation logic, no booking-engine UI.

## 12.2 V2 vision

Without revenue truth, there is no AI Data Analyst worth running. V2 splits Booking from Stay, tracks commission per channel, and ingests payment state from PMS + WA Pay.

## 12.3 Sub-modules

### 12.3.1 Booking entity

```python
class Booking:
    id, tenant_id, guest_id, inquiry_id, property_id
    source: Enum  # direct | whatsapp | call | webform | booking_com | airbnb | makemytrip | expedia | agoda | …
    ota_reference: str | None
    confirmation_code: str
    status: Enum  # held | confirmed | cancelled | no_show
    gross_inr: Decimal
    ota_commission_inr: Decimal | None
    payment_fee_inr: Decimal | None
    net_inr: Decimal  # computed
    deposit_received_inr: Decimal
    payment_state: Enum  # unpaid | partial | paid | refunded
    created_at, confirmed_at, cancelled_at: datetime
    cancellation_reason: str | None
```

One Booking → 1 or more Stays.

### 12.3.2 PMS sync hooks

Hostaway and Cloudbeds sync writes Booking + Stay (V1 sync writes Stay only). Reconciliation handles updates and cancellations.

### 12.3.3 Channel-specific commission model

Per-tenant configuration of OTA commission %:
- Booking.com 15–18%
- Airbnb 3% (host fee) + 14% (guest fee, optional)
- Expedia 15–30%
- MakeMyTrip ~17%

Net revenue computed automatically. Reports show direct vs OTA net contribution.

### 12.3.4 Cancellation & refund logic

- Cancellation reason captured (Inquiry.lost_reason equivalent for bookings).
- Refund Touchpoint event for analytics.
- Cancellation rate dashboard.

### 12.3.5 Light booking-engine (V2.1)

A widget that a Property's website can embed: shows live availability via PMS adapter, captures the booking, creates Inquiry + Booking, triggers Pre-arrival Flow. Not a full booking-engine replacement; designed to convert *the operator's own website traffic*.

## 12.4 Data model deltas

Already shown above (§12.3.1) plus:
- `BookingPayment` (booking_id, amount, type=deposit|balance|refund, method, occurred_at).

---

# 13. Campaign Attribution & Marketing Intelligence

## 13.1 Where V1 is today

No campaign entity. UTM tracking not implemented. CTWA `ctwa_clid` not stored. Ad spend not ingested. Attribution is impossible.

## 13.2 V2 vision

Marketing has been the single biggest "this product needs an analyst" complaint. V2 fixes the data layer first, then the model, then the report.

## 13.3 Sub-modules

### 13.3.1 Ad source ingestion

- Meta Ads (FB + IG + CTWA) via Marketing API — hourly sync of spend, impressions, clicks, conversions.
- Google Ads via Google Ads API — same shape.
- Manual offline campaign entry (print, OOH, influencer) — entered by owner with spend + dates + UTM.
- Each ad write creates / updates a Campaign row.

### 13.3.2 UTM + CTWA capture

- Webform widget passes UTM to inbound write.
- CTWA `ctwa_clid` arrives in webhook payload (already structured by Meta).
- IG Ads `ad_id` arrives in DM webhook.
- All written to `Touchpoint.metadata`.

### 13.3.3 Conversions API (CAPI)

Meta CAPI for Business Messaging — every Inquiry receiving a CTWA click writes back `Lead` event (mid-funnel) and `Purchase` (when Booking confirms). Required for CTWA ROAS to function correctly (research finding).

### 13.3.4 Attribution models

Three models exposed in the UI:

- **Last-touch** — simplest; default for SMB.
- **Time-decay** — 7-day half-life; default for owner-level reporting.
- **MMM (Marketing Mix Modeling)** — V2.1 ships using Google Meridian (open-source). Quarterly retrain; tenant-level model.

The AI Data Analyst can compute attribution under any of the three on demand.

### 13.3.5 Marketing Dashboard

- Spend, impressions, clicks, conversations started, leads, bookings, revenue, ROAS — per campaign / per platform / per Property.
- Time-decay-weighted ROAS as the default chart.
- Campaign launch checklist (KPI targets, audience, creative).

---

# PART V — THE AI INTELLIGENCE LAYER

# 14. The Agent Operating System

## 14.1 Why a single Agent OS

V1 has Celery tasks (`classify`, `judge`, `wrap_up`, `concierge_draft`) that each call an LLM directly. This is a "scripts that happen to use AI" architecture. It works for V1 but breaks for V2 because:

- Different agents need shared memory of the same Guest.
- Tools (PMS lookup, send message, hold a room) must be reusable across agents.
- Every agent action must be auditable for DPDP + customer trust.
- We need to evaluate and version agents, not one-off prompts.
- The product story is "you get AI Concierge + AI Booking + AI Re-engagement + AI Data Analyst" — these must feel like one system to the buyer.

The Agent OS is the runtime that turns multiple specialist agents into a coherent product.

## 14.2 Architecture

```
                       ┌──────────────────────────┐
                       │ Agent OS — orchestrator  │
                       │ (LangGraph, FastAPI svc) │
                       └────────────┬─────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
        Memory layer          Tool registry         Eval & Audit
        (pgvector + Postgres) (typed JSON schemas)  (Braintrust + AuditEvent)
              │                     │                     │
              └─────────────────────┼─────────────────────┘
                                    │
       ┌──────────┬──────────┬──────┴──────┬──────────┬──────────┐
   Concierge   Booking  Pre-Arrival   Support    Re-engage    QA-Judge
       │           │          │           │           │           │
    (WA, IG, IVR slots — all use same registry)
                                    │
                                    ▼
                          ┌──────────────────┐
                          │   Athena (AI     │
                          │   Data Analyst)  │
                          └──────────────────┘
```

**Orchestrator** — LangGraph (state machine; production-tested in 2026 benchmarks). Each agent is a graph with nodes for retrieval, tool-call, generate, evaluate, output.

**Memory** — three tiers:
- *Short-term* — within an agent run (conversation context).
- *Episodic* — per Guest (last 90 days of Touchpoints + summary).
- *Semantic* — pgvector embeddings over Property KB, FAQ, transcripts (for RAG).

**Tools** — typed JSON-schema tools, e.g.:
- `lookup_guest(phone) → Guest`
- `lookup_property_availability(property_id, dates) → Availability`
- `send_whatsapp(guest_id, template_id, params) → MessageRef`
- `hold_room(property_id, dates, hours) → Hold`
- `quote_rate(property_id, dates, rate_plan) → Quote`
- `escalate(reason) → None`
- `run_metrics_query(metric, dims, filters) → Grid` (used by Athena)

Each tool call is logged to `AgentToolCall`.

**Evals & Audit** — Braintrust as the eval platform. Every agent has a frozen test set; CI gates regression. Audit log shows model used, tokens, cost, latency, tools called, result.

## 14.3 Agent catalog (V2 launch)

| Agent | Trigger | Default mode | Owns |
|---|---|---|---|
| Concierge | Any inbound on WA/IG/voicebot, no other agent claimed | Draft or Autonomy per tenant config | First-response, generic Q&A |
| Booking | Concierge classifies intent=book | Autonomy with hold-approval | Rate quotes, Catalog, Cart, payment, hold |
| Pre-Arrival | 48h before check-in | Autonomy | Pre-arrival Flow + ops checklist |
| Support | During Stay, or post-Stay complaint | Draft | Service issues, escalations |
| Re-engagement | Cohort cron (inactive 90d, anniversary, etc.) | Draft | Win-back broadcasts |
| QA-Reviewer | After every call / chat thread closure | Autonomy | LLM-as-judge, coaching tasks |
| Receptionist (voicebot) | First-ring after-hours | Autonomy | Triage + callback scheduling |
| Compliance-Auditor | Nightly | Autonomy | DPDP readiness checks |
| Ad-Optimiser | Daily | Draft | CTWA / IG Ads spend recommendations |
| Athena (Data Analyst) | Owner asks | Autonomy | NL → metric query + narrative |

## 14.4 Versioning, evals, rollout

- Every agent has a `prompt_version` string. AgentRun captures it.
- Braintrust eval set per agent — minimum 50 ground-truth examples (V2 ships 100+ per agent).
- Eval gates in CI — new prompt PR must pass on regression set + uplift on improvement set.
- Phased rollout — new prompt version goes to 5% → 25% → 100% over 7 days; auto-rollback on metric drop.

## 14.5 Cost & latency

- Default routing: Haiku 4.5 for classify/extract; Sonnet 4.6 for generate/reason; Opus 4.6 only for QA-Judge on disputed calls.
- Prompt caching enabled for all agents (>1K-token system prompts qualify).
- Streaming for guest-facing replies (first token <800ms).
- Cost target: < ₹3 per agent invocation on average; < ₹1.5 with caching after 14 days of warm tenant.

---

# 15. AI Data Analyst ("Athena")

## 15.1 The problem Athena solves

This is the single most-requested capability from V1 customers. Quote: *"My analyst takes 3 days a month to build the deck. He resigns every 18 months. I want HAIP to be him."*

Operators want:
- "What's my CTWA ROAS this quarter, by Property?"
- "Why are we losing Goa leads in May?"
- "Which rep is best at converting repeat guests?"
- "Should I increase ad spend on Booking.com or stop using them entirely?"
- "Compare June vs same week last year, and flag anomalies."

Existing AI tools generate generic dashboards. Athena differs because it sits on HAIP's semantic layer and Touchpoint stream — it has *truth*, not generic metrics.

## 15.2 Architecture

```
Owner question (NL) → Intent classifier → Plan agent
                                            │
                          ┌─────────────────┼─────────────────┐
                          │                 │                 │
                     Metric query     Anomaly check       Narrative gen
                     (MetricFlow)     (Stat models)       (Claude Sonnet)
                          │                 │                 │
                          └─────────────────┴─────────────────┘
                                            │
                                  Final answer + chart + audit trail
```

The Plan agent decomposes a question into one or more metric queries against the semantic layer (§7), runs them, may call anomaly-detection if asked, and weaves a narrative reply with chart recommendation.

## 15.3 Capabilities

- **Conversational queries** — chat interface anywhere in HAIP. Each answer cites the metric used and the SQL.
- **Dashboards-as-prompts** — owners pin questions; pinned questions become live dashboard widgets that refresh on schedule.
- **Insights feed** — daily/weekly anomalies pushed to WA + email + in-app feed (e.g., "TFR p50 climbed from 4 minutes to 11 minutes last week — investigate weekend coverage").
- **Data cleansing assistant** — when ingesting ad spend CSV from Google Ads or a Boutique PMS export, Athena auto-detects format, suggests mappings, flags duplicates, normalises currency/timezone. (Solves the "garbage data, no time to clean" pain point.)
- **MMM + MTA reconciliation** — owner asks "Did Booking.com bring me more revenue than Direct in Q2?" Athena runs both MTA and MMM, reports the spread, explains differences.
- **What-if simulations** — "If I increase CTWA spend 30%, what's the expected revenue lift?" Linear projection from MMM model.
- **Drill-down auditability** — every chart links to the raw rows used; every claim links to a SQL query.

## 15.4 Anomaly detection

- Per-metric daily/weekly seasonal decomposition (Prophet or StatsForecast).
- Multivariate outlier detection on the Touchpoint stream (Isolation Forest on key feature buckets).
- LLM-narrative generation for each anomaly — Sonnet 4.6 with metric context + raw rows.
- Severity assignment based on metric variance + dollar impact.

## 15.5 Insights feed UX

Card-based in-app feed (think: Linear inbox). Each Insight card has:
- Title ("Goa villa lead conversion fell 22% this week").
- Narrative (3 sentences with the cause).
- Chart.
- Suggested actions ("Pause Reel 3 — high spend, no bookings").
- Buttons: Acknowledge / Investigate / Dismiss / Convert to Task.

Cards also push to WhatsApp/email as a daily digest.

## 15.6 Data cleansing module

When a tenant uploads an unfamiliar CSV (or maps a new ad source):

- Auto-detect format (column types, encoding, separator).
- LLM-assisted column mapping ("This column looks like 'ad_spend' — confirm?").
- Anomaly check (negative spend? duplicated dates? missing currency?).
- Normalise (currency conversion, timezone, ID matching).
- Confirm preview + ingest.

This single feature is the differentiator from "we ship dashboards" — it removes the "I need a data person to clean this" objection.

## 15.7 Acceptance criteria

- 90% of natural-language questions answered correctly on a fixed eval set (50 hospitality questions).
- Insights feed shows non-trivial insights weekly in beta tenants.
- Data cleansing recognises Hostaway, Cloudbeds, Booking.com, Airbnb, Google Ads, Meta Ads, MakeMyTrip export formats out of the box.
- SQL audit trail visible on every answer.

---

# 16. AI Concierge & Guest Agents

## 16.1 Beyond Q&A — agents that progress lifecycle state

Each guest-facing agent has a job-to-be-done, not just a script.

### 16.1.1 AI Concierge (Generalist)

**Job:** Answer anything within 30 seconds, in the guest's language, with property context.

**Tools:** lookup_guest, lookup_property_kb, send_whatsapp, schedule_callback, escalate.

**Hand-off triggers:** Intent shifts to booking → Booking agent. Intent shifts to complaint mid-stay → Support agent. Confusion detected (3 failed turns) → human escalation.

### 16.1.2 AI Booking Agent

**Job:** Close direct bookings.

**Tools:** + check_availability, hold_room, quote_rate, send_catalog, initiate_wa_pay.

**Guardrails:** Can never quote below Property's floor rate (defined per RatePlan). Holds require human confirmation if Booking value > ₹50,000. Cannot send a final confirmation; that step is operator-approved unless tenant opts into full-autonomy mode.

### 16.1.3 AI Pre-Arrival Agent

**Job:** Collect arrival info + delight pre-stay.

**Tools:** trigger_flow (PreArrival template), write_stay_fields, notify_ops.

**Guardrails:** Runs only inside 48h-before-checkin window. Cannot suggest changes to Booking without ops approval.

### 16.1.4 AI Support Agent (in-stay)

**Job:** Handle routine service requests; escalate quickly.

**Tools:** lookup_stay, create_ops_task, notify_property_manager, escalate.

**Guardrails:** Cannot promise refunds or rate adjustments. All financial impact decisions escalate.

### 16.1.5 AI Re-engagement Agent

**Job:** Bring back inactive guests.

**Tools:** cohort_select, draft_offer, schedule_broadcast.

**Guardrails:** Must check Consent.marketing = true before send. Frequency cap per Guest.

### 16.1.6 AI Receptionist (voicebot)

Already described in §10.4.2.

## 16.2 Persona & brand voice

Each tenant configures a brand voice (formal / warm / playful), preferred phrases, banned phrases. Stored as `BrandVoiceProfile` and injected into every agent system prompt.

## 16.3 Multilingual

V2 ships English, Hindi, Marathi, Gujarati, Tamil, Bengali, Kannada, Telugu, Malayalam, Punjabi, Arabic. Detection on first guest turn; lock language for the conversation. Brand voice profile is per-language (operators can over-ride translations).

## 16.4 Hand-off & seamless transitions

When an agent escalates, the conversation summary, key facts, and recommended next action are visible to the human in 2 seconds. The human can reply directly; the agent steps back gracefully. The Touchpoint stream records actor_type transitions for analytics.

---

# PART VI — CROSS-CUTTING CONCERNS

# 17. UX / UI Vision & Design System

## 17.1 Principles

1. **One screen, one job.** Operators spend their day on the inbox or the Inquiry detail. These two screens get the love.
2. **AI is a side rail, never the main column.** AI suggestions live in a right rail; the operator's primary action area is untouched. Reduces fear; builds trust.
3. **Density without noise.** Hospitality operators run multi-property — they need 50 leads in view, but with visual hierarchy that surfaces the urgent.
4. **Time-to-context under 5 seconds.** Any screen, any role, the user should know what's going on within 5 seconds of landing.
5. **No empty states without action.** Every empty state explains and offers a one-click next step.

## 17.2 Design system

V1 ships shadcn/ui + Tailwind 4. V2 extends with:

- **HAIP component library** — branded variants of shadcn (cards, tables, kanban, timeline, conversation thread, score ring, sentiment trajectory, metric tile).
- **Tokens** — `--haip-primary`, `--haip-success`, `--haip-warning`, `--haip-danger`, sentiment-color tokens (positive=green, neutral=slate, negative=amber).
- **Dark mode** — first-class. Operators use this late at night.
- **Density modes** — comfortable / compact / dense — set per user.
- **Accessibility** — WCAG 2.2 AA. Keyboard nav across all major workflows.

## 17.3 Key screens — V2 priorities

| Screen | V1 state | V2 changes |
|---|---|---|
| Dashboard | Widgets | Becomes North-Star Dashboard: TFR p50 hero, today's leads, anomalies, top insights |
| Inbox | Conversation list + thread | Multi-WABA, unified guest, AI rail, inline rate quoting |
| Inquiry Kanban | Drag-drop columns | Add lead-score chip, SLA stopwatch, AI next-action |
| Inquiry Detail (NEW) | — | Single power workspace described in §11.4.6 |
| Calls list | Filter + table | Add LLM-judge score, sentiment trajectory thumbnail |
| Call detail | Player + transcript | Add real-time whisper history, coaching task creator |
| Properties | CRUD | Add KB editor, voicebot config, OTA commission |
| Analytics | Static charts | Replace with Athena chat + Insights feed |
| Reports | Stub | Replace with semantic-layer report builder |
| Messaging | Template/Campaign stubs | Replace with WhatsApp Intelligence Hub (§8) |
| Settings → AI Agents (NEW) | — | Agent toggles, mode per agent, prompt version pin |
| Settings → SLAs (NEW) | — | SLA definition, escalation chain |
| Settings → Branding | Stub | White-label asset upload, theme preview |
| Onboarding | Multi-step | Add CTWA setup wizard, Meta WABA connect, Vapi number link |

## 17.4 Inbox redesign — the daily workspace

Three columns:
- **Left (220px)** — channel filters, inbox folders (Unassigned / Mine / Team / Snoozed / Done), saved filters.
- **Center (flex)** — conversation list with Guest avatar, channel icon, last message preview, time, badges (SLA, lead score, language).
- **Right (380px)** — selected conversation thread with timeline merge across channels.
- **AI rail (slides out, 320px)** — Suggested replies, Guest summary, Property suggestions, Next-best-actions, internal notes.

Composer supports text, image, voice note, Catalog message, Flow attachment, rate-quote drag-in, AI-draft button.

## 17.5 Mobile

V2 ships a responsive PWA covering Inbox, Inquiry detail, Call player, Athena chat. A native React Native app is V3 scope.

---

# 18. Multi-Tenancy, Branding & White-Labeling

## 18.1 V1 baseline

RLS-enforced multi-tenancy works. Each Tenant has users, settings, integrations. Branding UI exists but is CSS-only.

## 18.2 V2 additions

- **BrandTheme** entity (§6.3) per tenant.
- **Custom domain** — `app.thevilla.com` instead of `app.haip.io`. Wildcard SSL via Caddy or Cloudflare for SaaS.
- **Per-tenant assets** — logo, favicon, OG image, email signature, WA display name.
- **Per-tenant marketing site** — V2.1 ships a generated marketing landing per Property (`villasaffron.haip.app`) optimised for direct booking.
- **Reseller mode** — agencies running multi-tenant on behalf of clients can switch tenants from a single login.

## 18.3 Tier-based feature gating

Feature flags scoped to plan (Spark / Pro / Scale / Enterprise) — gated at backend, hidden in UI, with an upgrade CTA when a free-tier user clicks a gated feature.

---

# 19. Compliance: DPDP, GDPR, TRAI, Meta policy

## 19.1 Why this section is more than a checklist

The DPDP Act (2023) + Rules (2025) phase in through 2026–2027 with penalties up to ₹250 crore. Hospitality data — guest IDs, payment, room preferences, transcripts — is high-sensitivity. HAIP must ship operator-grade compliance tooling out of the box, because most hospitality SMBs do not have a privacy officer.

## 19.2 Capabilities

- **Consent ledger** — `Consent` entity already exists; V2 adds per-purpose granularity (§6.3) and proof-of-consent storage (screenshot URL of the opt-in surface).
- **Itemised notice generator** — generates DPDP-compliant notice from tenant config, displays at opt-in.
- **Withdrawal mechanism** — one-tap from any HAIP-sent message; propagates within 30s.
- **Retention policies** — per-purpose retention windows; auto-purge job; soft-delete then hard-delete on schedule.
- **Breach notification toolkit** — 72-hour DPDP requirement; in-app incident form pre-fills the regulator template.
- **Recording disclosure** — voicebot + IVR plays compliance prompt automatically.
- **PII redaction** — transcripts + messages run through Presidio (with India-tuned models for names, Aadhaar, PAN, GST) before LLM evaluation.
- **Audit log** — every access to Guest data logged (V1 has this; extend for cross-tenant search attempts, exports).
- **Data export & delete** — Guest can request export (machine-readable) and erasure. Both surface as operator tasks.
- **Meta policy guardrails** — template lint, hour-cap enforcement, opt-out keyword normalisation, IG rate-limit-aware throttling.

## 19.3 Roadmap to SOC 2 / ISO 27001 (V3, but start now)

- V2 ships with: encrypted-at-rest (Postgres TDE / RDS KMS), encrypted-in-transit (TLS 1.3 everywhere), MFA for all users (V1 has it), audit log, RBAC, vulnerability scanning, dependency scanning, secret management (Doppler/AWS Secrets Manager).
- V2 deliverable: a Trust Center page (`/trust`) with control inventory, sub-processors list, breach history (empty hopefully), audit reports as we earn them.

---

# 20. Evals, Guardrails & Production AI hygiene

## 20.1 Why this is a P0 module

Generic AI tools earned the "unreliable" reputation by shipping unmeasured prompts. HAIP cannot win the "most trustworthy" positioning (§3) without a closed eval loop.

## 20.2 Stack

- **Braintrust** — production traces + CI eval gates. Industry-leading in 2026.
- **LangSmith** — kept for LangGraph state debugging.
- **Patronus Lynx** — hallucination detection (open-source 70B), runs as sidecar on every Sonnet output where a factual claim is made.
- **Custom evals** — per-agent ground-truth sets (50–200 cases each), checked into the repo.

## 20.3 Eval gates

- PR opening with prompt or model change must run eval suite.
- Regression set must not degrade > 2% on any metric.
- Improvement set must show > 5% lift on the targeted dimension.
- Cost regression > 30% requires explicit approval.

## 20.4 Production guardrails

- **Output schema validation** — Pydantic models for every structured-output agent call; retry on parse failure with a constrained reprompt.
- **Tool-call argument validation** — typed JSON schemas; reject on validation failure.
- **Brand-voice / policy filter** — second-pass LLM eval against banned phrases, prohibited content categories.
- **Halt-on-hallucination** — Lynx flags + human-escalation if confidence < threshold on a guest-facing reply with factual claims.
- **Rate caps per Guest** — agents cannot send > N messages / hour to one Guest, even autonomously.

## 20.5 Observability

- Every AgentRun written to Postgres + streamed to Braintrust.
- Per-tenant agent dashboards: success rate, avg latency, avg cost, escalation rate, satisfaction (when measurable).
- Cost guardrails — per-tenant monthly AI budget with alert at 70%, hard cap at 100% (configurable).

---

# 21. Cost Model & Pricing Strategy

## 21.1 Unit economics in 2026

| Surface | Variable cost | Notes |
|---|---|---|
| Inbound WA reply (Concierge, Haiku cached) | ~₹0.4 | + Meta service-window fee (free 24h) |
| AI Booking agent turn (Sonnet, RAG) | ~₹2.5 | RAG hits Property KB |
| Voicebot minute (Vapi) | ~₹6 | Includes STT + TTS + LLM |
| Real-time agent assist (Haiku, per call min) | ~₹0.3 | 6 evals/min |
| Call QA judge (Sonnet, 8 min call) | ~₹4 | One-shot eval |
| Athena query (Sonnet + metric query) | ~₹2.0 | Plan + answer |
| WA broadcast send | Meta rate | Marketing template per delivery |
| Storage (call recording, 8 min) | ~₹0.05 | S3/R2 |
| Database / infra per tenant | ~₹600/mo at small | At Pro tier (5 properties, ~5K msgs/mo) |

Aggregate variable cost per active small tenant: **~₹1,800/mo at Spark, ~₹4,500/mo at Pro**. Headline price ₹4,999 / ₹14,999 gives healthy gross margins.

## 21.2 Plans (recap, full detail)

**Spark — ₹4,999/mo**
3 users, 1 Property, 5K inbound messages, 200 call minutes transcribed/scored, 10K marketing template sends, WA + IG channels, Inbox + Kanban + basic Analytics, AI Concierge (draft mode only), Athena (5 queries/day).

**Pro — ₹14,999/mo**
10 users, 5 Properties, 50K messages, 3K call minutes, 100K template sends, all channels, all V2 modules, all AI agents (autonomy mode), Athena (unlimited), CTWA Ads Manager, Voicebot (1 number, 1K min/mo), insights feed.

**Scale — ₹39,999/mo**
Unlimited users, 25 Properties, 200K messages, 15K call minutes, unlimited template sends, white-label, Agent OS prompt-pinning, advanced eval dashboard, dedicated CSM, custom voicebot voice.

**Enterprise — custom**
50+ Properties, SOC 2 (when earned), SLA, dedicated VPC option, dedicated success engineer.

## 21.3 Pass-throughs

Meta WA fees, IVR provider minutes, Deepgram minutes — pass-through at cost + 10% (no hidden Wati-style markups). Transparent monthly invoice.

## 21.4 AI cost guardrails

Per-tenant monthly AI budget bar. 70% alert. 100% cap (configurable; default soft-throttle for Concierge non-critical paths).

---

# PART VII — EXECUTION

# 22. Phased Roadmap (Q3 2026 → Q2 2027)

Four quarters; each delivers a shippable surface area. Within each quarter, weeks are reserved for stabilisation + tech-debt before the next push.

## 22.1 Q3 2026 — Foundation & finish lines

Deliverables:

- **Identity & data layer** (§6) — Touchpoint table, GuestAlias, Campaign, Booking distinct from Stay, schema migrations, backfill.
- **Semantic layer** (§7) — dbt + MetricFlow sidecar, 25 metrics defined, `/v2/metrics` API.
- **Finish V1 half-built modules** — WhatsApp broadcast engine, Instagram inbox UI, concierge approval workflow, PMS → Booking sync.
- **Athena MVP** (§15) — NL → metric query, basic insights feed (5 anomaly detectors), data cleansing assistant for top 3 CSV formats.
- **SLA Engine + Routing Engine** (§11.4.1–2).
- **Tech debt** — webhook signature enforcement, stage transition validation, rate limiting on API, Meta API retry strategy.
- **Tests** — mocks for Meta/Deepgram/Claude, integration tests for Celery chains.

Definition of done: Pro-tier customer can connect Meta WABA, Hostaway, define SLAs, run a broadcast, and see "yesterday's TFR" answered by Athena.

## 22.2 Q4 2026 — Conversational depth & call intelligence

Deliverables:

- **WhatsApp Flow Studio** (§8.4.4) — visual designer, 8 pre-built hospitality flows, FlowRun state machine.
- **CTWA Ads Manager** (§8.4.5) — Meta Marketing API integration, CAPI plumbing, CTWA dashboard.
- **Catalog + Cart + WA Pay** (§8.4.6) — Razorpay/PayU adapter, India launch.
- **Instagram Intelligence Hub** (§9) — comment-to-DM engine, story mention handling, IG ads attribution, rate-limit throttling.
- **Call Intelligence 2.0** (§10) — Voicebot integration (Vapi primary), real-time agent assist (whisper), LLM-as-judge QA, paralinguistic sentiment, Hindi/Marathi/Tamil multilingual transcription.
- **Coaching loops** (§10.4.6) — coaching tasks, per-rep digests, leaderboards.
- **Lead Scoring v1** (§11.4.3).

Definition of done: A pilot customer can run a CTWA → WA Flow → Booking → Stay loop end-to-end, while voicebot handles after-hours calls and judges every conversation.

## 22.3 Q1 2027 — Agent OS & advanced analytics

Deliverables:

- **Agent OS** (§14) — LangGraph orchestrator, tool registry, AgentRun + AgentToolCall audit, Braintrust eval gates, phased prompt rollout.
- **All V2 agents** (§14.3) wired through Agent OS, replacing direct LLM calls.
- **Athena v2** — MMM model (Meridian), MTA, what-if simulations, insights feed expanded.
- **Marketing attribution dashboard** (§13.3.5).
- **Pre-built hospitality QA rubrics library** (§10.4.4) — 6 rubrics, editable.
- **Workflow Builder** (§11.4.4) — visual automation editor.

Definition of done: An owner can ask Athena "what should I do next?" and get a ranked list of actions grounded in MMM + MTA + insights feed.

## 22.4 Q2 2027 — Enterprise hardening & white-label

Deliverables:

- **White-label suite** (§18.2) — custom domain, theme, per-property landing pages.
- **Reseller mode** — agency multi-tenant switching.
- **Compliance toolkit** (§19) — itemised notice generator, retention auto-purge, breach incident form.
- **SOC 2 path** — Trust Center page, controls inventory, vendor assessments.
- **Performance hardening** — message partition strategy, analytics query optimisation, multi-region read replicas.
- **Light booking-engine** (§12.3.5) — embeddable widget.
- **Mobile PWA** (§17.5).
- **Agent marketplace v1** — pre-built agent templates published quarterly (anniversary upsell, lost-deposit recovery, etc.).

Definition of done: A scale-tier customer can run HAIP on `app.theirbrand.com`, with retention auto-purging per DPDP rules, and own developer can author new Agent OS agents from a marketplace template.

## 22.5 Sequencing rationale

The order is deliberate:

- **Foundation first (Q3)** because Athena, Agent OS, and attribution all depend on the Touchpoint stream + semantic layer.
- **Conversational depth + call intelligence (Q4)** because these are the most-requested features and the most-revenue-impactful for pilots.
- **Agent OS (Q1)** comes after the agents have been running in production for a quarter — we will know what reuse abstractions are right.
- **Enterprise (Q2)** lands when product-market fit is proven on Pro tier; premature white-label kills early product velocity.

## 22.6 Out of scope for V2 (parked to V3)

- Native iOS/Android apps.
- Booking-engine replacement (channel manager / OTA pushing).
- AI-generated video ad creative.
- Hotel chain / multi-country tenancy at scale (enterprise sales).
- Revenue management (rate recommendation, demand forecasting) — that is Cloudbeds Signals' territory; we integrate, not compete.
- Customer-success-platform features (NPS surveys at scale, advocacy programs).
- Marketplace of 3rd-party agents (only HAIP-authored agents in V2).

---

# 23. Success Metrics & North-Star Dashboard

## 23.1 The internal scorecard

The product team reviews these weekly:

| Metric | Q3 target | Q4 target | Q1 target | Q2 target |
|---|---|---|---|---|
| Median TFR (Pro tenants) | < 12 min | < 7 min | < 5 min | < 4 min |
| % tenants with median TFR < 5min | 10% | 30% | 60% | 75% |
| AI-attributable revenue / Pro tenant / mo | ₹50K | ₹150K | ₹350K | ₹500K |
| Calls auto-scored / Pro tenant / mo | 70% | 95% | 100% | 100% |
| Repeat-guest share lift (90d post-onboard) | n/a | +3pp | +5pp | +8pp |
| CTWA-running tenants ROAS p50 | n/a | 4× | 6× | 7× |
| Athena daily active owners | n/a | 30% | 60% | 75% |
| Insights feed → action conversion | n/a | 20% | 35% | 50% |
| Gross margin per AI minute | 60% | 65% | 70% | 72% |
| Tenant NPS | n/a | 30 | 50 | 60 |
| Logo retention 90d | 80% | 88% | 92% | 95% |

## 23.2 The customer-facing scorecard

Each tenant has a Health Dashboard with:
- TFR p50 + trend
- AI agent utilisation
- Conversion rate
- Booking value attributed to HAIP-touched flows
- Active Insights to act on

This is the screen the owner sees on Monday morning.

## 23.3 What we will not measure

- Vanity message volume.
- "AI accuracy" without a defined task.
- Generic CSAT without sample-size discipline.

---

# 24. Risks & Mitigations

## 24.1 Product risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Meta WA policy shift bans vertical agents | Low | Critical | Lobby BSP relationships; design abstraction so we can swap WA for SMS+web chat in 4 weeks |
| Gupshup / Twilio ships hospitality vertical | Medium | High | Speed of vertical depth; lock in PMS integrations; community of hospitality customers |
| Operators reject autonomy mode | Medium | Medium | Draft mode default; gradual autonomy by section; clear handoff UI |
| AI hallucinations on rate quotes | Medium | High | Hard guardrail: cannot quote below floor; require human approval for high-value holds |
| Voicebot brand-damage incidents | Medium | High | Conservative defaults; opt-in autonomy per Property; coaching loop on transcript review |
| Multilingual quality below acceptable threshold | Medium | Medium | Continuous eval per language; tenant override to disable per language |

## 24.2 Technical risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Touchpoint table grows unbounded | High | Medium | Partition strategy by tenant_id + month from day 1 |
| Celery backlog under burst load | Medium | High | Auto-scaling workers; priority queues for guest-facing tasks |
| pgvector limits at >5M vectors | Low (in V2) | Medium | Migration path to Qdrant pre-planned |
| LLM provider outage cascades to inbox lag | Medium | High | Multi-provider fallback (Claude → Gemini → local) on critical paths |
| Per-tenant cost explosion | Medium | Medium | Per-tenant budget caps; cost alerting; model routing audit |

## 24.3 Market risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Hospitality recession (lower CAC budgets) | Medium | High | Spark tier priced for SMB; ROI proof central to sales |
| OTAs lock down API access | Low | Medium | Direct booking is the long arc; OTA ingest is convenience |
| DPDP regulator interpretation tightens | Medium | High | Conservative defaults; legal review quarterly |
| India tariff/rupee shock | Medium | Medium | USD invoicing for GCC + SEA tenants |

---

# Appendix

## A. Data model deltas (full)

```sql
-- New entities

CREATE TABLE touchpoint (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id),
    guest_id UUID REFERENCES guest(id),
    inquiry_id UUID REFERENCES inquiry(id),
    property_id UUID REFERENCES property(id),
    occurred_at TIMESTAMPTZ NOT NULL,
    channel TEXT NOT NULL,
    event_type TEXT NOT NULL,
    direction TEXT,
    actor_type TEXT NOT NULL,
    actor_id UUID,
    payload JSONB DEFAULT '{}',
    parent_id UUID REFERENCES touchpoint(id),
    metadata JSONB DEFAULT '{}',
    cost_inr NUMERIC(12, 4),
    revenue_inr NUMERIC(12, 4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (occurred_at);

CREATE INDEX idx_touchpoint_tenant_guest ON touchpoint (tenant_id, guest_id, occurred_at DESC);
CREATE INDEX idx_touchpoint_inquiry ON touchpoint (inquiry_id, occurred_at DESC);
CREATE INDEX idx_touchpoint_event_type ON touchpoint (tenant_id, event_type, occurred_at DESC);

CREATE TABLE guest_alias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id),
    guest_id UUID NOT NULL REFERENCES guest(id),
    channel TEXT NOT NULL,
    channel_identifier TEXT NOT NULL,
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, channel, channel_identifier)
);

CREATE TABLE campaign (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id),
    platform TEXT NOT NULL,            -- meta, google, offline
    external_id TEXT,                  -- meta campaign id
    name TEXT NOT NULL,
    ad_set_id TEXT,
    ad_id TEXT,
    spend_inr NUMERIC(12, 2) DEFAULT 0,
    impressions BIGINT DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    conversations_started INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    utm_source TEXT,
    utm_medium TEXT,
    utm_campaign TEXT,
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE booking (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id),
    guest_id UUID NOT NULL REFERENCES guest(id),
    inquiry_id UUID REFERENCES inquiry(id),
    property_id UUID NOT NULL REFERENCES property(id),
    campaign_id UUID REFERENCES campaign(id),
    source TEXT NOT NULL,              -- direct | whatsapp | call | webform | booking_com | airbnb | ...
    ota_reference TEXT,
    confirmation_code TEXT NOT NULL,
    status TEXT NOT NULL,              -- held | confirmed | cancelled | no_show
    gross_inr NUMERIC(12, 2) NOT NULL,
    ota_commission_inr NUMERIC(12, 2) DEFAULT 0,
    payment_fee_inr NUMERIC(12, 2) DEFAULT 0,
    net_inr NUMERIC(12, 2) GENERATED ALWAYS AS
        (gross_inr - ota_commission_inr - payment_fee_inr) STORED,
    deposit_received_inr NUMERIC(12, 2) DEFAULT 0,
    payment_state TEXT NOT NULL DEFAULT 'unpaid',
    cancellation_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ
);

CREATE TABLE lead_score (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id),
    guest_id UUID NOT NULL REFERENCES guest(id),
    inquiry_id UUID REFERENCES inquiry(id),
    score INTEGER NOT NULL,            -- 0-100
    model_version TEXT NOT NULL,
    features JSONB DEFAULT '{}',
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ltv_forecast (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id),
    guest_id UUID NOT NULL REFERENCES guest(id),
    forecast_12m_inr NUMERIC(12, 2),
    forecast_60m_inr NUMERIC(12, 2),
    confidence_band NUMERIC(5, 4),
    model_version TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE flow (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id),
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    definition JSONB NOT NULL,         -- nodes + edges
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE flow_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id),
    flow_id UUID NOT NULL REFERENCES flow(id),
    guest_id UUID NOT NULL REFERENCES guest(id),
    inquiry_id UUID REFERENCES inquiry(id),
    state TEXT NOT NULL,
    node_history JSONB DEFAULT '[]',
    collected JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    abandoned_at TIMESTAMPTZ
);

CREATE TABLE agent_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id),
    agent_type TEXT NOT NULL,
    agent_version TEXT NOT NULL,
    guest_id UUID REFERENCES guest(id),
    inquiry_id UUID REFERENCES inquiry(id),
    parent_run_id UUID REFERENCES agent_run(id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    model TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_inr NUMERIC(10, 4),
    status TEXT,
    error TEXT,
    eval_score NUMERIC(5, 2)
);

CREATE TABLE agent_tool_call (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_run_id UUID NOT NULL REFERENCES agent_run(id),
    tool_name TEXT NOT NULL,
    args JSONB,
    result JSONB,
    latency_ms INTEGER,
    error TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE insight (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id),
    type TEXT NOT NULL,                -- anomaly | trend | opportunity | warning
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    narrative TEXT NOT NULL,
    evidence_query JSONB,
    suggested_actions JSONB DEFAULT '[]',
    status TEXT DEFAULT 'open',        -- open | acknowledged | resolved | dismissed
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE sla (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id),
    channel TEXT NOT NULL,
    property_id UUID REFERENCES property(id),
    target_first_response_seconds INTEGER NOT NULL,
    business_hours JSONB NOT NULL,
    escalation_chain JSONB DEFAULT '[]',
    enabled BOOLEAN DEFAULT TRUE
);

CREATE TABLE sla_breach (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sla_id UUID NOT NULL REFERENCES sla(id),
    inquiry_id UUID NOT NULL REFERENCES inquiry(id),
    breached_at TIMESTAMPTZ NOT NULL,
    breach_minutes INTEGER NOT NULL,
    notified_users JSONB DEFAULT '[]',
    resolved_at TIMESTAMPTZ
);

CREATE TABLE brand_theme (
    tenant_id UUID PRIMARY KEY REFERENCES tenant(id),
    logo_url TEXT,
    favicon_url TEXT,
    primary_color TEXT,
    secondary_color TEXT,
    font_family TEXT,
    email_signature TEXT,
    whatsapp_display_name TEXT,
    white_label_domain TEXT UNIQUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## B. API surface additions (selected)

```
POST   /v2/touchpoints                         # write event (system)
GET    /v2/guests/:id/timeline                 # unified channel timeline
POST   /v2/guests/merge                        # merge two guests
POST   /v2/metrics/query                       # semantic layer query (Athena)
GET    /v2/insights                            # feed
PATCH  /v2/insights/:id                        # ack / resolve / dismiss
GET    /v2/sla                                 # CRUD
POST   /v2/sla
GET    /v2/routing-rules                       # CRUD
POST   /v2/agents/:agent_type/run              # trigger an agent run
GET    /v2/agents/runs/:id                     # audit
POST   /v2/flows                               # flow CRUD
POST   /v2/flows/:id/runs                      # start a run
POST   /v2/campaigns                           # campaign CRUD
POST   /v2/campaigns/:id/sync                  # pull spend from Meta/Google
POST   /v2/bookings                            # create / update / cancel
POST   /v2/integrations/meta-ads/connect       # OAuth handshake
POST   /v2/integrations/google-ads/connect
POST   /v2/voicebot/sessions                   # voicebot lifecycle
POST   /v2/coaching-tasks                      # create
GET    /v2/analytics/athena/conversations      # Athena chat history
POST   /v2/analytics/athena/ask                # NL ask
```

## C. Celery task graph additions

```
touchpoint.create                              # synchronous trigger
metrics.precompute_daily                       # nightly
insights.scan                                  # hourly
ad_sync.meta                                   # hourly
ad_sync.google                                 # hourly
lead_score.recompute                           # on touchpoint, debounced 30s
ltv_forecast.recompute                         # nightly per active guest
flow.advance                                   # on inbound message or timer
agent.run                                      # on demand or scheduled
agent.eval_run                                 # CI / scheduled
qa.judge                                       # on call.complete
qa.coach                                       # on judge.complete with score<60
campaign.send                                  # broadcast throttle
broadcast.opt_out_propagate                    # on opt-out signal
attribution.compute_mta                        # nightly
attribution.compute_mmm                        # weekly
voicebot.session.close                         # on voicebot handover/end
retention.purge_expired                        # nightly (DPDP)
audit.export                                   # on user request
```

## D. Recommended infrastructure stack

| Layer | Tech | Reason |
|---|---|---|
| App server | FastAPI on Uvicorn behind Nginx, auto-scaling group | V1 stack, working |
| DB | PostgreSQL 16 + pgvector + RLS, RDS Multi-AZ | V1 stack |
| Cache / queue | Redis 7, ElastiCache | V1 stack |
| Workers | Celery, multiple priority queues, autoscaling on queue depth | V1 stack |
| Object storage | Cloudflare R2 (cheaper than S3) | V1 stack |
| LLM | Anthropic Claude (Haiku/Sonnet/Opus 4.6), Gemini fallback | V1 stack |
| Voice | Vapi (primary), Retell (fallback) | NEW V2 |
| STT | Deepgram (streaming + batch), Groq Whisper (free tier) | V1 stack |
| Vector | pgvector | V1 stack; migrate to Qdrant past 5M |
| BI / Semantic | dbt + MetricFlow | NEW V2 |
| Evals | Braintrust | NEW V2 |
| Frontend | Next.js 16 on Vercel | V1 stack |
| Auth | NextAuth 5 | V1 stack |
| Observability | Sentry + Logflare/Axiom + Braintrust | V1 partial |
| Secret mgmt | Doppler | NEW V2 |
| CI/CD | GitHub Actions, Vercel + AWS | V1 stack |
| White-label DNS | Cloudflare SaaS / Caddy on-demand | NEW V2 |

## E. Hospitality QA Rubrics (sample — Inbound new inquiry)

```yaml
name: Inbound_New_Inquiry_v1
description: For inbound calls from never-stayed guests inquiring about availability.
weight_total: 100
criteria:
  - id: opening_warmth
    label: Greeted with brand name + warm tone within 5 seconds
    weight: 10
    evidence_prompt: Quote the opening turn.
  - id: need_discovery
    label: Asked at least 3 of (dates, guests, occasion, budget, preferences) before quoting
    weight: 20
  - id: rate_quote_accuracy
    label: Quoted rate matches RatePlan for the property and dates
    weight: 15
  - id: amenity_anchor
    label: Anchored value with at least 2 amenities relevant to the occasion
    weight: 10
  - id: objection_handling
    label: Handled objections with empathy + alternative, did not capitulate immediately
    weight: 15
  - id: next_step
    label: Set a concrete next step (hold, WA followup, callback time)
    weight: 15
  - id: close_warmth
    label: Closed warmly with brand name + named goodbye
    weight: 10
  - id: compliance
    label: Recording disclosure and no prohibited claims
    weight: 5

sentiment:
  - track: guest
    flag_threshold_frustration: 0.7
coaching_action_on_score_below: 60
```

## F. Glossary

- **Touchpoint** — Any event in the Guest's journey across any channel; written to a single event-stream table.
- **TFR** — Time to First Response; HAIP's hero metric.
- **CTWA** — Click-to-WhatsApp Ads (Meta).
- **CAPI** — Meta Conversions API.
- **MMM** — Marketing Mix Modeling; econometric attribution.
- **MTA** — Multi-Touch Attribution; user-level path attribution.
- **OSI** — Open Semantic Interchange; the dbt/Snowflake/Salesforce YAML standard.
- **DPDP** — Digital Personal Data Protection Act (India, 2023 + Rules 2025).
- **WABA** — WhatsApp Business Account.
- **Athena** — HAIP's AI Data Analyst codename.
- **Agent OS** — HAIP's agent orchestration runtime (LangGraph-based).
- **LLM-as-judge** — Pattern where a Large Language Model evaluates another model's output or a recorded interaction against a rubric.
- **Insights feed** — Push-based stream of detected anomalies, opportunities, and warnings, in place of static dashboards.

---

*End of PRD.*







