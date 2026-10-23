# Marketing Studio plan, phases 0-5 (owner-approved 24 Oct 2026)

Source: the plan page "HAIP Marketing Studio" (build order). Each phase lists what was built, where, and what still
needs the owner (keys, Meta/Google approvals). External services are OFF by default and never called in tests.

## Phase 0: make what's built work

- **Home + setup checklist**: `GET /marketing/studio/setup` (`services/marketing_setup.py`). Items: module, brand profile
  + voice, >= 12 library photos, >= 2 clips (optional), Instagram connected with posting permission, Facebook Login
  (optional), autonomy chosen, ads budget (optional), server keys. Each open item has one fix (a Studio tab, or
  Settings > Integrations). Server keys are named, never shown.
- **Navigation**: Home, Insights, Plan, Create, Publish, Settings; each groups the older tabs (`?tab=<leaf>`).
- **Photos**: a draft with an empty slot cannot be sent for approval (422 `needs_photos`, shown as "Needs photos" with
  an upload link). The weekly run holds such drafts and says how many; AI images are requested only for a post/promo
  still without a photo, and approving the image fills that draft (and sends an agency draft on for approval).
- **Instagram at scheduling time**: scheduling refuses when Instagram is not connected or was connected without
  `instagram_business_content_publish` (recorded at connect from the scopes Instagram granted; older connections are
  trusted until the publisher says otherwise).
- **Autopilot skips are visible**: a `marketing_tasks` row (`step=auto_schedule`, failed, with the reason), a push to
  owners/managers, and the reason on the item.
- **Activation** polls until the module is on (2 s, about a minute), and **connect buttons** fetch a fresh token at
  click time, so an old tab never lands on a raw 401.

## Phase 1: the analyst

- **Watch curve**: Meta insights add `video_thruplay_watched_actions`, `video_p25..p100_watched_actions`,
  `video_avg_time_watched_actions`, `inline_link_click_ctr` (stored on `ad_metrics`, migration 174). Hook rate =
  3-second views / impressions; hold rate = ThruPlays / 3-second views.
- **Reels**: the Instagram poller reads the 25 latest posts of the account (all of them, not only HAIP's) and adds
  `views`, and for Reels `ig_reels_avg_watch_time` and `reels_skip_rate` (in a separate call, so a refused metric never
  loses reach / saves / shares).
- **Tags**: one record per post, Reel and ad (`marketing_creative_tags`, RLS). The AI reads the post's own text
  (caption, slide text, photo descriptions, ad copy); "unknown" when the text does not show it. Format comes from the
  platform. Owners correct with `PATCH /marketing/studio/tags/{id}` (audited; corrected = final). No correction screen yet.
- **Money funnel**: spend -> chats -> leads (people with a phone) -> qualified (same rule as the KPI catalogue) ->
  booked -> revenue, per ad (lead_attribution) and per organic post (the post the lead's last named touch credits).
- **Organic tracking**: each post has a code (`c-<8>`, the same as its utm tag), an Instagram DM link carrying it as
  `ref` and a WhatsApp link prefilling it (Content drawer). Inbound matching reuses the referral capture and the first
  WhatsApp message.
- **Weekly Insights report**: Monday from 08:00 workspace time (hourly tick), stored with the AI analyst's reports
  (`kind=marketing_insights`), pushed once. Sections: verdict, money funnel, ad leaderboard, posts vs own 30-day
  median, what works by element, tired ads, context, next plan (fed to the weekly plan). Confidence words only:
  Strong / Early signal / Not enough data. Numbers in code; the AI's sentences with a number not in the facts are
  dropped; any AI failure leaves the deterministic report.

## Phase 2: the researcher (every source OFF until the owner switches it on)

| Source | Evidence | Needs | Notes |
|---|---|---|---|
| Competitor posts/Reels (collector) | platform | `RESEARCH_PROXY_URL` + the collector worker | instaloader, logged out; Apify fallback (`APIFY_TOKEN`) |
| Meta Ad Library | platform | `APIFY_TOKEN` | active ads only; India shows no spend |
| Trending audio | platform | Facebook Login connection | `GET /ig_audio` per the owner's spec, **unverified**: keep off until one live call works |
| Hashtag top posts | platform | Facebook Login connection | 30 unique hashtags per 7 days, enforced |
| YouTube trending travel (IN) | platform | `YOUTUBE_API_KEY` | |
| Google Trends daily (IN) | google | nothing | RSS |
| Google News | google | nothing | RSS, queries from published destinations / profile city |
| Competitor Google ratings + review themes | google | `GOOGLE_PLACES_API_KEY` | Places API (New); themes counted in code |
| Keyword Planner volumes | google | `GOOGLE_ADS_*` (5 keys) | Google Ads API v19, **unverified** |
| Reel reading (swipe file) | platform | `GEMINI_API_KEY` | ffmpeg cut times + vision model with the video |

- The collector runs only in the `research_collector` service (`docker compose --profile research up -d
  research_collector`), consumes only the `research_collect` queue, never logs in and never receives a tenant token or
  HAIP's Meta app. Note: it shares `backend/.env` to write its rows, so the container holds the same server secrets.
- Not built: Pinterest Trends (needs a Pinterest app + business OAuth); yt-dlp (instaloader returns the video URL).

## Phase 3: the strategist

- **Season calendar**: `brand_config.marketing_studio.season_calendar`, seeded with the plan's dates (Diwali 7-9 Nov,
  24 Nov bridge weekend, Christmas, New Year, Republic Day 2027, Holi, summer escape). Owner-only `PUT /calendar`
  (audited). No editing screen yet.
- **Theme radar** (`GET /radar`): top 3 themes for the next 8 weeks, 0-100, all in code: season lead time 20, own
  demand (guest messages naming it) 20, Google 15, platform + competitor posts 10, how similar posts did 10, gap
  (demand while competitors are quiet) 10, free vehicle nights 10, novelty 5. "Shoot by" = 21 days before the dates.
- **Shoot & collab brief** (`POST /briefs`): the plan's JSON shape (focus, must-get, shot list with size / angle /
  movement / lens / seconds / time of day / talent / props / audio / why / priority, B-roll, 5 hooks, 2-3 Reel
  scripts, captions, 2-4 week posting plan; collab: creator brief, deliverables, usage rights). The ASCI label and the
  WhatsApp tracking code are added by code. Golden-hour times are not computed.
