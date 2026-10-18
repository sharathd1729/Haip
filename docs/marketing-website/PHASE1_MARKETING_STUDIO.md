# Marketing Studio — Phase 1

**Branch**: `feat/marketing-studio` (from `master` @ `a87934e`) · **Migration**: `129` · **Status**: local commit, not pushed, not deployed.
Design reference: [PHASE0_AUDIT.md](PHASE0_AUDIT.md) §7.3. Owner decisions D1–D5 are recorded there.

## 1. Scope and design decisions

**In scope:**
- Business profile.
- Social audit: measured Instagram numbers plus the AI's assessment.
- AI strategy and content calendar.
- AI and human content for post, carousel, story and promo.
- Immutable versions and approval history.
- A media library with template creatives.
- Usage metering.

**Out of scope (Phase 4):**
- Publishing or scheduling to Instagram.
- Video.
- Campaign attribution.
- Billing.

The Studio does not post anything to Instagram.

| Decision | Choice | Why |
|---|---|---|
| Module | New `marketing_studio` row, `requires_modules=["instagram"]`, **not** in `DEFAULT_MODULE_CODES` | The owner switches it on (`POST /workspace/modules/marketing_studio/activate`, fixed in PR #40). |
| Business profile | `tenants.brand_config["business_profile"]`, validated by `schemas.marketing.BusinessProfile` | No duplicate brand entity. `Tenant.brand_name` and `branding_theme` stay canonical. |
| Measured vs AI | `marketing_audits.measured` (frozen copy of the IG poller snapshot) and `.assessment` (AI) are separate columns | The brief requires keeping AI opinion separate from provider data. The UI labels each block. Metric keys the AI cites that are not in the measured data are dropped. |
| Versions | `marketing_content_versions` rows are never updated. Each one carries a `sha256` of its canonical JSON. | Approval integrity. |
| Approval | Guarded UPDATE on (`status`, `current_version_id`) stores `approved_version_id` + `approved_sha256`. | A double click or two reviewers at once cannot both win. An approval of an older version is refused (409 `version_changed`). A tampered payload is refused (409 `integrity_failed`). |
| Who approves | `marketing.approve` = owner + manager (D3). Nobody but the owner may approve a version they wrote or asked the AI for. | D3 departs from the brief's owner-only rule. The owner can remove the manager's grant in the permissions matrix. |
| Edit after approval | Creates a new version, sets status back to `draft`, and records a `withdrawn` decision. | An approval never carries over to changed content. |
| Publisher contract | `marketing_content_service.approved_payload()` returns the payload only if the item is approved, the approved version is still current, and the hashes match. | Phase 4 must call this immediately before any external request. |
| Text rules | Every stored version and plan goes through `price_policy.detect_price`, applied when `price_disclosure` is `handoff`, plus the profile's `avoid` words. | Ratha never shows prices in public content. |
| AI | LLM router task keys `marketing_audit`, `marketing_plan`, `marketing_content` (NVIDIA `gpt-oss-20b`, Gemini fallback). One tool call each; the output is re-validated with Pydantic. | A model that ignores the schema produces a recorded failure, never stored content. |
| Retries | Only transient provider errors (timeout, connection, 429/5xx) are retried, twice, with backoff of 30s then 60s. Anything else fails on the first attempt with a readable error. A crash or a down broker never leaves a row `pending`. | Bounded retries; the user sees the error. |
| Images (D2) | Uploads are decoded and re-encoded by Pillow (JPEG/PNG/WebP, ≤10 MB, ≤40 MP, EXIF/GPS stripped) and de-duplicated by sha256. Creatives are the tenant's photo plus a brand-coloured text panel (1080×1350, 1080×1080, 1080×1920). | No AI imagery in Phase 1. |
| Usage | `usage_events` rows for LLM tokens (in/out/total, provider, model) and creative renders. | Phase 4 monetisation has history from day one. |

### Prompt v2 (18 Oct 2026)

`marketing-*-v2` prompts adapt techniques from Ootto-AI/claude-content-skills (MIT; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)). Each rule is enforced in the schema where it can be:

