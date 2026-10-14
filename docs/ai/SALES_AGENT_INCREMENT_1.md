# Sales Agent — first implementation increment (proposal, nothing built)

Written 14 Oct 2026 against the code on `feat/mai3-reliability`. Every claim below was checked in the source; paths are relative to `backend/app`. Every defect below is proven by an executable specification in `backend/tests/test_increment1_defect_specs.py` (strict `xfail`, named by PR; a PostgreSQL run reproduces the double send). It refines `SALES_AGENT_PLAN.md` I-0…I-5 into pull requests that are small enough to review and that each leave the product working with the sales agent off.

## 0. What the code check changed in the plan

| Finding (verified) | Where | Effect |
|---|---|---|
| `reject_ai_draft` has **no capability check** (any signed-in user, even `read_only`) and no state check: it can set `was_approved=False` and clear `delivery_state` on a **sent human message**. | `api/v1/endpoints/conversations.py:1110-1137` | Priority 1 |
| `approve_ai_draft` does not check the message is an AI draft, is outbound, or is still pending: it can **rewrite the body of an already-sent message**, revive a rejected draft, and queue a second send. Two concurrent approvals both pass. `rewrite_draft` edits `Message.body` in place, so what a human saw can differ from what is sent. | `conversations.py:1024-1107`, `workers/tasks/rewrite_draft.py` | Priority 1 |
| `detect_opt_out` treats **"cancel", "end", "remove", "block", "stop" as opt-out anywhere in a message** and **"yes", "start", "begin" as opt-in**. "I want to cancel my booking" opts the guest out of marketing and silences the AI reply; a reply of "yes" to *any* question records a **marketing consent grant**. | `services/opt_out_detector.py`, called from `workers/tasks/whatsapp.py:~433` | Priority 1 (consent integrity) |
| **Verified by test:** two concurrent approvals on PostgreSQL both returned `approved_and_queued` and queued **two** sends. | `test_concurrent_approvals_queue_exactly_one_send` | Priority 1 |
| `POST /conversations/{id}/messages/ai-draft` has no capability check: a read-only user can spend provider credit (the rewrite endpoints were gated for the same reason). | `conversations.py:612` | PR-1 |
| The opt-out / opt-in **confirmation is never sent**: `opt_out_responder` imports `send_template_message` from `send_whatsapp.py`, which does not define it; the `ImportError` is swallowed and logged as a warning. | `services/opt_out_responder.py:128` | PR-2a |
| Outbound messages leave through **14 call sites**; none of the AI, one-click, flow, scheduled, public-API or direct-adapter paths reads consent. Only campaigns filter. | `grep` of `.delay`/`send_text`/`send_template` (§3) | Priority 2 |
| The inbox exposes **"scheduled send"**; `Message.scheduled_for` is stored and **never sent**; no beat task reads it. | `conversations.py:471-505`, `inbox/page.tsx:405,569` | Visible silent failure; and a rollout trap (§8) |
| `POST /actions/execute` takes `action_config` from the client and any signed-in role may call it; the audit row stores `entity_refs` but **not** the config that ran. `send_whatsapp_draft` sends a draft by id with no approval-state check. | `endpoints/automations.py:284-380`, `schemas/action_execution.py` | Priority 3 |
| AI-setting changes (`ai-mode`, kill switch, thresholds, rate limits, escalation keywords) write only a log line; autonomous sends and draft approve/reject write no audit-chain row. | `endpoints/tenants.py:133-300` | Priority 3 |
| `Message.suggested_actions` already carries AI-proposed actions with `action_config` (written by the concierge). | `concierge_draft.py` (`suggested_actions`), `models/conversation.py:145` | Lets approval binding start **without a new table** |
| The Gemini adapter puts system prompt and guest-facing content in **one user turn** and returns only the first function call; the NVIDIA adapter does the same. | `adapters/llm/gemini.py:195-222`, `nvidia_nim.py` | Tool loop needs a new method, not a patch (§9) |

## 1. Recommended order

