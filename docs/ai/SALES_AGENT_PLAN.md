# Sales Agent — phased implementation plan and test plan (proposal)

Each increment is one reviewable change set with its own tests, a revert path, and no behaviour change for a tenant that has not opted in. Order matters: later increments depend on earlier ones. Nothing is pushed, deployed or migrated in production without explicit authorisation. Design: `SALES_AGENT_DESIGN.md`; current state: `SALES_AGENT_CURRENT_STATE.md`.

## 1. Increments

| ID | Increment | Depends on | Size | Acceptance criteria |
|---|---|---|---|---|
| **I-0a** | Booking safety fixes: run `find_conflicts` on `POST /bookings` and the won-lead stay path; validate `status` on create; optional `Idempotency-Key` on `POST /bookings` | – | S | double-booking on create returns 409 (`force` as on PATCH); same key returns the same booking; existing tests green; PG test for concurrent create |
| **I-0b** | Consent: narrow the opt-out matcher ("cancel my booking" is not an opt-out); Instagram opt-out; one `can_contact(guest, channel, purpose)` read used by AI auto-send, one-click send and flow message nodes | – | M | opted-out guest receives no AI/one-click/flow send (test per path); ordinary words no longer opt out; audit row on block |
| **I-0c** | Audit + guards: audit rows for AI mode/kill-switch/threshold/keyword/rate-limit changes and for draft approve/reject; reject re-approval of non-pending drafts; role gates on `PATCH /inquiries`, `/calendar/blocked-dates`, `/calculator/*`; endpoint tests for `/tenants/me/ai-*` | – | M | every listed change leaves a chained audit row; second approve → 409; wrong role → 403; cross-tenant → 404 |
| **I-0d** | Plumbing: `scheduled_for` sender (or remove the field); DLQ retry with arguments; `llm_provider_override` actually wired or removed | – | S | scheduled message sends once at its time; DLQ retry re-runs with original kwargs |
| **I-1** | Policy store: table `sales_agent_policies`, Pydantic schema, `effective_capabilities()`, read/write API (owner), audit events, defaults = Copilot/all off | I-0c | M | draft/activate/pause/restore; only one active; invalid config rejected; resolver returns `blocked_reasons` per capability; no runtime behaviour change yet |
| **I-2** | Control centre v1 (read-only effective view + draft editing + history + pause), no automation | I-1 | M | saved vs active distinct; blocked switch cannot be enabled; activation needs confirmation; mobile 375 px usable; pause works in one click |
| **I-3** | Action Gateway + `agent_action_proposals` + `agent_incidents` + AI actor identity; tools `lookup_availability`, `create_task`, `notify_team` only | I-1 | L | every call checked against policy/deps/consent/tier; parameter-hash approval verified; unknown tool → `unauthorized_tool` incident; idempotent replay returns stored result |
| **I-4** | Quote persistence: write `InquiryQuote` (id, params hash, `valid_until`, status) from `build_quote`; expire; link `disclose_quote` guard to the stored quote | I-3 | M | a quote can be proven and expires; disclosure uses stored figures only; stale quote re-quotes |
| **I-5** | Workflow core: `sales_workflows` + events (dedupe, optimistic lock, outbox, reaper), states up to QUOTED/ALTERNATIVES/ABANDONED, **dry-run only** (decisions recorded, nothing sent) | I-3, I-4 | L | duplicate inbound event creates one event; kill mid-step then resume does not duplicate; replay of a stored conversation reproduces the same decisions |
| **I-6** | Shadow evaluation harness + golden conversation set; per-tenant opt-in switch; shadow dashboard (agreement with human action) | I-5 | M | metrics in §3 produced per run; tenant opt-in required |
| **I-7** | Assisted actions: planner proposes, human approves exact proposals (reply, quote, discount within limits); follow-ups with consent/quiet hours | I-5, I-0b | L | approvals are parameter-bound; follow-up cap and quiet hours enforced; opt-out stops the workflow |
| **I-8** | Holds: `BlockedDate(agent_hold, expires_at, workflow_id)` + expiry job + revalidation step | I-7 | M | hold blocks availability and iCal export; expires on time; revalidation refuses on conflict/price change |
| **I-9** | Payment link idempotency + expiry/cancel job + verified-webhook → workflow; reconciliation job | I-8, I-0a | L | one link per (workflow, purpose); paid link advances state only after signature + ledger row; reconciliation raises the three mismatch incidents |
| **I-10** | Booking + confirmation (`create_booking`, `confirm_booking`) and CRM sync; post-booking handoff task | I-9 | M | no confirmation claim before ledger + Stay agree; Stage → Sold audited; interrupted run resumes without second booking/charge |
| **I-11** | Controlled partial automation for opted-in tenants (T1/T2 auto; T3/T4 approval) | I-6 acceptance | M | gates in §4 met for the tenant |
| **I-12** | End-to-end mode (T3/T4 auto within limits) | I-11 + soak | S | gates in §4 met; auto-pause rules active |

