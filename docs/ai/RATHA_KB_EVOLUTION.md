# Ratha — evolving the Knowledge Base into the business knowledge and configuration centre

Written 14 Oct 2026 on `feat/mai3-reliability`. Scope: **Ratha Retreats only.** No duplicate "Business Configuration" module: the existing Knowledge Base page stays and gains a second tab. Paths relative to `backend/app` unless stated.

## 1. Audit of what exists

### 1.1 Knowledge Base (descriptive knowledge)

| Area | Today | Verdict |
|---|---|---|
| Page | `frontend/src/app/dashboard/settings/knowledge/page.tsx` (~900 lines): category filter chips, list, modal editor, upload, add-from-website, indexing status, Approve/Reject/Keep, property scope, "Test what the AI knows" box | Keep; add tabs |
| Categories | `pricing, availability, amenities, addons, location, routes, faq, policy, other` (`schemas/knowledge.py`) | Reuse. `pricing`/`availability` become descriptive only |
| Model | `KnowledgeEntry` (one row per passage; content overwritten in place), `embeddings` (pgvector, namespace `kb`) | Reuse; add versions (K-1) |
| Lifecycle | manual = approved on create; imports = `pending` until approved; edit → `embedding_status=pending` (entry unusable until re-indexed); retry sweep; out-of-date marker; deactivate immediate | Reuse. **Gap:** an edit takes the live answer offline instead of keeping the old published text serving until the new text is ready |
| Versioning / history | none: edit overwrites, no previous text, no effective date, no rollback | **Missing** |
| Audit | `endpoints/knowledge.py` writes **no** audit rows; only `created_by` is stored, no editor on edits | **Missing** |
| Retrieval | `knowledge_service.search_detailed` (active + approved + indexed + not stale + scope); prices stripped before the model sees KB text; same function used by replies and the test box | Reuse |
| Test box | `POST /knowledge/search` → retrieval only. Does not exercise structured data, tools, or quotes | Extend (K-5) |
| Permissions | `settings.manage` (owner only by default) for all writes | Reuse; split edit/publish later (decision B2) |

### 1.2 Commercial data that is already structured (verified by code audit)

| Need | Existing | Gap |
|---|---|---|
| Vehicle capacity, home base, routes | `Property.max_adults/seats/home_base`, `Property.routes` JSON `[{from,to,km}]`, `price_per_km` | no travel time, stops, overnight halts; routes live in a JSON blob; `seats`/`driver_included` never used |
| Product rates | `RatePlan` (`duration_type` same_day/overnight/multiday, `base_price_per_night`, `min_nights`, flat `inclusions` list), `SeasonalRate` (date range, `occupancy_pricing`), `PropertyAddOn` | **No RatePlan CRUD or UI**; `min_nights` not enforced; seasonal match on check-in date only and ignores `duration_type`; no exclusions; no included km, extra-km, extra-guest, driver/toll/night-halt charges; GST fixed 12 %, advance fixed 30 %, both hard-coded |
| Quote | `calculator_service.build_quote`, `build_route_quote` | computed live, **never stored** (`InquiryQuote` exists, nothing writes it); no rate version on a quote |
| Packages / itineraries / destinations | none (iCal text parser labels only) | **Missing** |
| Reseller commission, discount limits | none (only `InquirySource.TRAVEL_AGENT`; report column "not tracked") | **Missing** |
| Payment / cancellation rules | per-booking `StayInstalment`, `StayPaymentLink`; cancellation only as FAQ text | tenant-level rules **missing** |
| Versioning, rollback, effective dating | `is_active` flags; `SeasonalRate` date range only; no audit on rate/property edits | **Missing** |
| Admin UI for caravan pricing | properties page edits name/city/type only; sidebar hides Properties/Calculator for caravan tenants | **Missing** |
| Ratha live data | Seeds (`seed_ratha.py`) hold one property and one placeholder plan; real rates were entered by hand in the database | unknown to the repo: must be confirmed by Ratha |

### 1.3 Authoritative services (reuse, never copy into knowledge)

