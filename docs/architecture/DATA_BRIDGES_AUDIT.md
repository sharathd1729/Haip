# Data bridges audit (Part A)

**Date**: 3 Nov 2026 · **Code read**: `master` at `4e0a7d56` (Alembic head 182) · **Method**: code reading only. Nothing was run,
no database or `.env` was opened. Every claim carries a `file:line`; the most important ones were re-read by hand (marked ✔).
**Not covered**: the open website branches (PR 111, PR 112) are not merged, so website findings describe `master` only.
Live data (what is published, which templates Meta approved, whether Razorpay is connected) could not be seen: marked *live?*.

Paths: `BE` = `backend/app/`, `FE` = `frontend/src/`.

---

## 1. Fact map

### 1.1 Properties / vehicles / rooms
| Stored | Written by | Read by |
|---|---|---|
| `properties` (`BE/models/property.py:7-60`): capacity `max_adults/max_children` :28-29, `home_base` :36, `routes` :37, `price_per_day/price_per_km` :38-39, `faqs` :54-60. No check-in/out time column. | `POST/PATCH /properties` (`BE/api/v1/endpoints/properties.py:34,68`). The Properties page sends only name, city, type (`FE/app/dashboard/properties/page.tsx:416-460`); routes/prices/address/capacity have **no form**. Seeds `backend/scripts/seed_ratha.py:67-88`. | concierge `concierge_facts.py:97-143`; `caravan_availability.py:35`; `package_pricing_service.py:159-175`; `booking_compose_service.py:232`; `website_public_service.py:114-136`; `website_pricing.py:163`; Marketing `marketing_ai_service.py:69-76`, `marketing_demand.py:54`; ops `ops_fleet_service.py:55`; GPS, iCal, fleet pickers all read `/properties` (no duplicate) |
| `rooms` (`property.py:71-84`) | `properties.py:112-169` | none of the audited modules |
| `PackageData.vehicle_property_ids/max_guests` (`BE/schemas/business_data.py:149,152`) | business-data API | `package_pricing_service.py:243,254`; `rate_calculator.py:136,165` (warning only); `sales_agent_service.py:139` |

### 1.2 Packages, prices, rate plans, seasonal rates — **two worlds**
| World | Stored | Written by | Read by |
|---|---|---|---|
| **A (legacy)** | `rate_plans` (`property.py:89-112`), `seasonal_rates` (:184-206), `Property.price_per_day` | **no UI**. RatePlan: scripts only (`seed_ratha.py:90`). SeasonalRate: `PUT /properties/{id}/rates` (`calculator.py:445-500`) with no frontend caller | staff `/calculator` (`calculator_service.py:481-563`); website stays + booking widget (`website_pricing.py:75-119,202-212`); calendar nightly rate (`calendar.py:264-290`); `POST /bookings` suggested total (`bookings.py:425-450`); MCP `check_availability/get_quote` (`mcp/tools.py:324,356`); concierge `check_availability.price_per_night` + `get_quote` (`concierge_draft.py:401-475`) |
| **B (published records)** | `business_records` kind package/destination/itinerary/policies (`BE/models/business_record.py:13-40`), versioned, effective-dated | business-data API (`business_data.py:199-249` → `business_data_service.py:230-352`); UI Structured Data tab (`FE/components/knowledge/StructuredDataTab.tsx:84-127`) and Quotes › Packages/Routes (`PackagesTab.tsx:46`, `RouteEditor.tsx:35`) = same table | `sales_gateway.py:116-218`; `package_pricing_service.py:198+`; `sales_requirement.py:109`; `rate_calculator.py:124`; `quote_calc_catalog.py:104`; `booking_compose_service.py:140`; `quote_builder_service.py:232`; `bio_packages.py:40`; `website_bindings.py:94-130`; `marketing_context.py:62`; `ops_rates.py:53-75` |

Bridge between them: `business_data_import_service.py:79-141` copies A→B **once, as drafts**, skips existing keys (:85-87). Nothing flows after that.
Concierge strips World-A prices only when `price_disclosure=grounded` **and** packages are published (`sales_agent_service.py:221-230` ✔).

### 1.3 Add-ons — four catalogues
`PropertyAddOn` (`property.py:160-179`, API `calculator.py:375-430`, no UI) · package `charges` (`schemas/business_data.py:137-142`) ·
`brand_config.quotes.addons` (no API writer; **replaces** package charges when set, `quote_calc_catalog.py:199-205`) · KB category "addons".
Per-booking `stay_addons` (`models/stay_finance.py:14-27`) is the only one that is a fact about a booking, not the catalogue.
Readers: concierge and website read `PropertyAddOn` (`concierge_facts.py:105`, `website_pricing.py:175`); AI quotes read package charges; calculator reads `quotes.addons` else charges.

