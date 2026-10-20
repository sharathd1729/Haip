# Google Business Profile into the knowledge base: design note (not built)

Status: design only, Oct 2026. Nothing is exposed. HAIP has no Google integration today (no `Integration` kind for Google, no
OAuth client, no Google adapter); `User.google_id` is an unused column from the reverted Google Sign-In.

## Why

The owner wants the bot to know what the public already reads about the business: the Google listing's description, hours,
questions and answers, posts, and what reviewers say. Today the bot only knows what the team types, the website pages the team
imported, and (from this release) Instagram posts and running ads.

## Which API

Google Business Profile APIs (the successor of the Google My Business API v4), all with the tenant's own Google account through
OAuth 2.0 (the listing owner or a manager on it grants access; no scraping, no Places API reading of other businesses):

| What | API | Notes |
|---|---|---|
| Accounts and locations | `mybusinessaccountmanagement.googleapis.com/v1/accounts`, `mybusinessbusinessinformation.googleapis.com/v1/{account}/locations` | pick the location once, like the Meta ad account |
| Description, categories, hours, special hours, attributes | Business Information API `locations.get` (`readMask=title,profile,regularHours,specialHours,categories,serviceItems`) | |
| Questions and answers | Q&A API `mybusinessqanda.googleapis.com/v1/{location}/questions` | Google has been winding Q&A down; check availability before building |
| Posts ("updates", offers, events) | My Business API v4 `accounts/{a}/locations/{l}/localPosts` | still v4 |
| Reviews | My Business API v4 `accounts/{a}/locations/{l}/reviews` | |

OAuth scope: `https://www.googleapis.com/auth/business.manage` (the only scope these APIs accept; it is a sensitive scope, so the
Google Cloud project needs Google's verification and the Business Profile API access request approved before production use).

## What we would ingest, and how

Same rules as the Instagram sync (`services/knowledge_sources.py`):

* one knowledge entry per item, `source="google_business"`, `source_ref` = `gbp:desc`, `gbp:hours`, `gbp:post:<id>`,
  `gbp:qa:<id>`, `source_published_at` = the item's own time; idempotent upsert, removed items marked out of date;
* description, hours and the owner's own Q&A answers: pending approval unless `knowledge.auto_approve_social` is on;
* posts: the same, and an offer post with a price is flagged `mentions_price` and always waits for the owner (prices only ever
  come from published business data; figures are stripped from knowledge text before the concierge sees it);
* reviews: NOT knowledge. A reviewer's sentence is an opinion, not a fact the bot may repeat. They would feed a separate
  "what guests say" summary for the owner (Voice of Guest, a future module), never the reply prompt. Reviewer names are personal
  data and are not stored in the knowledge base.

Token: encrypted in `integrations.credentials_kms_blob` (kind `google_business`), refresh token rotated by a beat task like
`instagram_token.refresh_all_tenants`; host pinned to `*.googleapis.com`; disconnect deletes the token and the API-sourced entries.

## To build it later

1. Google Cloud project: enable the Business Profile APIs, request API access, OAuth consent screen verification for
   `business.manage`.
2. Integration + OAuth flow (state single-use in Redis, like the Instagram Business Discovery connection).
3. `adapters/google/business_profile.py` (mocked HTTP in tests), `knowledge_sources.sync_google_business`, a route in
   `celery_app.py` and the routing test, a source badge "Google" on the knowledge page.