Availability and blocks: `calculator_service._is_available`, `availability_report`, `vehicle_pool`, iCal/Google blocks. Booking state: `Stay` + `booking_service`. Payment state: `StayPayment`/`StayPaymentLink` + Razorpay webhook. Previously agreed terms: **to be** `InquiryQuote` snapshots (K-4) and `StayAddOn`-style copies at booking time (already the pattern for add-ons).

### 1.4 AI side

Concierge grounding is deterministic code (no model-driven tool loop). `get_llm().complete()` returns the first tool call only; the Gemini adapter has no multi-step support. MCP tools `check_availability`, `get_quote` exist for external clients; there is no package/route/quote-by-package tool. Gemini billing is blocked today (concierge runs on NVIDIA). → The model-facing tools in this design are *backend functions behind the gateway*; the bounded loop is PR-8 of Increment 1.

## 2. Principles

1. **Three sources of truth, never mixed.** Descriptive text → Knowledge Base (retrieved). Exact commercial values → structured published records (looked up by key/id, calculated by code). Live state → availability, booking and payment services. A number in prose is never used to compute anything.
2. **Draft ≠ published.** Guest-facing paths read only *published, effective* data. Drafts, rejected and deactivated versions are invisible to them, by construction (the only read function filters on status) and by test.
3. **Published versions are immutable.** A change is a new version; rollback publishes a copy of an older version as a new version (history is never rewritten).
4. **A quote is a snapshot.** It stores the amounts, the inputs, and the record ids and versions it used; later edits cannot change it.
5. **Missing or conflicting data degrades safely:** no price is stated; the reply says the team will confirm; an incident/task is raised (design `SALES_AGENT_DESIGN.md` §6).

## 3. Proposed data model

### 3.1 Structured business records (new, one table, typed by kind) — migration 124

`business_records` — one row per **version**:

| Column | Notes |
|---|---|
| `id`, `tenant_id` (RLS + tenant policy, like every tenant table) | |
| `kind` | `package`, `destination`, `itinerary`, `reseller_terms`, `discount_policy`, `stay_rules`, `payment_policy`, `cancellation_policy` |
| `key` | stable slug within tenant+kind (`signature-2-pax`, `coorg`) |
| `version` | integer, per (tenant, kind, key), starts at 1 |
| `status` | `draft` · `published` · `superseded` · `rejected` · `inactive` |
| `data` (JSONB) | validated by a Pydantic model per kind on every write (below) |
| `effective_from`, `effective_to` | dates; a future `effective_from` schedules a price change |
| `created_by`, `created_at`, `published_by`, `published_at`, `change_note` | editor, timestamps, reason |
| `supersedes_id` | previous version it replaced; `rollback_of_id` when created by rollback |
| unique | `(tenant_id, kind, key, version)`; partial unique: one `published` per `(tenant_id, kind, key)` whose effective window overlaps is rejected by the publish validator (and checked in a transaction) |

Why one table, not eight: all kinds share the same lifecycle (draft/validate/preview/publish/rollback/audit); per-kind shape lives in typed schemas, so exact calculations read **typed fields**, never free text. Why not extend `RatePlan`/`SeasonalRate`: they are live-edited in place with no CRUD, no exclusions or charges, and are tied to the per-night model used by bookings; changing them risks the booking and calendar flows. They stay as they are; an **import helper** can create *draft* packages from them (never auto-published).

Reused as they are: `Property` (vehicle capacity, home base, routes JSON stays a fallback), `PropertyAddOn` (per-booking add-ons and experience extras), `StayInstalment`/`StayPayment*` (per-booking payments), `Consent`, `append_audit`, `authz_service`, `InquiryQuote` (extended, §3.3).

**Kind schemas (Pydantic, strict, money as integer rupees or `Decimal`):**