- **Monthly strategy deck**: written on the 1st from 08:00 (or on demand); facts in code (last month vs goal, Insights
  next plan, radar, market signals, swipe hooks, briefs), prose grounded, deterministic fallback.

## Phase 4: the producer

- **Template Reel from photos** (Create > Produce, `POST /produce/reel-from-photos`): 2-5 library photos, a caption
  line each, 6-15 s, 9:16, brand look and cover frame, rendered by the existing ffmpeg/Pillow reel renderer.
  Hyperframes was not added: the server already renders Reels; a Node sidecar would be a second renderer.
- **One brief -> several pieces** (`POST /briefs/{id}/produce`, button on a ready brief): each Reel script becomes a
  Reel draft (shots as slots with the shot description), the first one again as a **trial Reel** with the second hook
  as its opening, plus a carousel (hooks) and a story (posting plan). Library photos fill what they can; the rest is
  "Needs photos" until shot.
- **Trial Reels**: `trial_params` (graduation `SS_PERFORMANCE`) on the Reel container.
- **Licensed audio**: `audio_configuration` with a trending-audio id, sent only while the owner's trending-audio source
  works. Unverified: confirm with Meta before relying on it.
- **Best posting time**: the existing suggestion from this account's own reach by hour.
- **Not built**: the `is_ai_generated` flag (no documented publishing field found); label AI visuals in the app.

## Phase 5: the judge

- **Conversions API for Business Messaging** (Ads settings, OFF by default): with "Tell Meta about bookings" on and
  a dataset id, the extra switch also sends **LeadSubmitted** (the person gave a phone number) and **QualifiedLead**
  (the enquiry passed the qualified rule) for chats that came from a click-to-WhatsApp ad (`ctwa_clid` already
  captured from the first message's referral), once each, `action_source=business_messaging`,
  `messaging_channel=whatsapp`, hashed identifiers only, only for guests whose latest marketing consent is granted.
  Purchase (bookings) works as before. Migration 177.
- **Ranking**: every HAIP content item ranked by bookings, then qualified leads, then cost per qualified lead (its
  organic results plus the ads made from it); in the weekly Insights report.
- **Opening tests**: the producer's Reel / trial Reel pairs are decided with the AI analyst's half-and-half rule
  (`learning.evaluate.decide`: keep at p < 0.05 with at least 1,000 people reached per arm, stop-loss, 14 days). The
  result says which opening to keep; nothing changes by itself.
- **Autopilot per content type** (Home > Posting by content type, owner): e.g. stories post by themselves while Reels
  wait for a person. Publishing switched off and the kill switch still stop everything.
