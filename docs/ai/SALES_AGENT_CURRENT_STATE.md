# Sales Agent — current-state architecture and capability matrix

Status: **audit only, no code changed for the sales agent.** 14 Oct 2026, branch `feat/mai3-reliability`.
Sources: direct code reading plus three read-only audits (bookings/payments, approvals/escalation/workflows, tenant config/permissions/tools/identity). Paths are relative to `backend/app`. "Not found" means a search found nothing, not that it cannot exist.

Rating — **Reuse** (works, build on it) · **Extend** (right place, missing a piece) · **Missing** · **Risk** (exists but unsafe for an autonomous actor as is).

## 1. Capability matrix

| # | Capability | What exists today | What is missing | Rating | Risk if automated | Tests today |
|---|---|---|---|---|---|---|
| 1 | LLM gateway | `adapters/llm/__init__.py::get_llm(task, tenant_id)`, static `_TASK_ROUTES`, `FallbackAdapter` (NVIDIA→Gemini, internal tasks only). Gemini via `gemini.py` (forced function call + JSON fallback). `concierge_draft` temporarily on NVIDIA `gpt-oss-20b` (Gemini billing) | `complete()` is one system+user string, returns only the first tool call's args: no message history, no tool-result round trip. `llm_provider_override` is read but no caller passes `tenant_id` and nothing sets it | Reuse (single-shot structured output) | A multi-turn tool loop would need an adapter change; avoid it (see design) | `test_llm_*`, `adapters/test_gemini_adapter.py` |
| 2 | Conversation orchestration | Inbound WA/IG → identity → conversation → inquiry → debounced `concierge_draft` (guards, modes, rate limits, kill switch). Deterministic grounding, **no model-driven tool loop** | No per-lead workflow state, no multi-step plan, no wait-for-reply | Extend | Reply path is stateless: each message is decided alone | `test_concierge_*` |
| 3 | Tenant configuration | Columns on `Tenant` (ai modes per channel, thresholds, kill switch, escalation keywords, rate limits) + untyped `brand_config` JSON (`price_disclosure`, `brand_voice_guide`) | No typed policy, no versioning, no draft/publish, no rollback. AI-setting changes only reach structlog, not the audit chain. No endpoint tests for the `/tenants/me/ai-*` routes | Extend | A policy that cannot be diffed or rolled back cannot authorise commercial actions | none for the AI-config routes |
| 4 | Permissions | `authz_service` capability matrix per tenant role, `require_capability`, module/flag gating, audited matrix edits | No capability for an **AI actor**. Write endpoints for bookings/payments use `require_roles`, not capabilities (no `bookings.write`/`payments.*`). `Capability.module_code` never enforced. New defaults need hand-written backfill migrations. `ai_concierge` module/flag is not checked in the drafting path | Extend | Today "the AI may do X" cannot be expressed or revoked per tenant | `test_authz_service`, `test_capabilities_endpoints`, `test_mcp_authz` |
| 5 | Identity | `identity_service` facade → `identity_resolution`: normalised exact match, ≥0.85 attach, 0.65–0.85 flag, audited merge/unmerge; `phone_identity`; lead = guest with usable phone | `add_signal` can auto-merge on a conflicting signal: unsafe for AI-originated signals without a gate | Reuse (+ gate) | Silent merge of two real guests from model-extracted text | `test_identity_service`, `test_lead_identity` |
| 6 | Properties, rates, availability | `calculator_service.search/availability_report/build_quote`, `BlockedDate`, vehicle pool, iCal/Google Calendar blocks, cancelled bookings free dates | Quotes are computed on the fly: **no id, no validity window, not stored** (`InquiryQuote` exists, nothing writes it) | Extend | Cannot prove what was quoted, or that a quote is still valid when the guest accepts | `test_calculator_service`, `…operational_data` |
| 7 | Booking creation | `POST /bookings` (OWNER/MANAGER/RESERVATIONS), won-lead path, calendar/PMS sync, `booking_service.find_conflicts` | **No hold/pending state.** `POST /bookings` and the won-lead path do **not** run the conflict check (double-booking possible); no DB exclusion constraint; **no idempotency** on create; `status` unvalidated on create. Only hold is `hold_dates` = `BlockedDate` with no expiry and no link to guest/quote | Risk | Concurrent or retried creates double-book or duplicate | `test_bookings_endpoint`, `test_booking_detail` |
| 8 | Payments | Per-tenant Razorpay keys (encrypted), `create_payment_link` (staff endpoint, default balance due, 1–30 day expiry), signed webhook idempotent on payment id, ledger (`StayPayment`), instalments, deposit | Link creation not idempotent; no expiry/cancel job; a paid link **does not change booking status**; link not tied to a quote/instalment; webhook dates with `date.today()`; **no refund API call**, no cancellation-fee policy | Extend | Duplicate links, paid-but-unconfirmed bookings, unpaid bookings that never release | `test_booking_detail` (links/webhook), `test_booking_extras` |
| 9 | CRM updates | `inquiry_service.update_stage_by_id` (audited, order rules), `lead_assignment_service`, `update_lead_fields` (MCP allow-list), tasks (`task_service`) | The AI has no `User`: stage moves need `actor_user_id/role`. `PATCH /inquiries/{id}` has no capability check and no audit | Extend | Unattributed AI writes | `test_update_stage_by_id` |
| 10 | Messaging | `send_whatsapp*`/`send_instagram_dm` (now never resend a SENT message), templates, 24 h window handling, campaigns (unique recipient, batches) | **`Message.scheduled_for` is accepted but never sent.** No follow-up cadence/sequence engine, no per-lead next-touch, no quiet hours/frequency policy | Missing | Follow-ups would not happen, or would happen without limits | `test_send_whatsapp_failures`, campaigns |
| 11 | Consent / opt-out | `Consent` model, WhatsApp STOP detection (EN/HI/MR) → marketing opt-out, audited | **No do-not-contact check on any AI/one-click/flow send.** No Instagram opt-out. The keyword matcher is broad (a message like "cancel my booking" counts as an opt-out). Opt-out is marketing-scope only | Risk | Messaging an opted-out guest; wrongly muting a real customer | little (incidental) |
| 12 | Approval | AI draft approve/reject (`conversations.send`), `ai_mode_service` (off/shadow/autonomous + threshold + kill switch), rate limits, `ai_draft_outcomes`, one-click action execute (allow-list, audited) | **No approval is bound to the exact action and parameters** (`action_config` is client-supplied at execute time and not recorded). Approve does not check the draft is still pending (re-approval). Draft approve/reject and autonomous sends write no hash-chain audit row | Risk | An approval can be replayed or applied to different parameters | `test_ai_draft_outcomes`, `test_action_execution` |
| 13 | Escalation | `escalation_policy` (keywords, never-autonomous intents), push alerts, human tasks (price handoff, phone decline) | Runs inside the concierge task, not a shared policy layer. Tasks have no type, SLA or chain. No automatic kill-switch trip | Extend | Commercial guards can't be reused by a planner | `test_escalation_policy` |
| 14 | Incidents | `Incident` model exists but is the **DPDP breach register** (declared inside `endpoints/incidents.py`, no tests) | No operational/AI incident entity, severity routing, owner, retry history | Missing | Failures are logs and pushes only | none |
| 15 | Audit | `core/audit.append_audit` hash chain (per-tenant advisory lock), ~70 call sites, MCP calls audited | AI-settings changes, draft approve/reject, rule/flow CRUD unaudited | Extend | Cannot answer "who enabled autonomy, when" | `test_audit`, `test_audit_concurrency_postgres` |
| 16 | Workflow engines | `automation_engine` (single-step rules), `flow_engine` (JSON graph, persisted only at delay nodes), `check_automation_timers` | Node errors swallowed; no reaper for `claimed` rows; no loops/wait-for-event/goal; guest-keyed not lead-keyed; `fire_trigger` has no retry | Missing (for a sales workflow) | Not durable enough for money or inventory | `test_flow_engine*` |
| 17 | Retry / outbox | Celery `acks_late`, ad-hoc `max_retries`, DLQ push, webhook outbox (real), call-recovery sweep | DLQ retry re-queues **without arguments**; no general outbox for sends or agent actions | Extend | Lost or repeated side effects | `integration/test_celery_retries` |
| 18 | MCP tools | 23 tools; writes need `confirm` + `idempotency_key` (24 h Redis), owner/manager tokens, audited, PII-masked | External-client surface: needs a real `User`; no booking/payment tools | Reuse as a pattern, not as the agent's tool layer | – | `test_mcp_*` |
| 19 | Frontend | AI settings (mode radios, thresholds, kill switch with native `confirm()`), permissions matrix with diff-then-save, knowledge page | No impact summary or confirmation when switching to Autonomous, no change history view, no policy UI | Extend | An autonomous switch is one click | – |

