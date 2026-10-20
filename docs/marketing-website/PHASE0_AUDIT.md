# Marketing Agency + Website Builder — Phase 0 Audit

**Date**: 18 Oct 2026 · **Branch audited**: `phase0-reliability` @ `0ccd14b` (18 ahead / 12 behind `master`) · **Alembic head**: `128`
**Scope**: read-only audit for the two modules in the "Hype Marketing Agency and Website Builder" brief.
"Hype" in the brief is treated as this codebase (HAIP). No code changed in Phase 0.

Paths are relative to `backend/app/` unless they start with `frontend/`, `backend/` or `docs/`.

---

## 1. Summary

- **What already exists and can be reused:**
  - Module entitlement and capability (RBAC) frameworks.
  - A tenant-scoped RLS migration pattern.
  - Hash-chained audit.
  - The LLM router, with prompt versioning.
  - Celery, with a retry, backoff and DLQ helper.
  - Fernet-encrypted integration credentials.
  - R2 media storage.
  - Draft → publish → supersede versioning (`business_records`).
  - Guarded-UPDATE approval (AI drafts).
  - An SSRF-safe fetcher.
  - Signed outbound webhooks.
  - Instagram Business Login OAuth. **It already requests `instagram_business_content_publish` and `instagram_business_manage_insights`**, has token refresh, and has a daily insights poller.
- **Nothing exists yet for either module.** There is no site builder, content calendar, social post model, brand kit, custom domain, public lead form, image generation, Google OAuth, usage metering or media asset table.
- **Biggest blockers:**
  1. Custom domains and wildcard subdomains have no TLS or reverse-proxy story in the repo; prod is a compose VPS.
  2. No image-generation provider has been chosen.
  3. A public lead form cannot safely reuse identity enrichment, because it auto-merges on any phone or email match and so can be spoofed.
  4. There is no Google OAuth client.
  5. There is no usage table to base monetisation on.
- **Recommendation**: build both modules as new `modules` rows (`marketing_studio`, `website_builder`), with their own tables and services. Reuse existing services for identity, inquiries, availability, pricing, audit, LLM, media and integrations. Do **not** copy bookings, availability or prices into module tables.

---

## 2. Existing architecture & boundaries