### 1.4 Policies
| Fact | Places it lives | Readers |
|---|---|---|
| Cancellation / payment / stay rules / discount | `business_records` singletons (`schemas/business_data.py:309-376`), publish needs `confirmed_by_ratha` (`business_data_service.py:195`) | `sales_gateway.py:232-326`, `package_pricing_service.py:385-420`, website `website_public_service.py:139-149` |
| Cancellation text, again | `Property.faqs` (seed puts one there, `seed_ratha.py:81`) + KB "policy" entries | concierge gets FAQ (`concierge_facts.py:132`) **and** record (`sales_gateway.py:310`) in one prompt |
| Advance % | `payment_policy.advance_percent`; `brand_config.quotes.advance_percent`; `Site.settings.deposit_percent` (copied once at site creation, `website_service.py:74-93`); hard-coded 30 % (`calculator_service.py:92,338,419`); 50 % (`booking_compose_service.py:313`, `FE/.../bookings/new/helpers.ts:81`) | see §2 M3 |
| Security deposit | `stay_deposits` (`stay_finance.py:93-108`); default ₹10,000 hard-coded (`helpers.ts:81`). No policy field. | ops settle flows; never revenue (consistent ✔) |
| GST | `invoice_profile.gst_rate` (default 12, `schemas/invoice.py:63`); `brand_config.quotes.gst_percent`; `PackageData.gst_percent` (default 12, on top, `business_data.py:161`); `stays.gst_percent`; website 5/18 slab (`website_pricing.py:24-27`); `calculator_service.py:29` 12 %; bio "+ GST" (`bio_packages.py:55`) | see §2 M4 |
| Check-in / out time | `stay_rules` record; `Stay.check_in_time` default "12:00" (`schemas/booking_compose.py:65-67`); ops fallback "12:00" (`ops_auto_messages.py:56`) | concierge `concierge_facts.py:176` |

### 1.5 Destinations and itineraries
`business_records` destination/itinerary (`schemas/business_data.py:206-271`) is the live source (`sales_gateway.py:156-195`, `sales_requirement.py:82`, `website_bindings.py:97`).
`Property.routes` is read only by `calculator_service.build_route_quote` (:378-426), **which has no callers**, and by the one-off import.
Overlap that matters: KB "routes" entries (`scripts/import_ratha_kb_2026_10.py:38-63`) vs destination `usual_nights` — both reach the concierge prompt.

### 1.6 FAQs and knowledge base
`knowledge_entries` (`BE/models/knowledge.py:20-80`). Writers: manual (approved at once, `endpoints/knowledge.py:159`), crawl/upload (pending, `knowledge_ingest.py:217`),
consult answers (pending, `agent_consult_service.py:278`), Instagram/ads (pending unless `auto_approve_social`, always pending if a price, `knowledge_sources.py:100`).
Readers: concierge via `knowledge_service.search_detailed` (`concierge_service.py:181`); Marketing via `usable_entries` (`knowledge_service.py:495`); `kb_test_service`.
`Property.faqs` is a second FAQ store (`concierge_facts.py:132`, `website_public_service.py:127`).

### 1.7 Brand profile and tone
| Store | Written by | Read by |
|---|---|---|
| `brand_config.brand_voice_guide` | **nothing** (only a test) | concierge prompt, default "Warm, professional, and helpful." (`prompts/concierge_reply.jinja:80`) |
| `brand_config.business_profile.tone/voice/channel_tone` (`schemas/marketing.py:79-99`) | `PUT /marketing/studio/profile` (`marketing_studio.py:93`) | Marketing only. **`channel_tone.whatsapp` is read by nothing.** |
| `brand_config.sales_playbook` | `PUT /ai/sales-playbook` | concierge (`concierge_draft.py:1171`), follow-ups |
| `Property.brand_voice` (`property.py:59`) | — | nothing |

### 1.8 Contact details, WhatsApp number, business hours
- **Phone/WhatsApp: four stores.** `business_profile.contact_phone` (no UI input) · website `site.contact.*` (`FE/components/website/SimpleWebsite.tsx:190-193`, seeded from contact_phone only when empty) ·
  WhatsApp integration `config.display_phone` (from Meta, `integrations.py:291`) · `Tenant.whatsapp_phone_number_id`.
  wa.me links: website/bio use site → contact_phone (`bio_packages.py:22-30`); Marketing posts/newsletter use **contact_phone only** (`marketing_links.py:121`, `marketing_newsletter.py:143`). The real Meta number is never used for links. The concierge prompt has no contact section.
- **Business hours: six sources.** `Tenant.business_hours` (no writer; empty = a hard-coded week in `core/tenant_tz.py:23-31`, but IVR treats empty as always open, `ivr_routing_service.py:260`) ·
  `IVRConfig.business_hours` · `brand_config.agent_consult` 09:00-21:00 (`agent_consult_settings.py:24-31`) · `brand_config.lead_playbooks` quiet 22→8 (also lead alerts) ·
  `ops_settings.quiet_hours` 22→07 (API only) · hard-coded guest window 09:30-20:00 (`lead_followup_service.py:44`). The Settings page shows a fake read-only schedule (`FE/app/dashboard/settings/page.tsx:250-261`).

