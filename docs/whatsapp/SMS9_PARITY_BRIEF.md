# WhatsApp SMS9 parity (Nov 2026): shared brief for the four build tracks

Owner's words: "the UI must be super user friendly, no confusion, very easy to use; anyone can use the portal without a
help doc, video or user manual." This is the acceptance bar for every screen in this branch.

## UX rules (apply to every screen you touch)
- Plain words a hotel sales person uses. No jargon ("webhook" only on the developer screen; elsewhere "send to another app").
- Every setting has a one-line hint under it saying what happens, with an example ("Guests who write on Sunday get: …").
- Sensible defaults, pre-filled example text the owner can keep. A feature that needs setup shows a short empty state
  that says what it does and has ONE obvious button to start.
- Show a live preview wherever a guest-facing message is written (reuse the WhatsApp bubble look already used in
  frontend/src/components/automations/ or components/messaging/).
- Confirm destructive or bulk actions with the count ("Opt out 12 contacts?"), show a success toast with what happened.
- Loading, empty and error states on every list. Phone first: nothing scrolls sideways at 375px, tap targets >= 44px,
  inputs >= 16px. Build from frontend/src/components/ui/kit; colours only from --haip-* tokens; icons from
  frontend/src/lib/icons; no AI-looking icons or emoji (frontend/src/lib/noAiIcons.test.ts).
- Follow root CLAUDE.md: multi-tenant everywhere, audit permission-sensitive/bulk actions (core/audit.append_audit),
  SSRF guard on outbound URLs (app.core assert_public_url), no PII in logs, files < 500 lines, tests per new
  service (happy + tenant isolation) and endpoint (happy + wrong role 403 + cross-tenant).
- New table => migration + RLS + tenant_id, idempotent (IF NOT EXISTS, guarded policy); check `alembic heads` = one
  head, chain onto it. Prefer JSON in an existing column (e.g. tenants.brand_config) when it is just settings.

## Coordination
Four agents work in this same worktree (C:\Users\dasup\Desktop\HAIP\.claude\worktrees\wa-parity) at once, each on its
own track and files. Do not edit files owned by another track. Shared files (CLAUDE.md, celery_app.py routes,
api/v1 router registration, alembic): make small, additive edits and re-read the file right before editing.
SQLite test DB (backend/test.db) is shared: run only your own test files, never the full suite, and if you see
"database is locked" wait and retry. Do not commit, push, or install packages. Do not start dev servers.
Another branch (feat/wa-flow-canvas) is rebuilding the Flow Builder canvas and flow_engine: do NOT touch
backend/app/services/flow_engine.py, backend/app/workers/tasks/flow_engine.py or frontend/src/app/dashboard/messaging/flows.
In backend/app/workers/tasks/whatsapp.py keep any edit to ONE small call into your own new service (the canvas branch
edits that file too).

## Tracks
A. Inbox + keyword replies: file attachments from the inbox composer; several files per WhatsApp keyword reply.
B. Contacts: lists, bulk actions, bulk enrol into a drip/flow, 30-day contact growth chart, developer API contact CRUD.
C. WhatsApp settings: business hours with off days + holidays, first-message welcome, location reply, editable STOP/START.
D. Integrations: missing webhook events, API usage log, Google Sheets lead sync.