| Concern | Where | Notes for the new modules |
|---|---|---|
| Tenant = workspace = brand | `models/tenant.py` (`slug` unique, `brand_name`, `brand_config` JSON, `timezone`, `llm_provider_override`) | There is no organisation or portfolio entity. A tenant has many `Property` rows. "Portfolio" exists only as a calendar UI route. |
| Tenant context / RLS | `core/database.py:63 set_tenant_context` (`app.tenant_id`); pattern in `alembic/versions/124_business_records.py` | Raw `CREATE TABLE IF NOT EXISTS`, ENABLE + FORCE RLS, guarded `CREATE POLICY`. Prod runs `create_all` at startup, so migrations must be idempotent. **RLS is not yet confirmed effective on prod** (`alembic/proposed/118_*` is unapplied); check with `backend/scripts/verify_rls_isolation.py`. App-level `tenant_id` filters remain mandatory. |
| Modules | `alembic/versions/031_module_registry.py`, add pattern `075_ai_insights_module.py`; `services/workspace_context.py` (`MODULE_FLAG_MAP`, `DEFAULT_MODULE_CODES`, `provision_default_modules`); `api/v1/deps.py:126 require_module` | Existing codes: whatsapp, instagram, calls, leads360, channel_manager, analytics, ask_haip, ai_concierge, campaigns, flow_builder, ai_insights. `requires_modules` is seeded but **not enforced**. |
| Capabilities | `services/authz_service.py` (`_ROLES`, `_DEFAULT_GRANTS`, `require_capability`); catalogue in `057_capability_registry.py`; existing-tenant grant pattern in `119_foh_conversations_send.py` | Roles: owner, manager, reservations, concierge, foh, **marketing**, compliance, read_only. The `marketing` role already exists. |
| Audit | `core/audit.py:66 append_audit(db, *, tenant_id, action, actor_user_id, target_type, target_id, payload)` | Per-tenant hash chain with an advisory lock. Use one transaction per tenant. |
| LLM | `adapters/llm/__init__.py` (`get_llm(task, tenant_id)`, `_TASK_ROUTES`), `fallback.py`, `core/prompt_versions.py` (`PROMPT_VERSIONS`, `stamp`) | Text-only interface. **No image or video adapter.** New task keys must be added to `_TASK_ROUTES` and to `tests/adapters/test_llm_routing.py`. |
| Jobs | `workers/celery_app.py` (queues transcription, ai_scoring, whatsapp, call_ingest, default); `workers/retry_policy.py task_with_retry` | Every new task needs an exact-name route (`tests/test_celery_task_routing.py`). |
| Credentials | `models/integration.py` (`kind` is a free string, `credentials_kms_blob` is Fernet despite the name, `config` JSON); `core/encryption.py` | One global key, no rotation. `decrypt_credentials` returns `{}` on failure, so callers must treat empty as an error. |
| Integration health | `services/integration_health.py classify()` | New kinds need `LABELS` entries. Token expiry is read from `config.token_expires_at`. |
| Media | `services/media_storage.py` (R2 via boto3, single bucket, tenant-prefixed keys, `get_presigned_media_url` GET only) | No asset table, no presigned PUT, and size limits are set per endpoint. |
| SSRF | `core/url_safety.py assert_public_url`, `safe_get` (re-checks each redirect) | Use for any fetch of URLs a user supplies. |
| Webhooks in | `core/webhook_security.py verify_meta_signature[_any]`; `services/webhook_verify_service.py` (per-tenant verify token) | No processed-event table. Dedup is per entity (`channel_message_id`) or Redis `idem_check_and_set`, which fails open. |
| Webhooks out | `services/webhook_service.py` (`EVENTS`, `queue_event`, HMAC `ts.body`, ~22h backoff) | Easy to add `website.form_submitted`, `content.published`. |
| Public API | `public_api/app.py` at `/api/public/v1`, API-key scopes | Read-only bookings/properties plus messaging. **No inquiry-create endpoint.** API-key auth is wrong for a browser-facing site form. |
| Frontend | Next 16.2.6 (`frontend/AGENTS.md`: breaking changes, read `node_modules/next/dist/docs/`), React 19, Tailwind 4, react-query, axios `frontend/src/lib/api.ts`; UI kit `frontend/src/components/ui/kit/`; nav `frontend/src/components/layout/nav.ts` | **Nav is role-gated, not module-gated.** `useModule()` exists in `WorkspaceProvider.tsx`, but nothing calls it and it fails open while loading. `frontend/src/middleware.ts` has a hardcoded subdomain map and an explicit matcher list. No zod, DOMPurify, dnd-kit or rich-text editor. |
| Deploy | `docker-compose.prod.yml` (api, worker, beat, frontend, whatsapp-bridge, redis, flower) on a VPS; Supabase Postgres; R2 | No nginx/Caddy/Traefik/ACME config in the repo, and no wildcard DNS. `deploy-staging.yml` / `deploy-prod.yml` target ECS and `main` and look stale. |

---

## 3. Directly relevant existing capabilities

### 3.1 Instagram (Module A)
- **OAuth**: `api/v1/endpoints/integrations.py`.
  - Endpoints: `start_instagram_oauth` (L446) and `instagram_oauth_callback` (L502).
  - Scopes at L475-481 already include **content_publish** and **manage_insights**.
  - The callback produces a 60-day token on `graph.instagram.com`. The client secret is a per-tenant `app_secret` pasted beforehand (`connect_instagram_manual` L379).