- `package`: `name`, `summary`, `product` (`same_day|overnight|multiday|route`), `vehicle_property_ids` (empty = all), `min_nights`, `max_nights`, `max_guests`, `included_km` (per day or total), `inclusions[]`, `exclusions[]`, `rates[]` = `{label, valid_from, valid_to, amount, unit: package|night|day, min_nights?, days_of_week?}`, `extra_guest_charge {per_guest_per_night, free_guests}`, `extra_km_charge {per_km}`, `charges[]` = `{name, kind: experience|driver|toll|night_halt|other, amount, unit: per_stay|per_night|per_person|per_unit, optional}`, `destination_keys[]`, `gst_percent`, `quote_valid_days`.
- `destination`: `name`, `description`, `stops[]` = `{name, order, overnight}`, `distance_km_from_base`, `travel_hours_from_base`, `best_months`, `notes`.
- `itinerary`: `name`, `destination_key`, `nights`, `days[]` = `{day, title, stops[], overnight_location, notes}`, `package_keys[]`.
- `reseller_terms`: `tiers[]` = `{name, commission_percent, applies_to_package_keys, max_discount_percent}`, `settlement_notes`.
- `discount_policy`: `max_discount_percent`, `max_discount_amount`, `floor_rule` (`never_below_base`), `requires_approval_above_percent`, `approver_roles`, `valid_conditions[]` (e.g. min nights, off-season), `stackable: false`.
- `stay_rules`: `check_in_time`, `check_out_time`, `early_check_in_allowed`, `min_age`, `id_required`, `house_rules[]`.
- `payment_policy`: `advance_percent`, `balance_due_days_before_checkin`, `instalments[]`, `accepted_methods`, `payment_link_expiry_hours`, `confirmed_by_ratha: bool` — **a policy with `confirmed_by_ratha=false` cannot be published** (nothing is invented).
- `cancellation_policy`: `tiers[]` = `{days_before, refund_percent}`, `non_refundable_items[]`, `confirmed_by_ratha: bool` (same rule).

**Publish-time validation** (blocks publish, returns a list of problems): required fields per kind; rates have non-negative amounts, `valid_from ≤ valid_to`, **no overlapping rate windows for the same product**; `min_nights ≤ max_nights`; `max_guests ≥ 1` and ≤ the vehicle's `Property.max_adults`; every `destination_key`/`package_key` referenced exists as a published record; at least one rate covers today or a stated future date (warning, not error); discount limits within 0–100; commission within 0–100; `inclusions` and `exclusions` do not contain the same item; GST within 0–28; payment/cancellation tiers sorted and consistent (refund % non-increasing as the date nears). Cross-record checks run again on **deactivation** (cannot deactivate a destination still used by a published package).

### 3.2 Narrative knowledge versions (extend `KnowledgeEntry`) — migration 125

`knowledge_entry_versions(id, tenant_id, entry_id, version, category, question, content, property_id, alt_phrasings, status draft|published|superseded|rejected, embedding_status, embedding_error, content_hash, created_by, created_at, published_by, published_at, change_note)`.
The `knowledge_entries` row always holds the **published** text (so the retrieval SQL is unchanged). An edit creates a draft version; its vectors are written under a separate namespace (`kb_draft`) so retrieval cannot see them; **publish** (after indexing succeeded) swaps entry fields and moves the vectors to namespace `kb` in one transaction: the old answer serves until the instant the new one is ready, and a failed index leaves the live answer untouched. Rollback = new draft from an older version → publish. `is_active`, `priority`, `review_status` (controls) stay immediate. Imports keep the `pending → approve` path; approval of an import = publish of its first version.

### 3.3 Quotes (extend `InquiryQuote`, which already exists and is never written)

Add `snapshot` (JSON: inputs, lines, subtotal, GST, total, advance), `record_refs` (JSON `[{record_id, kind, key, version}]`), `params_hash`, `property_id`, `check_in`, `check_out`, `guests`. `valid_until` from the package's `quote_valid_days`. Issued by `quote_service.issue_quote(...)`; never recomputed from live records after issue.

### 3.4 Audit and attribution

Every create/edit/publish/reject/deactivate/rollback on both stores writes `append_audit` (`business_record.published`, `knowledge.version_published`, …) with actor, record key, versions, and a **diff** (previous value → new value for structured data; hashes for long text, full text lives in the version rows). Editor, timestamp, previous/new value and effective date are therefore recoverable from the version rows and the chain.