### 1.9 Guests, leads, bookings, availability, payments, sources
| Fact | Stored | Written | Read (key) |
|---|---|---|---|
| Lead moment | `guests.lead_identified_at` | `identity_resolution.py:357,513` | `lead_metrics.py:119`, `work_queue_service.py:315` |
| Lead type / validity | `inquiries.lead_type`, `validation_status` | `lead_auto_create.py:70`, `lead_review_service.py:57-74` | `lead_types.is_guest_sql`, `lead_validity.effective` :110 |
| Source / attribution | `inquiries.source`; `lead_attribution` | channel ingests; `attribution_service.py:48` | `lead_paid.classify` :67; `meta_ads_service.summary` :332 |
| Bookings | `stays` | compose, `POST /bookings`, quote payment, iCal (`ical_booking_service.py:226`) | §2 M6 |
| Blocks | `blocked_dates` | iCal sync, calendar, ops defects | §2 M8 |
| Payments | `stay_payments` | Razorpay (`payment_events_service.py:73`), quote links, iCal "advance" with `paid_on=today` (`ical_booking_service.py:111`), manual | `kpi_metrics.payment_totals` :312 |

### 1.10 KPIs — see §2 M5-M7 and the table in §2.3
### 1.11 Staff and roles
Logins `users.role` + capabilities · ops `staff_profiles` (may have no login, `models/ops.py:26-33`) · lead owners `inquiries.assigned_to` · sellers `SELLING_ROLES` (`sales_performance_service.py:56`).
Two alert pickers: `roster_service` ("the only place", :3-4) and `lead_alert_service.recipients_for` (:92-108, straight from `users`, no `is_deleted` check at :94).
The Ops staff form never sends `user_id` (`FE/app/dashboard/ops/staff/page.tsx:44-49`) although the link exists (`models/ops.py:33`).

---

## 2. Duplicates and mismatches (ranked by how often the owner will see them)

### 2.1 Business facts
| # | Fact | Evidence | What the user sees | Owner |
|---|---|---|---|---|
| M1 | **Package price, World A vs B** | §1.2 | Owner edits a package price in Quotes › Packages. AI quote, calculator, bio links and website package cards change; website "Our stays" from-price and booking total, staff Calculator, calendar rate, MCP and the concierge `get_quote` fact (handoff mode or nothing published) keep the RatePlan figure. | `business_records` package |
| M2 | **Seasonal rules three ways (World A)** | `calculator_service.py:515-531` ✔ season covering check-in, largest tier ≤ guests; `website_pricing.py:75-86` ✔ night by night, smallest tier ≥ guests; `calculator.py:318` needs a season covering both ends | Tiers `{2: ₹10,000, 4: ₹14,000}`, 3 guests: staff calculator ₹10,000, website ₹14,000. | retire World A (B1) |
| M3 | **Advance %** five ways | §1.4 | Publish payment policy at 30 % after the site exists: AI asks 30 %, website charges its old copy, New booking defaults 50 %, staff Calculator 30 % hard-coded. After one save of Quote defaults the policy no longer reaches the calculator (**freeze on save**: the form loads resolved values and writes all of them back, `QuoteDefaultsCard.tsx:20-25` ✔, `quote_calc_catalog.py:46-69` ✔). | `payment_policy` record |
| M4 | **GST** six sources | §1.4 | A ₹35,000 day package: AI quote and website package card ₹39,200 (12 % on top); rate calculator ₹35,000 with ₹5,339 inside (18 % inclusive); bio "Rs 35,000 + GST". Saving Settings › Invoices writes `gst_rate: 12` and silently moves the calculator from 18 % to 12 %. Option lists disagree (invoice 0/5/12/18, quotes 0/5/18/40). | invoice profile (tax registration) + per-package override |
| M5 | **Discount cap / floor** | AI: `discount_policy` + `Rate.floor_amount` (`package_pricing_service.py:178-195,305`); calculator: `quotes.max_discount_percent` default 10, never checks the floor (`quote_calc_catalog.py:63`) | A staff override can go below the package floor with only the 10 % approval rule. | `discount_policy` record |
| M6 | **Check-in time** | §1.4 | `stay_rules` says 14:00: bot tells the guest 14:00, pickup message says 12:00. | `stay_rules` record |
| M7 | **Add-on unit maths** | `calculator_service.py:49-50` vs `website_pricing.py:143-144` | per_person qty 2, 4 guests: one charges 8, the other 2. | package charges |
| M8 | **Availability, five checks** | `booking_service.find_conflicts` :113-158; `calculator_service._is_available` :431-478 (same-day stay does not block, no times, no placeholder rule); `caravan_availability.py:71` uses server `date.today()` not IST; website `taken_nights` ignores the vehicle-pool shortage (`website_booking_service.py:76-98`); website holds are invisible to staff and the agent | Site calendar shows a night free, the quote then says "not available"; a website hold on 10 Nov does not stop staff or the AI booking that night. | `find_conflicts` (+ holds) |
| M9 | **Capacity** | checked against packages only at publish (`business_data_service.py:160-167`) | Lower a caravan to 4 seats later: website refuses 5, AI still quotes 6 from the package. | Property capacity, re-checked |
| M10 | **Price mode** | one key `brand_config.price_disclosure` (`price_policy.py:39` ✔) read live by concierge, website v2, bio, Marketing — good. Duplicate: v1 `Site.settings.show_prices` snapshot (`website_service.py:92`, `website_public.py:107`); learning loop can make one chat turn grounded (`concierge_draft.py:1135`) | Owner switches to grounded: bot and v2 site show prices, v1 booking widget still hides them. | `price_disclosure` |
| M11 | **Tone** | §1.7 | Owner sets WhatsApp tone in Marketing Studio; the bot still writes "Warm, professional, and helpful." | one voice block in `business_profile`, read by concierge |
| M12 | **Contact number** | §1.8 | Change the number in the website editor: site buttons open the new number, Instagram post links the old one, the bot replies from the Meta number. | workspace contact block |
| M13 | **Business hours** | §1.8 | Sunday 15:00: consult path promises "within 15 minutes", playbook says "tomorrow morning". At 07:30 ops alerts go out, lead alerts wait to 08:00. | `Tenant.business_hours` with an editor; others default from it |