| PR | Contents | Items | Migration | Size |
|---|---|---|---|---|
| **PR-1** | Atomic, authorised, audited draft approve/reject | 2, part of 6 | none | S |
| **PR-2a** | Consent semantics, no enforcement yet: classifier fix, explicit opt-in only, proof recorded on every consent change, Instagram path, working opt-out confirmation | 4, part of 3 | none (`Consent.scope` is a free `String(50)`, `consent_payload` JSON already exists) | S–M |
| **PR-2b** | `contact_policy.can_contact` at the three send tasks and the direct-adapter paths, **log-only for 48 h, then enforcing** | 3 | none | M |
| **PR-3** | Audit rows for AI mode / kill switch / thresholds / keywords / limits and for autonomous sends; endpoint tests for the `/tenants/me/ai-*` routes | 6 | none | S |
| **PR-4** | Scheduled messages: sender task, UTC normalisation, old-row sweep (or explicit disablement) | 8 | 124 (partial index) | S–M |
| **PR-5** | Parameter-bound execution of AI-proposed actions | 1 | none | M |
| **PR-6** | `agent_incidents` model, service, API, first emitters | 5 | 125 | M |
| **PR-7** | Durable workflow core (dry-run) | 7 | 126 | L |
| **PR-8** | `run_tool_loop` adapter method + read-only backend tools | 9 | none | M |

The eight-PR structure is kept; PR-2 is split in two because classification (pure, easy to review) and enforcement (touches every send path and needs a log-only soak) carry different risks. PR-1, PR-2a and PR-3 are independent; PR-2b needs PR-2a; PR-4 needs PR-2b (the sender must call `can_contact`). PR-1…PR-4 fix live product risks and are the **first increment**. PR-5/6 are its second half (the foundation the agent needs). PR-7/8 follow once the Increment-1 decisions (§10) are made. Each PR: tests first, one concern, no change to any tenant's policy.

## 2. PR-1 — atomic approve/reject (item 2) and the approval half of item 6

**Reuse:** `approve_ai_draft`, `reject_ai_draft`, `ai_draft_outcomes_service.record_outcome`, `append_audit`, `require_capability("conversations.send")`, the MCP wrapper (calls `approve_ai_draft` directly, `mcp/tools.py:373`).

**Change**
- Replace read-modify-write with one guarded `UPDATE messages … WHERE id, tenant_id, conversation_id, direction='outbound', is_ai_generated, was_approved IS NULL` and check `rowcount`. `rowcount == 0` → reload and answer: already approved by this actor with the same body → `200 {status:"already_approved"}` (idempotent double-click); otherwise `409 {code:"draft_not_pending", state}`; missing → 404.
- `approve` accepts `expected_body_sha256` (what the human saw). If present and different from the stored body → `409 draft_changed`. Optional in this PR (UI sends it); making it mandatory is decision D5.
- Dispatch the send **after** the update commits, exactly once (only the request that won the UPDATE enqueues). `send_whatsapp*` already refuses to resend a SENT message.
- `POST …/ai-draft`: add `require_capability("conversations.send")` (same reason as the rewrite endpoints).
- `reject`: add `require_capability("conversations.send")` (decision D4), same guarded UPDATE, store an optional `reason`.
- Both write `append_audit` (`ai_draft.approved` / `.rejected`; payload: message id, conversation id, channel, `body_sha256` actually sent, `edited`, actor). The final body is hashed, not stored again.
- Non-AI messages and inbound messages can never be approved or rejected through these routes.

**Files:** `endpoints/conversations.py`, `schemas/conversation.py` (`ApproveDraftRequest.expected_body_sha256`, `RejectDraftRequest.reason`), frontend inbox (send the hash, treat 409 `draft_not_pending` as "already handled", refresh).
**Schema/migration:** none.
**Tests:** happy path; second approve → idempotent 200; approve after reject → 409; reject after send → 409; approve of a human message / inbound message → 409/404; wrong role on reject → 403; cross-tenant → 404; changed body with stale hash → 409; **PostgreSQL concurrency test** (two simultaneous approvals → one send enqueued); audit row present and chained; MCP `approve_and_send_draft` unchanged behaviour.
**Rollout risk:** UI double-submit now returns 409/200 instead of silently re-queuing; a UI that ignores the response must refresh. Read-only/marketing users lose the ability to reject (intended).
**Acceptance:** exactly one send per draft under concurrency; no message that was already sent or human-written can be modified by approve/reject; every transition has an audit row.

## 3. PR-2a and PR-2b — consent, opt-out semantics and central do-not-contact (items 3, 4)

### 3.1 Opt-out semantics (item 4)

Proposed classification of an inbound message (`services/opt_out_detector.py`, pure function, table-driven tests):

