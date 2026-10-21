# Website builder

HAIP builds, edits and hosts a complete, bookable website for each workspace. Module `website` (off by default; an
owner switches it on in Marketing › Website). Capabilities `website.read` / `website.edit` (owner, manager, marketing)
and `website.approve` (owner, manager).

## Pieces

| Piece | Where | What it does |
|---|---|---|
| Section spec | `backend/app/services/website_blocks.json` = `frontend/src/site-blocks/blocks.json` | 17 sections and their fields, 6 theme packs, 3 personalities, system pages. The two copies must be identical (`tests/test_website_ai.py`). |
| Validation | `services/website_blocks.py` | `validate_doc()` never trusts input: drops unknown sections/fields, trims text, allows links to internal paths or https/tel/mailto/wa only, images only as `asset:<media id>` (checked against the tenant's active media), always keeps the required pages. |
| Versions | `services/website_version_service.py` | Only the head draft autosaves, by the sha it was based on (409 `version_changed` otherwise). Submit freezes it; editing after submit makes a new draft and withdraws the review. Approve = publish, bound to the sha. No self-approval except the owner. `checks()` is the publish checklist. |
| First draft | `services/website_defaults.py` | Built from the business profile, properties, business type and region (theme pack by place names). No AI, nothing invented. |
| Guest API | `endpoints/website_public.py` → `/api/v1/public/sites/{host}/…` and `/api/v1/public/preview/{token}/…` | Tenant from the hostname only (`website_host_lookup()` SECURITY DEFINER, migration 158) or a signed preview token. Rate tier `_CLIENT_SITE_*`. |
| Prices | `services/website_pricing.py` | Seasonal rate > cheapest nightly rate plan > `price_per_day`. GST per night: ≤ ₹7,500 → 5%, above → 18%, none without a GSTIN; meals 5%, other extras 18%. Mixed slabs → `gst_percent` NULL and a staff task to raise the invoice by hand. |
| Bookings | `services/website_booking_service.py` | Holds (20 min, advisory lock per property, counted as taken by the website), Razorpay payment link per hold (`callback_url` back to `/book/done`), confirm only from the signed `payment_link.paid` webhook via `booking_service.create_booking`, idempotent; a clash at confirm → urgent task, no double booking. Modes: `instant`, `deposit`, `request` (task, no payment), `enquiry` (contact form only). |
| Leads | `services/website_leads.py` | Guest via `identity_service` (phone = lead signal), DPDP consent rows, one open WEBSITE lead per person for 30 days. |
| AI developer | `services/website_ai_service.py`, `website_ai_prompts.py` | Router task `website_content` (Celery `website.ai_job`, never inline). The model returns operations; `apply_ops()` validates each and refuses prices, reviews and system sections. Saves a draft; never publishes. |
| Domains | `services/website_domain_service.py` | Free `{slug}.SITES_BASE_DOMAIN`; custom domains verified by `TXT _haip-verify.<host>` + `CNAME → SITES_CNAME_TARGET` over DNS-over-HTTPS; Cloudflare for SaaS custom hostname when `CLOUDFLARE_*` is set. |
| Editor | `frontend/src/components/website/*`, `app/dashboard/marketing/website/*` | Website page (overview), editor with "AI developer" (chat + live canvas + section fields) and "Builder" (Puck 0.23, MIT), phone quick edit (bottom sheet). Sections are the same React components guests see. |
| Renderer | `sites/` (Next.js, container `haip_sites`) | Hostname → `/s/<host>/<path>` (middleware), ISR 5 min + revalidate on publish, `/_haip/api/*` proxy to the guest API, `/_haip/media/<id>` signed photo redirect, previews, sitemap, robots, JSON-LD. Copies `frontend/src/site-blocks` at build (`scripts/sync-blocks.mjs`). |

## Celery
`website.ai_job` (default), `website.after_booking` (whatsapp: invoice, email + WhatsApp confirmation, staff push),
`website.expire_holds` (beat */5), `website.verify_domains` (beat hourly :17), `website.revalidate` (after publish),
`website.send_manage_link` (whatsapp).

## Settings (backend)
`SITES_BASE_DOMAIN`, `SITES_CNAME_TARGET`, `SITES_RENDERER_URL`, `SITES_REVALIDATE_SECRET`, `CLOUDFLARE_API_TOKEN`,
`CLOUDFLARE_ZONE_ID`. Renderer: `HAIP_API_URL`, `SITES_REVALIDATE_SECRET`.

## WhatsApp templates (owner submits to Meta; email works without them)
- `haip_booking_confirmed_v1` (UTILITY): "Hi {{1}}, your stay at {{2}} on {{3}} is confirmed. Booking {{4}}. We'll share directions before you arrive."
- `haip_manage_booking_v1` (UTILITY): "Hi {{1}}, here is the link to your booking {{2}}: {{3}}"

## Not built yet
Reviews import from Google/Airbnb, promo codes, multi-language pages, blog, Google free booking links, room-level
inventory (one booking blocks a whole property, as in the rest of HAIP).
