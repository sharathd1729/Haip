# HAIP — Claude Code Working Instructions
**Version**: 2.4 · **Owner**: Sharath D. · **Updated**: 19 Oct 2026 (Alembic head `148`)
**Reference docs**: HAIP_FULL_BUILD_PLAN.md · architecture-delta.md · execution-plan.md · docs/HAIP_Module_Audit_M0.md (module status matrix, 11 Oct 2026 — update statuses as gaps close)

**KEEP THIS FILE CURRENT — standing rule from the owner.** When a change adds or alters a
module, migration, endpoint, Celery task, integration, LLM route, env var, test baseline or
rule, update the matching section here **in the same commit**. Bump the `Updated` date and
the Alembic head. If this file and the code disagree, the code wins and this file is a bug.
Keep it under 500 lines: compress old incident notes rather than dropping new facts.

---

## PRODUCT IN ONE LINE
HAIP is the AI intelligence and communication layer for Indian luxury
hospitality — pre-call prep, post-call analysis, AI-drafted WhatsApp
replies, unified lead record across every touchpoint.

## WHAT HAIP IS NOT
- Not a PMS (Hostaway/eZee remain source of truth)
- Not a softphone (agents take calls on personal mobile via IVR)
- Not a channel manager (we sync via Hostaway)
- Not a booking engine

---

## CURRENT MILESTONE
**M4 — COMPLETE** ✓ Leads360 (unified sales pipeline, progressive identity, async AI summaries)

**M5 — IN PROGRESS** Acefone full integration + Hostaway sync + Owner Daily dashboard
(Acefone/Hostaway still open; the items below shipped Aug–Oct 2026 alongside them)

**Shipped since M4 (all live; migration numbers in brackets):**
- **Bookings** (`Stay`): list + full booking page, add-ons, payment ledger, payment schedule, security deposit (never revenue), service requests mirrored as Tasks, change guest via `identity_service`, date-conflict guard [110, 111]. **Razorpay**: per-tenant keys (encrypted) + signed webhook, idempotent on the payment id via unique index `uq_stay_payments_external` (IntegrityError in a savepoint = duplicate) [141]. DPDP erasure clears all booking children except invoices (kept for GST, detached: `stay_id` NULL).
- **Invoices + booking WhatsApp (Phase 4, Oct 18)** [141]: `payment_events_service.on_payment_link_paid` is the ONE paid-link entry point (webhook: DB only). Booking link -> StayPayment + audit + Celery `invoices.after_payment` (`payment_followup_service`: first payment = tax invoice, later = receipt against it; PDF via `invoice_pdf` (reportlab, "Rs. 1,25,000") -> `media_storage.upload_invoice_pdf`; then `ratha_booking_confirmed_v1` / `ratha_payment_received_v1` with the PDF; push to staff). Quote link (`stay_payment_links.inquiry_quote_id`, stay_id NULL) -> `quote_payment_service` (see Quote builder). `invoices`/`invoice_sequences`: number `{prefix}/{FY 2026-27}/{0001}` from one guarded `UPDATE ... RETURNING` (row lock until commit; rollback returns the number); issued rows immutable (ORM `before_update` guard; only status/pdf_media_key change); "Reissue" = new number + old `superseded` (`POST /bookings/{id}/invoices/reissue`, owner/manager). GST: amounts INCLUDE GST, tax only with a seller GSTIN, CGST+SGST when place of supply = seller state else IGST (accountant to confirm). Seller profile `brand_config.invoice_profile` (GSTIN checksum, `schemas/invoice.py`), page `/dashboard/settings/invoices`; logo = upload (Pillow PNG) else Branding data-URL logo, never fetched. WhatsApp: `wa_booking_messages.send_booking_template` (idempotency_key `bk:{stay}:{event}`, skips + audits `booking.message_not_sent` unless APPROVED); per-message DOCUMENT header + URL `{{1}}` suffix ride in `Message.channel_metadata` (`document`, `button_params`), signed at send. Pack of 4 (`wa_booking_pack`, `POST /messaging/templates/booking-pack` = drafts only, never submitted). Beat `payments.balance_reminders` 09:35 IST, opt-in `brand_config.payments.auto_balance_reminder`, once per instalment. Tasks `invoices.after_payment|render_pdf`, `payments.notify_staff|balance_reminders` on queue `whatsapp`. Dep: `reportlab`.
- **iCal feeds** [109]: per-property export (`/ical/{token}.ics`, dates only) + optional import URL (Fernet-encrypted, SSRF-guarded, polled
  every 30 min into date blocks, re-exported to the other links). Overlap with a HAIP booking raises ONE task per clash (block x vehicle; title `ical_clash_tasks.clash_title` is its identity), which every sync closes again once the clash is gone (`ical_clash_tasks.close_stale`, audited `task.auto_closed`; by hand: `scripts/close_stale_clash_tasks.py`, dry-run default, `--apply`). (Two-way Google Calendar: not built.)
  **Shared calendar** [120]: one link, several vehicles (`ical_feed_vehicles` keywords, whole-word; no match = all held + a "Which vehicle?" task).
  Trip dates in the description widen the block (`ical_event_details.py`); details show on the calendar (amounts: `revenue.read`).
  **Lead attribution (Oct 14)**: `inquiry_service._stage_id_for` resolves legacy stages by meaning (valid-entry / closed-won / closed-lost), never to a gone key; the stage chips apply the list's filters; a manual booking links to the guest's one open lead (or `inquiry_id`) and marks it Sold; `organic_call` source [126] = inbound call with no ad behind it (older call leads keep their source); no source = "Not recorded". One `PeriodBar` (Today/Yesterday/7d/This month/Last month) on both Home views, Today on EVERY load (`useDashboardPeriod`: sessionStorage only, never per device; the old localStorage memory made phones show "Today" zeros next to the laptop's month), and dashboard queries (`business-overview`, `dashboard-overview`, `work-queue`, `impact-since-haip`, `portfolio-calendar`) are never persisted (`queryClient.NEVER_PERSIST`; key also carries tenant + IST day); calendar = month grid on phones, timeline above 768px, entries open booking/lead (`/calendar` returns `inquiry_id`). Campaign report has Replied (inbox match, 7 days).
  **Vehicles (Oct 16)**: caravans are named "Ratha 1"/"Ratha 2"; a booking with no vehicle goes to the FIRST FREE one (`booking_service.pick_free_property`, natural name order; manual `POST /bookings` may omit `property_id`, calendar events too; 409 when all taken). The "Unassigned" placeholder is now only the overflow when every vehicle is taken (+ task). Black/White lives in the booking's staff Notes (`internal_notes`, shown on the calendar sheet). One-off `scripts/ratha_vehicles.py` (dry-run default; `--include-past` for ended bookings) renames + moves legacy placeholder bookings. The calendar shows the "Unassigned" row only while it holds a real booking (its blocks are just the shared calendar's own record).
  **Calendar bookings** [121]: a complete event becomes a `Stay` (`ical_booking_service.py`), tied to the guest's one open lead (marked Sold); no vehicle = "Unassigned", picked at check-in (`vehicle_pool.py`); a CRM edit locks it.
