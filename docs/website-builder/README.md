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

## v2 (SiteSpec) sites: booking and prices (verified 3 Nov 2026)
A v2 site books and pays on the SAME path as v1: `/availability` -> `/quote` -> `/holds` (Razorpay link) -> signed
`payment_link.paid` webhook -> `on_hold_link_paid` -> `create_booking` (Stay, payment ledger, balance instalment, lead Sold,
`website.after_booking` queued) -> the dates show as taken and a second guest gets 409 `dates_taken`. Tests:
`backend/tests/test_website_v2_booking.py`.

- **What a guest gets** = `website_spec_service.guest_terms(tenant, site, doc)`, used by the v2 bootstrap, `/quote`,
  `/availability` and `/holds`. A v2 site follows the tenant's `brand_config.price_disclosure`: `grounded` shows prices and
  keeps the site's booking mode; `handoff` (default) shows no figure and turns `instant`/`deposit` into `request` (dates +
  details, a "requested" hold and a high task; the team confirms the price and sends the link). v1 sites keep `show_prices`.
- **Booking section** (`frontend/src/site-blocks/v2/booking-v2.tsx`): instant/deposit = price summary from `/quote`,
  policies checkbox, "Pay ₹X securely" -> Razorpay ("Pay by UPI, card or netbanking": UPI named first; the Razorpay page
  itself chooses the order). request/enquiry = `/enquiries` (lead with dates, no payment). Variant `with-rates` puts each
  free day's nightly rate in the calendar (grounded only).
- **Prices come from the website price engine only** (`website_pricing`, the one that sets what the guest pays):
  stays/booking "From ₹X per night" = `from_price`, the calendar = `rate_calendar` (seasonal > cheapest nightly plan >
  `price_per_day`, per date; a date with no rate is left out), the total = `quote`. Packages keep their
  `package_pricing_service.quote` sample (bindings `_price`). Nothing is typed into the spec. `calculator_service` (staff
  calculator, flat 12% GST) is NOT used for the website: its GST differs from what the website charges.
- **Pages every v2 site has** (sites app, `systemPage` in `SiteRendererV2.tsx`, drawn with the v1 parts in the site's
  palette) unless the spec has its own: `/policies` (bootstrap `policies` = cancellation / payment / stay rules records),
  `/book/done` (Razorpay's return: waits for the webhook), `/my-booking` (confirmation links). Footer links Policies. The
  publish checklist no longer blocks a paying v2 site on "Policies page".
- **Stays offered** = the site's chosen properties (`settings.property_ids`), the same list `/availability`, `/quote` and
  `/holds` accept.
- **Missed webhook**: `payment_reconcile_service.reconcile_tenant` also asks Razorpay about website holds (held/expired, link
  lapsed less than a day ago) and books a paid one through `on_hold_link_paid`.

## Phase 2: measurement (3 Nov 2026, migration 183)
- **Settings** (Website page › What your website brought in › Tracking; owner/manager): Meta Pixel id, Google Analytics 4
  id, and "Also send from HAIP" (Conversions API) with the owner's own CAPI token (Fernet-encrypted in
  `sites.capi_token_enc`, never shown again) and an optional test event code. `GET/PUT /api/v1/websites/tracking`.
- **Consent** (sites app `components/Consent.tsx`): a DPDP cookie banner appears only when a pixel or GA4 id is set.
  Nothing from Meta or Google loads until the visitor taps Accept; "Only necessary" keeps the site cookie-less. The
  page-view beacon never sets a cookie. A "Cookie choices" link lets the visitor change their mind. Previews never load
  tracking.
