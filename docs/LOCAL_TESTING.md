# Testing HAIP on your laptop

A full copy of HAIP runs on your Windows laptop: its own database, the real app, the real AI. Everything that would
reach a guest or cost money (WhatsApp, Instagram, Meta, Razorpay, email, calls, push, file storage) is answered on
the laptop instead and written to a **fake outbox** you can read. Nothing is ever sent to a real person or charged.

What is real and what is fake:

| Real | Fake (recorded in the outbox, never sent) |
|---|---|
| The AI (NVIDIA, Gemini) with your own keys | WhatsApp messages and templates, Instagram DMs and posts |
| The database (PostgreSQL + pgvector, same as production) | Meta ads / Graph calls, Razorpay payment links |
| Background jobs (Celery worker + scheduler) | Emails (Resend), click-to-call (Vobiz/Acefone), web push |
| | Photo and file storage (a folder on the laptop instead of Cloudflare R2) |

## First time (about 10 minutes)

1. **Open Docker Desktop** and wait until it says *Engine running*.
2. In a PowerShell window, in the HAIP folder, run:
   ```
   powershell -ExecutionPolicy Bypass -File scripts\local\start.ps1
   ```
   The first run creates `backend\.env.local`, starts the database, builds every table, loads the demo business
   and prints the demo password **once**. Write it down. (To choose it yourself: `$env:DEMO_PASSWORD = "..."` first.)
3. Open `backend\.env.local` in Notepad and paste your keys after `NVIDIA_API_KEY=` and `GEMINI_API_KEY=`.
   Leave every other line as it is. Then stop and start again (steps below) so the AI picks the keys up.
4. Open **http://localhost:3000** and sign in as `owner@wanderwheel.example` (or `manager@wanderwheel.example`, `agent@wanderwheel.example`)
   with the printed password. The first page takes about a minute to appear while it compiles.
5. See what would have been sent: **http://localhost:8000/dev/outbox**. Every WhatsApp reply, payment link,
   email and Instagram post you trigger shows up here with who it was for and what it said.

The demo business is *Wanderwheel Caravans*: two vans, ~50 leads across every stage and source, WhatsApp and
Instagram chats (some waiting for a reply), calls with transcripts, bookings with payments, ads and Instagram numbers,
and a photo library. All names and numbers are made up (+91 90000 000xx).

## Every day

| To | Run |
|---|---|
| Start | `powershell -ExecutionPolicy Bypass -File scripts\local\start.ps1` |
| Stop (data is kept) | `powershell -ExecutionPolicy Bypass -File scripts\local\stop.ps1` |
| Reset the demo business | `start.ps1 -Reseed` (prints a new password) |
| Start without the scheduler (fewer AI calls) | `start.ps1 -NoBeat` |

`start.ps1` opens four windows: API, worker, scheduler (beat), website. Closing a window stops that part. Each window
also writes to `.local-data\logs\<part>.log`, so you can ask Claude to "read the local API log".
The scheduler runs the same timed jobs as production (reply recovery, briefings, marketing runs): with AI keys
pasted, those use your AI credit. Use `-NoBeat` when you don't need them.

## Testing on a scrubbed copy of production

When you need real-shaped data (real volumes, real edge cases) without real people in it:

1. On the VPS, make a dump (this only reads production):
   ```
   docker run --rm --network host -v "$PWD:/out" postgres:17 sh -c 'pg_dump "$PROD_DATABASE_URL" --schema=public --no-owner --no-acl -T "whatsmeow_*" -T "togthr_*" --exclude-table-data=refresh_tokens --exclude-table-data=personal_access_tokens --exclude-table-data=oauth_grants --exclude-table-data=guest_access_tokens --exclude-table-data=push_subscriptions --exclude-table-data=whatsapp_personal_sessions | gzip > /out/haip_prod.sql.gz'
   ```
   (`PROD_DATABASE_URL` is the `DATABASE_URL` from the VPS's `backend/.env`. Use the Postgres image version that
   matches the production server, e.g. `postgres:15` if production runs 15.)
2. Copy it to the laptop: `scp <vps>:haip_prod.sql.gz .local-data\dumps\`
3. Load and scrub it:
   ```
   powershell -ExecutionPolicy Bypass -File scripts\local\load_prod_scrubbed.ps1 .local-data\dumps\haip_prod.sql.gz
   ```
   It restores into a holding database, replaces every guest name, phone, email, message, transcript, summary and
   note, removes every token, password and saved credential, and only then makes it available as `haip_prodcopy`.
   It prints what it changed, anything still shaped like a phone or email (check that list), and one local password.
   The dump file is deleted afterwards (it holds real data); `-KeepDump` keeps it. If anything fails, the unscrubbed
   copy is dropped.
4. Start on it: `start.ps1 -Db haip_prodcopy`. Every user signs in as `<role><n>@prodcopy.example` (e.g. `owner1@prodcopy.example`)
   with the printed password. Stages, sources, amounts, dates and counts are real; people are not.

Dumps live only in `.local-data\` (git-ignored). Never put one anywhere else, never commit or share one.

## Tests

```
powershell -ExecutionPolicy Bypass -File scripts\local\test.ps1            # tests for what you changed (SQLite + PostgreSQL)
powershell -ExecutionPolicy Bypass -File scripts\local\test.ps1 push       # the before-push set (below)
powershell -ExecutionPolicy Bypass -File scripts\local\test.ps1 full       # everything, ~1 hour
```
Other modes: `gate` (tenant-isolation gate on PostgreSQL), `migrations` (one head, up/down/up on a fresh database),
`frontend` (type check + all frontend tests). Each PostgreSQL run uses its own new database and deletes it afterwards.

## Before every push

1. `test.ps1 push` is green (migrations up/down/up, isolation gate on PostgreSQL, your selected tests on SQLite and
   PostgreSQL, frontend checks if you touched the frontend).
2. Click through what you changed at http://localhost:3000, on a phone-sized window (375 px) and on desktop.
3. Open http://localhost:8000/dev/outbox and check every message, link or email your change produces: the right
   person, the right words, nothing sent twice.
4. If the change touches migrations, models, auth or more than ~25 backend files: `test.ps1 full`.

## When something goes wrong

- *"Docker Desktop is not running"*: open Docker Desktop, wait for *Engine running*, run the command again.
- *Sign-in fails*: the password is the one printed by the last seed; `start.ps1 -Reseed` makes a new one.
- *A page shows an error*: read `.local-data\logs\api.log` (or ask Claude to).
- *AI replies never appear*: check the keys in `backend\.env.local`, then stop and start again.
- *Port already in use*: something else is on 3000/8000; stop it, or run `stop.ps1` first.

How it works (for developers): `EXTERNAL_SERVICES=fake` (`backend/app/core/fake_services.py`) patches httpx,
requests and boto3 once per process; AI hosts and localhost pass through, everything else is recorded in
`.local-data/outbox.jsonl` and answered with a realistic success payload. Production refuses the setting at startup.
The local stack reads only `backend/.env.local` (via `HAIP_ENV_FILE`), never `backend/.env`.
