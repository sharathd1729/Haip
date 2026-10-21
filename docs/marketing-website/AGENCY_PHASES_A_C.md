# Autopilot marketing agency: phases A–C

**Branch**: `feat/marketing-studio` (local, not pushed) · **Migrations**: 131 (run log, post history), 132 (research), 133 (publish attempts)
**Plan and owner decisions** (18 Oct 2026, Q1–Q4): `~/.claude/plans/uh-let-s-plan-a-misty-hamster.md`

## What it does
| Role | Default | What runs |
|---|---|---|
| Research analyst | Autopilot | Weekly audit (measured + own-median baseline). Competitor snapshots via Business Discovery once Facebook is connected. A research brief built from those snapshots and from posts people paste in. |
| Strategist | Autopilot | 7-day plan + calendar. It reads the audit and the research brief (`marketing-plan-v3`). |
| Copywriter | Autopilot | One draft per calendar slot (max 7). Drafts are sent for approval. |
| Designer | Autopilot | An AI image request per drafted post/promo, only if AI images are on and the workspace is under its monthly cap. |
| Video editor | Autopilot | *Phase D (template reels), not built yet.* |
| Reporting analyst | Autopilot | *Phase G, not built yet.* |
| Scheduler & publisher | **Asks first** | Owner/manager schedules approved posts; posting happens at the slot. On autopilot, approved posts are scheduled automatically. |
| Community manager | **Asks first** | *Phase E, not built yet.* |
| Reputation manager | **Asks first** | *Phase F (needs Google Business Profile API access).* |

- **Kill switch:** "Pause all" stops the weekly cycle and posting; public roles fall back to "asks first".
- **Approval:** always a person. No role approves its own output.

## API (all under `/api/v1/marketing/studio`, module `marketing_studio`)
- `GET/PUT /agency`: team roster, levels, kill switch (PUT is owner-only).
- `POST /agency/run`: start a run now.
- `GET /approvals`; `POST /approvals/{content|ai_image}/{id}/approve|reject`.
- `GET /research`; `POST /research/competitors`; `DELETE /research/competitors/{id}`; `POST /research/competitors/{id}/posts`; `POST /research/refresh`.
- Facebook Login (for Business Discovery):
  - `GET /research/facebook/oauth-start?token=` and `/oauth-callback`. The OAuth state is single-use in Redis.
  - `DELETE /research/facebook` deletes all data that came from the API.
- Publishing: `GET /content/{id}/publishing` (preflight, suggested time, attempts); `POST /content/{id}/schedule {scheduled_for?}`; `POST /content/{id}/unschedule`.
- **Beat:** `marketing_agency.orchestrate` runs hourly and fires at the workspace's local Monday 09:00. `marketing_publish.dispatch` runs every 5 minutes.

## Safety properties (tested)
- **Only the approved version is posted.** Posting goes through `approved_payload()`, and the hashes are re-checked at publish time. An edit after scheduling cancels the schedule.
- **No double posts.** There is one attempt per (content, version). Container and media ids are saved as soon as they exist. A retry first checks whether Instagram already published the container. Only one worker can claim an attempt.
- **Retries:** transient errors, quota exhaustion and media still processing retry at +5, +15 and +60 minutes. After that the attempt is marked failed, the item goes back to "approved", and the owner is notified.
- **Competitor data:**
  - Pasted links are stored as text and never fetched; Instagram forbids scraping.
  - API data is public counts only (no reach) and is deleted on disconnect.
- **Instagram needs JPEG.** Preflight blocks posts that are missing a photo or use a non-JPEG one. Story stickers can't be added through the API, so the editor shows a note.

## Needed from the owner
- **Meta:** link Ratha's Instagram to a Facebook Page and submit App Review (instagram_basic, instagram_manage_insights, pages_read_engagement) for Business Discovery. Set `API_BASE_URL`, plus `META_APP_ID`/`META_APP_SECRET` (already used).
- **Google Business Profile API:** apply for access now; it is needed for phase F.
- **Real Instagram data:** a staging deploy to run the audit, research and publishing against the real account.

## Verification
- **Tests:** `tests/test_marketing_agency.py` (12), `test_marketing_research.py` (16), `test_marketing_publish.py` (16), plus the Studio suites.
- **Real runs on the local preview (demo data):**
  - Weekly run in 125 s: 7 drafts, 6 image requests, all submitted.
  - Research brief from pasted posts in 25 s.
  - Preflight blocked a draft that had no photo.
- **Not yet done:**
  - Real Instagram publishing (needs a connected account; no post was made).
  - Real Business Discovery (needs Meta App Review).
  - The PostgreSQL suite.

## Known gaps
- Drafts from the weekly run have no photo attached. A reviewer asks for changes, someone picks a photo (new picker in the editor), and it is resubmitted. Auto-attaching approved AI images is a follow-up.
- Each publish job can tie up a `default` worker for up to about 90 s while media processes.
- SQLite returns timestamps without a timezone, so preview times show in UTC. PostgreSQL is unaffected.