| Area | Change | How it is enforced |
|---|---|---|
| Baseline | `measured.baseline` holds each metric's median (needs at least 3 posts), each post's multiple of it, and medians by media type | Computed in `marketing_ai_service.post_baseline()`, never by the AI. |
| Audit | `stop`, `keep`, `test` lists, plus `not_enough_signal` for questions the data can't answer yet | Schema (at most 5 items per list). |
| Content | `first_comment` on captioned kinds | Price and banned-word checks cover it. |
| Carousel | Short slide 1 and one idea per slide | Prompt only. |
| Story | `sticker` (poll/question/link) and `shot_note` per frame | Validator: at most one poll or question and one link per story; a poll needs exactly two answers. |
| Plan | At most 5 pillars, plus `position`, `rotation`, `out_of_scope` | Validator: every calendar entry must use one of the plan's pillars. |

### AI images (D2 revised, 18 Oct 2026) — migration `130`

AI images are opt-in and approval-gated. NVIDIA's hosted catalog is called on the existing `NVIDIA_API_KEY`.

**Models** (`adapters/image/__init__.py`). A model is enabled only when its provider page clears it for commercial use **and** a live request confirmed its hosted endpoint.

| Model | Licence on build.nvidia.com | Status |
|---|---|---|
| FLUX.1-schnell | "ready for commercial use" (Apache-2.0) | **enabled**. `ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell`; our key passed the API's validation. |
| qwen-image | commercial + non-commercial (Apache-2.0) | disabled: the hosted endpoint isn't found (guessed paths return 404) |
| Stable Diffusion 3.5 Large | "ready for **non-commercial** use"; commercial use needs a Stability AI licence | **blocked** on licence |
| FLUX.1-dev | non-commercial only | **never** |

**Flow:**
1. **Owner switches it on.** `PUT /marketing/studio/settings {ai_images_enabled}`, which needs `settings.manage` and is audited.
2. **Request.** `POST /marketing/studio/images {prompt, model, shape}` creates a `marketing_image_jobs` row and queues Celery `marketing_studio.generate_image`. The prompt passes the price and banned-word checks. A fixed suffix keeps text, logos and watermarks out of the image (version `marketing-image-v1`).
3. **Generate.** The adapter is pinned to `ai.api.nvidia.com` and `api.nvcf.nvidia.com`, polls 202/NVCF-REQID within a 300s budget, and treats timeouts, 429 and 5xx as transient (the task retries twice). Other errors and filtered images fail the job with the reason.
4. **Result.** The image is re-encoded to JPEG and stored as `media_assets` with `source='ai'`, `status='pending_review'`, and a provenance record of provider, model, prompt, seed and licence. It is metered as `image_gen`.
5. **Review.** `POST /marketing/studio/media/{id}/approve|reject` needs `marketing.approve`. Nobody but the owner may approve an image they requested. Approve sets the image `active`; reject sets it `archived`.
6. **Gate.** Every content version is checked: each `asset_id` it references must belong to this tenant and be `active`. Otherwise it gets 422 `asset_not_usable`.

**Caveats:**
- **NVIDIA API Trial Terms.** These govern the hosted catalog. Check them, and NVIDIA AI Enterprise, before production use. This applies to the existing LLM routes too.
- **Live reliability.** On 18 Oct 2026 two real FLUX.1-schnell generations did not answer within 300s, and even a validation error took 35s. A real image has **not yet been produced end to end**.
- **Worker load.** An image job can occupy a `default`-queue worker for up to about 5 minutes per attempt.

## 2. Implementation and migration

**Migration `129_marketing_studio.py`** (head; down_revision `128`). It is idempotent.
- **New tables:** `media_assets`, `usage_events`, `marketing_audits`, `marketing_plans`, `marketing_content`, `marketing_content_versions`, `marketing_approvals`. Each has `tenant_id NOT NULL` and, on PostgreSQL, ENABLE + FORCE RLS with a `<table>_tenant_isolation` policy.
- **Catalogue rows:**
  - Module `marketing_studio`.
  - Capabilities `marketing.read`, `marketing.edit`, `marketing.approve`, with `module_code='marketing_studio'`.
- **Grants:** provisioned tenants get the missing cells per the default matrix. Existing cells are never edited.
- **Downgrade:** drops the tables and the catalogue/role rows.