- **Refresh**: `workers/tasks/refresh_instagram_token.py` (daily). Credential checks: `workers/tasks/check_meta_credentials.py`.
- **Adapter**: `adapters/instagram/meta_graph.py InstagramGraphAdapter`.
  - Covers DMs, comments, `get_account_insights`, `get_account_engagement_totals`, `get_follower_demographics`, `get_recent_media` and `get_media_insights`.
  - No paging, rate-limit handling, retries or host pinning.
  - **No publish calls** (no `/media` container, `/media_publish` or container-status polling).
- **Insights**: `workers/tasks/instagram_insights_poll.py` stores daily `InstagramInsightsSnapshot` / `InstagramPostSnapshot` (the models are defined inside the worker file). They are served at `api/v1/endpoints/instagram_insights.py`, with UI at `/dashboard/instagram-insights`. **This is the measured-data source for social audits.**
- **Pattern to copy for robustness**: `adapters/marketing/meta_ads.py` (`MetaAdsError.rate_limited` / `.bad_token`, host pin incl. `paging.next`, resumable backfill state).

### 3.2 CRM, bookings, content (Module B)
- **Lead creation template**: `services/inquiry_service.py create_manual_lead` (L276). It goes through `identity_service.resolve_gid` → consent → open-inquiry reuse → `resolve_entry_stage_id` → `assign_new_lead`. `InquirySource.WEBSITE` exists, but nothing uses it.
- **Identity**: `services/identity_service.py`. `_write_consent` (L188) is hard-coded to `source="agent_manual"`, `channel="crm"`. `Consent` already has `proof_ip`, `proof_user_agent`, `notice_version`, `notice_text_hash` and lists `web_form` as a channel.
- **Availability (authoritative, read-only)**: `services/calculator_service.py availability_report` (L269) / `is_open` (L323). These cover Stays, `BlockedDate` (iCal/Rentalwise imports) and the Ratha vehicle pool, and expose no prices.
- **Pricing gate**: `services/price_policy.py price_mode(tenant)`. Ratha is `handoff`, meaning never show a price. Price sources are `calculator_service.build_quote` and `sales_gateway.quote_package`.
- **Content sources**:
  - `Property` (description, amenities, photos JSON, faqs, brand_voice, location, capacity).
  - `sales_gateway.list_packages/get_destination/get_itinerary/policy_check` (published `business_records` only).
  - Knowledge base (`knowledge_service`).
- **Attribution**: `models/lead_attribution.py`. It is Meta CTWA only, and `conversation_id` and `destination_channel` are NOT NULL. There are no UTM, gclid or fbclid fields anywhere.

### 3.3 Brand
- `brand_config.branding_theme` (`api/v1/endpoints/tenants.py BrandingTheme`) holds primaryColor, logoUrl, fontFamily, companyName, tagline and similar.
- The logo is stored as a **base64 data URL**.
- `PATCH /tenants/me` deep-merges arbitrary keys without a schema.
- There is no business profile (contact details, social links, GST, address).

---

## 4. Missing capabilities & technical blockers