## 2. Findings that affect today's product (independent of the sales agent)

These exist now and are small, separate fixes; they are scheduled as increment I-0 in the plan rather than mixed into the reliability branch.

1. `POST /bookings` and the won-lead stay creation skip the double-booking guard.
2. WhatsApp opt-out matches ordinary words ("cancel", "end", "yes") so "cancel my booking" opts the guest out; Instagram has no opt-out handling at all.
3. AI send paths never read consent / opt-out.
4. Approving a draft twice, or approving a rejected draft, is not blocked.
5. AI mode, kill switch, thresholds, escalation keywords and rate limits change without an audit row.
6. `PATCH /inquiries/{id}` has neither a capability check nor an audit row; `POST/DELETE /calendar/blocked-dates` and `/calculator/*` have no role gate.
7. `Message.scheduled_for` never sends; DLQ retry loses arguments.
8. `llm_provider_override` can never take effect (no caller passes `tenant_id`).

## 3. Reuse decisions (what the design must build on, not replace)

| Need | Reuse | Because |
|---|---|---|
| Rates, availability, quote | `calculator_service` | already honours bookings, blocks, vehicle pool, cancelled stays |
| Stored quote | `InquiryQuote` (exists, unwritten) | avoids a second quote table |
| Booking, conflicts | `Stay`, `booking_service.find_conflicts` | one source of truth for inventory |
| Payments | `adapters/payments/razorpay`, `StayPaymentLink`, `StayPayment`, webhook | signature check + idempotency on payment id already exist |
| Identity | `identity_service` | only sanctioned GID path |
| Stage/CRM | `inquiry_service.update_stage_by_id` | audited, order rules |
| Reply generation, guards | `concierge_draft` + `concierge_facts` + `price_policy` | already hardened this branch |
| Human work items | `task_service`, `push_service` | existing inbox/worklist surfaces |
| Audit | `core/audit.append_audit` | hash chain; no new audit table |
| Retries | Celery + the webhook-outbox pattern | proven in this repo |
| Capability checks | `authz_service.require_capability` | extend the catalog; do not invent a second system |
| Model calls | `get_llm` single-shot structured output | no adapter rewrite needed (design §3) |

## 4. Where the pieces are genuinely missing (justified new components)

Four new tables and some added columns are proposed; each is justified in `SALES_AGENT_DESIGN.md`: a versioned policy (nothing versioned exists), action proposals (no parameter-bound approval exists), a workflow plus event log (existing flows are not durable or lead-keyed), agent incidents (the only `Incident` is a DPDP register), and validity columns on the existing `InquiryQuote`.