## 4. How the AI reads each source (no database access for the model)

| Question | Source | Mechanism |
|---|---|---|
| "What's included in the Coorg package?" | `package` record (published, effective) | `package_facts()` → prompt; exact inclusions/exclusions from fields |
| "How much for 3 nights, 4 guests, 12–15 Dec?" | `package` record + availability | `package_pricing_service.quote(...)` (code): picks the effective rate, applies extra-guest/km/charges, GST, advance; checks `availability_report`; returns lines + record versions or a typed reason (`no_rate`, `conflicting_rates`, `over_capacity`, `unavailable`, `needs_confirmation`) |
| "Can you do 10 % off?" | `discount_policy` | `policy_check(discount)` → allowed / needs approval / refused, never a model decision |
| "Tell me about Coorg" / itinerary | `destination` + `itinerary` records for exact stops/overnight; KB prose for the story | both returned; the KB part by retrieval |
| "Is my booking confirmed / paid?" | `Stay` + payment ledger | existing `guest_booking_facts` |
| "What did you quote me?" | `InquiryQuote` snapshot | `get_issued_quote(id)` |
| Narrative: amenities, scripts, policies in words | KB | retrieval as today |

These are backend functions behind the Action Gateway (read-only, tenant-scoped, schema-validated arguments). Until the bounded multi-step loop (Increment 1, PR-8) exists, the concierge calls them deterministically before drafting, as it does for availability today. Gemini is then a *reader* of these results, never a source of prices.

## 5. Proposed UI (existing page, two tabs)