| # | Gap | Blocks | Proposed resolution |
|---|---|---|---|
| B1 | No TLS or routing for tenant subdomains and custom domains | Phase 2 publish, Phase 3 domains | **Decided (D1):** Caddy on-demand TLS on the VPS. Its `ask` endpoint allows only verified hostnames. Separate sites apex with a wildcard cert via DNS-01. Still open: which apex domain, and a DNS API token. |
| B2 | No image generation provider | Phase 1 creatives | **Decided (D2):** templates only in Phase 1, using uploaded or library photos with text overlays rendered by Pillow (already a dependency). AI image generation will sit behind a new `adapters/image/` router; provider still to be chosen. |
| B3 | Public form → `enrich_guest` auto-merge (`services/identity_resolution.py:231-235`) | Phase 2 CRM capture | The web path calls `resolve_gid` on the **phone only**. Email is attached without merging (a new `merge=False` option, or a queued merge suggestion). This needs a small, tested change in identity code. |
| B4 | No Google OAuth client, no GA4 or Search Console code | Phase 3 | A generic OAuth-client helper: single-use state nonce in Redis, refresh-token storage in `Integration`. Consider calling REST over `httpx` instead of adding google-api-python-client (dependency justification). |
| B5 | No usage / metering table | Phase 4 monetisation | Add `usage_events` in Phase 1 so the data already exists by Phase 4. |
| B6 | No media asset table, no direct upload | Both modules | New `media_assets` table and presigned PUT, with server-side MIME/size/dimension checks via Pillow. |
| B7 | No schema validation or sanitisation libraries | Website schema | Backend: Pydantic v2 discriminated unions (already a dependency). Text is plain text or a tiny markdown subset rendered by our own components, with **no stored HTML**, so neither bleach nor nh3 is required. Frontend: render via React (auto-escaped). No `dangerouslySetInnerHTML`. |
| B8 | IG OAuth `state` is a stateless JWT (replayable within 10 min); the callback returns raw HTML containing error text | Module A connection lifecycle | Single-use nonce, plus a redirect back to the frontend with an error code. |
| B9 | IG adapter has no paging, rate-limit handling or retries; Graph versions are mixed (v20/v21) | Insights backfill, publishing | Add a `MetaAdsError`-style error class, host pin, and bounded retries for the publish path. |
| B10 | Nav has no module gating; `useModule` fails open | UI gating | Add `module?` to `NavLink`. Server-side `require_module` stays the real gate. |
| B11 | `npm run gen:api` does not exist (CLAUDE.md step 8 is stale) | Frontend types | Keep the current convention (inline types plus axios), or add openapi-typescript as a separate decision. |
| B12 | Inquiry attribution | Phase 4 attribution | Extend `lead_attribution`: make `conversation_id` nullable and add `utm_*`, `landing_path`, `referrer`, `website_project_id`. Do not create a parallel table. |

---

## 5. Pre-existing defects found (not fixed; out of scope unless you ask)

1. **Module activation is broken.** `api/v1/endpoints/workspace_context.py:93/107` calls `activate.delay(..., actor_id=...)`, but the task signatures are `activate(self, workspace_id, module_code, activated_by)` (`workers/tasks/module_activation.py:24/75`). This will raise `TypeError` in the worker. The new modules depend on this path.
2. **Owners can self-activate any module code.** There is no plan or entitlement check, and `requires_modules` is not enforced. Relevant to monetisation.
3. **`POST /inquiries`** (`api/v1/endpoints/inquiries.py:57`) writes `source="web"`, which is not an `InquirySource` value, and bypasses `identity_service`. It is also the only path that fires the `new_inquiry` automation trigger.
4. The **placeholder "Unassigned" property** (`vehicle_pool.py:42`, `is_active=True`) is not filtered out of `availability_report` or public `/properties`. A public site would list it.
5. **NextAuth `GoogleProvider` is still wired**, though only when `GOOGLE_CLIENT_ID` is set (`frontend/src/lib/auth.ts:242`). CLAUDE.md says Google Sign-In was reverted. It is dormant, but it is a latent path that bypasses backend-checked MFA.
6. **CLAUDE.md drift**: `gen:api` (above); migration 035 is named as the module backfill, but it is actually 036; "frontend vitest green (57)" vs 16 files.
7. **Repo hygiene**: dozens of stray zero-byte files with junk names in the root, `backend/` and `frontend/`, apparently from bad shell redirects. The branch has diverged from `master` by 18 and 12 commits.
8. **Stale deploy workflows** (`deploy-staging.yml` triggers on `main` and uses ECS) do not match the VPS compose deployment.

---

## 6. Regression risks