**Code:**

| Layer | Files |
|---|---|
| Schemas | `schemas/marketing.py` |
| Models | `models/marketing.py`, `models/media_asset.py`, `models/usage_event.py` |
| Services | `services/marketing_content_service.py`, `services/marketing_ai_service.py`, `services/marketing_prompts.py`, `services/media_library_service.py`, `services/usage_service.py`, `media_storage.upload_marketing_media` |
| Tasks | `workers/tasks/marketing_studio.py` (`marketing_studio.generate_audit` / `generate_plan` / `generate_content`, queue `default`, exact-name routes) |
| Endpoints | `api/v1/endpoints/marketing_studio.py` |
| Registry edits | `authz_service._DEFAULT_GRANTS`, `workspace_context.MODULE_FLAG_MAP`, `_TASK_ROUTES` / `_GEMINI_FALLBACK_TASKS`, `PROMPT_VERSIONS` (`marketing-*-v1`) |
| Frontend | `app/dashboard/marketing/studio/page.tsx`, `components/marketing/studio/*`; a "Marketing Studio" button on `/dashboard/marketing`; `ROUTE_LABELS.studio` |

## 3. API (all under `/api/v1/marketing/studio`, JWT, module + capability gated)

| Method + path | Capability | Notes |
|---|---|---|
| `GET /profile` · `PUT /profile` | read · edit | PUT validates the full profile and audits before/after. |
| `GET /measured` | read | Latest stored IG numbers (`available:false` if none). |
| `POST /audits` · `GET /audits` · `GET /audits/{id}` | edit · read | POST returns 202 with a `pending` row. |
| `POST /plans` · `GET /plans` · `GET /plans/{id}` | edit · read | Period of at most 62 days. `audit_id` is optional and tenant-checked. |
| `POST /plans/{id}/content` | edit | One draft item per calendar entry. Re-running is safe. |
| `GET /content?status=` · `POST /content` | read · edit | POST can include a first payload. |
| `GET /content/{id}` | read | Item, current version, every version, every decision. |
| `POST /content/{id}/versions` | edit | `{payload, note}` → new version. Voids any approval. |
| `POST /content/{id}/generate` | edit | `{brief}` → 202. 409 if already generating. 503 (row marked failed) if the queue is down. |
| `POST /content/{id}/submit` | edit | `{version_id}`, from `draft` or `rejected` only. |
| `POST /content/{id}/approve` · `/reject` | approve | `{version_id, note}`. 409 `version_changed` / `integrity_failed` / `wrong_state`; 403 `self_approval`. |
| `POST /content/{id}/archive` | edit | |
| `GET /media` · `POST /media` (multipart `file`, `alt_text`, `property_id`) | read · edit | Presigned GET URLs valid for 15 minutes. |
| `GET /templates` · `POST /media/{id}/render` | read · edit | `{template, headline, subline}`. The text goes through the same price and banned-word checks. |
| `GET /usage?days=` | read | Totals per kind for this module. |

Errors from these endpoints look like `{"detail": {"code", "message", "problems": []}}`. Module and capability refusals keep the existing shapes.

**Configuration:** no new environment variables. The feature uses the existing `NVIDIA_API_KEY` (plus `GEMINI_API_KEY` for the fallback), the R2 settings (`AWS_*`, `S3_BUCKET_NAME`) and the Instagram integration (the daily insights poll feeds audits).

## 4. Tests (actually run, SQLite, Python 3.11.9 locally)

- `tests/test_marketing_studio_content.py`: 21 passed.
  - Full approve flow; marketing role cannot approve.
  - Manager self-approval refused and another manager allowed; owner self-approval allowed.
  - Double-approve is idempotent; an edit voids the approval and blocks publishing; a stale reviewer gets 409.
  - Tampered version gives 409; reject then resubmit works.
  - Price blocked in handoff mode and allowed when grounded; banned words blocked.
  - Four schema rejections, including an unknown `script` field; profile validation.
  - Module off gives 403; another tenant sees nothing and gets 404 on approve.
  - Generate-twice gives 409; queue down marks the row failed; audit/plan endpoints; front-of-house denied; media upload, including HTML rejected.
