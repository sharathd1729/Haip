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