| Risk | Mitigation |
|---|---|
| New Instagram publish code shares the integration row and token with live DM handling | Separate adapter methods. Publish failures never change `Integration.status` except on token rejection, which already flips it. Run `tests/` for instagram before each merge. |
| Requesting new IG scopes forces a reconnect | Scopes are already requested, so no reconnect is expected. Verify on Ratha's connected account that `content_publish` was actually granted (check the token's `permissions` / `/me`). |
| Website form floods the CRM or work queue | Rate limit per site and IP, honeypot, optional Turnstile, and one open inquiry per guest (existing reuse). Only phone-bearing submissions become leads (existing lead rule). |
| Second source of truth for bookings/prices | Website components store **references** (property id, package key). Values are resolved live from `calculator_service` / `sales_gateway` at render time and honour `price_mode`. |
| `create_all` on prod skips columns on existing tables (migration 128 incident) | New tables only. Any column added to an existing table (`lead_attribution`) uses an explicit `ADD COLUMN IF NOT EXISTS`. |
| Celery routing test | Exact-name routes for every new task, and new beat entries registered. |
| LLM routing test / NIM model end-of-life | New task keys go on `openai/gpt-oss-20b` (the reliable tier), with Gemini fallback for non-guest-facing generation. |
| Audit chain deadlock | One tenant per transaction in all batch jobs (scheduler, poller). |
| Middleware host routing breaks `genhaip.com` | Site hosts resolve only when the host is **not** in the app's own host allowlist. Unit test the middleware matcher. |

### Test baseline
- **Claimed** (CLAUDE.md): PG 2537 passed / 1 skipped; SQLite 2487 / 51. No CI artifact was found to confirm it (`gh run list` returned 404).
- **Measured**: the SQLite full suite was started on `0ccd14b` during this audit. Results: see §9 (filled in when the run finishes). The PG suite has not been run yet. It should be run once before Phase 1 merges, sequentially, never in parallel with SQLite.

---

## 7. Proposed architecture

### 7.1 Module registration
- Migration `129`: add `marketing_studio` and `website_builder` to `modules` (075 pattern). They are **not** in `DEFAULT_MODULE_CODES`; enable them per tenant.
- Every endpoint gets `Depends(require_module(...))` plus `require_capability(...)`.
- New capabilities, added via the 057 catalogue and the 119 existing-tenant pattern:

| Capability | Default roles |
|---|---|
| `marketing.read` | owner, manager, marketing |
| `marketing.edit` (generate, edit drafts) | owner, manager, marketing |
| `marketing.approve` | owner, manager (D3; no self-approval of a version you wrote or edited) |
| `marketing.publish` | owner, manager, marketing (can only publish an **approved** version) |
| `website.read`, `website.edit` | owner, manager, marketing |
| `website.publish` | owner, manager |
| `website.domains` | owner |

### 7.2 Shared platform additions (both modules)

| Table / service | Purpose | Justification vs reuse |
|---|---|---|
| `media_assets` | tenant_id, property_id?, r2 key, mime, bytes, width, height, sha256, alt_text, source (`upload`/`ai`/`instagram`/`property`), provenance JSON | No asset table exists. `Property.photos` stays as-is; the website reads it through an adapter rather than copying it. |
| `usage_events` | tenant_id, module, kind (`llm_tokens`/`image_gen`/`publish`/`site_pageview_batch`), provider, model, units, cost_estimate_paise, ref | Nothing records usage today. Write it from day one. |
| `brand_config.business_profile` (typed Pydantic schema, validated on `PATCH /tenants/me` for this key only) | contact, address, socials, GST, languages, tone, audience, USPs | **No new table.** `Tenant.brand_name` stays canonical, and `branding_theme` stays the visual source. Avoids a duplicate brand entity. |
| `services/oauth_client.py` | Redis single-use state, PKCE where supported, refresh-token storage in `Integration` | Needed for Google; Instagram adopts it in B8. |
| `adapters/image/` (Phase 1: template renderer only; AI providers later) | Same router pattern as LLM | No image adapter exists. |