### 2.2 Numbers (KPIs) — the owner's "numbers don't match"
| # | Number | What differs | Example |
|---|---|---|---|
| K1 | **"New leads"** | Command Center = people by `lead_identified_at` (`lead_metrics.count_new_leads` :123); OperationsHome (non-owner home) = enquiry records (`kpi_metrics.lead_filters` :186, sample guests included); Leads list = records incl. b2b by default (`lead_list_extras.py:37-40`) | Same guest enquires twice: 1 on owner Home, 2 for staff, 2 + any b2b on Leads. |
| K2 | **Leads list date filter (bug)** | presets return bare `YYYY-MM-DD` (`date_presets.py:99-102` ✔) compared directly to `created_at` (`leads_service.py:818-821` ✔); the IST helper right above it is unused here | "Today" on Leads ends at midnight → near zero; "Last 7 days" misses today. Phone Home "N valid enquiries · today" inherits it. *Not run on PG.* |
| K3 | **Qualified** | owner tile = phone + check-in date (`owner_dashboard_blocks.py:64`); same payload's funnel + owner email = valid stage (`business_overview_service.py:73`, `owner_brief_service.py:82`); daily email = valid stage incl. spam + b2b (`daily_report_service.py:242`) | Dated lead still in a non-valid stage: tile 1, funnel 0, morning email 0. |
| K4 | **Booked value** | D-24 (rental + add-ons) on KPI tile/target; stay charge only on `revenue.gross_booking_value`, Impact, Since HAIP, executive, marketing monthly | ₹40,000 + ₹5,000 add-on: ₹45,000 on the tile, ₹40,000 on Impact and on the same page's revenue block. |
| K5 | **Bookings date basis** | booked-on (`kpi_metrics.booking_filters` :253) vs check-in (OperationsHome `dashboard_overview.py:158`, executive); revenue report has **no status filter** and UTC days (`reports.py:484-494`); iCal stays are "made" on the import day | Booking made today for 20 Dec: "this week" on owner Home, "December" for staff. Importing 30 old calendar events spikes "Bookings made". |
| K6 | **Target progress** | `owner.target` = booked_value whitelist; `revenue.target` = pickup "not cancelled" (`business_overview_service.py:235`); marketing monthly = charge only, no creator stays (`marketing_reports.py:176-181`) | Marketing report "off track", owner card "ahead". |
| K7 | **Conversion** | records won-stage ÷ records (OperationsHome); people with a live stay ÷ people (Command Center); won stage (analyst); same-day ratio (daily email) | Same month: 12 % on one, 30 % on another. |
| K8 | **Occupancy** | executive divides by all properties **incl. "Unassigned"**, UTC month (`analytics_executive.py:109-119`); caravans card per vehicle, whole month; `owner_daily.occupancy_rate` is really a win rate (`analytics.py:198-206`) | 4 caravans: executive divides by 5. |
| K9 | **Missed calls** | queue card: 7 days, active IVR, one per person (`work_queue_service.py:375`); AI & Calls: period, all providers, not de-duplicated (`impact_metrics.py:218`) | 3 missed calls from one person on the old line: 3 in one block, 0 in the card on the same page. |
| K10 | **Lost reasons** | owner stages, Impact, owner email read legacy `lost_reason`; reports read `outcome_reason` (D-29) | Owner card "Not recorded" while the reasons report shows a confirmed reason. |
| K11 | **Meta leads** | Marketing page = enquiries with any referral incl. organic story replies (`meta_ads_service.py:332`); owner Home = people from ad referrals only (`business_overview_service.py:278`) | A story reply is a "Meta lead" on Marketing only. |
| K12 | **UTC days** | executive MTD, owner-daily calls, daily funnel (`leads_service.py:1214`), revenue report, Meta summary (`meta_ads_service.py:306`) | A 02:00 IST enquiry lands on yesterday. |
| K13 | Smaller | "owing money" twice on one payload (30-day card vs all live, `owner_dashboard_attention.py:106` vs `business_overview_service.py:129`); spam can pass D-28 validity (`lead_validity.py:87-107` never reads `qualification_status`); sparkline ignores the property filter (`dashboard_overview.py:306`); agent credit = enquiry owner vs person owner (reassign moves money) | — |

D-nn decisions not followed: D-22 (legacy `conversations_new` still in `business_overview_service.py:108`), D-24 (K4 list), D-27 (Leads list, dashboard funnel, executive, source breakdown, daily email, workflow report), D-28/29/30 (K3, K10). Catalogue `KPI_METRIC_CATALOGUE.md:211` is out of date (revenue tile is now agent-scoped, `dashboard_overview.py:165`).

