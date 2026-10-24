# Website builder v2 — W1: spec + renderer

Plan: the "HAIP Site Builder Plan" page (25 Oct 2026). W1 ships the format and the renderer; the AI art director (W2),
references (W3), editing + lead attribution (W4) and the extra motion presets / publish gates (W5) build on it.

## The SiteSpec

A v2 site is an ordinary `site_versions` row whose `doc` carries `"spec_version": 2`. No new table or migration: drafts,
submit/approve/publish, rollback and the sha256 integrity check are unchanged (`website_version_service`). A doc without
`spec_version` is a v1 block document and takes the v1 path exactly as before.

```json
{ "spec_version": 2,
  "site":   { "name": "...", "tagline": "...", "ref_prefix": "WW", "contact": {"phone","whatsapp","email","address"}, "social": {} },
  "tokens": { "palette": "forest-amber", "display": "fraunces", "body": "figtree", "radius": "soft", "motion": "calm" },
  "pages":  [{ "slug": "/", "title": "Home", "nav": false, "seo": {"title","description"},
               "sections": [{ "id": "hero", "type": "hero", "variant": "fullbleed-image", "slots": {"headline": "..."} },
                            { "id": "packages", "type": "packages", "variant": "cards-3", "source": "business_data:packages" }] }] }
```

- Schema: `backend/app/schemas/site_spec.py`. Catalogue (types, variants, sources, palettes, fonts, radii):
  `backend/app/services/website_spec_v2.json`, copied to `frontend/src/site-blocks/v2/spec.json` (a test compares them).
- Strict: unknown keys, section types, variants or sources are rejected (422 `spec_invalid` with every problem), never repaired.
- Palette: a named preset or `{name, ink, surface, primary, accent}`. Every text/background pair the renderer paints is checked
  for WCAG AA in code (`contrast_problems`): body and muted text, links, button text 4.5:1; the accent (large text, rules) 3:1.
- Fonts: a fixed list of OFL faces (display: Fraunces, Bricolage Grotesque, Instrument Serif, DM Serif Display, Cormorant
  Garamond, Playfair Display; body: Figtree, Inter, Karla, Manrope, Source Sans 3, DM Sans). W1 loads them from Google Fonts
  like the v1 packs; W5 self-hosts them.
- A price typed into any slot, SEO text or site detail is rejected (`price_policy.detect_price`), in both price modes.

## Sections (8 types x 3 variants)

| Type | Variants | Bound from (server-side, `website_bindings.py`) |
|---|---|---|
| hero | fullbleed-image, split, centered-minimal | slot photo, else the newest approved library photo |
| packages | cards-3, comparison, feature | published retail packages in effect today (`business_data_service.list_effective`) |
| itinerary | timeline, accordion, day-cards | a published itinerary (slot `key`, else the first) + its destination |
| gallery | masonry, filmstrip, grid | slot photos that are approved, else approved library photos (`marketing_photos.library`) |
| reviews | quote-carousel, grid, rating-strip | `marketing_guest_reviews` with recorded consent, 4-5 stars; average over all rated |
| faq | accordion, two-column, compact | `knowledge_entries` faq, active, approved, not stale, workspace-wide |
| contact | split, card, minimal | the spec's `site.contact`; map = a "Get directions" link (no third-party embed) |
| booking-cta | sticky-bar, banner, inline-form | WhatsApp + call; inline-form reuses the v1 enquiry form (`/enquiries`) |

A section with nothing to show is not rendered; the publish checklist warns instead (`website_spec_service.checks`).

## Price policy

`brand_config.price_disclosure`:
- `handoff` (default): no figure anywhere. Package cards say "Get the price on WhatsApp". Bound text that looks like a price
  (a figure typed into a package summary or FAQ) is dropped before it leaves the server.
- `grounded`: one figure per package, the live `package_pricing_service.quote` for a stated sample (shortest stay, 2 adults,
  14 days out), shown with what it covers. A refused quote shows no figure.

## WhatsApp reference codes

Every WhatsApp link pre-fills `... (Ref WW-HOME-HERO)`: `PREFIX-PAGE-SECTION`, deterministic (`website_bindings.ref_code`),
prefix = `site.ref_prefix` or the name's initials. The rendered link carries `data-wa-ref`. Parsing inbound codes into
lead attribution is W4.

## API and render path

- `POST /api/v1/websites/draft/v2` (module `website`, `website.approve` = owner/manager): `{"spec": {...}}` or
  `{"seed": "starter"}`. Creates a NEW draft version (audited `website.spec_v2_draft`); the live site changes only on publish.
- Public bootstrap returns `spec_version: 2`, the spec, `theme` (CSS variables + font link), `bound`, `page_wa`, `assets`.
- `sites/`: `isV2()` picks `SiteRendererV2` (`frontend/src/site-blocks/v2/`) or the v1 `SiteRenderer`; preview, sitemap and
  `/links` handle both.
- The classic editor shows a notice with a preview button for a v2 draft; the AI developer refuses v2 drafts (W2 replaces it).

## Rendering rules

Server components only; CSS variables from `website_spec_service.theme` (colour maths lives in Python, once). Container
queries so a phone-width preview lays out like a phone. Gutter 20px+ at 375px, no page-level sideways scroll (strips and
carousels scroll inside themselves), tap targets 44px+. Motion `calm`: CSS scroll-driven fade + rise and cross-document View
Transitions, transform/opacity only, nothing under `prefers-reduced-motion`. No new npm dependencies; never GSAP.

## Demo

`backend/scripts/seed_local_demo.py` now ends with `scripts/_demo_site.py`: itineraries, FAQs and consented reviews for the
made-up Wanderwheel Caravans, then a published three-page v2 site that uses all 24 variants.

## Left for later phases

W2 art director (brief, sitemap/wireframe/style approvals, AI writes specs); W3 references; W4 chat + click-to-edit,
parsing `data-wa-ref` codes into leads, forms with page/section, funnel report; W5 editorial/cinematic motion, more section
types, image pipeline (AVIF/WebP sizes), self-hosted fonts, JSON-LD per section, Lighthouse/contrast publish gates, a
policies page for v2 (until then a v2 site can't take online payments: the checklist blocks it).