### 7.3 Module A — Marketing Studio

**Tables (all tenant_id + RLS):**
- `marketing_strategies`: one row per generated plan. Holds `inputs` (measured snapshot ids) and `assessment` (AI text). `prompt_version`, `model`, `status`.
- `social_audits`:
  - `measured` JSON copied from `InstagramInsightsSnapshot` with source/timestamps. **Kept separate from `assessment`** (AI) so the UI can label each.
  - `generation_status`, `error`.
- `content_items`:
  - kind (`post`/`carousel`/`story`/`reel`/`promo`), channel (`instagram`), property_id?, campaign tag.
  - status (`draft` → `in_review` → `approved` → `scheduled` → `publishing` → `published` | `failed` | `rejected` | `archived`).
  - `current_version_id`, `approved_version_id`, `scheduled_at`.
- `content_versions` (**immutable**):
  - item_id, version n, payload (caption, hashtags, slides → media_asset ids, alt text), `content_sha256`.
  - origin (`ai`/`human`), prompt_version, model, generation_status, provider error.
- `content_approvals`: version_id, content_sha256, decision, actor, note, at. Also `append_audit`.
- `publish_attempts`:
  - item_id, version_id, `idempotency_key = item:version` (unique), provider container ids, provider media id, permalink, status, error, attempts.

**Rules:**
- Approve is a guarded UPDATE on `content_items`: `WHERE current_version_id = :seen AND status='in_review'`. It stores `approved_version_id` plus the sha256.
- **Any edit creates a new version and drops status back to `draft`.** The approval no longer matches, and publishing is refused.
- The publisher recomputes the sha256 of the approved version before any external call. It refuses if the hash differs or the status is not `approved`/`scheduled`.
- The unique idempotency key plus the stored container/media id mean a retried task never posts twice. The task checks for an existing `published` attempt first.
- The IG publish flow follows Meta's container model:
  1. Create a container per image (carousel children, then parent).
  2. Poll `status_code` until it is `FINISHED`.
  3. Call `media_publish`.
  4. Media must be a public HTTPS URL, so use a short-TTL presigned R2 GET.
  - Respect the account's publishing rate limit (check `content_publishing_limit` before each publish).
  - Stories and reels depend on the account type and API support; the adapter declares capabilities and the UI disables anything unsupported.
- Generation runs as a Celery task (`marketing.generate_*`, queue `default`). It never calls the LLM inline. Failures are stored on the version row and are visible in the UI.
- Reports are measured metrics only (the existing poller plus `get_media_insights` for published media ids). The AI commentary is a separate, labelled field.

### 7.4 Module B — Website Builder

**Tables (all tenant_id + RLS):**
- `website_projects`:
  - name, scope (`property`/`portfolio`), `property_ids` JSON, `subdomain` (globally unique, validated slug), status.
  - `draft_version_id`, `published_version_id`.
- `website_versions` (**immutable snapshots**):
  - project_id, n, `schema_version`, `site` JSON (validated), sha256.
  - origin (`ai`/`human`/`rollback`), parent_id, prompt_version, created_by, note.
  - Editing writes a new version and moves `draft_version_id`. Autosave can coalesce versions inside a time window. This gives revision history for free.
- `website_releases`: project, version_id, status (`pending`/`live`/`failed`/`superseded`), error, actor, timestamps.
  - Publish is a guarded UPDATE of `published_version_id`.
  - **Rollback = a new release pointing at an older version** (no mutation of history).
- `website_domains`:
  - hostname (globally unique, lowercased, punycode), project_id, `verification_token`.
  - status (`pending`/`verified`/`active`/`failed`/`removed`), dns check results, `last_checked_at`.
  - Verified via a TXT record `_hype-verify.<host>` plus a CNAME to the edge. Checked by a Celery beat task with bounded retries. No serving until `active`.