- `tests/test_marketing_studio_ai.py`: 18 passed.
  - An AI version is metered; schema-breaking AI output is recorded but not stored; an AI price mention is refused.
  - A non-transient provider error fails once; a transient one is raised; the task backs off then gives up; a crash never leaves a row pending.
  - Audit with no data never calls the AI; audit keeps measured data separate and drops invented metric keys; plan calendar is clipped to the period.
  - Uploads are re-encoded, de-duplicated and tenant-prefixed; PDF, SVG and empty uploads are refused.
  - Creative render works; another tenant's asset is refused; the migration grant applies once and never edits existing cells.
- **Regression set** (output of `scripts/select_tests.py` for this diff, plus LLM routing, module activation, audit and business type): **457 passed, 40 skipped (PostgreSQL-only), 17 xfailed, 1 failed.**
  - The failure was `test_foh_messaging_capability.py`, which pins the whole default matrix. I updated it to pin the three new keys too; the file now passes (59 passed).
- `tests/test_migration_117_postgres.py` head assertion moved to `129`. `alembic heads` = `129` (one head).
- **Frontend:** `tsc --noEmit --skipLibCheck` is clean. vitest: 133 passed before the new file; the new `studio.test.ts` has 5 passing tests.

**Not run (release blockers until done):**
- The PostgreSQL suite for these files, plus the fresh-DB `alembic upgrade head → downgrade -1 → upgrade`.
- A browser check. Local `haip-backend` reads `backend/.env`, whose database may be production, and startup runs `create_all`, so I did not start it.
- The full SQLite/PG suites (this change touches more than 25 backend files once tests are counted, so CLAUDE.md rule 5 applies before release).

## 5. Known limitations and risks

- **Live run on demo data (18 Oct 2026, local preview, NVIDIA gpt-oss-20b with Gemini fallback):**
  - **Audit:** ready in about 20s and read the median baseline correctly.
  - **Carousel:** 6 slides in about 35s, grounded and price-free.
  - **Plan:** 14 days via Gemini after NVIDIA timed out.
  - **Bugs this exposed, now fixed:**
    - Gemini returned 400 on `additionalProperties`/`const` in the tool schema; the schema is now reduced to Gemini's subset.
    - A plan overran the 3,000-token output and lost its tool call; there are now per-task budgets, with 8,000 for plans.
    - `out_of_scope` naming a banned word was refused; that list is now exempt from the check.
    - The Studio page had a hydration mismatch (the persisted query cache); it now renders after mount.
  - **Quality:** gpt-oss sometimes adds details not in the facts (a "fire pit"). It also wrote an odd cadence line, and once listed "Images" as out of scope. A person must still review before approving.
  - **Still to do:** a run on the real Instagram account, since the demo numbers are synthetic.
- **`gpt-oss-20b`** is the reliable tier, not the best writer. Quality needs review on real output.
- **Gemini fallback:** profile and property text can reach Google when NVIDIA fails, the same tradeoff as the internal tasks.
- **Price detector:** it also blocks "20% off" style promos in handoff workspaces. This is intentional, but owners may find it strict.
- **Audits** depend on the daily IG insights poll. With no snapshot, an audit fails with "No Instagram insights" instead of guessing.
- **No AI image provider (D2).** Creatives use Pillow's default font, so typography is basic.
- **Visibility:** the nav entry still uses the existing Marketing link (role-gated). The Studio is reached from that page; there is no module-gated nav item yet (audit B10).
- **RLS:** policies are created, but whether prod's DB role is subject to RLS is unverified (`scripts/verify_rls_isolation.py`). App-level `tenant_id` filters are on every query.
- **SQLite and the version unique constraint:** a concurrent-edit collision on `(content_id, version)` returns 409 and rolls the session back. This is safe, but on SQLite tests a rollback erases fixture rows, so that path is covered only by reasoning, not a test.

## 6. Release criteria

1. PostgreSQL run of the selected files plus the isolation gate; fresh-DB upgrade, downgrade, upgrade of 129.
2. Full SQLite and PostgreSQL suites, run one after the other.
3. Staging: activate the module, run a real audit, plan and content generation, upload and render; check the Studio at 375px and on desktop.
4. Owner review of AI output quality on Ratha's real profile before enabling there.