- **Public API + webhooks** [112, 113]: `/api/public/v1` is a *separate* FastAPI app (`app/public_api/`). Scoped API keys (SHA-256 only, shown once, lookup via SECURITY DEFINER fn). Signed outbound webhooks (HMAC-SHA256 over `timestamp.body`, outbox written in the same transaction, ~22h backoff, auto-off after 100 consecutive failures, HTTPS + SSRF guard).
- **HAIP's own website leads** [145] (the old book-demo/contact forms posted to a route that never existed and showed "success": every lead was lost). `POST /api/v1/public/leads` (no login; kind `demo|contact|assessment`; `endpoints/public_leads.py`, `platform_lead_service.py`): bounded schema (`schemas/platform_leads.py`, body tenant ignored, 16 KB cap, phone -> E.164), honeypot `website` (stored as spam, no lead), DPDP notice by version (`NOTICE_TEXTS` = `frontend/src/lib/publicLeads.ts`; hash stored), idempotent on the browser's `submission_id`, rate limit = middleware tier `/api/v1/public/` (10 lead POSTs/min/IP, fail-open) + DB count per hashed IP (10/h, holds without Redis). Stored FIRST in `platform_leads` (DOCUMENTED PLATFORM-LEVEL EXCEPTION: HAIP's own prospects, no `tenant_id`, no RLS; read only by the owner of the `PLATFORM_LEADS_TENANT_SLUG` workspace via `GET /platform-leads`, page `/dashboard/settings/platform-leads`), then copied into that workspace (guest via `identity_service`, phone else email; web_form consent rows; WEBSITE inquiry, a 2nd form within 30 days joins the open one; audit `platform_lead.routed`); unset slug = `not_configured`, failure = `failed` (row kept). Celery `platform_leads.notify` (queue default) pushes + emails the owners once. Forms show success only on a 2xx.
- **Property assessment + ROI tool v1** [145] (public `/assess`, linked from the marketing nav/footer): `endpoints/public_assessment.py` = `GET /public/assessment/options`, `POST /public/assessment/estimate` (free headline range, no writes), `GET /public/assessment/{lead}/report[.pdf]?token=`; the full report needs name + phone + consent and goes through `POST /public/leads` kind `assessment` (server recomputes, stores `{input, result, benchmark_version}` on the platform lead, returns report + HMAC report token; retry = same snapshot). Engine `assessment_engine.py` is pure + deterministic (segment small <5,000 sq ft / medium <1 acre / large; 12-month occupancy x ADR x scenario low/likely/high, extras, events, OTA cost, running costs, investment, payback, slice-and-dice zoning on 600x400 rendered as SVG + in `assessment_pdf.py`). ONE source of numbers: `assessment_benchmarks.active()` = active `roi_benchmarks` row (DOCUMENTED PLATFORM-LEVEL EXCEPTION, no tenant_id; immutable versions; `POST /roi-benchmarks` + `/{v}/activate`, sales-workspace owner only, audited `roi_benchmarks.*`; UI on the website-leads page) else seed `app/data/roi_benchmarks/ka-2026-10-sample-v1.json` (SAMPLE Karnataka values, every entry "sample — owner to confirm"; schema `schemas/assessment.py::BenchmarkSet`, also holds the SaaS/Service CTA text). Optional AI write-up: Celery `assessment.narrative` (queue ai_scoring, `ASSESSMENT_NARRATIVE_ENABLED`), router `assessment_narrative`, prompt `assessment-narrative-v1`; numbers-only-from-facts guard (`check_numbers`), rejected/failed = not shown.
- **A LEAD is a person (Guest) with a usable phone number** (`guests.lead_identified_at`, migration 122; `phone_identity.py`, `lead_metrics.py`).
  A DM/conversation/enquiry alone is not a lead; leads, conversations, enquiries, bookings and cash are counted apart, conversion is a
  cohort. Same person = exact normalised phone (phone or WhatsApp number) / verified identity / approved merge, never names; merges are logged
  (`guest_merge_events`) and reversible; first touch is written once. Catalogue: `docs/analytics/KPI_METRIC_CATALOGUE.md` "Lead definition".
  **A number typed in a chat** (Instagram) -> `chat_phone_capture.capture_from_text` ONLY: `phone_identity.find_phones` (phonenumbers matcher, NOT a digit regex: dates/prices/pincodes are not phones, a number next to a date is found; placeholders like 9876543210 rejected) -> `identity_service.add_signal` (lead) + default->valid stage + closes "Guest declined phone number" tasks; `lead_auto_create.text_contains_phone` uses the same rule. `add_signal(observed_at=)` dates a backfilled lead at the message. `scripts/backfill_chat_phones.py` (dry run default). Concierge: a WhatsApp-number signal = has a phone.
- **Work queue** (My day, Oct 17): `work_queue_service` is the single source behind My day, the Home "Waiting for you" cards and Today strip, the nav "Now"/My day badge and Calls; never add a parallel "what to do now" query. It is about PEOPLE with a usable phone (`guests.lead_identified_at`), one row per person, kinds `callback` > `new_lead` (no PERSON has contacted them since the number arrived; the AI's autonomous replies do not count; a quote shared from the rate calculator (sent or copied, `inquiry_quotes.shared_at`) does; an unanswered outbound call is an "attempt") > `reply` (lead whose last message is theirs, nobody incl. the bot answered, 5 min bot grace) > `no_reply` (D-23: last message OURS incl. approved/auto-sent AI, guest silent 24 h+, lead open, 14-day look-back; `work_queue_signals.py`) > `followup` (task due, about a lead or about no guest; a task about a no-phone guest stays on Tasks/Inbox) + `clash` (the calendar sync's own tasks, created_by NULL with a calendar title prefix: "Calendar clashes" section on My day, in the nav total, not in people/severity/Follow-ups overdue). A person with a live booking (`work_queue_signals.booked_guests`: not cancelled, made since `lead_identified_at` or check-out today+, no newer open enquiry) is never `new_lead`/`no_reply` nor flagged `not_called`/`at_risk`, but still a `reply`. `concierge_draft` raises "Call lead about pricing" only for a guest with `lead_identified_at`. Items carry `flags` (`not_called`, `open_lead` = follow-up on an open valid-stage lead, `at_risk` = warm + check-in in 30 days + quiet 48 h), counted in `build()["flags"]`; My day filters `?kind=` / `?flag=`. Plain DMs with no number are NOT on it (Inbox only), and Home shows no DM/conversation counts. Each item has a `severity` (fresh/late/urgent/critical/stale from `SLA_MINUTES`); the same rule must drive any alert/reminder. Next (not built): alerts + repeat reminders to the "Hi Ratha" personal-WhatsApp group. **KPI metrics**: `services/kpi_metrics.py` holds shared definitions (`leads.new`, `stays.occupied_nights`, `stays.booked_value` = rental + add-ons, D-24; `lead_metrics.count_qualified_dated` = phone + check-in date); catalogue + gaps in `docs/analytics/`. Don't unify a metric without its D-nn decision. **Owner dashboard, layout A** (Oct 19; `/dashboard` for owner/manager; others keep `/dashboard/operations`): `GET /dashboard/business-overview` composes shared metrics, the page reads its `owner` block (`owner_dashboard_attention.py`: six cards from the ONE queue read + bookings owing money; `owner_dashboard_blocks.py`: KPIs, month target on booked value with pace (D-24, Targets page uses the same, IST days), check-ins `window_days` 3/7/15/30, travel weeks, stages + lost reasons, caravans, AI and calls, team); D-22: no-phone DMs/contacts never counted there; first touch `organic_call` = "Organic calls" (`lead_metrics.first_touch_expr`); catalogue section 15; booking amounts (list, detail, calendar) need `bookings.read`; targets, executive, calendar amounts and the revenue report need `revenue.read` (REST and MCP); restricted = `{restricted:true}`, never 0. Docs: `docs/analytics/BUSINESS_OVERVIEW_IMPLEMENTATION.md`.
- **Lead autopilot** [144] (`lead_autopilot_service` + `_rules` + `_ai` + `_view`, table `lead_autopilot_events`): stage decisions from bookings, dates, calls, chats, timing. Rules first (booking -> Sold; check-in passed, no booking -> Lost "dates"; human call disposition lost / guest's LATEST message is a clear decline -> Lost; N unanswered outbound calls over >=2 days, no reply -> `rnr` (forward only); quote/follow-up then silence -> Lost "no_response"; phone -> valid entry, + dates/route/headcount -> first open valid stage), then AI (`lead_stage_classify`, prompt `lead-autopilot-classify-v1`, evidence refs must quote real messages/calls). `brand_config.lead_autopilot.mode` = `suggest` (DEFAULT: stored as a suggestion, shown as the lead page's Apply card) | `autopilot` (rules + AI >= `ai_threshold` 0.85 with valid evidence applied via `update_stage_by_id`, audited `lead_autopilot.stage_moved` with evidence) | `off`. Owner-only `PUT /lead-autopilot/settings` (PATCH /tenants/me refuses the key). Guards: pinned (`inquiries.autopilot_paused_at`), never out of Sold/Lost or backwards, never auto-Lost with an open payment link or a future check-in + valid quote, an undone move is never re-applied, AI never applies Sold. `POST /leads/{id}/autopilot/undo|pin` (leads.write); `inquiry_service.revert_automatic_move`; `_notify_stage_hooks` in BOTH transition paths supersedes open decisions. Runs: end of `wrap_up` + `generate_ai_summary` (message debounce) -> `lead_autopilot.evaluate_inquiry`; beat `lead_autopilot.sweep_all_tenants` 07:45 IST (rules only). Lost taxonomy price/dates/no_response/booked_elsewhere/not_suitable/other maps onto the `LostReason` column. Lead list: `?autopilot=moved` + `autopilot_move` badge. The older `lead_recommendation_service` (call-only) shows only when the autopilot has no suggestion.
- **Actionable AI** (`services/ai_actionable.py`, one cleaner): next_best_action {action, owner, channel, deadline, why}, blocking_objection + counter, missed_revenue (`est_inr` only when grounded in a stated figure), temperature + reason, haip_updates. In `inquiries.ai_analysis` (summary v8), `calls.ai_insights` [144] (wrap_up v5 + outcome/decline_reason/decline_quote; judge v3 grounds missed revenue), daily briefing v2 `actions` (cached, not rendered anywhere yet). UI: `components/ai/ActionableInsights.tsx` (lead AI card + tab, call page), `components/leads/AutopilotPanel.tsx`, `/dashboard/settings/lead-autopilot`.
  Chat-extracted trip fields can be re-stated by later messages; `quoted_amount` stays write-once. Missed-call callback reminders.
- **WhatsApp**: template editor + Meta sync, campaigns (schedule, CSV import, CRM audiences, reports), health check, overview dashboard.
  **Instagram**: per-channel verify tokens (never shown in page), hourly alert if message access is off, referral-only events handled.
  **Personal WhatsApp bridge** (`bridge/whatsapp-personal`, Go/whatsmeow, unofficial, READ-ONLY; egress via `WHATSAPP_PROXY_URL` = a residential SOCKS proxy, else WhatsApp removes the device): WhatsApp-Web-style mirror (`mirror.go` + `whatsapp_personal_service.ingest_chat_message`): guest messages, the agent's own replies (outbound), groups (conversation keyed by `channel_conversation_id` = chat JID, guest = `channel_thread_id` signal, `Message.sender_name` per member), photos/video/voice/docs/stickers (bridge downloads, HAIP stores in Cloudflare R2 via `media_storage.upload_personal_whatsapp_media`, ≤16 MB, presigned on read) and recent history (`/history`, 30 days, 200/chat, text only). ONLY a live 1:1 guest message with a phone makes a lead; mirrored chats are guests with NO phone signal (`ai_mode=off`, no push/summary) but show their number + saved name on the guest row (`fill_mirror_identity`; the bridge resolves @lid ids via whatsmeow's lid map; `scripts/backfill_personal_whatsapp_numbers.py` fixes already-imported chats from the bridge DB), promoted to a lead when that person writes live. A guest may have only ONE open WhatsApp conversation (unique index `ix_conversations_one_open_per_guest_channel`): ingest and the backfill reuse/merge into a known lead's open thread, never create a second. The QR channel MUST use `context.Background()`, never the HTTP request ctx (it killed the socket 0.4s after the QR showed: "Couldn't link device"). Debug: `docker logs haip_whatsapp_bridge`. **Never answered from the official number** (Oct 19): a `Conversation.source == "personal_bridge"` thread (`Conversation.is_personal_bridge`) gets no concierge draft (`concierge_draft_refused_personal_bridge`), no reply-recovery requeue (it also skips any guest message whose `channel_metadata.source` is `personal_bridge`, even in an official thread), inbox send/send-template/retry/approve/ai-draft = 409 `personal_bridge_read_only` (internal notes still allowed). Booking/quote/invoice messages (`wa_booking_messages`, `quote_send_service`) are deliberate official sends and still go out. When the guest then writes to the official number the webhook reuses that thread and clears `source` (`wa_personal_bridge_thread_became_official`), so it becomes answerable. Tests: `tests/test_personal_bridge_read_only.py`.