### 2.3 Who should own each number
New leads → `lead_metrics.count_new_leads` (rename the record count "Enquiries") · Qualified → one `lead_metrics` function per D-28 · Bookings + booked value → `kpi_metrics.booking_filters` / `booked_value` (D-03/D-04/D-24) · Cash → `payment_totals` (fix iCal `paid_on`) · Occupancy → a capacity helper without the placeholder (D-06/07) · Conversion → `lead_metrics.lead_to_booking` (D-02) · Missed calls → one counter (D-15) · Lost reasons → `lead_outcome` (D-29) · Availability → `find_conflicts` + holds · Alert recipients → `roster_service`.

---

## 3. Why the bot misses knowledge-base data

Path: `concierge_draft.py:959` → `concierge_service.py:177-200` (`retrieval_query_text` → `knowledge_service.search_detailed`) → price strip (`concierge_draft.py:1157`) → prompt (`concierge_reply.jinja:121-126`).
Structured data goes separately: `sales_gateway.concierge_business_facts` (`concierge_draft.py:1084`) → `concierge_reply.jinja:146-177`.

| # | Miss | Evidence | Fix idea (B4) |
|---|---|---|---|
| R1 | **Property scope trap**: an entry tied to a property is used only when the chat has that property; most WhatsApp chats have none | `_ELIGIBLE_SQL` `knowledge_service.py:142` ✔; Marketing's `usable_entries` treats None as all (:500) — the two disagree; test box uses `conv.property_id` only (`endpoints/knowledge.py:526`) | unscoped chat = all properties (match `usable_entries`) |
| R2 | **Pending after an edit**: any content change → `embedding_status=pending` → invisible until indexed; an edit during indexing is not marked done | `endpoints/knowledge.py:338-344`; `knowledge_service.py:296-304` | keep serving the last good vector until the new one is done |
| R3 | **Gives up after 6 failures** and nobody is told per entry. One save burns 4 attempts in ~3 min (task retries 3×), the sweep backs off to 60 min and stops at 6 → a 2-3 h provider outage leaves entries dead until "Re-index" | `embed_knowledge.py:45,62-65,86-88`; `knowledge_service.py:125` | count only sweep attempts; alert + health card |
| R4 | **Sweep starvation**: sweep takes the 50 *oldest* pending/failed rows, *then* drops given-up ones → 50 dead rows block every newer entry | `embed_knowledge.py:102-118,143` ✔ | filter attempts < 6 in SQL |
| R5 | Sweep-indexed entries get **no alternate phrasings** (fewer guest wordings match) | `embed_knowledge.py:118` vs :60 | call `_ensure_phrasings` in the sweep |
| R6 | **Re-crawl wipes a page**: chunk boundaries shift (150-char overlap), every old approved chunk goes stale, every new one arrives pending | `knowledge_ingest.py:217,225-228`; `knowledge_service.py:182-215` | carry approval over when text is near-identical |
| R7 | **Social posts wait for approval** (`auto_approve_social` off; a price post always waits; an edited caption goes back to pending) | `knowledge_sources.py:36,100,122` | health card: "N waiting for you" |
| R8 | **Price strip eats non-prices**: "Free km per day: 300", "2 per person", "1 per day" removed; runs in both modes; the test box shows unstripped text | `price_policy.py:48-65` ✔; `kb_test_service.py:127` | require a currency/rate context; strip in test box too |
| R9 | **Query misses context**: only the guest's unanswered burst (or last 4 inbound if < 6 words); our own question is never included ("yes, what's included?" after "Want the Coorg route?" has no "Coorg"); several questions = one vector | `concierge_service.py:48-93` | add our last question; split multi-question bursts |
| R10 | **Top-k squeeze**: 15 vector rows, up to 10 vectors per entry → two phrasing-heavy entries can fill all 15 | `knowledge_service.py:110-113,460,469,535` | distinct-entry limit in SQL |
| R11 | **Silent embedding timeout**: 8 s, no retry → "knowledge base could not be searched" in the prompt; nothing stored on the message | `embeddings.py:54,95-98`; `knowledge_service.py:451`; `concierge_service.py:202` | store `kb_status` + hit ids on the draft |
| R12 | **No record of what knowledge a reply used**: `kb_status`/hits not stored, model `citations` thrown away | `concierge_draft.py:875-919,1496` | same as R11 → makes `diagnose_bot_replies` able to explain KB misses |
| R13 | **Handoff mode** hides payment + cancellation policies from the prompt (only stay rules shown) | `concierge_reply.jinja:168-173` | show non-money policy text in handoff |
| R14 | **`concierge_business_facts` leaves out**: drafts and scheduled versions, b2b, discount/reseller policies, policies not `confirmed_by_ratha`, itinerary day stops, destination best months/notes, package km/day and at-actuals lines; no property scope | `sales_gateway.py:124,244,300-337`; `concierge_reply.jinja:151-163` | render the missing fields |
| R15 | **Language**: no translation; Hindi/Kannada/Hinglish embedded raw against English entries; `MIN_SCORE 0.25` calibrated on one sample | `knowledge_service.py:103-111` | measure on the bench first |
| R16 | **STOP false positive kills the reply** (not a KB gate, but the owner will read it as "bot ignored us"): any whole word "cancel/end/remove/block/quit" → opt-out → `return` before the concierge, consent revoked | `opt_out_detector.py:15-25,64-75` ✔; `whatsapp.py:540-566` ✔ | opt-out only on a whole-message keyword (as `ai_handoff.is_stop_message` already does) |