**Tab A — Knowledge & Training** (today's page, plus): version badge (Published v3 · Draft v4 pending), **History** drawer (who/when/what changed, restore as draft), **Publish** button on a draft (disabled until indexed; shows indexing state), category filter unchanged, imports panel unchanged.
**Tab B — Structured Business Data**: left list by kind (Packages, Destinations, Itineraries, Reseller terms, Discount policy, Stay rules, Payment policy, Cancellation policy); each record shows *Published vX (effective from …)*, *Draft vY*, *Scheduled vZ (from …)*. Editor = typed form (not JSON), live validation messages, **Preview** (renders the exact guest-facing summary and runs the pricing function for a sample stay), **Publish** (shows what changes: a field-level diff against the live version), **Deactivate**, **Roll back** (pick a version → creates a draft copy → publish). A banner states "Drafts never affect guest replies". Mobile-first (375 px), kit components, tokens only.
**Test box (both tabs):** one input; runs the **same** path as a reply: retrieval + package/route lookup + (optional) priced sample, and shows for each piece the **source, version and effective date**, plus flags: *missing price*, *conflicting rates*, *draft exists but is not live*, *index pending*.

## 6. Reuse vs new build

| Item | Decision |
|---|---|
| KB page, categories, lifecycle, retrieval, indexing sweep, prices-stripped rule | **Reuse** |
| Knowledge versions + publish swap + history | **New** (K-1): required for draft isolation and rollback |
| `Property`, `PropertyAddOn`, `RatePlan`, `SeasonalRate` | **Keep unchanged** (booking/calendar depend on them). No duplicate columns. Import helper creates drafts from them |
| Packages/destinations/itineraries/reseller/discount/stay/payment/cancellation | **New** `business_records` (nothing equivalent exists) |
| Quote persistence | **Reuse `InquiryQuote`**, add snapshot columns |
| Pricing calculator for packages | **New service** `package_pricing_service` next to `calculator_service`; reuses `availability_report`, GST helper; does not touch `search/build_quote` |
| Audit, capability check, tenant RLS pattern, migration pattern | **Reuse** |
| Payment-link creation, booking creation | **Not in this task** (dependencies in §8) |

## 7. Increments (each small, reviewable, tested on SQLite and PostgreSQL)

| ID | Increment | Depends on | Acceptance |
|---|---|---|---|
| **K-0** | Audit rows for every KB change; `updated_by` on entries | – | each create/edit/approve/reject/delete/deactivate leaves one chained row with actor |
| **K-2** | `business_records` model + migration 124 + per-kind schemas + validators + service (draft, validate, publish, supersede, deactivate, rollback, resolver) + audit + API (`/business-data`) | – | draft/rejected/inactive never returned by the resolver; publish blocked by validation; rollback creates a new version; tenant isolation; RLS |
| **K-4a** | `package_pricing_service.quote()` over published records + `quote_service.issue_quote()` snapshot + safe failures | K-2 | price change published → next quote changes with no re-index; old quote unchanged; missing/conflicting rate → typed refusal |
| **K-4b** | Facts for the concierge and read-only gateway functions: `list_packages`, `get_package`, `get_destination`, `get_itinerary`, `quote_package`, `policy_check` | K-4a | replies use published data; drafts invisible; availability from `availability_report` |
| **K-1** | Narrative KB versions + publish swap + history/rollback | K-0 | live answer unchanged until publish; failed index leaves live text; rollback works; drafts not retrievable |
| **K-3** | UI: tabs, structured editors, history, preview, publish/rollback | K-2, K-1 | usable at 375 px; validation messages; diff before publish |
| **K-5** | Test box runs the real pathways and shows source/version/flags | K-4b | same function as the reply path (asserted by test) |
| **K-6** | Import helper: draft packages from existing `RatePlan`/`Property.routes` | K-2 | creates drafts only |

Order: **K-0 → K-2 → K-4a → K-4b → K-1 → K-5 → K-3 → K-6.** (Prices and their safety first; polish after.)

## 8. Dependencies for the Ratha Sales Agent and the Razorpay module

| Needed by | Depends on |
|---|---|
| Qualification, recommendation | `package` + `destination` + `itinerary` published; `Property.max_adults`; KB prose |
| Negotiation | `discount_policy` + `reseller_terms` published; approval model (Increment 1 PR-5/6) |
| Quote | K-4a; `InquiryQuote` snapshot; availability service |
| Payment link | `payment_policy` (confirmed by Ratha); a stored quote id; **Razorpay link idempotency, expiry, hold state** (audit: current link creation is per-booking, not idempotent; no hold) |
| Payment reminders, status | `StayPaymentLink`/`StayInstalment`; reminder scheduler (scheduled-send, Increment 1 PR-4) |
| Booking creation/confirmation | conflict check on create, idempotency (Increment 1 / plan I-0a, I-8–I-10) |
| Escalation | incident model (PR-6), `escalation_policy` |
| Cancellation | `cancellation_policy` (confirmed by Ratha); refund remains human-only |

## 9. Information only Ratha can supply (blocking publication, not building)

The real package list and prices (the repo has placeholders only), seasonal windows, included km and extra-km/extra-guest/experience charges, route list with stops and travel times, reseller tiers and commission, maximum discount and who approves, GST rate, advance and balance-due rules, cancellation tiers, check-in/out times. Until they are entered and published, the agent says the team will confirm; nothing is invented.

## 10. Decisions needed

| ID | Decision | Recommendation |
|---|---|---|
| B1 | One typed `business_records` table (JSONB per kind) vs eight tables | one table; typed Pydantic schemas |
| B2 | Who may edit and who may publish (today `settings.manage`, owner-only) | keep `settings.manage` for both now; add `business_data.edit`/`.publish` capabilities later if a manager should draft but not publish |
| B3 | Future-dated publishes (schedule a price change) | yes, via `effective_from` |
| B4 | Do existing `RatePlan`/`SeasonalRate` stay authoritative for bookings until cut-over | yes; packages power quotes first |
| B5 | GST and advance move from hard-coded constants into published `payment_policy`/`package.gst_percent` | yes, with the old constants as the fallback only when no policy is published |
| B6 | Narrative-KB edit semantics change from "unusable until re-indexed" to "old text serves until the new text is published" (K-1) | yes |
| B7 | Draft preview in the test box (editors only, clearly labelled, never used by guest paths) | yes |

## 11. Status (14 Oct 2026, `feat/ratha-business-data`)

| Increment | State | Commit | What it delivers |
|---|---|---|---|
| K-2 | done | `09c60c9` | `business_records` (migration 124), typed per-kind schemas, draft → publish → superseded, rollback = new version, effective dating, audit, `/business-data` API |
| K-4a | done | `69d5015` | `package_pricing_service.quote`, `quote_service.issue_quote` / `check_still_valid`, issued-quote snapshots (migration 125) |
| K-4b | done | `65cafbc` | `sales_gateway` (read-only), concierge facts, prompt `concierge-reply-v13` |
| K-0 | done | `cd463e5` | chained `kb.*` audit row for every knowledge write |
| K-5 | done | `2338664` | `POST /knowledge/test`: same retrieval and gateway calls as a reply; sources, versions, flags |
| K-3 | done | `2c0f2e0` | two-tab knowledge page, typed editors, review/diff/publish, history/restore, 375 px |
| K-6 | done | `65096af` | `POST /business-data/import-existing` (drafts only) |
| K-1 | done in part | `450f7bb` | history and undo for narrative entries from the audit trail. **Not done:** "old text keeps serving until the new text is indexed" (B6) -- needs a versions table; today an edited entry is withheld until indexed, which never exposes unpublished wording |

### 11.1 How the acceptance tests are met

| Acceptance test | Where it is pinned |
|---|---|
| Published price change affects new quotes without re-indexing | `test_package_pricing.py::test_a_published_price_change_reaches_the_next_quote_without_any_re_indexing`; `test_concierge_business_data.py` (real concierge task, indexing patched to fail if called) |
| Draft and rejected changes never affect replies | `test_sales_gateway.py::test_draft_rejected_scheduled_and_unknown_records_are_invisible`; `test_concierge_business_data.py::test_a_draft_or_rejected_change_never_reaches_the_model`; `test_kb_test_box.py::test_drafts_are_never_previewed` |
| Published itinerary change is retrieved correctly | `test_sales_gateway.py::test_a_published_itinerary_change_is_retrieved_at_once_with_its_new_version` |
| Historical quotes keep original price and version | `test_package_pricing.py::test_an_issued_quote_keeps_its_price_and_terms_after_a_later_change` |
| Missing or conflicting prices give a safe response | `test_package_pricing.py` (parametrised refusals, conflicting rates, km without a rate); prompt tests show no figure reaches the model on a refusal |
| Availability and payment status come from authoritative services | quote availability = `calculator_service.is_open` (bookings and blocks), tests in `test_package_pricing.py`; payment status is **not** part of this work (stays with Razorpay/`StayPayment`) |
| Tenant permissions and audit logging stay enforced | `settings.manage` on every write and on the test box; cross-tenant tests in each file; `business_record.*` and `kb.*` audit rows |
| Existing KB and reliability tests still pass | full-suite results in §11.3 |

### 11.2 Decisions taken without asking (change them if you disagree)

* One typed table (B1), `settings.manage` for edit and publish (B2), future-dated publish (B3), `RatePlan` stays authoritative for bookings (B4).
* Payment and cancellation terms reach the model only when the workspace is in `grounded` price mode; descriptive data (what is included, routes, check-in times) is always available. Ratha's default hand-off rule is untouched.
* A quote is **priced**, not **issued**, until a person or a later tool calls `issue_quote`; issuing is idempotent and audited.
* The test box does not call the language model: you state what the classifier would have read (dates, party, destination). Draft preview (B7) was not built.

### 11.3 Verification

Full suites on this branch at `450f7bb` (exit 0 both): **PostgreSQL 16.14 + pgvector (fresh DB migrated to 125): 2764 passed / 0 failed / 1 skipped / 26 xfailed**; **SQLite: 2707 passed / 0 failed / 59 skipped / 25 xfailed**. Frontend: `tsc --noEmit --skipLibCheck` clean, vitest 72 passed. This branch is based before PR-1 (`a48ad25`), so PR-1's tests are not in these counts. The UI was also exercised in a browser against a throwaway PostgreSQL workspace (draft, review, publish, quote reflects the new price; 375 px, no horizontal overflow). Nothing was pushed, deployed or run against production.
