# AI feature matrix (mAI3, 14 Oct 2026)

Status: **Working** · **Partial** (works, with a stated gap) · **Disconnected** (code exists, nothing runs it) · **Not changed** (inspected, left as is).
The code wins over this table. Checked against `feat/mai3-reliability`. Tests: SQLite 2573 passed / 56 skipped; PostgreSQL 16.14 + pgvector 0.8.5 2628 passed / 1 skipped (retrieval SQL covered by `test_knowledge_pgvector_postgres.py`). No live model provider or production system was contacted.

## Reply path (WhatsApp / Instagram)

| Feature | Status | Reads from | Gap / limitation | Tests |
|---|---|---|---|---|
| Draft reply (`concierge_draft`) | Working | conversation, KB, property records, guest bookings, availability, enquiry | Gemini route is off while billing is blocked (runs on NVIDIA `gpt-oss-20b`) | `test_concierge_operational_data.py`, `test_concierge_draft_*` |
| Understanding the message (intent, dates, party, questions, sentiment) | Working | last 8 messages + enquiry fields, one `quick_classify` call | extracts only what was stated; relative dates resolved by the model | `…operational_data::test_dates_and_party_given_earlier…` |
| Availability | Working | `calculator_service` (bookings confirmed/checked-in, calendar blocks incl. iCal, shared-vehicle pool) + `availability_report` reasons | cancelled bookings free the dates; a failed lookup is reported, never guessed | `…::test_a_calendar_block…`, `…::test_a_cancelled_booking…` |
| Pricing | Partial | `calculator_service.search/build_quote` | default `handoff` mode never states a price (Ratha rule). `grounded` mode quotes only live figures. Quote needs one unambiguous property; add-ons are not auto-selected | `…::test_default_mode…`, `…::test_grounded_mode…` |
| Property facts (amenities, capacity, departure city, add-ons, FAQs) | Working | `Property`, `PropertyAddOn` | no per-property check-in time field exists; `Property.faqs` shape is not validated | `…::test_property_facts_are_scoped…` |
| Guest's own bookings | Working | `Stay` + payment ledger, by the conversation's guest id only | no amounts by design; an Instagram guest with no linked identity sees nothing | `…::test_pending_confirmed_paid_and_cancelled…` |
| Knowledge-base retrieval | Working | `knowledge_entries` + pgvector | pgvector SQL verified on PostgreSQL 16.14 + pgvector 0.8.5 (local container); embedding quality not measured with the real model | `test_knowledge_lifecycle.py` |
| Safety guards (grounding, media claim, escalation, price, confidence, rate limit, kill switch) | Working | – | an "I'll check if it's available" sentence can be held for review when nothing is open | `test_concierge_*` |
| Approval / autonomy modes | Not changed | `ai_mode_service`, tenant thresholds | send still needs `conversations.send`; shadow and kill switch verified | `…::test_shadow_mode_and_the_kill_switch…` |
| Model-output safety | Working (new) | – | bad/oversized/non-JSON output goes to review | `…::test_malformed_model_output…` |
| Duplicate protection | Working (new) | – | Meta has no idempotency key: a crash between "sent" and the commit can still repeat once | `…::test_a_retried_task…`, `test_ai_reliability_controls.py` |
| Rewrite / translate / tone | Working | draft or composer text | translation is only on request; a rewrite that changes a number is rejected | `test_ai_reliability_controls.py` |

## Knowledge base

| Feature | Status | Notes |
|---|---|---|
| Create / edit / delete | Working | edit → `pending` (not retrievable) until re-indexed; delete removes vectors |
| Indexing | Working | `knowledge.embed_entry`; beat `knowledge.sweep_all_tenants` every 15 min retries stuck/failed (backoff, cap 6); concurrent edits never marked done on old text |
| Status visibility | Working (new) | per-entry state, error, attempts, last indexed; stats; "Retry indexing" |
| Website / document import | Working | duplicates skipped; passages no longer on the page are marked out of date and not used (owner can Keep); needs Approve to go live (the Approve/Reject buttons were missing before) |
| Property scope | Working | tenant-wide or one property; set in the editor; validated against the tenant |
| Test box | Working | same function as replies; shows why nothing matched or that search failed |
| Re-crawl on a schedule | Disconnected | not built; import is manual |
| Conversation-mined entries (`source=conversation`) | Not inspected | enum value exists |

## Analysis

| Feature | Status | Notes |
|---|---|---|
| Lead summary + analysis (`generate_ai_summary`) | Working | 30 real messages, previous summary, real stage, computed booking state; refreshes on inbound, on team send, and when AI is off (10 min debounce) |
| Stage / next-action suggestions | Not changed | rule-based (`lead_recommendation_service`, `next_action_service`); a human applies them |
| Nightly intent tagging (`classify_intent`) | Disconnected | beat entry exists, task not routed; enabling it is an owner decision (`_KNOWN_UNROUTED`) |
| Ask HAIP agents / free-form SQL | Not changed | validated single-table SELECT, tenant predicate injected, read-only DB role |

## Providers

NVIDIA NIM first (`get_llm`), Gemini fallback for 8 internal tasks, embeddings NVIDIA `nemotron-3-embed-1b`. Added: embedding timeouts (8 s query / 30 s indexing, SDK retries off), NVIDIA token usage in results, per-completion log (provider, model, latency, tokens; never text). No new provider or paid service.