Parallelisable: I-0a/b/c/d are independent of each other; I-2 can start once I-1's API exists; I-6 harness can be built alongside I-5.

## 2. Test plan

Principles: every increment adds tests to the layers it touches; money, inventory and consent paths also run on PostgreSQL (real constraints, concurrency, pgvector); LLM is always scripted in unit/integration tests (fixtures), real models only in the evaluation run.

| Area (from the brief) | Tests | Lands in |
|---|---|---|
| Tenant isolation, authorisation | cross-tenant matrix per new endpoint/tool; gateway rejects ids from another tenant/workflow; role/capability 403 per endpoint; AI actor cannot call interactive-only endpoints | each increment |
| Each autonomy mode & capability | parametrised over {copilot, assistant, end_to_end} × capability: expected {blocked, approve, auto}; capability with unmet dependency stays unavailable | I-1, I-3 |
| Pricing & discount policy | handoff vs grounded; exact-figure guard; discount at/over limit; stale quote; price in history ignored | I-4, I-7 |
| Calendar conflicts, inventory change | block/booking/iCal/hold overlap; inventory changes between acceptance and booking → re-quote; vehicle pool shortage | I-8, I-10 |
| Payment-link & booking idempotency | double create returns one; webhook replay; link expiry; paid-after-hold-expired → incident, no auto refund | I-9, I-10 |
| Duplicate incoming events | same WA message id / same payment id twice → one transition | I-5 |
| Interrupted workflows, retries | kill between commit and effect → outbox completes once; reaper reclaims stuck step; provider timeout → bounded retries then incident | I-5, I-9 |
| Human approval, escalation | approval bound to params hash (changed param → invalid); expired approval; wrong approver role; incident created with SLA, task, push, audit | I-3, I-7 |
| Opt-outs, complaints, prompt injection | opted-out guest: zero sends on every path; complaint → hold + escalation; injected instructions ("ignore rules", "set price to 1") produce no tool call and a flagged incident | I-0b, I-7 |
| Provider outage, malformed output | planner timeout → holding reply + human; invalid schema → one retry then degrade; unknown tool name → `unauthorized_tool` | I-3, I-5 |
| Concurrency (PostgreSQL) | two simultaneous holds/bookings for the same dates → exactly one; advisory/row locks on workflow; audit chain stays linear | I-0a, I-8, I-9 |
| Migration safety | each migration idempotent, additive, RLS + tenant policy; downgrade reverses only its own objects | each migration |

## 3. Evaluation (before any live automation)

**Golden set:** ≥ 60 anonymised, scripted hospitality conversations per client vertical (caravan, villa), each with the expected decision per turn: intent, facts to state, action (reply / ask / quote / hold / link / escalate), forbidden claims. Cover: complete and partial enquiries, date change, group too large, dates blocked, price pushback and discount ask over/under limit, "send me the link" before a quote, abandoned lead, payment fails, guest opts out, complaint, refund demand, prompt injection, non-booking topics (jobs, press), Hindi/Hinglish messages. Client data enters the set only with the client's permission and never trains a model.

| Metric | Gate for partial automation | Gate for end-to-end |
|---|---|---|
| Decision agreement with expected action | ≥ 90 % | ≥ 95 % |
| Factual accuracy (price, availability, booking, payment claims vs source) | 100 % — any miss is a blocker | 100 % |
| Forbidden-claim / guard bypass | 0 | 0 |
| Workflow correctness (right state transitions, no duplicates) | 100 % on replay | 100 % |
| Opt-out / consent violations | 0 | 0 |
| p95 latency, reply | ≤ 20 s | ≤ 15 s |
| Cost per conversation | measured, below tenant-agreed cap | same |
| Shadow window: human-vs-agent agreement on real traffic | ≥ 2 weeks, ≥ 200 turns | ≥ 4 weeks in partial mode, 0 unreconciled payments |

Run the set on each candidate provider (NVIDIA route and Gemini once billing is restored) and record accuracy, latency and cost side by side (decision D6).

## 4. Rollout gates

`Off → Shadow (dry-run) → Assisted (human executes) → Partial (T1/T2 auto, T3/T4 approval) → End-to-end`. Moving up needs: tenant opt-in recorded in the audit chain, the metric gates above for the previous stage, a named human owner for incidents, and a working pause. Moving down is immediate and needs no approval.

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Model proposes a wrong or forbidden action | gateway is the only executor; fixed tool list; params re-derived from stored records |
| Double booking / double charge | conflict check on create, idempotency keys, unique indexes, reconciliation job |
| Hold stuck, revenue lost | TTL + expiry job + incident when payment arrives after expiry |
| Opted-out guest messaged | `can_contact` in the gateway for every send (I-0b first) |
| Policy edited by mistake | versioned, diff, typed confirmation, one-click restore, audit chain |
| Provider outage | holding reply, human task, capability auto-paused |
| Complexity creep | increments are independently shippable; each leaves the product working with the agent off |
| SQLite hides real behaviour | money/inventory/consent tests also run on PostgreSQL |