- **Events, counted once**: the browser and HAIP use the same event id, so Meta de-duplicates the pair.

  | Event | When | event_id |
  |---|---|---|
  | Lead | enquiry form, or a booking request on a handoff/request site | `wl:<uuid>` (returned by the API) |
  | InitiateCheckout | a hold with a Razorpay link | `wc:<hold id>` |
  | Purchase | the paid hold became a booking | `stay:<stay id>` (the same id the ads Conversions API uses) |

  HAIP sends an event (beat `website.send_events`, every 5 min) only for a guest whose latest marketing consent is
  granted, re-checked at send; otherwise the row is `skipped` and nothing about the guest leaves HAIP. Phone, email and
  guest id are SHA-256 hashed; `fbp`/`fbc` (Meta's cookies, present only after Accept) and the browser's user agent
  help Meta match. GA4 gets `generate_lead` / `begin_checkout` / `purchase` from the browser only.
- **WhatsApp buttons**: each v2 WhatsApp link prefills "(Ref PREFIX-PAGE-SECTION)". When a guest's first message carries
  the live site's own prefix, the chat's lead stores `custom_fields.website_ref` and a lead created in the last 10
  minutes becomes source WEBSITE (older leads keep their source). Shown as a website touch in the attribution chain.
- **Report** (`GET /api/v1/websites/report?days=30`): visits -> enquiries -> bookings by source (utm_source or the
  referring site, normalised: `l.instagram.com` = `instagram`), plus which WhatsApp buttons started chats and how many
  booked. Booked value only for roles with `bookings.read`.
- Not built: GA4 server-side (Measurement Protocol needs an API secret per property), Google Ads conversion tags.

## Phase 3: Google and speed (3 Nov 2026, no migration)
- **Structured data** (`services/website_seo.py`): every live v2 page gets JSON-LD built from the data the page shows.
  The business is VacationRental (villa, homestay, farmhouse), Hotel (boutique hotel), Resort, TravelAgency or
  LodgingBusiness (caravan, service apartments, unknown), from `tenants.business_type` via `business_kind()`.
  `aggregateRating` averages EVERY rated review HAIP holds (not only the 4-5 star ones shown); `review` lists only reviews
  the guest agreed to show, first name only. `makesOffer` and `priceRange` appear only in grounded price mode. A page
  with an FAQ section also gets FAQPage. Previews carry none.
- **Photos** (`sites/src/app/x/media/[id]/route.ts`): `?w=480|640|960|1280|1920` returns the photo resized to that width
  as AVIF or WebP (JPEG for old browsers), cached a day in the browser and a week at the CDN. The v2 `Img` part writes
  the srcset and keeps width/height, so nothing jumps while loading.
- **Fonts** (`sites/src/lib/fonts.ts`): the 12 v2 catalogue fonts are self-hosted with next/font (downloaded at build,
  served from the site). A page downloads only its two. Classic v1 sites still use Google Fonts' stylesheet.
- **Publish gate** (`services/website_quality.py`): speed, accessibility and search scores out of 100 in the publish
  checklist, with what to improve. They warn only; publishing is blocked only by text colours below WCAG AA contrast.
  This is the static part of a Lighthouse audit (HAIP has no headless browser in the API).
- **Google Business Profile**: Website page › Google profile, a 12-step guidance checklist (claim, category, matching
  name/address/phone, photos, reviews, posts...). Nothing is changed on Google from HAIP.

## Phase 4: starting designs and offers (3 Nov 2026, migration 184)
- **Starting designs** (`services/website_starters.py`): boutique hotel, resort, service apartments, homestay / Airbnb-style,
  villa, farmhouse, caravan, travel agency. Each sets the palette, fonts, corners, hero layout, which sections come
  first, their variants and the tone of their headings. "Make my website" picks one from the business type
  (`website_seo.business_kind`); the content still comes from HAIP data (stays, published packages and itineraries,
  approved photos, consented reviews, approved knowledge-base FAQs), and a section with no data is left out.
- **Promo codes** (Website page › Promo codes; owner/manager; `services/website_promos.py`): percent off the nights
  (up to 90%) or rupees off the stay; check-in window, minimum nights, a usage cap, optional stays. HAIP checks the code
  (live holds count against the cap) and lowers each night's rate before GST, so the GST and the Razorpay amount are on
  what the guest really pays. A paid booking counts one use. Every create/change/use is audited. On a site that
  doesn't show prices the guest sees no amount; the code travels with their booking request for the team.
- **Seasonal offer section** (`offer`, banner or card): the owner's heading and text plus, while the code is usable,
  "15% off · use code MONSOON15 · until 30 Sep". The amount shows only in grounded price mode; a discount typed into the
  text is refused like any typed price.

## Celery
`website.ai_job` (default), `website.after_booking` (whatsapp: invoice, email + WhatsApp confirmation, staff push),
`website.expire_holds` (beat */5), `website.verify_domains` (beat hourly :17), `website.revalidate` (after publish),
`website.send_manage_link` (whatsapp), `website.send_events` (beat */5, default: Conversions API).

## Settings (backend)
`SITES_BASE_DOMAIN`, `SITES_CNAME_TARGET`, `SITES_RENDERER_URL`, `SITES_REVALIDATE_SECRET`, `CLOUDFLARE_API_TOKEN`,
`CLOUDFLARE_ZONE_ID`. Renderer: `HAIP_API_URL`, `SITES_REVALIDATE_SECRET`.

## WhatsApp templates (owner submits to Meta; email works without them)
- `haip_booking_confirmed_v1` (UTILITY): "Hi {{1}}, your stay at {{2}} on {{3}} is confirmed. Booking {{4}}. We'll share directions before you arrive."
- `haip_manage_booking_v1` (UTILITY): "Hi {{1}}, here is the link to your booking {{2}}: {{3}}"

## Not built yet
Reviews import from Airbnb, multi-language pages, blog, Google free booking links, room-level
inventory (one booking blocks a whole property, as in the rest of HAIP).