- **Reply safety net**: `concierge.recover_missed_replies` (beat every 10 min, queue `whatsapp`, `workers/tasks/reply_recovery.py`) re-queues `concierge_draft` for a guest message 4 min–6 h old with no outbound after it (once/hour/message, ≤25/tenant). `scripts/diagnose_bot_replies.py` (read-only) explains why a guest got no reply: mode, drafts by outcome, held-back reasons, Meta delivery errors.
- **Integration health**: one rule (`integration_health.py`) for the bar, insights and Integrations page.
- **Vobiz outbound answered?** The session recording starts when the AGENT picks up, so an outbound call's duration includes the guest's ringing (29 of 63 Ratha outbound calls were no-answer, only 2 had duration 0). The click-to-call guest `<Dial>` posts its `DialStatus` to `/webhooks/vobiz/.../outbound-dial-status` (cache only, never touches agent attribution); `ingest_call` stores it in `ivr_dial_status`, so the callback reminder works and an unanswered callback does not mark the missed inbound call recovered.
- **AI reliability (mAI3, Oct 2026) [123]**: inventory + gaps `docs/ai/AI_FEATURE_MATRIX.md`; sales-agent roadmap `docs/ai/SALES_AGENT_*.md` (proposal only, nothing built). **KB**: ONE
  retrieval path, `knowledge_service.search_detailed`; an entry is used only if active + approved + indexed + not `stale_since` + in scope; an edit makes it `pending`
  (unused) until re-indexed; beat `knowledge.sweep_all_tenants` retries (cap 6); a failed lookup is never reported as "no answer". **Concierge facts** (`concierge_facts.py`):
  property records, the conversation guest's OWN bookings, availability WITH reasons; guards block "available" when nothing is open and any price that is not an exact
  live figure; KB text has prices stripped. **Pricing is a TENANT policy**: `brand_config.price_disclosure` = `handoff` (default; Ratha: never a price in chat) | `grounded`.
  Summary `leads360-summary-v8` (updates the previous one, ignores unsent drafts, booking state computed). `send_whatsapp*` never resend a SENT message.
  **Ratha business data** (`business_records`, migration 124; `docs/ai/RATHA_KB_EVOLUTION.md`): versioned typed records (package, destination, itinerary, reseller/discount/stay/payment/cancellation policy);
  draft → publish → superseded, immutable once published, rollback = new version, effective-dated, audited. Guest-facing code reads ONLY `business_data_service.get_effective` (never drafts). Package prices: `package_pricing_service.quote` (refuses, never guesses; availability via `calculator_service`); `quote_service.issue_quote` snapshots amounts + record versions in `inquiry_quotes` [125], so a later price change never alters an issued quote. The AI reads this data ONLY via `sales_gateway` (read-only: `list_packages/get_package/get_destination/get_itinerary/quote_package/policy_check`, each returns data + sources + flags; `concierge_business_facts` feeds the concierge; prompt `concierge-reply-v15` (sales step + guardrails; snippets carry their date, published records > newer snippet > older, RECENT CONVERSATION may be out of date)). Payment/cancellation terms reach the prompt only in `grounded` price mode. Every KB write (create/edit/delete/reindex/upload/crawl) appends a chained `kb.*` audit row with before/after values (`knowledge_service.audit_change`). `GET /knowledge/{id}/history` + `POST /knowledge/{id}/rollback` undo an edit via that trail (normal edit path: re-indexed before use). `POST /knowledge/test` (`kb_test_service`, `settings.manage`) runs the same retrieval + gateway calls as a reply and returns sources/versions/flags. UI: KB page has two tabs (`dashboard/settings/knowledge`: Knowledge & Training | Structured Business Data); typed editors are spec-driven (`components/knowledge/businessDataSpecs.ts` mirrors `schemas/business_data.py` — change both together). `POST /business-data/import-existing` drafts packages/destinations from RatePlan/SeasonalRate/Property.routes (drafts only; never overwrites).
  **Knowledge sources + freshness (Oct 18)** [143]: `knowledge_sources.py` reads Instagram posts/reels (existing `instagram` integration token, `list_media_page`, graph.instagram.com, cursor paging) and RUNNING ads' creative title/body (`ad_entities`, never the ad name) into KB entries `source` instagram/meta_ad, `source_ref` ig:/ad:<id>, `source_published_at`, `content_flags` (mentions_price/offer); idempotent upsert, deleted post / stopped ad -> `stale_since`, one `kb.ingested` audit per run, state in `integration.config.kb_sync`. Settings `brand_config.knowledge`: `social_sync` (default on; entries arrive pending), `auto_approve_social` (default OFF; a price-quoting post always waits), `website_recrawl` (default OFF; weekly re-read of imported pages via the SSRF-guarded fetcher). Celery `knowledge_sources.sync_all_tenants|sync_tenant` (beat 4h) and `recrawl_all_tenants|recrawl_tenant` (Sun 03:47 IST), queue ai_scoring. `GET /knowledge/freshness`, `POST /knowledge/refresh` (Re-index now + read Instagram; audited `kb.refresh_requested`), `PUT /knowledge/source-settings` (audited `kb.settings_updated`) -- owner/manager (`endpoints/knowledge_freshness.py`); UI `KnowledgeFreshnessPanel`, `SocialApprovalQueue`, `SourceBadge`. Retrieval ties go to the newer entry. Owner notes import: `scripts/import_ratha_kb_2026_10.py` (source owner_notes, pending only). Google Business Profile: design only, `docs/ai/GOOGLE_BUSINESS_PROFILE_KB.md`.