### 3.1 Owner tools, and the commands to run on the VPS (read-only)
- **Settings › Knowledge › Test** (`POST /knowledge/test`, `settings.manage`): same retrieval + business facts as a reply, but uses the raw question, the conversation's property only and unstripped text (R1, R8, R9 make it differ from a real reply).
- **GET /knowledge/freshness** (owner/manager): per-source counts (used, waiting, indexing, failed, gave up, stale, price-flagged). Counts only, no list.
- `scripts/diagnose_bot_replies.py --tenant-slug SLUG [--days 7] [--show 15]`: AI mode, drafts, holds, delivery. **It never looks at the KB** (and cannot: R12).
- **Since B4 (4 Nov)**: Settings › Knowledge › **Knowledge health** card (`GET /knowledge/health`) lists each entry the bot cannot use with its reason, usable entries no reply used, and replies per search status; `diagnose_bot_replies.py` now prints a "Knowledge base use" section. Both read what drafts record from 4 Nov on. Before B4 is deployed, this read-only query shows the same reasons:

```bash
docker exec haip_api python scripts/diagnose_bot_replies.py --tenant-slug rathaa --days 7 --show 15
```

```bash
docker exec -i haip_api python - <<'PY'
# Read-only: lists Rathaa knowledge entries the bot cannot use, and why. No writes, no commit.
from collections import Counter
from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant
from app.models.knowledge import KnowledgeEntry as K
db = SessionLocal()
t = db.query(Tenant).filter_by(slug="rathaa").one()
set_tenant_context(db, t.id)
why = Counter()
for e in db.query(K).filter(K.tenant_id == t.id).order_by(K.updated_at.desc()):
    r = [x for x, bad in (("inactive", not e.is_active), (f"review={e.review_status}", e.review_status != "approved"),
         (f"index={e.embedding_status}/{e.embedding_attempts}", e.embedding_status != "done"), ("stale", e.stale_since is not None),
         ("property-only", e.property_id is not None)) if bad]
    if r:
        why.update(r)
        print(e.source, e.category, (e.question or e.content or "")[:60].replace("\n", " "), "|", ", ".join(r), "|", (e.embedding_error or "")[:60])
print(why)
db.rollback(); db.close()
PY
```
Imports match `scripts/diagnose_bot_replies.py:26` and `app/core/database.py:63`. Not run anywhere (no prod access from here); use your workspace slug if it is not `rathaa`.
"property-only" is not always a miss: it is one only when the guest's chat has no property (R1).

---

## 4. End-to-end sales agent: guest asks → booking paid