| Message | Class | Effect |
|---|---|---|
| Whole message (ignoring punctuation/emoji/case) is `STOP`, `UNSUBSCRIBE`, `OPT OUT`, `बंद करो`, `रोको`, `नको`, `band karo`… | `stop_marketing` | marketing consent withdrawn (today's behaviour), no AI/automated **follow-ups or campaigns** |
| Explicit phrase in a sentence: "stop messaging me", "don't message me again", "do not contact", "stop sending", "unsubscribe me", "remove my number", Hindi/Hinglish equivalents | `stop_all_automated` | **no AI or automated sends at all** to this guest; humans may still reply to what the guest writes |
| "cancel my booking/reservation/trip", "I want to cancel", "cancel the stay", "refund" | `booking_cancellation` | **not an opt-out.** Handled by the existing `escalation_policy` (category `cancellation`): AI reply held, push "needs a human now" |
| `cancel`, `end`, `remove`, `block`, `yes`, `start`, `begin`, `हाँ` alone or inside a sentence | `none` | ambiguous words no longer match; `yes`/`begin`/`हाँ` removed from opt-in; opt-in only for `START`, `SUBSCRIBE`, `OPT IN`, `RESUBSCRIBE` as the **whole message** |

**Explicit, auditable, purpose-scoped consent.** A grant is recorded only for an explicit opt-in (whole-message `START`/`SUBSCRIBE`/`OPT IN`, a form, or a template button), never inferred from a reply. Every consent change stores proof in the existing `Consent.consent_payload` (inbound message id, SHA-256 of the text, channel, surface, notice version, matched rule) and writes the audit row. Scopes stay free strings: `marketing` keeps today's meaning (all promotional and follow-up messaging); finer scopes (`sales_followup`, `promotional`) are possible without a migration (decision D14). Withdrawal always wins over an older grant.

Instagram DMs get the same classifier (today they get none). Existing consent rows created by the old `yes`/`start` rule are **not changed**; a read-only report query is supplied for the owner to review (decision D6).

### 3.2 `contact_policy.can_contact` (item 3)

`services/contact_policy.py::can_contact(db, tenant_id, guest_id, channel, purpose) -> Decision(allowed, reason, scope)`; purposes: `service_reply` (answering a message the guest just sent, inside the channel window), `transactional` (booking/payment confirmations), `follow_up` (sales follow-up), `marketing`.

| Guest state | service_reply | transactional | follow_up | marketing |
|---|---|---|---|---|
| no opt-out | allow | allow | allow | needs marketing consent |
| `stop_marketing` | allow | allow | **deny** | **deny** |
| `stop_all_automated` | **deny for AI/automation**, human allowed | allow (human-initiated or payment-bound) | **deny** | **deny** |

**How the purpose is known at the send step without a new column:** a WhatsApp template's `category` already exists (`MARKETING` → `marketing`, `UTILITY`/`AUTHENTICATION` → `transactional`); a free-text message from a signed-in human → `service_reply`; an AI or automation message → `service_reply` only when it answers an inbound message from the last 24 h, otherwise `follow_up`; the opt-out confirmation itself is always allowed. If this inference proves too coarse, a nullable `messages.purpose` column is added later (decision D13).

Enforced at the **last common point** of every send, so no caller can forget:
- `workers/tasks/send_whatsapp.py` (text and template) and `send_instagram_dm.py`: before the provider call; a denial sets `delivery_state=FAILED`, `delivery_error="Blocked: guest opted out"`, writes `contact.blocked` to the audit chain, and does not retry.
- Direct adapter paths that bypass those tasks: `endpoints/calculator.py:263` (share quote), `services/ig_quick_reply.py:91`, `workers/tasks/automation_engine.py:257`, `run_campaign.py:172` (keeps its list filter, adds the central check), `services/flow_engine.py:288`, `public_api/routes_messaging.py:200,256,259`.
- `concierge_draft`: an AI auto-send to a guest with `stop_all_automated` is downgraded to a draft for a human.

**Reuse:** `Consent` (scope today: recording/marketing/profiling — confirm it is a free string; if there is a check constraint the migration adds `automated`), `WASubscriber.opted_in`, `opt_out_responder.process_opt_out_event` (audit + confirmation template), `whatsapp.py` opt-out hook.
**Files:** `services/opt_out_detector.py` (rewrite), `services/contact_policy.py` (new), `opt_out_responder.py` (scope handling), `workers/tasks/whatsapp.py`, `process_instagram_dm.py`, the send tasks and call sites listed.
**Migration:** none expected (verify `Consent.scope`).
**Tests:** ≥ 60 phrase cases EN/HI/Hinglish (including "cancel my booking", "weekend", "stop by tomorrow", "yes please", "STOP."); one test **per outbound path** proving an opted-out guest receives nothing; `service_reply` vs `follow_up` distinction; Instagram opt-out; template confirmation of opt-out still sent exactly once; cross-tenant isolation of consent lookups; PostgreSQL run.
**Rollout risk:** over-blocking transactional messages (mitigated by the purpose matrix); changing opt-out matching changes behaviour for real guests — ship with a log-only mode first (`contact_policy` logs `would_block` for 48 h, then enforces) — decision D3.
**Acceptance:** zero provider calls for denied sends on every listed path; "cancel my booking" produces an escalation and no consent change; "yes" creates no consent row.

## 4. PR-3 — auditable settings and autonomous actions (item 6)

Add `append_audit` to: `PATCH /tenants/me/ai-mode` (`ai_mode.changed`, old→new per channel + thresholds), `POST /ai-kill-switch` (`ai_kill_switch.toggled`, reason), `PATCH /ai-rate-limits`, `PUT /ai-escalation-keywords` (counts + hash, not the words), `PATCH /tenants/me` when `brand_config.price_disclosure` changes, workspace flag PUT, and automation-rule/flow CRUD. Autonomous sends write `ai_message.sent_autonomously` (message id, intent, confidence, guards passed) next to the existing `record_outcome`. Add the missing endpoint tests (none exist for these routes today).
**Reuse:** `core/audit.append_audit` (hash chain; caller commits), `capabilities.py:107` as the pattern. **Migration:** none. **Risk:** low; audit failure must not block the setting change (log and continue, as the one-click path does) — decision D7 if you want it to fail closed.
**Acceptance:** each change leaves exactly one chained row with the actor and old/new values; the compliance audit tab shows them.

## 5. PR-4 — scheduled messages (item 8)

Recommendation: **implement, behind a per-tenant flag that starts off**, because the inbox already offers the control. Nothing is bulk-sent.

**Step 0 — audit before anything runs.** `backend/scripts/audit_scheduled_messages.py` (written, tested, read-only, prints counts and ids only) classifies every row that has a `scheduled_for`: `future`, `due_within_grace`, `stale`, `unparseable`, `already_handled`, `internal_note`, `orphan`, plus flags `opted_out`, `duplicate`, `not_outbound`. You run it against production and review the numbers before PR-4 is merged. Stale rows are **never** sent automatically; a separate owner-run script (written in PR-4, dry-run by default) marks them `FAILED: scheduled time passed before the sender existed`.

**The sender (`workers/tasks/scheduled_messages.py::send_due`, beat every minute, exact-name route):**
- *Eligibility* — only rows with `delivery_state IS NULL`, not internal, outbound, parseable time, due **within the grace window (15 min)**, conversation open and in the same tenant, guest present, integration healthy; the AI kill switch applies to AI-authored rows; `can_contact` re-checked at send time; the channel window checked (outside it the row fails visibly with the "send a template" reason rather than sending).
- *Deduplication* — claim by guarded update `delivery_state NULL → QUEUED` (two workers cannot both take a row); dispatch goes through the normal send task, which already refuses to resend a SENT message; a duplicate (same conversation, text and due minute) is skipped and flagged.
- *Rate limits* — at most N rows per tenant per sweep (default 30) and one per conversation per sweep; the rest wait for the next minute; the existing AI rate limiter still applies to AI-authored rows.
- *Cancellation* — `DELETE /conversations/{id}/messages/{mid}/schedule` (capability `conversations.send`) clears `scheduled_for` with a guarded update that only succeeds while `delivery_state IS NULL`; a cancel racing a claim loses cleanly (409).
- *Normalisation* — the API stores UTC `YYYY-MM-DDTHH:MM:SSZ` (naive input is read in the tenant timezone); past times are rejected at write; a limit on how far ahead.
- *Controlled rollout* — flag `scheduled_send_enabled` per tenant, default **off**. Order: (1) deploy with the flag off everywhere; (2) shadow: the sweep only logs `would_send` for 48 h and the audit script is re-run; (3) enable for one tenant you name; (4) widen. Disable = flip the flag; pending rows stay pending.
- Migration 124: partial index `ix_messages_scheduled_due ON messages (scheduled_for) WHERE scheduled_for IS NOT NULL AND delivery_state IS NULL` (additive, `IF NOT EXISTS`), plus the flag row.

**Fallback (if you prefer to defer):** the API returns 422 for `scheduled_for` and the inbox hides the control; the column stays.
**Tests:** legacy rows classified and never "due" (written: `test_scheduled_message_audit.py`); due message sends once; not yet due waits; two concurrent sweeps → one send; opted-out → blocked; closed window → failed with reason; cancel before due; cancel racing the claim; rate cap per tenant; flag off → nothing; timezone and DST; routing test passes.
**Acceptance:** with the flag on, a message scheduled for T is sent once within a minute of T or fails visibly; no row older than the grace window is ever sent; turning the flag off stops all sends.

## 6. PR-5 — exact-parameter approval binding (item 1)

**Reuse:** `Message.suggested_actions`, `ExecuteActionRequest`, `ONE_CLICK_ACTIONS`, `dispatch_action`, the audit row in `automations.py`.
**Change:** when the concierge (or a recommendation service) proposes an action it stores `{proposal_id, action_type, action_config, params_hash, expires_at}` in `suggested_actions`. `POST /automations/actions/execute` gains `proposal_ref {message_id, proposal_id}`; the server loads the stored config, checks tenant, expiry, `executed_at is null` (guarded update, so it cannot run twice) and the hash, **ignores any client `action_config`**, runs it, and records `params_hash` and the config summary in the audit payload. Free-form calls without `proposal_ref` remain for human-initiated buttons but now record the full config in the audit row and require the action's capability (`conversations.send` for sends, `leads.write` for stage/assignment) instead of "any signed-in user".
**Schema:** none for human-click proposals. The standalone `agent_action_proposals` table (design §6.1) is added in PR-7 for agent-originated proposals that are not tied to a message.
**Tests:** tampered config ignored; second execute → 409; expired → 409; cross-tenant proposal id → 404; read-only role → 403; audit contains hash; `send_whatsapp_draft` only for a still-pending AI draft.
**Risk:** frontend must pass `proposal_ref` for AI cards; old cards without ids fall back to the stricter capability path.

## 7. PR-6 — operational incidents (item 5)

**Reuse:** `task_service.create_task` (human work item), `push_service.send_to_tenant`, `append_audit`, existing triggers (`escalation_policy`, price-leak/ungrounded guards, send failures, rate-limit pause). The DPDP `Incident` (declared inside `endpoints/incidents.py`) is a breach register — left untouched; new table name `agent_incidents`.
**Schema (migration 125):** `agent_incidents(id, tenant_id, type, severity, status, conversation_id, inquiry_id, guest_id, workflow_id NULL, triggering_event jsonb, attempted_action jsonb (tool + params_hash), reason, owner_user_id, due_at, retry_history jsonb, resolution_note, created_at, acknowledged_at, resolved_at, dedupe_key)` + RLS + tenant policy (as 106/122), index `(tenant_id, status, severity)`, unique partial `(tenant_id, dedupe_key) WHERE status IN ('open','acknowledged')`.
**Service:** `services/incident_service.py::raise_incident(...)` (dedupe, SLA from severity table, creates the task and push, audits). API `GET/POST /incidents`, `…/ack`, `…/resolve` guarded by new capabilities `incidents.read`/`incidents.manage` (migration seeds the catalog and backfills like `119`, skipping tenants whose owner edited the matrix — decision D8).
**First emitters (no behaviour change):** price leak, ungrounded claim, escalation, permanent send failure, consent block, rate-limit pause.
**Tests:** dedupe; SLA; tenant isolation; role gates; task+push+audit created; resolve flow; RLS (PostgreSQL).
**Acceptance:** every blocked or failed AI action leaves one open incident with owner and due time.

## 8. PR-7 — durable per-lead workflow (item 7)

**Reuse:** `FlowPendingExecution` compare-and-set claim and `drain_pending` as the template; `WebhookDelivery` outbox + `retry_due` for effect delivery; Celery `acks_late`; `identity_service`; inbound message id / payment id as dedupe keys.
**Schema (migration 126):** `sales_workflows` and `sales_workflow_events` (design §3.1) and `agent_action_proposals` (design §6.1), all RLS. Unique `(tenant_id, source, source_event_id)` on events gives duplicate-event safety; `version` column for optimistic locking; `next_wake_at` for timers.
**Scope in this PR:** state machine up to QUOTED, **dry-run only** (decisions recorded, nothing sent), reaper for stuck steps, bounded retries with backoff, recovery on worker restart.
**Tests:** duplicate inbound event → one transition; kill between commit and effect → effect delivered once by the outbox; reaper reclaims; optimistic-lock conflict retried; replay of a stored conversation yields identical decisions; PostgreSQL concurrency.
**Not in this PR:** holds, payment links, booking creation (I-8…I-10).

## 9. PR-8 — bounded multi-step tool calls (item 9)

**Gap:** `LLMAdapter.complete()` takes one system string and one user string, returns only the first tool call's arguments, and cannot send a tool result back. Gemini additionally concatenates system and user text into a single user turn.
**Design (new method, existing one untouched):**
```python
async def run_tool_loop(self, *, system: str, messages: list[Msg], tools: list[ToolSpec],
        execute: Callable[[str, dict], Awaitable[ToolResult]], max_steps=4, max_tool_calls=6,
        deadline_s=20.0, max_result_chars=4000) -> ToolLoopResult   # final_text|final_json, steps, usage, stop_reason
```
- Gemini: native `contents` multi-turn with `functionCall` / `functionResponse` parts, a real `systemInstruction`, `toolConfig mode AUTO` during the loop and `ANY` on the final structured turn; OpenAI-compatible adapter (NVIDIA, used today because Gemini billing is blocked): `tool_calls` + `role:"tool"` messages. Same interface, provider chosen by `get_llm`.
- Bounds enforced by the loop, not the prompt: step cap, tool-call cap, wall-clock deadline, per-result size cap, one retry on malformed arguments then stop; `stop_reason` is always returned.
- `execute` is supplied by the **Action Gateway**: it checks the tool is in the policy allow-list, validates arguments against the tool's JSON schema, enforces tenant scope, runs **read-only (T0) tools immediately** and turns anything T1+ into a stored **proposal** (never executes it inside the loop).
- Tool results are wrapped as untrusted data; guest text is never placed in the system turn.
- Logging: provider, model, steps, tool names, latency, token usage per step; never arguments containing PII or the prompt.
**Tests:** scripted provider transcripts (fixtures) for both dialects; step/deadline/size caps; malformed arguments; unknown tool → rejected + incident; tenant-scoped tool results; prompt-injection text in a tool result does not create a call.
**Decision D9:** which provider the loop targets first (NVIDIA works today; Gemini needs billing restored).

## 10. Decisions needed from you

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Opt-out classes and effects (§3.1 table), in particular that "stop messaging me" blocks **all AI/automated** sends while humans may still reply | approve as written |
| D2 | May the AI reply to an opted-out guest who writes in again? | no for `stop_all_automated`; yes (service reply) for `stop_marketing` |
| D3 | Ship the consent enforcement in log-only mode for 48 h first | yes |
| D4 | `reject` requires `conversations.send` (so `read_only`/`marketing` can no longer reject) | yes |
| D5 | `expected_body_sha256` on approve: optional now, mandatory after one release | yes |
| D6 | Review (read-only report) of consent rows created by the old "yes/start" rule; no data change without your say | yes |
| D7 | Audit write failure on settings changes: log and continue, or block the change | log and continue (as one-click does) |
| D8 | New capabilities `incidents.read/manage`: grant to owner/manager only for existing tenants via a backfill migration | yes |
| D9 | Provider for the first tool loop | NVIDIA now; Gemini after billing is restored; same interface |
| D10 | Scheduled messages: implement (recommended) or disable the control | implement, with the old-row sweep run by you |
| D13 | Add a nullable `messages.purpose` column now, or infer purpose (template category / origin) and add the column only if needed | infer first |
| D14 | Consent scopes: keep one `marketing` scope or split into `promotional` and `sales_followup` | keep one for now; split when the sales agent's follow-ups ship |
| D15 | Scheduled sends: per-tenant flag default off, 15-minute grace, 30 rows per tenant per sweep, stale rows marked failed by an owner-run script | yes |
| D11 | AI actor identity: a per-tenant service identity vs `actor_type="agent"` with no user row (affects `inquiry_service` signatures) | `actor_type` field first; service user only if audit needs it |
| D12 | Earlier design decisions D1–D6 in `SALES_AGENT_DESIGN.md` (policy table, hold mechanism, paid-link confirmation, refunds human-only, Instagram as sales channel, planner provider) | unchanged |

## 11. Out of scope for Increment 1

Policy table and control-centre UI, holds, payment-link automation, booking creation by the agent, follow-up cadences, cancellation/refund automation, evaluation harness. None is started; none is needed to make PR-1…PR-4 correct.