- `website_form_submissions`:
  - project_id, idempotency key (client UUID), sanitised fields, `ip_hash`, user agent.
  - `consent_id`, `inquiry_id`, `guest_id`, `spam_reason`, status.

**Page schema** (`schemas/website.py`, Pydantic v2, `schema_version`):
- `Site {theme, nav, pages[], seo_defaults, redirects[]}`; `Page {slug, title, seo, sections[]}`.
- `Section` is a **discriminated union** of hospitality components:
  - Hero, PropertyShowcase, RoomOrVehicleGrid, Gallery, Amenities, Packages, Itinerary, AvailabilityChecker, Testimonials, FAQ, Map, InquiryForm, RichText, CTA, Footer.
- Theme tokens are constrained: hex colours validated, fonts from an allowlist, spacing/radius from enums, breakpoints with per-section responsive overrides from an enum set.
- Text fields are plain strings or a minimal markdown subset (bold, italic, links with an `https`/`mailto`/`tel` allowlist). No HTML, no script, no style attributes, and no free URLs for embeds (Map uses lat/lng).
- **Data-bound components store references only.** PropertyShowcase stores `property_id`; Packages stores keys; AvailabilityChecker stores property scope. They resolve at render through a read-only site API using `calculator_service.availability_report`, `sales_gateway` and `price_policy`.
- AI editing: the LLM returns a **JSON patch against the schema**, which is validated server-side. An invalid patch is rejected and the reason shown. A valid patch becomes a new draft version, previewed before publish.

**Rendering & security:**
- A public Next.js route group `frontend/src/app/(sites)/[host]/[[...slug]]`. Middleware rewrites any host not in the app allowlist.
- Published JSON comes from a public read endpoint `GET /api/site/v1/render?host=` (cached by version sha).
- Strict CSP: no inline scripts, `img-src` limited to R2/CDN. No tenant-provided JS.
- Preview uses short-lived signed tokens on an isolated preview path with `noindex`, never on the tenant domain.
- Analytics: the GA4 measurement ID is a validated `G-XXXX` field. Our own component injects the gtag snippet; tenants cannot inject arbitrary script.
- SEO: per-page meta, OG, canonical, `sitemap.xml` and `robots.txt` generated from the published version, and redirects from the schema (validated paths, loop detection). Checks are a deterministic lint (missing titles, duplicates, image alt text, broken internal links) kept separate from AI suggestions.

**CRM lead capture:**
- Endpoint: `POST /api/site/v1/forms/{project}`. Rate-limited, honeypot, idempotency key.
- Calls a new `inquiry_service.create_from_website_form`:
  1. `identity_service.resolve_gid(phone, source="website")`, which sets `lead_identified_via=website`.
  2. Web consent with IP, user agent, notice version and hash.
  3. Attach email **without auto-merge** (B3).
  4. Reuse the open inquiry, or create one with `InquirySource.WEBSITE`.
  5. `assign_new_lead`.
  6. Record attribution (B12).
  7. Emit the webhook `website.form_submitted`.
- A submission with no phone is stored and shown on the website project, but it is **not** a lead (it follows the existing "lead = person with usable phone" rule).

---

## 8. Implementation sequence