- **Impact view (Oct 18)** [146]: `/dashboard/impact` (owner/manager; nav Insights > Impact) + `endpoints/impact.py`: "Before HAIP" vs "With HAIP" around a go-live date (`impact_profiles.go_live_date`, owner sets it). Before = the N days before go-live, With = latest N days (default 30). Tiles = `impact_service.BASELINE_METRICS`; "before" is the OWNER-ENTERED baseline (`impact_baselines`: value, period label, source note; PUT/DELETE `/dashboard/impact/baselines/{metric}` owner only, audited `impact.baseline_*`) else what HAIP measured. Measured numbers: `impact_metrics.py` (catalogue section 14: `replies.first_response` per guest turn split by channel cloud/personal mirror/Instagram and responder ai/staff_ai_draft/staff, `replies.after_hours`, `leads.quoted_cohort`, `calls.missed_returned`, `enquiries.lost`) + the shared lead/booking/cash metrics; plain ORM, SQLite = PG. Change only vs a non-zero baseline. Money needs `revenue.read` (`{restricted:true}`). PDF `GET /dashboard/impact/export.pdf` (`impact_pdf`, aggregates only). **Case study**: owner "Publish to case study" freezes a whitelisted aggregate snapshot (`impact_case_study.public_snapshot`, no guest data, no source notes, money only if ticked) into `impact_profiles`; public `GET /api/v1/case-studies[/{slug}]` (no auth; SECURITY DEFINER `impact_published_case_study`) -> marketing `/case-studies` + `/case-studies/[slug]` (server fetch, 5 min cache), "coming soon" until published / after withdraw. Chart series tokens `--haip-series-1/2`. **Since HAIP card** (Oct 19, under Team on the owner dashboard, `SinceHaip.tsx`): `GET /dashboard/impact/since-haip` (owner/manager + analytics.read; `impact_since.py`) = leads, bookings made, bookings value, average first human reply, AI drafts sent: latest N days vs the SAME number of days before go-live (go-live = the impact profile, not brand_config), each before figure with a `source` line, empty = "No data", no change. **Reply time by source**: `message_metrics.chat_response_by_agent_source` (PG-only SQL) splits human first reply by personal WhatsApp bridge / Cloud number / Instagram, drops group chats and mirrored history (`include_history` for the card); per agent row `response_by_source` in the business-overview `agents` block.
- **Meta Ads + Marketing page** [115, 116] — see "META ADS / MARKETING" below.
- **Quote builder** [140] (API only now; Routes/Packages/WhatsApp-messages tabs moved to `/dashboard/settings/quotes`, owner/manager). `endpoints/quotes.py` (NO module gate) + `quote_builder_service.py`: `GET /quotes/catalog` (effective packages/routes + pending drafts, kits, reseller terms, vehicles, permissions), `GET /quotes/leads?q=` (picker, /leads visibility), `POST /quotes/preview` (no writes; may price a DRAFT route/package, flagged `uses_drafts`), `POST /quotes` (re-prices from PUBLISHED records only; `quote_service.issue_options` = primary rank 1 + fallback rank 2 sharing `option_group_id`; snapshot `meta` = overnight-stay check; next step = the lead's follow-up Task, not a new field), `GET /quotes?inquiry_id=`, `GET /quotes/{id}`. Prices: `package_pricing_rules.py` (billed days `calendar`|`noon_to_noon`, route km = stop distances + chosen `sights`, extra-km fixed or a range the agent picks with a suggested ladder (applied rate stored), rate `level`s, extra hours, `kits_included`, `at_actuals` lines outside the total, reseller tier commission range / min days / min billing); every rule is a typed refusal with a `fix`. New schema fields are optional and stored only when used (`canonical` prunes them), so older records and the AI path are unchanged. Caps `quotes.write` (owner, manager, reservations, concierge), `business_data.draft` (owner, manager, reservations) / `business_data.publish` (owner, manager) on `/business-data` for destination/package/itinerary only (policies stay `settings.manage`); four eyes: whoever drafted or edited a version may not publish it unless owner. **Send + pay (Oct 18)**: `POST /quotes/{id}/send` (`quotes.write`, `quote_send_service`) = a Razorpay link PER OPTION for its own advance (notes `haip_tenant_id`/`haip_inquiry_quote_id`, expires with the quote, live links reused) + Celery `quotes.send_with_links` (queue whatsapp): PDF (`quote_pdf.py`, key on the primary's `pdf_url`) + `ratha_quote_payment_v1` via `wa_booking_messages.send_guest_template` (shared with bookings; key `qt:{group}:sent:{link}`); its body has no fallback slot, so the fallback link goes as ONE plain text only while the 24h window is open (else audit `quote.fallback_link_not_sent`, staff copy it). Typed refusals: `quote_not_valid` 409, `stay_not_confirmed`, `no_phone`, `razorpay_not_connected`, `no_advance` 422; template not approved = links made, `message.status=not_sent`. Paid quote link (`quote_payment_service`, in the webhook): quote's vehicle (else first free) still free -> claim the group with guarded UPDATEs (accepted / other withdrawn) -> `booking_service.create_booking` (the POST /bookings path, lead -> closed-won) with total = quote total, StayPayment on the pay id -> `invoices.after_payment` + `quotes.cancel_payment_links`; not free / already booked / not bookable -> NO booking, high-priority Task, staff decide (no auto refund). `GET /quotes/{id}` adds `payment_link`, `send` (journey, `quote_journey.py`), `send_readiness`; the list adds `payment_link`; catalog `send_setup`; lead `quote_history` has link status. The builder's UI was replaced by the rate calculator (below); its endpoints stay for the AI sales agent. `/calculator/share` now awaits the async WhatsApp adapter with `body=` (it never sent).
- **Rate calculator (Oct 19)** [148] (`/dashboard/quotes` + the "Send quote" sheet): ONE component `components/quotes/calc/QuoteCalculator.tsx`, inline on the page and in `QuoteSheetProvider` (mounted in `dashboard/layout.tsx`; `useQuoteSheet().open({inquiryId|guestId|conversationId|callId|phone, from})`; kit Drawer 1100px, full screen on phones). `SendQuoteButton` (quotes.write roles, caravan workspaces) on: Inbox header + guest panel, inbox call card, call detail panel/page, Calls rows, My day rows, Home "Waiting for you" (also on /dashboard/operations) + Today strip, Leads360 card + lead page. API `endpoints/quote_calculator.py` (`/quote-calculator/*`, all `quotes.write`, tenant + /leads visibility): `setup`, `price` (no writes), `quotes` (save + action send|copy|save), `quotes/{id}`, `/share`, `/approve` (owner/manager, no self-approval except owner, guarded UPDATE, audited `quote.approved`), `leads` GET (picker: open first; `add` offer for an unknown number) / POST (Add as new lead), `context` (prefill from lead/chat/call: `haip_updates` / number), `settings` GET/PUT (`brand_config.quotes`, owner/manager). Pricing ONLY in `services/rate_calculator.py` (server numbers are what is saved/sent; page shows them, debounced): fixed package (published only, by route, levels = `key::level`, ₹0 packages hidden and counted, drafts counted + "Publish" link) or custom trip (the tenant's day-rate package terms: rate/day, km over included/day at a chosen rate, extra guests); add-on units one_time|per_day|per_guest|per_guest_day; discount % on everything; GST slab 0/5/18/40/other, inclusive (GST inside) or on top; "Your price" override in the same basis, > `approval_threshold_percent` (default 10) below suggested or a discount > max by a non owner/manager = `inquiry_quotes.status = pending_approval` + owner task + push, unshareable until approved; advance % of the final total. Defaults: `quote_calc_catalog.settings` (brand_config.quotes, else invoice GST rate, else 18 / inclusive; advance from payment policy else 50; valid 3 days). Snapshot `kind=calculator` (PackageQuote-compatible keys + every input, override + reason + suggested total) via `quote_service.issue_calculated`. Send: 24h window open = the EXACT preview text as plain WhatsApp (`quote_send_service._send_text`), else `ratha_quote_payment_v1` via `quote_tasks.send_with_links` (needs the link + approved template; otherwise saved, not sent, with the reason). Copy and Send both record `shared_via` and move a not-engaged lead (invalid category or the valid-lead entry stage) forward to `active` via `update_stage_by_id` (legacy enum: `update_stage`), never a valid/won/lost one; follow-up task = validity end. Leads: `quote_calc_leads` (closed lead = new lead for the trip at save; `identity_service.find_person_by_phone`/`resolve_person_by_phone` reuse a guest known only by `guests.phone`; `inquiry_service.create_lead_for_guest`). Card/timeline: `lead_quote_view` (`latest_quote` on cards, `quote` timeline entries). Paid calculator quote -> booking notes the tax; `invoice_service.quote_gst_rate` makes its invoice use the quote's GST rate. One-off `scripts/route_packages.py --tenant-slug X [--apply [--publish]]` (dry run default) merges vehicle-based package drafts (Black/White) into route packages.
- **AI sales agent (Oct 18)** [142] (`docs/ai/SALES_AGENT_*.md`): owner-only switches in `brand_config`, changed ONLY via `PUT /ai/sales-agent` (audited `ai.sales_settings_changed`; `PATCH /tenants/me` refuses them; UI Settings > AI `SalesAgentSettingsCard`): `price_disclosure` handoff (default)|grounded and `sales_agent.mode` off (default = today's concierge, nothing runs)|suggest|autopilot (`sales_agent_settings.py`). Per message, inside `concierge_draft` (never a request handler): `sales_requirement.assemble` (this turn's extracted details + the lead's fields; no extractor of its own; plan/route matched on PUBLISHED records; handoff for b2b/discount/custom route) -> `caravan_availability.check` (THE availability answer: `booking_service.find_conflicts` per vehicle = confirmed stays, every block incl. iCal/maintenance, shared-vehicle pool; noon to noon; nearest free dates; never the Unassigned placeholder) replaces the dated calculator fact -> in grounded mode `sales_gateway.quote_package_detailed` (published only; refusal = handoff task) -> `quote_service.issue_options` on the lead (never replaces a staff-issued quote; one per lead per 24 h per requirement) -> `SalesAction` (`sales_actions`: pending for staff, bound to that quote). Autopilot sends only when every hold clears (`_holds`: overnight stay needs `auto_bookable` on the package/destination schema, `quote_send_service.readiness`, template approved, guest not asking for a person, guest has not said STOP = withdrawn marketing consent) AND the reply itself auto-sent: guarded pending->sending, Celery `sales_agent.send_quote` (queue whatsapp) -> `quote_send_service.send_as_agent` (actor NULL + `payload.actor=ai_sales_agent`); failure = staff task. Payment -> booking -> invoice stays `quote_payment_service`. Staff: `GET /sales-actions?inquiry_id|conversation_id` (leads.read/quotes.write), `POST /sales-actions/{id}/approve|reject` (quotes.write, guarded, audited) -> `SalesActionCard` in the inbox thread + lead page. Guards (sales mode only, `sales_agent_service.check_reply` + concierge): no booked/confirmed before payment, no discount offer, no link, no "sent" claim the system did not make, no "available" without a calendar check. In grounded mode with published packages the only figures left are the package engine's (`merge_facts`). Prompt `concierge-reply-v15` (SALES STEP block, merged with the current-data-wins rules).
- **UI: Hospitality Hybrid** (Oct 17, replaced teal/navy sidebar): see UI RULES below; concept lab `/design-lab` (dev only).

Active clients:
- Ratha (luxury caravan) — Vobiz IVR, WhatsApp live (migration `064`: moved CallerDesk → Mcube → Vobiz-only;
  Mcube's Integration row is disconnected, not deleted)
- Jade (pool villas, Bangalore) — Acefone IVR, onboarding

---

## TECH STACK — LOCKED, DO NOT SUGGEST ALTERNATIVES

| Layer | Decision |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Frontend | Next.js 16 App Router |
| Database | PostgreSQL 16 + pgvector + RLS |
| Queue | Celery + Redis |
| Storage | AWS S3 + KMS (Mumbai ap-south-1) |
| Transcription | Provider chosen by `TRANSCRIPTION_PROVIDER` or by which key is set (Sarvam, then Groq, then Deepgram, else local Whisper). **No runtime failover**: a failed call only retries the same provider (5×, backoff). Sarvam model = `SARVAM_STT_MODEL` (default `saaras:v3` translate job; `saaras:v4` = plain job in translate mode + `SARVAM_KEYTERMS`, opt-in after `scripts/compare_sarvam_models.py` on a real call); SDK `sarvamai==0.1.33` |
| LLM | Router pattern — see LLM routing table below |
| Auth | NextAuth.js + JWT (15m) + refresh token |
| IVR | Vobiz (Ratha) + Acefone (Jade) — CallerDesk/Mcube adapters still exist in code (historical Ratha providers, not currently active for any tenant) |
| WhatsApp | Meta Cloud API via client's own WABA credentials |
| Region | AWS Mumbai ap-south-1 |

---

## LLM ROUTING TABLE — ALWAYS USE ROUTER, NEVER IMPORT DIRECTLY

Routing is **NVIDIA NIM-first**, except `concierge_draft` (guest replies): **Gemini `gemini-3.6-flash`** again since 2026-10-16.
It detoured to NVIDIA `openai/gpt-oss-20b` 2026-09-27 → 10-16 because the Gemini billing balance went negative and Google refused
every call (guests got only the holding reply). If that recurs, reroute `_TASK_ROUTES["concierge_draft"]` + `tests/adapters/test_llm_routing.py`
back to NVIDIA. Its NVIDIA time bound is 45s (Gemini 40s). No Claude in the live table; `openai/gpt-oss-20b` runs on `NVIDIA_API_KEY`.

**Gemini fallback** (`adapters/llm/fallback.py`): internal-analysis tasks (`call_analysis`,
`call_scoring`, `lead_summary`, `daily_briefing`, `quick_classify`, `lead_stage_classify`, `agent_*`, `deep_reason`, `assessment_narrative`)
run on NVIDIA with a 30–120s limit and retry once on Gemini on error/timeout (needs
`GEMINI_API_KEY`; without it, unchanged). Tradeoff: transcripts can reach Google during NVIDIA
outages. A negative Gemini balance also disables this fallback.

Task keys below are the exact strings accepted by `get_llm(task)` — verified against
`_TASK_ROUTES` in `backend/app/adapters/llm/__init__.py`. That dict is the source of
truth; if this table and the code disagree, the code wins and this table is stale.

| Task key | Provider | Model |
|---|---|---|
| `call_analysis` · `call_scoring` | NVIDIA | openai/gpt-oss-20b |
| `lead_summary` | NVIDIA | openai/gpt-oss-20b |
| `ruflo_domain` · `ruflo_synthesis` | NVIDIA | openai/gpt-oss-20b |
| `agent_performance_narrative` · `agent_leads_feedback` · `daily_briefing` | NVIDIA | openai/gpt-oss-20b |
| `ask_haip_rca` | NVIDIA | nvidia/nemotron-3-ultra-550b-a55b |
| `ask_haip_freeform_sql` | NVIDIA | nvidia/nemotron-3-ultra-550b-a55b |
| `deep_reason` · `report_gen` | NVIDIA | nvidia/nemotron-3-ultra-550b-a55b |
| `ask_haip_intent` | NVIDIA | openai/gpt-oss-20b |
| `ask_haip_freeform_summary` | NVIDIA | openai/gpt-oss-20b |
| `quick_classify` · `bulk_batch` | NVIDIA | openai/gpt-oss-20b |
| `lead_stage_classify` (lead autopilot) | NVIDIA (+Gemini fallback) | openai/gpt-oss-20b |
| `concierge_rewrite` | NVIDIA | openai/gpt-oss-20b |
| `fallback` | NVIDIA | mistralai/mistral-nemotron |
| `concierge_draft` | Gemini | gemini-3.6-flash |
| `assessment_narrative` | NVIDIA (+Gemini fallback) | openai/gpt-oss-20b |

Unknown task keys route to `fallback` (they previously defaulted to Claude,
which fails in prod — no `ANTHROPIC_API_KEY` is provisioned there).

⚠️ **NIM models reach end-of-life and return HTTP 410.** Dead: `mistral-medium-3.5-128b` (08-07), `meta/llama-3.1-8b-instruct` +
`nvidia/llama-3.3-nemotron-super-49b-v1.5` (08-26, broke classify/judge/summaries/briefing until 08-30). `gpt-oss-120b` (100s+, 504s) and
`deepseek-v4-flash-0731` (504 outage) failed as mid tier, so mid tier = `openai/gpt-oss-20b` (a capability step-down accepted for
reliability). Revisit bigger models with a direct trivial-prompt call, not just `/v1/models`.
- **Fix any call site that hardcodes `model=`** on `.complete()`: an explicit kwarg always beats the
  routed default (see `_build_adapter` docstring in `adapters/llm/__init__.py`).
- Verify a model serves before routing to it: `GET https://integrate.api.nvidia.com/v1/models`.
- `mistral-nemotron` answers tool-call prompts in prose; route structured output to `gpt-oss-20b`
  or the 49B/ultra models. `kimi-k3` and `gpt-oss-120b` tool-call correctly but cold-start 90s+.

Per-tenant override: `tenants.llm_provider_override` (cached 300s) is NOT applied today: no `get_llm` caller passes `tenant_id` (and an override would also drop the routed model). Check a tenant's real route with `GET /ai/routing` (owner) or `scripts/diagnose_llm_routing.py --tenant-slug` (keys present/absent only).

All AI calls go through `backend/app/adapters/llm/` router.
Never import provider clients directly in services.

---

## IDENTITY ARCHITECTURE — CRITICAL

**GID (HAIP Guest ID) is the canonical identity — a system-generated UUID.**

Phone is one signal among many. It may never exist (Instagram-only guests are valid).
Identity lives in the `guest_identities` table (migration 022).
Dedup threshold: composite confidence **≥ 0.85** → auto-merge into single GID.

**The only place for GID resolution is `backend/app/services/identity_service.py`.**
Never resolve guest identity directly in endpoints or other services.

| Method | Purpose |
|---|---|
| `add_signal()` | Add one signal; auto-writes DPDP consent for phone/email |
| `resolve_gid()` | Resolve-or-create from an inbound signal |
| `merge_guests()` | Merge two GIDs; idempotent |
| `get_confidence_score()` | Max confidence across all signals for a guest |

Signal confidence weights (`CONFIDENCE_WEIGHTS` in `models/guest_identity.py`):
booking_id 0.95 · phone 0.90 · WA 0.85 · ota_guest_id 0.85 · channel_thread_id 0.80 · call_record_id 0.80 · email 0.75 · IG 0.70

See: `architecture-delta.md` → MODIFICATION 1

---

## CORE DATA THREAD — NEVER BREAK

```
Inquiry → Conversation → Booking → Stay → Revenue
```

Every entity must trace back through this thread.
Every table must have tenant_id.

---

## MULTI-TENANCY — NON-NEGOTIABLE

- Every table has tenant_id
- RLS policy on every tenant-scoped table
- Every new table needs: migration + RLS + tenant_id column
- Weekly cross-tenant breach simulation test; per-tenant KMS encryption for credentials

---

## ACTIVE MODULES (BUILD THESE)

- Unified Inbox (WhatsApp + Instagram DM + post-call wrap-ups)
- AI Call Intelligence (transcript + QA + missed-revenue flags)
- **Leads360** — unified sales pipeline CRM ✓ COMPLETE (M4)
- AI Concierge (shadow → autonomous on WhatsApp)
- Auto-QA (100% call coverage)
- Owner Daily dashboard
- Personal scorecard (per concierge)
- After-call wrap-up card
- Compliance Center (DPDP, audit, deletion)
- Bookings + payments (Razorpay), invoices + booking WhatsApp messages, iCal feeds, public API + webhooks, work queue (see Current Milestone)
- **Marketing** — Meta ads spend/metrics joined to leads, bookings and revenue (see below)

## META ADS / MARKETING (Oct 2026)

- Reads only. Reuses the WhatsApp System User token (needs `ads_read`); Graph v20.0, host pinned
  to `graph.facebook.com` including `paging.next`. Integration `kind="meta_ads"`, ad account chosen
  on the Marketing page (`PUT /marketing/ads/account`; the token must have the account assigned to
  its system user in Meta Business Settings or `/accounts` is empty).
- Tables: `ad_metrics` (daily per ad: spend, impressions, clicks, link/unique clicks, CPC,
  engagements, video views, first replies, chats started, raw `actions` JSON) [115, 116] and
  `ad_entities` (campaign/ad set/ad status, objective, budget, dates, creative, targeting) [116].
- Code: `adapters/marketing/meta_ads.py`, `services/meta_ads_service.py`
  (`sync` = last 7 days, `backfill` = months in 30-day chunks, up to 36, state in
  `integration.config["backfill"]`, stops on rate limit/token rejection and can resume),
  Celery `meta_ads.sync_tenant` / `meta_ads.backfill_tenant` (queue `whatsapp`, exact-name routes
  required by `tests/test_celery_task_routing.py`), endpoints in `endpoints/meta_ads.py`
  (`/marketing/ads/{status,summary,sync,backfill,accounts,account}`, owner/manager).
- Attribution: `lead_attribution` links ad_id → campaign → inquiry → Stay revenue (cancelled stays
  excluded); a conversation fallback finds the lead. ROAS = revenue ÷ spend; `attribution_gap` =
  Meta chats − HAIP-traced chats (leads/revenue shown are a floor).
- Instagram sends the ad referral as its own `messaging_referral` event; HAIP records it
  (`process_instagram_referral.py`, `_handle_referral_event`). **Meta app must be subscribed to
  `messaging_referral`** or attribution stays near zero. Past chats cannot be attributed later.
- Token expiry: `meta_token_expiry.py` + `check_meta_credentials.py` warn owners/managers by email
  (once per 24h) before the Meta token expires. Prod token expires **2026-11-24** — replace with a
  never-expiring System User token (keep `ads_read`, `business_management`, WhatsApp scopes).
- Prod DB pool is capped via `DB_POOL_SIZE=3` / `DB_MAX_OVERFLOW=2` in `backend/.env` after
  Supabase `EMAXCONNSESSION`; prod uses `create_all` at startup, so migrations must be idempotent
  (`IF NOT EXISTS`, guarded RLS policy).

## FUTURE MODULES — ARCHITECT FOR, DO NOT BUILD

- Predictive (no-show / cancellation risk)
- Two-way Google Calendar sync of bookings (plan drafted, not built)
- Marketing channels beyond Meta ads (Google Ads, ROAS by other sources)
- Voice of Guest thematic analysis
- Multi-region tenancy
- BYOK (customer-managed KMS)
- White-label
- Vendor marketplace
- Travel agent portal
- Channel manager (direct, beyond Hostaway sync)

---

## FILE CREATION ORDER — ALWAYS FOLLOW THIS SEQUENCE

1. Pydantic schema → `backend/app/schemas/`
2. SQLAlchemy model → `backend/app/models/`
3. Alembic migration → with RLS policy
4. Service → `backend/app/services/`
5. Endpoint → `backend/app/api/v1/endpoints/`
6. Worker task → `backend/app/workers/tasks/` (if async)
7. Tests
8. Frontend types → regenerate from OpenAPI (`npm run gen:api`)
9. Frontend page/component

---

## KEY SERVICES — LEADS360 (M4)

| Service | Path | Rule |
|---|---|---|
| Identity resolution | `services/identity_service.py` | Only place for GID ops — not guest_service.py |
| Pipeline query | `services/leads_service.py` | 1 inquiry = 1 card; joinedload prevents N+1 |
| AI summary | `workers/tasks/generate_ai_summary.py` | Always async — never LLM inline in endpoints |

**AI summary triggers:** inquiry created, `call.analyzed`, `POST /leads/{id}/refresh-summary` → immediate; message → 10-min Redis debounce per inquiry (`SUMMARY_DEBOUNCE_TTL`, one trailing catch-up run). Every successful run queues the lead autopilot.

## DATA MODEL — LEADS360

**`inquiries.source`** (15 values, per `InquirySource` in `backend/app/models/inquiry.py`):
`WEBSITE` · `GOOGLE` · `META_IG` · `META_FB` · `CLICK_TO_WA` · `WA_DIRECT` · `EMAIL` · `PHONE` · `WALK_IN` · `REFERRAL` · `TRAVEL_AGENT` · `OTA_AIRBNB` · `OTA_BOOKING` · `OTA_VRBO` · `CHANNEL_MANAGER`

**Pipeline stages are a tenant-owned catalog, NOT a hardcoded enum** (migrations `043`, `049`).

`pipeline_stages` (`backend/app/models/pipeline_stage.py`) is a per-tenant table — tenants
add/remove/reorder their own stages, same tenant-scoped-catalog pattern as
`modules`/`workspace_modules` (migration 031). Default taxonomy seeded for every tenant:

| key | label | category |
|---|---|---|
| `unqualified` · `general_enquiry` | Unqualified · General Enquiry | invalid *(default entry, no phone)* · valid *(valid-lead entry, has a phone; migration 062)* |
| `rnr` · `active` | RNR · Active | invalid · valid |
| `unsuitable` | Unsuitable | valid |
| `lost` | Lost | valid *(closed-lost)* |
| `sold` | Sold | valid *(closed-won)* |
| `collaboration_engagement` | Collaboration Engagement | marketing *(collab entry)* |

`category` drives lead counting: **only `valid` stages count as real leads** in dashboards
and metrics — `invalid` and `marketing` do not. Three "landing zone" flags mark where a
freshly auto-created inquiry lands, each at most one TRUE per tenant:
`is_default_entry` · `is_valid_lead_entry` · `is_collab_entry`.
Plus `is_closed_won` / `is_closed_lost` for funnel terminal states.

⚠️ **Two stage columns coexist during cutover.** `inquiries.stage_id` (FK → `pipeline_stages`)
is the new path; the legacy `inquiries.stage` enum is retained until every call site is
migrated, then dropped. Correspondingly there are **two transition code paths in
`inquiry_service.py`** — legacy `update_stage`/`_apply_stage` and the new
`update_stage_by_id`/`_apply_stage_by_id`. **Anything that hooks stage transitions must
hook both**, or transitions through the new path are silently missed.

The old `NEW → RESPONDING → QUOTED → SITE_VISIT_* → BOOKED → LOST` flow was replaced
wholesale by migration `049` — do not write new code against it.

**Indexes** (migration `023_leads360_enum_extensions_indexes.py`):
- `ix_inquiries_tenant_id_stage`
- `ix_inquiries_tenant_id_source`
- `ix_inquiries_tenant_id_assigned_to`
- `ix_guest_identities_tenant_id_guest_id`

## CODING RULES — ALWAYS

- Multi-tenant by default — every row has tenant_id
- API-first — no UI before backend contract is defined
- No hardcoded secrets — environment variables only
- Webhook idempotency — dedup every incoming webhook
- Fail loudly — no silent failures, log everything
- No new dependencies without justification in PR
- No refactors unless explicitly asked
- No new tables without migration + RLS + tenant_id
- Prompt version bump on every prompt content change
- **Never call LLM inline in a request handler** — use `generate_ai_summary` Celery task
- **One inquiry = one Leads360 card** — a guest with 2 inquiries = 2 cards in pipeline
- **`identity_service` is the only place for GID resolution** — never in endpoints or other services
- **Profile completeness uses active signal types only** — exclude FUTURE signals (`website_session_id`, `device_fingerprint`)

## PERFORMANCE REQUIREMENTS

- `GET /api/v1/leads` must respond in **< 200ms**
- Use `joinedload` for guest, inquiry, assigned_user — prevent N+1 on leads list
- Batch-fetch `guest_identities` for all guest_ids per page in one query
- Timeline capped at **50 entries** for V1; return `timeline_capped: true` in metadata
- AI summary reads from `inquiries.ai_summary` (DB) in all list and detail endpoints — no LLM calls

---

## TESTING REQUIREMENTS — EVERY PR

- New service function: 1 happy path + 1 tenant-isolation test
- New endpoint: 1 happy path + 1 forbidden (wrong role) + 1 cross-tenant
- New adapter: webhook signature verification + payload fixture test

---

## DEFINITION OF DONE — EVERY PR

- [ ] Tests added and green
- [ ] Alembic migration present if schema changed
- [ ] RLS policy added if table is tenant-scoped
- [ ] Audit event written if destructive or permission-sensitive
- [ ] Prompt version bumped if prompt content changed
- [ ] No new dependency without 1-line justification

---

## SECURITY — NON-NEGOTIABLE

- No bypass tokens (demo/owner-bypass removed)
  Fully removed from `frontend/src/lib/auth.ts` (Sept 2026): no hardcoded credentials, in any environment. Sign-in only succeeds if the backend accepts it. `backend/scripts/seed_ratha.py` still seeds users with a fixed demo password -- change those passwords on any environment it has run against.
- No dev fallback encryption keys
- Per-tenant webhook secrets (not global shared secret)
- SSRF protection on all external URL fetches
- PII never logged in plaintext — hash phone numbers in logs (`_phone_token()`)
- WhatsApp verify token uses `secrets.compare_digest` not `==`
- **Agent-added phone/email signals**: auto-write `Consent` row with `consent_source="agent_manual"`, `collected_by=user_id`, `collected_at=now`, `signal_type=type` (handled in `identity_service.add_signal()`)

---

## AUTH & IAM — PHASE 0 (July 2026)

Backend auth is custom JWT (HS256) via `backend/app/api/v1/endpoints/auth.py` — **not** Supabase Auth (evaluated, explicitly declined; see below). NextAuth v5 on the frontend (`frontend/src/lib/auth.ts`) is a thin client that exchanges credentials for these backend tokens — never trusts its own session data for authorization. **What changed this phase (all live, verified against Supabase prod schema):**
- **MFA (TOTP) is now enforced at login** — previously `is_mfa_enabled` was set by `/mfa/setup`+`/mfa/verify` but never checked in `login()`. Now: password-verified + MFA-enabled accounts get a short-lived `mfa_challenge` token (`create_mfa_challenge_token()`, 5min, distinct `type` claim so `get_current_user()` rejects it as a real access token) instead of full tokens; client completes `/auth/mfa/verify` to finish. Frontend: login page has a dedicated MFA code-entry step; `auth.ts`'s `authorize()` gained a `preAuthAccessToken`/`preAuthRefreshToken` branch for any flow (MFA, WhatsApp OTP) that already obtained real tokens directly from the backend before touching NextAuth.
- **Rate limiter path bug fixed** — strict tier was configured for `/auth/password/reset`, but the real endpoints are `/auth/forgot-password` and `/auth/reset-password`; they were silently falling through to the 60/min unauthenticated tier. Fixed in `backend/app/middleware/rate_limit.py`. **DPDP signup consent now persisted** — `users.consent_transactional/marketing/analytics/consent_recorded_at` columns added (migration `034`); previously the register form sent these fields but `RegisterRequest` didn't declare them, so Pydantic silently dropped them. **`user_invitations.expires_at` is now `TIMESTAMPTZ`**, not a fragile ISO string column (migration `034`). Compare directly (`datetime.now(timezone.utc) > invitation.expires_at`) — no more `.fromisoformat()`/`.replace("Z", ...)` parsing.
- **Module/flag entitlement now fails closed**, not open. `get_workspace_context()` in `deps.py` used to grant every workspace with zero `workspace_modules` rows full access (meant to survive the migration-031 backfill window, but the backfill never actually ran for any pre-existing tenant). Migration `035` backfilled real rows for every existing tenant; every new tenant now gets provisioned via `workspace_context.provision_default_modules()` (called from `/auth/register`) so no workspace is ever left at zero rows. A zero-row workspace today is treated as a genuine anomaly and gets **no** module access, logged as `workspace_unprovisioned` (ERROR level).
- **Google Sign-In was built, then explicitly reverted** at the user's request — do not re-add without being asked. If revisited: `User.google_id` column already exists (unused), backend verification must independently check the ID token against Google's public keys (`google-auth`, already a transitive dep via `google-generativeai`) rather than trusting client-supplied claims, and must respect a linked account's existing MFA requirement. **Supabase Auth migration was evaluated and declined** — current backend RLS relies on `current_setting('app.tenant_id')` set per-request via `set_tenant_context()`, not `auth.uid()`. Production DB *is* Supabase-hosted Postgres (confirmed July 2026), so a future hosted-Supabase-Auth migration wouldn't require a database move — but there's no active plan to do this.
**⚠️ Alembic migration gotcha — read before touching `backend/alembic/`:** `env.py` previously ran two "best-effort" setup statements before every migration transaction (`pg_terminate_backend(...)` and `SET lock_timeout`/`SET statement_timeout`), both wrapped in a silent `except: pass`. A failed statement poisons the rest of that connection's transaction in Postgres — so every migration after it would log "success" via Alembic's step-by-step logging (which fires before each step runs) while nothing ever actually committed, and `alembic_version` would never advance. This cost real time on both Neon (`neondb_owner` lacks `pg_signal_backend` — always failed) and Supabase (session pooler rejected the `SET` calls). Both statements are now removed. **If `alembic upgrade head` ever again logs success without `alembic_version` moving, suspect a silently-swallowed exception earlier in the same transaction, not a "did it really run" mystery** — check `env.py` first.
**Testing — run what the change needs, not everything** (full suites: SQLite ~20 min, PostgreSQL ~30 min, ~3,000 tests; last full run: PG 2537 passed/1 skipped (before Phase 4), SQLite 2960/61 on feat/quote-payments, 18 Oct).
1. `cd backend && python scripts/select_tests.py` (or `--base master`, `--files ...`) reads the git diff and prints the commands: tests that import or are named after each changed module, plus frontend checks. Read its output; `--run` runs the backend list on SQLite.
2. **Frontend only** (tsx/ts/css): `cd frontend && npx tsc --noEmit --skipLibCheck` + `npx vitest related <files> --run`, then ONE browser check of the affected screen at the affected width. No backend tests.
3. **Backend, localized**: the selected test files + the module's own regression tests. Do not run the whole suite.
4. **Migration / model / auth / tenant / RLS / audit**: the selected files, then `tests/test_cross_tenant_matrix.py test_rls_postgres.py test_audit_concurrency_postgres.py test_migration_117_postgres.py test_verify_rls_isolation.py test_call_score_status.py` (the CI isolation gate), the same files on PostgreSQL, and `alembic heads` = ONE head, then upgrade a FRESH PG database, downgrade one step, upgrade again.
5. **Full SQLite AND PostgreSQL suites** only for: migration merges, a change touching >25 backend files or `conftest.py`/`requirements`/`config`/`main.py`, release checks, or when asked. Run them ONE AFTER THE OTHER, never together: SQLite uses one shared `./test.db`, so a second pytest run at the same time (even a single file) fails with `database is locked`; PG uses its own database per run (`CREATE DATABASE haip_x`, `alembic upgrade head`, `REQUIRE_POSTGRES_TESTS=1`, own Redis db index).
6. Reuse a green result only if it is from this exact commit and environment. Never rerun green tests without a reason; do not chase unrelated failures (re-run that file alone first: a failure that vanishes was contention).
Run on PostgreSQL before trusting a result (SQLite ignores foreign keys, widths, booleans, partial unique indexes; `docs/HAIP_Phase0_Failure_Register.md`). Defects awaiting a fix are strict `xfail` specs in `tests/test_increment1_defect_specs.py` (each names its PR; remove the marker in that PR). PG `db` fixture uses savepoints; on SQLite a `rollback()` in code under test erases the test's rows. pgvector SQL: `test_knowledge_pgvector_postgres.py` (PG only); SQLite uses `knowledge_service.PYTHON_VECTOR_FALLBACK`.
Frontend: `tsc --noEmit --skipLibCheck` clean, vitest green (198); ESLint cannot run (no `eslint.config.*`). `tests/test_celery_task_routing.py`: every task routes to a consumed queue, every beat entry
names a registered task; pinned exceptions (`_KNOWN_UNROUTED`, `_KNOWN_DEAD_BEAT`) may only shrink. New tasks need an exact-name route. Tests default `ENCRYPTION_KEY` in `conftest.py`.
`core/audit.py::append_audit` chains within one transaction and, on PostgreSQL, takes a per-tenant advisory lock (held until
commit, 10 s bounded wait; failures log `audit_chain_lock_failed`) and stamps `created_at` strictly increasing, so concurrent
writers form one chain. A transaction must never audit several tenants (deadlock): use one transaction per tenant.
Row-level security: `alembic/proposed/118_*` is NOT applied; check the DB role with `backend/scripts/verify_rls_isolation.py` (read-only) and `docs/HAIP_Phase0_Production_Checklist.md` before assuming RLS protects anything. Migration 117 widens
`calls.ai_score_status`; 119 grants foh `conversations.send` to existing tenants unless the owner edited that cell; 120-121 add the iCal tables; 122 adds the lead columns on `guests` + `guest_merge_events`; 123 adds
`knowledge_entries.embedding_attempts/stale_since`; 124 adds `business_records`; 125 adds quote snapshot columns; 126 adds the `organic_call` source value; 127 merges 125 and 126 (no schema change); 128 adds `ical_event_bookings.locked` when missing (prod's table pre-dated it, so 121's CREATE IF NOT EXISTS skipped it and every booking page 503'd: **a `CREATE TABLE IF NOT EXISTS` migration never repairs an existing table**); 140 (follows 128 because 129-139 belong to unmerged branches) adds `inquiry_quotes.option_rank/option_group_id` and the quote-builder capability cells (never edits an existing cell); 141 (on 140 since the quote-builder and payments branches merged) adds invoices/invoice_sequences, flags duplicate Razorpay payments then the partial unique index, and quote-owned payment links; 142 adds `sales_actions` (+RLS); 143 (on 142) adds `knowledge_entries.source_published_at/content_flags`; 144 (on 143) adds `lead_autopilot_events` (+RLS), `inquiries.autopilot_paused_at/by`, `calls.ai_insights`; 146 (on 144) adds `impact_baselines` + `impact_profiles` (+RLS). 145 (on 146) adds `platform_leads` (documented platform-level exception, no tenant_id/RLS) + `roi_benchmarks`; 148 (head, on 145; 147 is reserved by another branch) adds `inquiry_quotes.shared_via/shared_at/approved_by/approved_at`. 118 is reserved for the proposed RLS file (re-parent on the head when promoted). Roll code back with `alembic downgrade 116` first (checklist 11).
**Sending needs `conversations.send`** (owner, manager, reservations, concierge, foh by default): `send_message`, `send_template`, `retry`, `approve`, `reject`, `ai-draft` and both AI-rewrite POSTs use `require_capability`. `approve`/`reject` are one guarded UPDATE (only a pending AI draft, text unchanged since read; 409 otherwise; audited `ai_draft.approved|rejected`). A new default grant only reaches NEW tenants; existing ones need a data migration.
**AI-rewrite tasks are bounded** (`rewrite_draft.py`): one request <= 30 s (`asyncio.wait_for`), a timeout is never retried, the draft task retries a
provider error once, the composer never retries; a rewrite that changes a number is rejected. Embedding calls: 8 s query / 30 s indexing, SDK retries off.
**CI:** GitHub's default shell is `bash -e` WITHOUT pipefail, so `pytest | tee` passes even when pytest fails; every such step
needs `shell: bash` + `set -eo pipefail`, and `! grep` is ignored by `set -e` (use `if grep ...; then exit 1; fi`).
⚠️ **Don't write a failure off as drift before checking for a latent bug.** Thirteen "pre-existing" failures were stdlib `logging` called
with structlog kwargs (`TypeError` at INFO, how production runs); Phase 0 found an audit-chain fork, dead inbox tasks, a Hostaway sync that never worked, a `varchar(20)` bug and a CI step that passed on failing tests.

---

## DOGRAH VOICE AI INTEGRATION (M5-Parallel)

### Active adapters
- `backend/app/adapters/ivr/` — CallerDesk, Acefone, Mcube, Vobiz (existing,
  do not touch). Only Acefone (Jade) and Vobiz (Ratha) are live for a
  tenant today; CallerDesk and Mcube adapters/webhooks remain in the
  codebase (Mcube's webhook still rejects posts once an Integration is
  marked disconnected — migration `064`) but aren't any tenant's active
  provider.
- `backend/app/adapters/voice/dograh/` — Dograh voice AI adapter (new, M5-parallel)

### Voice platform routing
⚠️ Two separate, similarly-named tenant fields exist — don't conflate them:
- `tenants.ivr_provider` (`callerdesk`/`acefone`/`mcube`/`vobiz`) — which IVR
  adapter `calls.py` and `call_ingest.py` use for a tenant's actual call
  handling. This is the one migration `064` set to `'vobiz'` for Ratha.
- `tenants.voice_platform` (`callerdesk`/`acefone`/`dograh`, default
  `callerdesk`) — Dograh-specific routing gate, used only to decide whether
  `webhooks_dograh.py` is in play for a tenant. Not read by the regular IVR
  call-handling path at all.

`voice_platform` determines which *Dograh-parallel* path processes calls:
- `callerdesk` → existing CallerDesk adapter + `webhooks_callerdesk.py`
- `acefone` → existing Acefone adapter + `webhooks_acefone.py`
- `dograh` → new Dograh adapter + `webhooks_dograh.py` → `dograh_call_processor` task

### Dograh conventions
- Per-tenant webhook secret stored in `tenants.dograh_webhook_secret_enc` (Fernet-encrypted JSON, key `webhook_secret`)
- Webhook endpoint: `POST /api/v1/webhooks/dograh/{tenant_slug}`
- Background task: `dograh.process_call_completed` (Celery, queue: `call_ingest`)
- Duplicate guard: `calls.dograh_call_id` unique constraint + idempotency check in webhook handler
- **Never touch** `webhooks_callerdesk.py`, `webhooks_acefone.py`, `call_ingest.py` when working on Dograh

### SSRF protection — allowed recording domains per provider

| Provider | Allowed Domains |
|----------|----------------|
| CallerDesk | `cdn.callerdesk.io`, `recordings.callerdesk.io` |
| Acefone | `cdn.acefone.com` |
| Dograh | `cdn.dograh.com`, `recordings.dograh.com`, `storage.dograh.com` |
| Mcube (Ratha's live IVR — replacing CallerDesk) | `recordings.mcube.com`, `mcube.vmctechnologies.com`, `s3.ap-south-1.amazonaws.com` (shared S3 host, additionally scoped to path prefix `/app.mcube.com/` — see `backend/app/adapters/ivr/mcube.py`) |

**SSRF protection required on ALL recording URL fetches** — validate scheme (`https`) and domain before any HTTP call.

---

## UI RULES — HOSPITALITY HYBRID (Oct 2026)

Direction: `docs/DESIGN.md` §7 (sea green `--primary` #1E7A5A, coral `--haip-accent` #E0694A for highlights only, sand-white canvas, Figtree body + Bricolage Grotesque display, 12/16px radii, pills). Decisions log: `docs/design/decisions.md`.

- Build pages from `frontend/src/components/ui/kit/` (`Card`, `Stat`, `Tabs`, `FilterBar`, `DataTable`, `Drawer`, `SectionNav`, `Timeline`) plus `PageHeader` / `EmptyState` / `StatusPill`. Check new components in `/dashboard/dev-kit` (dev only).
- Colours come from tokens (`--haip-*`, `--haip-status-*`, `--haip-avatar-N-*`, `--haip-cal-*`). No new hex, no raw Tailwind grays/teal/indigo, no new inline `style={{}}`. Avatars: `crm/UserAvatar`/`GuestAvatar` (`lib/avatarTint.ts`).
- Every list needs loading, empty and error states. Every number says what period it covers; no `-100%` against an empty baseline.
- Money in lakh/crore (`₹1,25,000`), times in the workspace timezone (IST).
- Phone first: nothing scrolls sideways at 375px, tap targets ≥ 44px on touch, inputs ≥ 16px. Shell: ONE nav model `components/layout/nav.ts` (visibility rules live only there). Desktop = `shell/HybridTopNav.tsx` (tabs + "More", no sidebar); phone = 52px `MobileHeader` (menu button -> `MobileMenuSheet`) + 60px `MobileNav` (Home, Inbox, raised Now = My day, Leads, Calendar); `dashboard/layout.tsx` bottom padding must match. The phone header names the page (every route needs a `ROUTE_LABELS` entry in `MobileHeader.tsx`), so `globals.css` visually hides every `.haip-page-title` + its next `<p>` and tightens header padding under 640px; a title that is DATA (guest, call, agent) adds `haip-page-title--keep`. Secondary filters go behind a Filters button.
- **Calendar** (`portfolio/calendar/page.tsx`): phones (<768px) get `components/calendar/MonthGrid.tsx`, a 7-column month grid for ONE property (property picker incl. "All vehicles" with R1/R2 tags, month arrows, pill bars with the guest initial span check-in→check-out, split per week; green direct / gray blocked / red maintenance via `--haip-cal-*`, coral today); tablets and up keep the multi-property timeline. Both open `EntrySheet` (booking details; "Open booking" only for `canViewBookings` roles). Phone fetches 42 days from the Monday before the 1st.
- **Bookings layout B** (Oct 18): one booking view, `components/bookings/BookingDetailView.tsx` (`variant` page | pane), used by `/dashboard/bookings/[id]` and by the list's split view (≥1024px: list left, booking right, open one in `?b=`; Split/Table toggle remembered per device, Table keeps bulk "move to property"). Phones keep list → full page. It sizes by container queries (`@container`), so change the pane and page together.
- **Booking page errors** (`lib/bookings.ts::loadFailure`): only HTTP 404 says "Booking not found"; 403 = no access, 401 = signed out, anything else = couldn't load + Try again. Never collapse these into one message.
- Touching a page for any reason: move it onto the kit only if the task asks for it. No drive-by redesigns.

## AVOID ALWAYS

- Phone as primary key or dedup key
- Direct LLM provider imports in services
- Shared webhook secrets across tenants
- Global rate limit bypass for webhook endpoints
- Synchronous blocking operations in webhook handlers
- Building UI before backend contract
- Expanding scope on bug fix PRs

---

## PRICING (for reference)

| Tier | Price |
|---|---|
| Starter | ₹3,999/mo |
| Growth | ₹6,999/mo |
| Scale | ₹9,999/mo |
| Enterprise | ₹15,000+/mo |

Ratha: Growth tier free 6 months (design partner)
Jade: Growth tier ₹4,999/mo first 3 months
