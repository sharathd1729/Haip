# Dynamic SOPs — plan (Part A, code reading only)

**Status**: S1 built 4 Nov 2026 (branch `claude/mystifying-blackwell-9e8258`, on PR #112; S2-S4 not built) · **Owner idea**: team meeting Nov 2026 · **Written**: 3 Nov 2026 against `master` @ `4e0a7d56`
(Alembic head `182`), also reading the open branches `feat/website-phases-2-6` (PR #112, website phases 2–6),
`claude/bold-merkle-6878b5` (AI Executive E1–E4) and `claude/focused-ramanujan-cacf4f` (`docs/architecture/DATA_BRIDGES_AUDIT.md`).

Some visibility work cannot be automated: OTA listings and promotions, discount programmes, Google Business Profile
(photo order, categories, reviews). HAIP gives the team **dynamic SOPs**: step-by-step procedures that the AI fills with the
client's own data, that a person carries out on the platform, that HAIP tracks to done and repeats on a schedule.

Ground rules:
- **Code decides, the model only writes.** Which SOPs apply, which steps, which categories are offered, the photo order, due
  dates, reminders and checks are code. The LLM writes only text slots (description, Q&A, offer text, review replies, bio),
  and only from facts handed to it.
- **The AI never invents a platform rule or category name.** Those live in a curated, dated catalogue the HAIP team edits.
  A fact missing from the catalogue = the step says "Check in the platform".
- **One shared data layer.** Inputs are read through `business_data_service.get_effective`, `sales_gateway`,
  `knowledge_service`, `brand_config.business_profile`, `media_assets` (and `marketing_context.business_facts`, which already
  combines them). Nothing is copied. A missing fact becomes a step "Fill this in HAIP" with a deep link to the existing editor.
- **HAIP never logs in to, scrapes or posts on a third-party platform for SOPs.** A person does the step. Automatic checks use
  only APIs the client has connected with their own token (Google Business, Instagram, Facebook Page, WhatsApp Cloud).
- **Every business type** (villa, farmhouse, homestay/Airbnb, boutique hotel, resort, service apartment, caravan/vehicle
  rental, travel agency); each client can switch SOPs off, change cadence and assignee, hide steps and add their own.

---

## 1. What exists and is reused (never copied)

| Piece | Where | SOPs use it as |
|---|---|---|
| **Google Business Profile checklist** (website phase 3, 12 items, ticks in localStorage only) | PR #112: `frontend/src/app/dashboard/marketing/website/google/page.tsx` (`ITEMS`), linked from `GrowthPanel.tsx` / `SimpleWebsite.tsx` | **Folded in**: its 12 items become the steps of `gbp_setup` + `gbp_upkeep`; the page redirects to the GBP SOP. Its category examples and "750 characters" become catalogue entries marked *unverified* until sourced. Device ticks are dropped (no server state existed). |
| Segment mapper (8 kinds = the owner's list) | PR #112: `services/website_seo.py::business_kind()` over `tenants.business_type` (free text) | **The one business-type rule.** SOPs read it; no second mapper. (S1 needs PR #112 merged, or the function moved first.) |
| Marketing Studio run log | `models/marketing.py:123` `marketing_tasks` (role, step, status, ref_type/ref_id) | Not used for SOP progress (it is the agency's run log). SOP generation runs may write one row `role=sops` only if the owner wants them on the Studio Home timeline (D9). |
| Agency roles + autonomy | `marketing_agency_service.py:52-115` | Pattern only. SOPs have no autopilot: a person always does the step. |
| Approvals inbox | `marketing_agency_service.pending_approvals:123`, `notify_needs_approval:154` (push + SSE) | **Notification helper** reused for "new SOP version ready" (push + SSE). SOP text needs no approval (a person pastes it); see D7. |
| Business profile | `schemas/marketing.py:79` `BusinessProfile` (description, tagline, usps, avoid, city, region, contact_*, socials, claims, voice, channel_tone) | Main input for descriptions, bios, NAP. |
| Approved photos | `models/media_asset.py` (status, `tags` from the vision model, `people_ok`) | Photo order for GBP/OTA/IG chosen in code from tags; `people_ok` rule kept. **Evidence uploads** land here with `source="sop_evidence"`, `status="evidence"` (never in the picker or library, which read `status="active"`). |
| Business facts for any AI step | `marketing_context.business_facts` (KB `usable_entries` + `sales_gateway.concierge_business_facts`, prices stripped, payment/cancellation only in grounded mode) | **The facts block** for `sop-generate-v1`. |
| OTA listing copy (agency M7) | `marketing_reputation.py` + `models/marketing_partners.py:54` `marketing_ota_copies`; limits in `schemas/marketing_partners.py:90-112` (Airbnb/Booking/MMT) | **The text generator for OTA listing steps** (not a second prompt). Its hard-coded field limits move into the platform-rules catalogue with as-of + source (S2); Agoda added. |
| Google reviews + AI reply drafts | `marketing_guest_reviews` (hourly sync), prompt `marketing-review-reply-v1` | Review-response SOP: auto-check "every review answered"; OTA/TripAdvisor reviews pasted by a person reuse the same route + prompt. |
| Google posts | Studio M4 channel `google` (`adapters/google_business.py::create_post`), `marketing_publish_attempts.channel` | "Post every week" step is auto-checked from HAIP's own publish attempts; Studio stays the way to post. |
| Tasks | `models/task.py` (`kind`, `assigned_to`, `due_date`; no-guest tasks show on My day follow-ups) | Recurring/overdue steps become `Task` rows `kind="sop"`; the progress row keeps `task_id`. |
| Alerts | `lead_alert_service.in_quiet_hours:77`, `wa_hold:131`; `lead_alert_sender.deliver:104` (PlaybookAction, staff opt-in); `push_service.send_to_tenant` | Overdue reminders: assignee → manager, same quiet hours, same WhatsApp hold, same opt-in. No new channel. |
| Integration health | `integration_health.classify:53`, `token_days_left:46` | "Connected?" auto-checks for Google Business / Instagram / Facebook Page / WhatsApp. |
| Instagram Graph | `adapters/instagram/meta_graph.py:209` `get_account_fields` reads `name, biography, followers_count, follows_count, media_count` | Auto-checks: bio filled, name set, posting cadence (poller data). **Not read today**: `username`, `website`, `account_type`, `profile_picture_url` (Meta documents them; UNVERIFIED on our Instagram-Login token, test live in S4). **Category is not exposed** by the API as far as the code shows → evidence. |
| Google Business adapter | `adapters/google_business.py` (business.manage OAuth; `locations()` readMask `name,title`; posts; reviews; reply) | S4: widen readMask (`categories, profile, regularHours, websiteUri, phoneNumbers, storefrontAddress`) and the verification state (Verifications API). Both UNVERIFIED until a live call; API access needs Google's approval. |
| Facebook Page adapter | `adapters/facebook_page.py` (posts, permalink only) | S4: Page fields `about, category_list, website, phone, hours` (documented, UNVERIFIED). |
| WhatsApp Cloud | `wa_health_service.py:175` reads `display_phone_number, verified_name, quality_rating` | Auto now: display name + quality. S4: `/{phone_id}/whatsapp_business_profile` (about, description, address, email, websites, vertical, photo; documented, not called yet). |
| Website SEO + launch report | PR #112: `website_quality.audit` (speed/accessibility/search scores), `website_seo` JSON-LD, `website_launch.build` (report, `content.checklist items still open`) | Maps hygiene SOP auto-checks: site live, LocalBusiness JSON-LD present, search score. The launch report's "checklist items still open" reads **SOP progress** instead of the old checklist. |
| Link in bio | sites `/links` (`GET /public/sites/{host}/links`) | The Instagram/GBP "website link" value to paste. |
| Season + demand | `brand_config.marketing_studio.season_calendar`, `marketing_demand.free_nights / long weekends` | Seasonal SOP cycles (OTA promotions) open before each season/long weekend. |
| LLM router | `adapters/llm/__init__.py` `_TASK_ROUTES`, `_GEMINI_FALLBACK_TASKS`; `core/prompt_versions`; `app/prompts/*.jinja`; `tests/adapters/test_llm_routing.py` | New task key `sop_generate` (§2.4). |
| Guards | `marketing_context.strip_prices / redact_price_facts`, Studio `price_policy`, `marketing_lint` (numbers not in facts = HIGH), profile `avoid` words | Every generated public text passes them; a failure falls back to fixed wording. |
| AI Executive detectors | `claude/bold-merkle-6878b5`: `services/chief/catalogue.py` (`Detector(code, role, cadence, category, next_step, rule)`), `detectors_growth.py` (MK7 reviews unanswered already exists) | SOP status exposed as signals; the Executive registers `detectors_sops.py` (§2.8). |
| Audit | `core/audit.py::append_audit` | Every SOP write. |

**Contact details today have four stores** (DATA_BRIDGES_AUDIT D9). SOPs read `business_profile.contact_*`, then the website's
`site.contact`, in that order, and switch to the workspace contact block when the data-bridges work adds it. No fifth store.

---

## 2. Design

### 2.1 Words
- **SOP template**: code-defined procedure for one platform job (e.g. `gbp_setup`), versioned.
- **Platform rules**: curated facts about a platform (category names, photo specs, text limits, promo programmes), dated.
- **SOP instance**: one template running for one tenant (and, for OTA listings, one property).
- **Version**: an immutable, filled-in copy of the steps for an instance. **Cycle**: one round of a recurring instance.

### 2.2 SOP catalogue (`services/sops/catalogue.py`, code, like `lead_playbook_catalog`)
```
Template(key, version, platform, title, recurrence: one_off|weekly|monthly|seasonal,
         applies_to: tuple[kind] | "all", per_property: no|optional|required,
         requires: integration/module keys (optional; missing = auto-checks become evidence),
         lead_days (seasonal), steps: tuple[Step])
Step(key, title, how (HAIP-written, with {slots} and [rule:key] refs),
     verify: auto|evidence|manual, check: check_key | None, slots: tuple[slot], due_offset_days, optional)
```
A template change bumps `version`; a CI test checks every `[rule:key]` exists in the rules catalogue, every `check` exists in
the check registry and every `applies_to` kind is in `website_seo.KINDS`.

### 2.3 Platform rules (`app/data/sop_rules/<platform>.json`, HAIP team edits by pull request)
Each entry: `key, platform, kind (category|photo_spec|text_limit|programme|policy), value, applies_to (kinds + rank),
status (verified|unverified), as_of, source_url, note`. A schema test refuses an entry without `as_of` + `source_url`
(`unverified` entries carry a source like "team belief, 3 Nov 2026").
- **Unverified** entries are shown to the client as "Not confirmed — check in the platform" with the candidate value; the AI
  never states them as fact. Example: `gbp.category.recreational_vehicle_rental_agency`, applies_to caravan rank 1, status
  `unverified`, source "HAIP team belief, team meeting Nov 2026". Its step asks the client for a screenshot of Google's
  category picker; the HAIP team reads it and, if it matches, flips the entry to `verified` with the date (a person, never automatic).
- **Stale**: `as_of` older than 180 days = shown with "may be out of date". `scripts/sop_rules_report.py` lists stale and
  unverified entries for the team.
- Missing fact = the step's slot renders "Check in the platform" (code, not the model).
- The OTA copy limits (`schemas/marketing_partners.py`) are read from here, so one number serves both.

### 2.4 Dynamic generation (`services/sops/generate.py`)
1. **Inputs in code** (`sops/inputs.py`): brand name, `business_kind`, `business_profile`, properties (+ address/city),
   effective published records (packages, destinations, stay rules, discount policy) via `get_effective` / `sales_gateway`,
   `marketing_context.business_facts`, approved active `media_assets` with tags, latest Google reviews, website URL + `/links`,
   price mode. `inputs_sha` = hash of what each step uses.
2. **Code fills** what must not be invented: ranked category list (catalogue `applies_to` rank for this kind), photo order
   (catalogue `photo_spec.order` × vision tags, `people_ok` respected, best resolution first), NAP values, links, hours,
   limits, due dates.
3. **The model fills text slots only**: description, short bio, Q&A pairs (from KB + business data only), offer text, post
   ideas, review-reply drafts. Route `sop_generate` (NVIDIA `openai/gpt-oss-20b` + Gemini low-model fallback, 60 s, empty/
   invalid tool output counts as a failure → one Gemini retry); prompt `sop-generate-v1`; facts JSON only; one call per version.
   Add to `_TASK_ROUTES`, `_GEMINI_FALLBACK_TASKS`, `prompt_versions`, `tests/adapters/test_llm_routing.py`, CLAUDE.md table.
4. **Guards**: length = catalogue `text_limit`; `price_disclosure` = `handoff` → no figure in any text meant for the public
   (`strip_prices`, Studio `price_policy`); `grounded` → only a `sales_gateway` figure; `marketing_lint` HIGH (number not in
   facts, guarantee, competitor) or `avoid` word → that slot falls back to the fixed text ("Use your description from Business
   profile" / "Write this yourself"). Internal instructions to the owner may quote the tenant's own published discount policy
   (D6).
5. OTA listing copy comes from the existing `marketing_ota_copies` row for that property + platform (its own task and prompt).

### 2.5 Versions and regeneration
- `sop_versions` rows are immutable (ORM `before_update` guard, like invoices). Each holds `template_version`, `rules_digest`,
  `inputs_sha`, steps (with each step's `step_sha` = hash of its instructions + values), model, prompt version, reason
  (`first | data_changed | catalogue_updated | template_updated | manual`).
- Regenerate: owner/manager button, or the nightly refresh when `inputs_sha`, `rules_digest` or `template_version` changed
  (max 1 AI version per instance per day).
- **Progress keeps on unchanged steps**: progress is keyed by `(instance, cycle, step_key)` and records the `step_sha` it was
  done against. Same sha in the new version = still done. Different sha = shown "Changed since you did it — check again" and
  counted as to-do; the old evidence stays in history.

### 2.6 Tracking
- Instance: assignee (default from settings, else the owner), status `active | paused | done | archived`, `next_cycle_at`.
- Step progress: `todo | done | skipped | not_applicable`, `done_by/at`, `due_at`, evidence asset or URL (https, shown only,
  **never fetched**), last check result, `task_id`.
- One-off SOP: due dates from `due_offset_days` at start. Recurring: beat opens a new cycle (`cycle_no+1`), new progress rows,
  one `Task` (`kind="sop"`, assignee, due) per due step. Ticking the step closes its task; closing the task from Tasks/My day
  ticks a **manual** step only (evidence/auto steps stay open with "needs a screenshot" / "HAIP will check").
- Customising (per instance `overrides`): recurrence, hidden steps, extra steps (text + manual tick), assignee.
- Audited: `sop.started|assigned|settings_changed|version_created|step_done|step_undone|step_skipped|evidence_added|check_ran|reminder_sent|archived`.

### 2.7 Reminders (existing alert pattern, no new channel)
Hourly tick: a step past `due_at` → level 1 push to the assignee (+ staff WhatsApp only if they opted in, through
`lead_alert_sender.deliver` with `PlaybookAction.playbook_key="sop"`, `wa_hold` and quiet hours respected); 3 days later →
level 2 to managers (owners if none); each level once per step per cycle. Staff WhatsApp needs a UTILITY template
`haip_staff_sop_due_v1` drafted into the pack (never auto-submitted); until APPROVED, push only (D8).

### 2.8 AI Executive hook (`services/sops/signals.py`, read-only)
`signals(db, tenant) -> list[{code, platform, instance_id, days, numbers, refs}]`, from SOP rows + the checks' last results:
| Code | Rule |
|---|---|
| `gbp_unverified` | GBP verify step not done (or check says unverified) ≥ 14 days after start |
| `gbp_no_post` | no Google post published from HAIP and no "post" step done in 30 days |
| `sop_overdue` | any step overdue > 7 days (per platform) |
| `profile_mismatch` | NAP/website/link check failed (S4) |
| `promo_window_missed` | seasonal promo cycle open, season starts in ≤ 14 days, steps not done |
| `sop_not_started` | `gbp_setup` / `instagram_profile` never started 7 days after the module is on |
The Executive's `detectors_sops.py` wraps these as catalogue entries (role marketing/SEO). Reviews unanswered stays MK7
(already built there); the SOP review step reads the same table, nothing duplicated. Whichever branch merges second adds the
detector file.

### 2.9 Data (migration **188**: master head is 182, PR #112 holds 183–184, the AI Executive 185–187; re-parent on the real
head at merge and confirm with `alembic heads`. Note: `feat/ops-segments` also carries a second `182_ops_room_board`.)
- `sop_instances`: id, tenant_id, template_key, property_id (nullable), status, assignee_id, overrides JSON, current_version_id,
  cycle_no, next_cycle_at, started_by/at, last_done_at. Partial unique: one non-archived instance per (tenant, template, property).
- `sop_versions`: id, tenant_id, instance_id, version_no, template_version, rules_digest, inputs_sha, steps JSON, reason,
  model, prompt_version, created_by. Unique (instance_id, version_no).
- `sop_step_progress`: id, tenant_id, instance_id, cycle_no, step_key, step_sha, status, due_at, done_by/at, evidence_asset_id,
  evidence_url, check JSON, task_id, reminder_level. Unique (instance_id, cycle_no, step_key).
- All three: tenant_id NOT NULL + ENABLE/FORCE RLS + guarded policy; idempotent DDL (prod runs `create_all`).
- No change to `media_assets` / `tasks` columns (new string values only). Module + capability rows in the same migration.

### 2.10 API (`endpoints/sops.py`, `/api/v1/sops/*`)
`GET /sops` (instances with progress + templates that apply but are not started) · `GET /sops/catalogue` · `POST /sops`
(start) · `GET /sops/{id}` (current version + progress) · `GET /sops/{id}/versions[/{n}]` · `PATCH /sops/{id}` (assignee,
overrides, pause) · `POST /sops/{id}/regenerate` · `POST /sops/{id}/steps/{key}/done|undo|skip` ·
`POST /sops/{id}/steps/{key}/evidence` (multipart ≤ 5 MB JPG/PNG/WebP/PDF, magic bytes checked, `media_storage.upload_sop_evidence`;
or `{url}`) · `POST /sops/{id}/steps/{key}/check` (queues) · `GET /sops/signals`. Never an LLM or external call in a handler.

### 2.11 Celery (exact-name routes + `tests/test_celery_task_routing.py`)
`sops.generate_version` (queue ai_scoring) · `sops.check_instance` (default) · beat `sops.tick_all_tenants` hourly :07 →
`sops.tick_tenant` (open cycles, create tasks, reminders) · beat `sops.refresh_all_tenants` 03:55 IST → regenerate changed
instances · beat `sops.check_all_tenants` 06:20 IST (S4).

### 2.12 Gating and roles
Module `sops` (D3: on by default). Capabilities:
| Cap | Roles (default) | Does |
|---|---|---|
| `sops.read` | owner, manager, marketing, reservations, concierge, foh | see SOPs |
| `sops.work` | owner, manager, marketing; others only on an instance assigned to them | tick, upload evidence, Check now |
| `sops.manage` | owner, manager | start/archive, assign, customise, regenerate |
The rules catalogue is HAIP-team only (repo), not a tenant role.

### 2.13 Screens (start from the kit; load impeccable + taste-skill + emil-design-eng before any mock-up)
- **Where**: Marketing › **Get found** (`/dashboard/marketing/sops`), nav item next to Website; Website › Google profile
  redirects to the GBP SOP; the Website launch report links here.
- **List** (phone-first `CompactRow`s): grouped by platform, each with progress "4 of 11", next due date, assignee avatar;
  "Due this week" on top; "Not started" with Start buttons; empty/loading/error states.
- **Detail**: steps as rows (number, title, status pill, due). Tapping opens a `BottomSheet` on phones / `Drawer` on desktop:
  how-to text, values with **Copy** buttons (description, bio, Q&A, offer, reply drafts, ranked categories with
  "Not confirmed" pills, photo order as thumbnails with Download), **Add screenshot** (camera on phones) / paste link,
  **Check now** (auto steps), **Mark done**. "Fill this in HAIP first" rows deep-link to Business profile / Photos / KB.
  Header: assignee, cadence, version ("Updated 3 Nov because your description changed"), Regenerate (managers).

---

## 3. SOP list per platform (S = phase)

| Platform | SOP (recurrence) | Applies to | Main steps |
|---|---|---|---|
| Google Business Profile | `gbp_setup` (one-off, S1) | all 8 kinds | claim, verify (method: check in the platform), main + extra categories (ranked from catalogue), name/address/phone match, website link, hours, photos in order, amenities/attributes, description, Q&A, messaging, review link |
| | `gbp_upkeep` (weekly, S3) | all | one post (via Studio), new photos, reply to new reviews |
| | `gbp_monthly` (monthly, S3) | all | check info still right, seasonal hours, Q&A refresh, photo order refresh |
| Google Maps / Search hygiene | `maps_hygiene` (monthly, S3) | all | same NAP on website/GBP/IG/FB/WhatsApp/OTAs, website live with structured data, search score, duplicate listings (check in Maps) |
| Instagram | `instagram_profile` (one-off, S1) | all | professional account, name with keyword, bio, link in bio (`/links`), contact/WhatsApp button, category (evidence), highlights, pinned posts, connect to HAIP |
| | `instagram_upkeep` (weekly, S3) | all | posting cadence (Studio), highlight refresh, reply to DMs/comments |
| Facebook Page | `facebook_page` (one-off, S1 if cheap, else S2) | all | category, about, website, WhatsApp button, hours, cover/profile photo, link to Instagram, connect to HAIP |
| WhatsApp Business profile | `whatsapp_profile` (one-off, S1) | all | display name = brand, about, description, address, email, website, profile photo, category ("vertical") |
| Airbnb | `airbnb_listing` (one-off per property, S2) + `airbnb_promos` (seasonal) | villa, farmhouse, homestay, service apt, boutique hotel; caravan only if the catalogue confirms it | title/summary/space (OTA copy), photo order + captions, amenities, house rules, calendar link (HAIP iCal export), discounts/promotions (catalogue), instant book (check in the platform) |
| Booking.com | `booking_listing` + `booking_promos` | hotel, resort, service apt, homestay, villa | headline/description, photos, facilities, policies, iCal, programmes (catalogue, unverified until sourced) |
| MakeMyTrip / Goibibo | `mmt_listing` + `mmt_promos` | hotel, resort, villa, homestay, service apt | title/about/highlights/house rules, photos, MMT tier programmes and package deals (catalogue; MMT Biz/Black named by the team, **unverified**) |
| Agoda | `agoda_listing` + `agoda_promos` | as Booking.com | copy, photos, promotions (catalogue) |
| TripAdvisor | `tripadvisor_listing` (one-off) | lodging kinds + travel agency (check in the platform) | claim listing, photos, description, review link |
| Review response | `reviews_reply` (weekly) | all | Google: every review answered (auto); OTA/TripAdvisor: paste the review, copy the AI draft, mark done |

Travel agencies get GBP, Instagram, Facebook, WhatsApp, TripAdvisor and reviews; no lodging OTA SOPs (switchable).

## 4. What HAIP checks itself vs what needs a screenshot

✅ now = HAIP data or a call already in the code · 🔌 = API documented, not called by HAIP yet (verify on a live call, S4) ·
📸 = screenshot or link · ✋ = tick

| Check | How |
|---|---|
| Google/Instagram/Facebook/WhatsApp connected to HAIP | ✅ integrations + `integration_health` |
| Instagram bio and name filled | ✅ `get_account_fields` |
| Instagram website link, username, account type, profile photo | 🔌 extra fields on the same call |
| Instagram category, highlights, pinned posts | 📸 (not in the API as far as the code shows) |
| Posting cadence (Instagram, Facebook, Google) | ✅ HAIP's poller + publish attempts (posts made outside HAIP: Instagram yes via the poller, Google/Facebook no) |
| Google reviews answered | ✅ `marketing_guest_reviews` |
| GBP location exists | ✅ `locations()` |
| GBP categories, description, hours, website, phone; verified or not; photo count | 🔌 Business Information + Verifications APIs (Google approval needed) — until then 📸 |
| WhatsApp display name, quality | ✅ `wa_health_service` |
| WhatsApp about/description/address/website/photo | 🔌 `whatsapp_business_profile` |
| Facebook about/category/website/phone | 🔌 Page fields |
| Website live, structured data, search score | ✅ after PR #112 (`website_quality`, `website_seo`) |
| OTA calendar link set up | ✅ HAIP iCal feed per property exists and is being polled |
| OTA bookings arriving | ✅ stays by channel (a signal, not proof of a good listing) |
| Everything on Airbnb, Booking.com, MMT/Goibibo, Agoda, TripAdvisor (copy pasted, photos, promotions, tiers) | 📸 or ✋ — no API, no scraping |
| Category choice on Google until the API is approved | 📸 |
| Same name/phone everywhere | ✅ inside HAIP; 🔌 against Google/Facebook/WhatsApp; 📸 for OTAs |

## 5. Phases

- **S1 — engine + catalogue + Google Business Profile + Instagram (all business types).** Migration 188 (3 tables + RLS,
  module, caps), `sops/catalogue.py`, `app/data/sop_rules/{google,instagram,whatsapp}.json`, inputs, generate (route
  `sop_generate`, prompt `sop-generate-v1`), versions/progress, evidence upload, manual + ✅ auto checks, endpoints, Get found
  list + detail. Templates `gbp_setup`, `instagram_profile`, `whatsapp_profile` (cheap: same fields). Website Google page
  redirects; launch report reads SOP progress. Tests: happy path, tenant isolation, wrong role, cross-tenant per endpoint; one
  test per check; catalogue/rules schema tests; routing test; Celery routing test. CLAUDE.md updated.
- **S2 — OTA listings + promotions.** Airbnb, Booking.com, MMT/Goibibo, Agoda, TripAdvisor templates per property; OTA copy
  limits moved into the rules catalogue, Agoda added to OTA copy; promo programme entries (all `unverified` until the HAIP
  team sources them); seasonal templates; Facebook Page if not in S1.
- **S3 — recurring upkeep + reminders + AI Executive signals.** Cycles, tasks, hourly tick, reminders assignee → manager,
  `haip_staff_sop_due_v1` draft, `gbp_upkeep`, `gbp_monthly`, `maps_hygiene`, `instagram_upkeep`, `reviews_reply`;
  `sops/signals.py` + `GET /sops/signals` (+ `detectors_sops.py` once the Executive branch is merged).
- **S4 — auto-checks via APIs.** Each 🔌 row: one live verification call on a demo/own account first, then the check;
  daily check beat; NAP mismatch signal.

## 6. Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| D1 | Name in the app | "Get found" (Marketing › Get found); code `sops` |
| D2 | Where the platform rules live | JSON files in the repo, changed by pull request (reviewed, dated, diffable). A DB table like `roi_benchmarks` only if non-developers must edit it |
| D3 | Module on by default for every workspace? | Yes (guidance only, nothing is sent; it replaces the Google checklist every website user already had) |
| D4 | Who on the HAIP team confirms unverified rules (e.g. Ratha's "Recreational vehicle rental agency") | Name one person; they look in the platform themselves or read a client's screenshot |
| D5 | LLM route | NVIDIA gpt-oss-20b + Gemini fallback as proposed; empty output retried on Gemini (Studio copy moved to Gemini on 24 Oct for empty replies; if that repeats here, move `sop_generate` to Gemini 3.6 Flash like `marketing_ota_copy`) |
| D6 | Discount figures in promo SOPs | Public text follows `price_disclosure`; the owner-facing instructions may show the tenant's own published discount policy (max %, floor), visible to owner/manager only |
| D7 | Does AI-written SOP text need an approval step? | No: a person reads and pastes it; lint + price guard run first. (Studio approval stays for anything HAIP posts) |
| D8 | Staff WhatsApp reminders | Push only until `haip_staff_sop_due_v1` is approved by Meta; owner submits it |
| D9 | Show SOP runs on the Studio Home timeline (`marketing_tasks`)? | No; Get found has its own list |
| D10 | One GBP SOP per business or per property (several villas at different addresses) | `optional` per property: one by default, add more |
| D11 | S1 depends on PR #112 (`business_kind`, website scores, Google page). Merge it first, or move `business_kind` to master first? | Merge PR #112 first |

## 7. Risks
- Platform rules go stale fast (OTA programmes especially): the as-of + stale report is the defence; never let the model fill
  a missing rule.
- Google Business Information / Verifications API access needs Google's approval; without it GBP checks stay screenshots.
- Instagram fields beyond `name, biography` are unverified on our token.
- Screenshots can contain guest names (reviews): evidence is private to the workspace, deleted with the instance on archive
  after 90 days (to confirm), and never used as marketing photos (`status="evidence"`).
- Many tasks on My day: one task per due step only when a step is actually due; upkeep steps grouped per cycle if it gets noisy.