| Phase | Deliverables | Exit criteria |
|---|---|---|
| **0 (this doc)** | Audit, baseline, plan | Owner signs off on decisions D1-D5 (below) |
| **1 Marketing MVP** | Migration 129 (modules, capabilities, `media_assets`, `usage_events`, marketing tables); business profile schema; social audit (measured + AI); strategy + calendar; caption/carousel/story **copy** generation + template-rendered images; versions + owner approval; UI under `/dashboard/marketing` (new tabs, existing Ads tab kept) | Approval-integrity, tenant-isolation, forbidden-role, cross-tenant, LLM failure/retry, Celery routing and migration up/down/up tests green on SQLite + PG. **No external publishing yet.** |
| **2 Website MVP** | Page schema + component library; AI initial draft; visual editor; AI patch editing; versions/releases/rollback; Hype subdomain serving (requires D1); web form → CRM | Draft/published separation, rollback, sanitisation and schema fuzzing, form dedup/consent/spoof-merge, preview token and middleware tests |
| **3 Portfolio + domains + SEO + Google** | Multi-property projects, custom domains + verification + TLS, SEO lint, sitemap/redirects, Google OAuth + GA4 + Search Console read | Domain verification state machine, hostname-takeover tests, OAuth state replay test |
| **4 Publishing + video + attribution + billing** | IG publish (containers, rate limit, idempotency), scheduling, optional video adapters, UTM attribution into `lead_attribution`, usage-based plan limits | Publishing idempotency under retry, rate-limit stop, failed-publish UI, attribution e2e |

Each phase includes: a CLAUDE.md update (modules, migrations, endpoints, tasks, LLM routes, env vars), API docs under `docs/marketing-website/`, known limitations, and test evidence.

### Owner decisions (18 Oct 2026)
- **D1 Edge — Caddy on-demand TLS on the VPS, separate sites domain.**
  - Caddy sits in front of the frontend container.
  - `on_demand_tls.ask` points at an internal endpoint that returns 200 only for `website_domains` rows in `verified`/`active` state, plus our own sites-domain subdomains.
  - Hype subdomains live on a new apex, kept separate from `genhaip.com`, so tenant pages cannot read or set app cookies. The owner still has to choose and buy this domain.
  - Wildcard cert for that apex via a DNS-01 challenge (needs a DNS provider API token).
  - Consequences we own: renewal monitoring, Let's Encrypt rate limits, and the VPS as a single point of failure with its IP exposed. Add a cert-expiry check to `integration_health`-style monitoring.
- **D2 Images — templates only in Phase 1.**
  - Tenant photos plus brand overlays rendered with Pillow; the AI writes copy and picks layouts.
  - The `adapters/image/` router is built so that an AI provider can be added later.
- **D3 Approval — owner and manager get `marketing.approve` by default.**
  - This is a deliberate change from the brief's owner-only rule.
  - A manager cannot approve a version they generated or edited.
  - The owner can remove manager's grant in the permissions matrix (audited).
- **D4 — Fix the module-activation kwarg bug in its own PR before Phase 1**, with a test that calls the tasks using the endpoint's kwargs. `requires_modules` enforcement is out of scope.
- **D5 — Merge `phase0-reliability` → `master` first**, then cut branches from `master`: `fix/module-activation`, then `feat/marketing-studio`.
  - The "12 behind" count is only PR merge commits #25–#36; master has no unique work.
  - Nothing is pushed and no PR is opened without the owner's explicit approval.

---

## 9. Verification evidence (Phase 0)

- Read-only audit: four parallel code sweeps, with key claims re-checked by direct grep:
  - module activation kwarg mismatch
  - `source="web"`
  - IG scopes L475-481
  - `enrich_guest` merge L231-235
  - conditional GoogleProvider
  - no `gen:api` script
- **SQLite full suite** on `0ccd14b` (Python 3.11.9 locally; prod runs 3.12), run 18 Oct 2026:
  - Result: **2846 passed, 1 failed, 59 skipped, 17 xfailed** in 14m31s.
  - The counts are higher than CLAUDE.md's figure (2487/51); tests have been added since that was recorded.
  - **The one failure is pre-existing test drift:** `tests/test_migration_117_postgres.py::test_alembic_head_is_117_and_118_is_not_auto_applied` asserts head `127`, but migration `128` (ical_event_bookings.locked) was added without updating it (`AssertionError: assert ['128'] == ['127']`). The fix is test-only: expect `["128"]` and add `assert get_revision("128").down_revision == "127"`. CI `test.yml` runs this file, so the branch as committed would fail CI.
- PostgreSQL suite: not run in Phase 0.