| Step | Status | Switch or gap (default) | Where to change | Evidence |
|---|---|---|---|---|
| Webhook → concierge draft | built | — | — | `whatsapp.py:593-610` |
| STOP detector | **bug** | R16: "cancel/end" anywhere = no reply + consent revoked → later blocks autopilot (`guest_said_stop`) | code | `sales_agent_service.py:93-100` |
| Channel AI mode | built, off | `wa_ai_mode_default` = shadow; autopilot needs **autonomous** (quote sends only if the reply auto-sent) | Settings › AI Concierge | `models/tenant.py:80-81`; `sales_agent_service.py:284` |
| Sales agent mode | built, off | `sales_agent.mode` = off | Settings › AI › AI sales agent (owner) | `sales_agent_settings.py:28-33` |
| Price disclosure | built, off | `handoff`: agent never quotes; every price question opens a consult (`price_handoff`) | same card | `agent_escalation_rules.py:295`; `agent_policy.py:47-59` |
| Collect requirement | built | asks for dates, guests, plan (≤ 2 items) | — | `sales_requirement.py:97-139` |
| Availability | built | `caravan_availability.check` (server date, M8) | — | `caravan_availability.py:63-103` |
| Published packages + rates | built, off (data) *live?* | catalogue imported as **drafts**; no published package = every quote refused | Knowledge › Structured Data › Publish | `import_ratha_catalogue.py:1-6`; `package_pricing_service.py:222-426` |
| Payment terms | built, off (data) *live?* | no published `payment_policy` → advance None → hard `no_advance` on every send | Structured Data › Payment terms | `package_pricing_service.py:412-420`; `quote_send_service.py:132` |
| Quote + SalesAction | built | one per lead per requirement per 24 h | — | `sales_agent_service.py:169-204` |
| Staff approve card | **gap** | overnight agent quotes carry `stay_check=not_checked` unless `auto_bookable` → `stay_not_confirmed` disables the Send button; the card has no way to confirm the stay | needs a "stay confirmed" action on the card | `quote_send_service.py:126`; `SalesActionCard.tsx:80-105` |
| `auto_bookable` | built, off | UI exists, set on **no** seeded package | Structured Data package/destination | `schemas/business_data.py:173,232` |
| `agent_policy.send_payment_link` | built, off | `draft_for_approval` | Settings › AI › AgentPolicyCard | `agent_policy.py:40-44` |
| **Learning cap** | **blocks autopilot** | once `brand_config.learning` exists, payment links are capped at `suggest` **by schema** (`AREAS["holds_payments"] = ("suggest","suggest")`); `seed_ratha_analyst.py` creates it. AgentPolicyCard still lets the owner pick "autonomous" and silently loses. | product decision | `learning/limits.py:31-44` ✔; `schemas/learning.py:16` ✔ |
| Quote template `ratha_quote_payment_v1` | built, off *live?* | must be Meta-approved | Settings › Invoices › templates | `quote_send_service.py:136,197` |
| Razorpay | built, off *live?* | per-tenant keys + webhook; `API_BASE_URL` https | Settings › Payments | `payment_link_service.py:34`; `payments_razorpay.py:45-101` |
| Paid → booking → Sold | built | webhook → `on_payment_link_paid` → `quote_payment_service` → `create_booking` → closed-won | — | `quote_payment_service.py:102-171` |
| Vehicle choice | risk | agent quotes have no `vehicle_property_id` → first free vehicle, not one the package allows | code | `quote_payment_service.py:76-84` |
| Invoice + confirmation | built, off *live?* | `ratha_booking_confirmed_v1` must be approved; no text fallback | templates | `wa_booking_messages.py:109-122` |
| Missed webhook | built | reconcile every 10 min | — | `payment_reconcile_service.py` |
| Ops file | built, **late** | created at 06:10 IST next day or when someone opens Ops today, not at booking | code (hook in `create_booking`) | `ops_files.py:20-28`; `celery_app.py:450` |
| Crew / guest pre-trip messages | built, needs a person | crew brief only after the file is accepted and crew assigned | Ops | `ops_auto_messages.py:1-13,191` |
| Balance reminders | built, off | `payments.auto_balance_reminder` = false | Settings › Invoices | `balance_reminder_service.py:41` |
| Readiness view | partial | `GET /ai/sales-agent` checks 4 things (packages, auto-bookable, Razorpay, quote template). Missing: channel autonomous, link policy, learning cap, payment terms, drafts vs published, confirmation template, webhook URL, ops pack, reminders | Settings › AI | `sales_agent_settings.py:36-51`; `SalesAgentSettingsCard.tsx:82-111` |
| End-to-end test | **missing** | no test from inbound message → paid → ops file; agent bench has 1 sales scenario and stops before payment | — | `tests/workers/test_sales_agent_concierge.py` forces `send_payment_link=autonomous` with no learning key, so the cap is never exercised |

**Order of blockers today**: (1) nothing published + no payment terms, (2) handoff mode, (3) agent mode off, (4) overnight quotes unsendable from the card, (5) Razorpay *live?*, (6) templates *live?*, (7) channel not autonomous, (8) link policy, (9) **learning cap: no setting can lift it**, (10) STOP false positives, (11) ops file next day.
Suggest mode (a person taps Send) can work end to end after (1)-(6) plus a fix for (4). Autopilot also needs (7)-(9).

---

## 5. Data the user types twice

| # | Fact | Typed in | Already linked? | Single source |
|---|---|---|---|---|
| D1 | GST rate | Invoices (`invoices/page.tsx:114`), Quote defaults (`QuoteDefaultsCard.tsx:41`), each package (`businessDataSpecs.ts:106`), website "rates include GST" (`Overview.tsx:188`) | quotes fall back to invoice, frozen after one save | invoice profile |
| D2 | Advance % | payment policy (`businessDataSpecs.ts:177`), Quote defaults (:42), website deposit (`Overview.tsx:185`) | one-time copies | payment policy |
| D3 | Quote validity | package `quote_valid_days` (:107), Quote defaults (:43) | no | workspace default + package override |
| D4 | Discount cap | discount policy (:209,212), Quote defaults (:44-45) | no | discount policy |
| D5 | Business hours | AI consult (`AgentConsultSettingsCard.tsx:61`), workflow quiet hours (`PlaybooksTab.tsx:202`), ops quiet hours (API); `tenants.business_hours` has **no editor** | no | `tenants.business_hours` |
| D6 | Logo | Branding (`branding/page.tsx:341-385`), Invoices (:140), brand kit (`BrandKitPanel.tsx:76`); website has none | invoice falls back to Branding (data-URL only) | Branding logo |
| D7 | Brand colours | Branding (:422), website palette (`DirectEditors.tsx:129`), brand kit (:90) | brand kit falls back; its "fill from website" reads only v1 sites (`marketing_brand_kit.py:135-154`); new sites always start "forest-amber" (`website_autobuild.py:66`) | Branding colours |
| D8 | Business name | workspace name, "Brand display name" (saved to `brand_config.brand_name`, **read by nothing** ✔), Branding company name, invoice legal name | invoice falls back to the `brand_name` column, which has no form | `tenant.brand_name` |
| D9 | Phone / email / address | website contact (`SimpleWebsite.tsx:190-193`), invoice address (:108); `business_profile.contact_*` exists with **no input** | website seeds from fields nobody can fill | workspace contact block |
| D10 | Package prices | rate plans (no editor), package `rates[]`, KB "pricing" free text | one-time import | package records |
| D11 | Staff | Team (name, email, phone) and Ops staff (name, WhatsApp) | `user_id` link never sent | `users`, Ops staff picks a team member |
| D12 | City / location | property city, Marketing city/region/state, lead-rules allowed locations, destinations | no | suggest from property + destinations |

