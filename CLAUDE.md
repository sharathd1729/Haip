# HAIP — Claude Working Instructions

You are working on a production-grade SaaS platform:

**HAIP (Hospitality AI Intelligence Platform)**

This is NOT a generic CRM.
This is a unified intelligence system for hospitality businesses.

---

## 🧠 PRODUCT CONTEXT

HAIP is designed for:
- Hotels
- Villa operators
- Airbnb businesses

The platform connects:

- CRM (Guest + Inquiry lifecycle)
- Omnichannel communication (WhatsApp, Calls, Email, Chat)
- AI Concierge (automation)
- Call & Chat QA (analysis)
- Campaign attribution (ROAS tracking)
- Booking & Stay lifecycle
- Reporting dashboards

Core principle:
👉 Maintain a continuous data thread:
**Inquiry → Conversation → Booking → Stay → Revenue**

Breaking this relationship is NOT allowed.

(Reference: internal architecture doc)

---

## ⚠️ CURRENT BUILD FOCUS (MVP)

We are NOT building the full system yet.

### Active module:
👉 IVR + Call Intelligence (QA)

### Build ONLY:
- Call ingestion (via IVR providers like Exotel / Twilio)
- Call storage
- Transcription
- QA scoring
- Insights dashboard

### DO NOT build yet:
- Full CRM UI
- WhatsApp automation
- Marketing automation
- Complex booking engine

However:
👉 Architecture must support future expansion

---

## 🧱 SYSTEM ARCHITECTURE

### Backend:
- Node.js (NestJS preferred) OR Python (FastAPI)
- PostgreSQL (single DB)
- pgvector (for AI / embeddings)
- Redis (queues, jobs)

### Services:
- API service
- AI processing service
- Webhook ingestion service
- Background worker (queues)

### Integrations:
- IVR (Exotel / Twilio)
- Transcription (Deepgram / Whisper)
- AI (Claude API)

---

## 🧩 CORE DATA MODEL (DO NOT BREAK)

Entities:

- Guest (phone = primary key)
- Inquiry
- Conversation
- Message
- Call
- Stay
- Villa
- Campaign
- Activity

Relationships:

- Guest → multiple Inquiries
- Inquiry → one Conversation
- Conversation → multiple Messages
- Inquiry → optional Stay
- Call → linked to Inquiry
- Campaign → linked to Inquiry

IMPORTANT:
👉 Phone number is the identity layer across all systems

---

## 📦 MVP FEATURE REQUIREMENTS

### 1. CALL INGESTION

- Receive webhook from IVR provider
- Store:
  - Call ID
  - Recording URL
  - Duration
  - Direction
  - Timestamp

- Link to:
  - Guest (via phone)
  - Inquiry (create if not exists)

---

### 2. TRANSCRIPTION PIPELINE

- Fetch recording
- Send to transcription service
- Store transcript
- Speaker separation (if possible)

---

### 3. QA ANALYSIS

Use AI to generate:

- Sentiment (positive / neutral / negative)
- Lead quality score
- Intent detection
- Objection detection
- Summary
- QA scoring (based on rubric)

Output must be structured JSON

---

### 4. CALL DASHBOARD

- List of calls
- Filters (date, score, status)
- Call detail page:
  - Audio player
  - Transcript
  - Insights panel

---

## 🎨 FRONTEND GUIDELINES

- React + Tailwind
- Minimal UI (Stripe / Linear style)
- Card-based layout
- Dark mode ready

### Pages:
- Dashboard
- Calls list
- Call detail

---

## ⚙️ CODING RULES

1. Always design for scale (multi-tenant SaaS)
2. Do NOT hardcode business logic
3. Use modular architecture
4. Every feature must be API-first
5. Add logging for all integrations
6. Handle webhook retries safely
7. Fail gracefully (no silent failures)

---

## 🔁 FUTURE MODULES (DO NOT BUILD, BUT PLAN FOR)

- WhatsApp Cloud API integration
- AI Concierge agent
- Unified inbox
- CRM (Guest / Inquiry pipeline)
- Booking & Stay management
- Campaign attribution
- Reporting dashboards

Design extensible schemas and APIs.

---

## 🧪 TESTING REQUIREMENTS

- Mock IVR webhook
- Test transcription pipeline
- Validate AI output format
- Ensure call → guest → inquiry linking works

---

## 🚫 AVOID

- Overengineering early
- Building UI before backend structure
- Creating disconnected modules
- Ignoring data relationships

---

## 💡 DEVELOPMENT PRIORITY

1. Data model
2. Call ingestion
3. Transcription
4. AI analysis
5. Dashboard

---

## 🎯 FINAL OBJECTIVE

Build a scalable SaaS foundation where:

Every call → becomes structured intelligence  
Every interaction → feeds into a unified guest profile  
Every insight → improves revenue decisions

---

Claude should:
- Think like a senior backend + product engineer
- Prioritize simplicity + scalability
- Challenge bad architectural decisions
- Keep alignment with long-term platform vision