Good patterns to reuse: `POST /business-data/import-existing` (drafts, never overwrites), `website_autobuild` (builds from HAIP data, lists gaps with links),
brand DNA draft (suggests, never saves), brand-kit suggest, invoice logo fallback. Copy the fallback idea, not the freeze-on-save.

---

## 6. Bugs found on the way (small, real)
1. Workspace timezone never saves: the form sends `timezone`, `TenantUpdate` has no such field (`BE/schemas/tenant.py:21-27` ✔), and the form reads `brand_config.timezone` which nothing writes.
2. `/calculator/dynamic-price` 500s when no season covers the stay: reads `prop.base_price_per_night`, a RatePlan column (`calculator.py:326` ✔, `property.py:97`).
3. Leads list date presets (K2).
4. STOP false positives (R16).
5. KB sweep starvation (R4).
6. ~~MCP `get_dashboard_metrics` skips the `revenue.read` check.~~ Checked 4 Nov: not a bug. The MCP tool registry requires `revenue.read` for `get_revenue_summary` (`mcp/tools.py:692`), and `get_dashboard_metrics` (`analytics.read`) withholds every money field without it (`mcp/tools.py:279-286`); both covered by `tests/api/test_money_access.py`. Occupancy and funnel are shown to `analytics.read` holders on purpose.
7. iCal "advance" payments get `paid_on = sync day` (`ical_booking_service.py:111`), so cash received jumps on import days.

---

## 7. Proposed plan (Part B), smallest useful steps first
Each phase = one commit + tests + CLAUDE.md update. Nothing pushed.

- **B0. Quick fixes (bugs in §6)**, one commit each: STOP whole-message only; Leads date presets via the IST helper; timezone field; dynamic-price; sweep filter + phrasings; iCal `paid_on`. Low risk, owner-visible. **Done 4 Nov** (the MCP item turned out not to be a bug).
- **B1. One read layer for business facts.** A thin `business_facts` module over `get_effective`/`sales_gateway` for: price (package), advance, GST, discount cap, check-in time, add-ons. Point the website stays pricing, staff Calculator, calendar rate, `POST /bookings` total, MCP and concierge `get_quote` at it. World A (RatePlan/SeasonalRate/PropertyAddOn) stays read-only as a fallback only where no package is published, then is retired later. Quote snapshots stay immutable. Quote defaults stop writing resolved values back (store only what the owner changed).
- **B2. Write once, flow everywhere.** `core/events.emit_event` is the guest event ledger (needs entity/guest context), so it is the wrong hook. Instead one `business_data_changed(tenant, kind, key)` call at publish/approve/profile-save that: re-indexes the KB entry, marks the website draft "data changed" (never publishes), refreshes Marketing inputs, and clears the concierge facts cache. A "Used by" list on each record/entry from a static map (which module reads which kind).
- **B3. One definition per number.** Route OperationsHome, executive, Impact, Since HAIP, marketing monthly, revenue report and the Leads list through `kpi_metrics`/`lead_metrics`; rename the record count "Enquiries". A consistency test: one fixture, every screen's endpoint, same New leads / Bookings / Booked value / Qualified. Open D-02, D-03, D-04, D-06/07, D-15 need **your decision** first (I will bring a one-page choice list).
- **B4. KB reliability.** Fix R1-R5, R8, R11-R14 with a regression test each; KB health card (entry list with reason, one-click re-index); store `kb_status` + hit ids on each draft so `diagnose_bot_replies` can say "KB not used because …". **Done 4 Nov**: R1 (unscoped chats get a property's passage only when no other property matches), R3, R4, R5, R6, R8, R9, R10, R11/R12 (kb record on drafts), R14 (concierge-reply-v20), health card. **Left on purpose**: R2 (an edited entry stays unused until re-indexed: pinned design, so old wording is never served), R7 (social approval is the owner's queue; the card shows it), R13 (policy text in handoff mode is an owner decision), R15 (language: measure on the agent bench first).
- **B5. Sales agent readiness.** One checklist in Settings › AI with every row of §4 and a Fix link; a "stay confirmed" action on the SalesActionCard; ops file created at booking time; vehicle limited to the package's vehicles. The learning cap needs **your decision** (keep "a person always taps Send on payment links" or allow autonomous). Autopilot stays off. **Done 4 Nov**: checklist (`sales_agent_readiness.checklist`, groups Suggest / Autopilot / after payment), confirm-stay on the card, ops file at payment (`invoices.after_payment`), package vehicles on a paid quote. **Not changed**: the learning cap (shown in the checklist as a deliberate limit, no Fix link; still your decision), the STOP-word false positives (fixed in B0), no end-to-end test from inbound message to paid booking yet.
- **B6. Enter once (§5).** Business hours editor (D5), workspace contact block (D9), brand name (D8), logo/colour defaults from Branding (D6/D7), Ops staff picks a team member (D11). Each is a small form change plus a fallback read.

Suggested order: B0 → B4 → B5 → B1 → B3 → B2 → B6 (fix what guests feel first, then the numbers, then the plumbing).
