# HAIP — Phase 0 production verification checklist

**Local test success is not production security.** The PostgreSQL results in `HAIP_Phase0_Failure_Register.md`
(Appendix 1) prove the policy SQL and the application's tenant filters behave correctly on a clean PostgreSQL 16
with a superuser connection. They say nothing about what the **production** database role is, which tables
production actually has RLS on, or whether production data matches the migrations. Only steps 1 to 3 below
establish that, and until someone has run them and recorded the answers **production tenant isolation is
UNVERIFIED** (application-level filters are tested; database-level enforcement is not known).

**Rules for every step:** the SQL is read-only (`SELECT` only). Run it in the Supabase SQL editor or `psql`.
**Never paste passwords, connection strings, API keys or tokens into this document, a ticket or a chat**; record only
the query results below (role names and `true`/`false` flags are not secrets). Do not run anything against production that
is not on this page, and do not change configuration or data while checking.

**Read-only unless a step says otherwise.** Nothing here deploys, migrates or deletes. Run the SQL in the
Supabase SQL editor (or `psql`), and the shell commands on the VPS in `/opt/haip`.
Record each result next to the step. A step that does not give the expected result is a finding.

Compose prefix used below: `dc="docker compose -f docker-compose.prod.yml"`.

## 0. The fastest correct path: run the read-only verifier

`backend/scripts/verify_rls_isolation.py` does steps 1-3 and 4's coverage check in one go **as the database role the application really
uses**, because it runs inside the API container with the application's own connection. Nothing is typed, pasted or printed that is secret
(it never prints the connection string, a password or a token) and it reads only aggregate counts, never row contents:
```bash
$dc exec api python scripts/verify_rls_isolation.py          # exit 0 = every check passed for this role, 1 = something needs attention
```
Every statement it runs is a `SELECT` or `SET LOCAL` inside a transaction opened with `SET TRANSACTION READ ONLY` that is always rolled
back, with a 10 s statement timeout (`tests/test_verify_rls_isolation.py` fails if it ever gains a write). Its three parts:

| Part | Establishes | How to read it |
|---|---|---|
| 1 CONFIGURATION | the role, whether it is superuser/`BYPASSRLS`/a member of such a role, who owns each tenant table, RLS and `FORCE` per table, policies not keyed on `app.tenant_id`, `SECURITY DEFINER` functions | `>> THIS ROLE BYPASSES ROW-LEVEL SECURITY` means every policy is irrelevant to the app |
| 2 BEHAVIOUR | for each table where RLS genuinely applies to this role: with the tenant context set to tenant X inside a read-only transaction, how many rows of **other** tenants are visible (must be 0) and how many rows are visible with **no** context (must be 0) | `PASS` for every table is proof of isolation **for this role on those tables**. `(table looks empty: a pass here is not informative)` means the table has no rows to leak, so repeat after real data exists |
| 3 COVERAGE | tenant tables without RLS that are in neither migration 118 nor the documented exceptions | any name listed there needs a decision |

**Configuration is not proof, and proof has limits.** Parts 1 and 3 read *settings*: they say what the database is set up to do. Only Part 2 tests
*behaviour*, and only for (a) the role you ran it as, (b) tables with RLS that applies to that role, (c) the tenants that exist today. It says nothing
about tables without RLS (those rest on the application's `tenant_id` filters, covered by the cross-tenant API tests, not by the database), about other roles
(for example a worker or a script connecting with a different login), or about code that bypasses the session (a `SECURITY DEFINER` function).
It was tested locally as a superuser (it reports the bypass and claims nothing), as a restricted non-owner role before migration 118 (51 tables pass) and after
(66 pass), 0 failures; it has **not** been run against production.

The sections below give the same checks as plain SQL if you prefer to run them by hand in the Supabase SQL editor.

## 1. Which database role does the app use? (decides whether RLS protects anything)

```sql
SELECT current_user, rolsuper, rolbypassrls, rolcanlogin
FROM pg_roles WHERE rolname = current_user;
```
Run it **as the same role the API connects with** (the user in `DATABASE_URL`). Easiest from the API container:
```bash
$dc exec api python -c "from app.core.database import engine; from sqlalchemy import text; print(engine.connect().execute(text('select current_user, (select rolsuper from pg_roles where rolname=current_user), (select rolbypassrls from pg_roles where rolname=current_user)')).all())"
```
Also record, for the same role, who owns the tables and whether it can become another role:
```sql
-- table owners (the owner bypasses RLS unless the table is FORCEd)
SELECT tableowner, count(*) AS tables FROM pg_tables WHERE schemaname = 'public' GROUP BY 1 ORDER BY 2 DESC;
-- roles the app role is a member of (membership can inherit BYPASSRLS/superuser behaviour)
SELECT r.rolname AS member_of, r.rolsuper, r.rolbypassrls
FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid
WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = current_user);
-- SECURITY DEFINER functions (run as their owner and ignore the caller's tenant)
SELECT p.proname, p.proowner::regrole AS runs_as
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.prosecdef ORDER BY 1;
```
Expected: the owner of most tables is the migration/`postgres` role; exactly two `SECURITY DEFINER` functions exist,
`api_key_lookup` (migration 112) and `ical_feed_tenant` (migration 109). Any other definer function is a finding.
Reference for a **fresh** build (before the proposed migration): 52 tables have RLS, 41 of them `FORCE`d; production may differ.

| Result | Meaning |
|---|---|
| `rolsuper` or `rolbypassrls` = true | **RLS is not enforced for the app.** Isolation rests entirely on the `tenant_id` filters in code (tested). Policies are defence in depth for other roles only. (Supabase's default `postgres` role bypasses RLS.) |
| both false, and the role owns the tables | Policies apply only to tables with `FORCE ROW LEVEL SECURITY` (see step 3). |
| both false, role does not own the tables | Policies apply everywhere they exist: a query without `set_tenant_context` returns **no rows**. |

## 2. Which tenant-scoped tables have RLS?

```sql
SELECT c.relname, c.relrowsecurity AS rls, c.relforcerowsecurity AS forced
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
  AND EXISTS (SELECT 1 FROM information_schema.columns k
              WHERE k.table_schema='public' AND k.table_name=c.relname AND k.column_name='tenant_id')
ORDER BY rls, relname;
```
**Expected (today, from a fresh PostgreSQL built by `alembic upgrade head` plus `create_all`):** `rls = false` for the
16 tables in the proposed migration 118 (`guest_identities, inquiry_quotes, inquiry_stage_log, automation_rules,
automation_runs, insights, saved_views, blocked_dates, property_addons, seasonal_rates, consent_log, incidents,
instagram_insights_snapshots, instagram_post_snapshots, stays_date_quarantine, meta_quality_snapshots`) plus the 6 documented exceptions
(`users, refresh_tokens, user_invitations, oauth_grants, personal_access_tokens, grievances`). Anything else with
`rls = false` is a new finding: add it to the register. Production may differ from a fresh build (`create_all` has
run there for years), which is exactly why this query has to be run on production.

## 3. Policies and FORCE

```sql
SELECT tablename, policyname, cmd, qual FROM pg_policies WHERE schemaname='public' ORDER BY 1;
SELECT relname FROM pg_class WHERE relforcerowsecurity ORDER BY 1;
```
Expected: every policy's `qual` is `tenant_id = current_setting('app.tenant_id', true)::text`.
`FORCE` is set only on tables from migrations 002, 017, 052+ (see migration list). If the role from step 1 owns
the tables, those are the only tables RLS actually constrains.

### 3b. Do the policies cover the intended operations?

```sql
SELECT tablename, policyname, cmd, permissive, roles, (qual IS NOT NULL) AS has_using, (with_check IS NOT NULL) AS has_with_check
FROM pg_policies WHERE schemaname = 'public' ORDER BY tablename, policyname;
```
Read it like this: `cmd = ALL` covers read, insert, update and delete; a policy with only `USING` also applies that expression to new and changed rows
(PostgreSQL uses it as the `WITH CHECK`), so `ALL` + `has_using` is complete. `cmd = SELECT` alone means writes are **not** constrained by that policy.
`roles = {public}` means it applies to every role. `permissive = false` (restrictive) policies combine with AND; the migrations here only create permissive ones.
Local PostgreSQL tests prove all four operations for the 16 proposed tables (own rows allowed; other tenants' rows invisible, not updatable, not deletable;
inserting or moving a row into another tenant rejected; no context sees nothing).

### 3c. Can a `SECURITY DEFINER` function bypass tenant boundaries?

```sql
SELECT p.proname, pg_get_userbyid(p.proowner) AS runs_as, pg_get_functiondef(p.oid) AS source
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.prosecdef ORDER BY 1;
```
Expected: exactly `api_key_lookup` (migration 112) and `ical_feed_tenant` (migration 109). Read each function body: both exist because a bearer token has no tenant yet, and
each must return **only** the row matching the presented secret, never a list. Any other definer function, or one that accepts a tenant id from the caller, is a finding.
Also check who can call them: `SELECT proname, proacl FROM pg_proc WHERE prosecdef AND pronamespace = 'public'::regnamespace;`

### 3d. Does proposed migration 118 cover every remaining tenant table? (production, not a fresh build)

```sql
WITH proposed(t) AS (VALUES ('guest_identities'),('inquiry_quotes'),('inquiry_stage_log'),('automation_rules'),('automation_runs'),
  ('insights'),('saved_views'),('blocked_dates'),('property_addons'),('seasonal_rates'),('consent_log'),('incidents'),
  ('instagram_insights_snapshots'),('instagram_post_snapshots'),('stays_date_quarantine'),('meta_quality_snapshots')),
excepted(t) AS (VALUES ('users'),('refresh_tokens'),('user_invitations'),('oauth_grants'),('personal_access_tokens'),('grievances'))
SELECT c.relname AS tenant_table_without_rls_and_not_covered
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
  AND EXISTS (SELECT 1 FROM information_schema.columns k WHERE k.table_schema='public' AND k.table_name=c.relname AND k.column_name='tenant_id')
  AND c.relname NOT IN (SELECT t FROM proposed) AND c.relname NOT IN (SELECT t FROM excepted)
ORDER BY 1;
```
Expected: no rows. Any row is a tenant table that 118 does not protect and that is not a documented exception: add it to the proposal (and to
`tests/test_rls_postgres.py`) before promoting. Also run the same query without the two `NOT IN` filters to see exactly which tables 118 would change in production.

## 4. Before promoting migration 118

Do **not** `git mv` it into `alembic/versions` until all of these hold, because the API runs
`alembic upgrade head` on start and that is the deploy.

1. Step 1 shows the role. If it bypasses RLS, 118 is harmless but also protective of nothing; promote it only for
   completeness.
2. Dry run on a **copy** (Supabase branch or a restored backup), not production: apply the SQL from
   `alembic/proposed/118_rls_remaining_tenant_tables.py` (`UPGRADE_SQL`), then exercise: WhatsApp inbound, call
   ingest, inbox, leads, bookings, automations, saved views. Look for pages that suddenly load empty.
3. The migration uses `ENABLE` without `FORCE`. **Never add FORCE** until every query on those tables is audited:
   Celery cross-tenant fan-outs (`check_automation_timers`, `run_insights`, `lead_assignment.tick`) and webhook
   lookups run before a tenant context exists, and under FORCE they silently return nothing.
4. CI job `tenant-isolation-postgres` is green with **0 skipped** on the branch. (It was executed locally on
   PostgreSQL 16.14 for this review: 44 passed, 0 skipped. The first GitHub Actions run is still outstanding.)
5. Migration tested on a clean database and on an upgrade path (rows preserved): done locally
   (`test_proposed_migration_is_idempotent`, `test_applying_the_migration_keeps_existing_rows`). Not yet tested on a
   restored copy of production data.

**Rollback:** `DOWNGRADE_SQL` in the same file (drops the sixteen policies, disables RLS). It touches no data. In production
the equivalent is `ALTER TABLE <t> DISABLE ROW LEVEL SECURITY` per table; ordering does not matter.

## 5. Are scheduled jobs actually running? (D-B1)

```bash
# Tasks the worker knows about
$dc exec worker celery -A app.workers.celery_app inspect registered | grep -E "dpdp|retention|sync_hostaway|sync_retalwise|owner_digest|meta_quality|lost_reason|classify_intent"
# Rejections of scheduled names that do not exist
$dc logs --since 72h beat worker 2>&1 | grep -i "unregistered task" | sort | uniq -c
# Queues the worker consumes (celery must NOT be listed)
$dc exec worker celery -A app.workers.celery_app inspect active_queues | grep -E "name|queue"
```
**Expected today (confirms the finding):** `unregistered task` lines for `dpdp_purge.run`,
`retention_purge.nightly_purge`, `sync_all_pms.*`, `owner_digest.orchestrate`, `meta_quality_poll.poll_all_tenants`,
`lost_reason_cluster.run`. No result for them means the schedule is not firing at all — also a finding.

Stranded work on the unconsumed `celery` queue (rewrite buttons, nightly classify):
```bash
$dc exec redis redis-cli LLEN celery         # Redis broker
```
(If the broker is RabbitMQ: `rabbitmqctl list_queues name messages | grep -w celery`.)
**Do not purge it blindly.** Inspect first (`LRANGE celery 0 5`); old `tasks.rewrite_draft` jobs are stale and safe
to drop, anything else needs a look.

## 6. Before enabling any dead beat entry (decision per job)

Full per-job analysis (task name, registration, routing, side effects, first-run result on PostgreSQL, idempotency,
required staging test) is in `HAIP_Phase0_Failure_Register.md`, Appendix 2. Headlines: **retention purge crashes on
first run** (`Call.recording_url` does not exist; `VARCHAR` vs timestamp comparison), **DPDP purge fails on any guest
that still has a referencing row and deletes S3 objects before the database commit**, **owner digest cannot send**
(`send_whatsapp_message` does not exist), **Meta quality poll is a no-op** (reads a token location production does not
use). None may be enabled as they stand.

| Job | Check first | Risk if enabled |
|---|---|---|
| `dpdp_purge` / `retention.nightly_purge` | Dry-run counts below | **Deletes data.** First run could remove anything older than policy (transcripts 24 m, recordings 12 m, messages 36 m, audit 24 m) |
| `sync_hostaway` / `sync_retalwise` | `SELECT tenant_id, kind, status FROM integrations WHERE kind IN ('hostaway','retalwise');` | Writes properties/stays; Hostaway fixed in Phase 0 but never run against a real account |
| `owner_digest.orchestrate` | Who would be messaged: owners with a phone/email | **Sends outbound messages** hourly |
| `meta_quality.poll_all_tenants` | `integrations` with `kind='whatsapp_meta'` | Read-only Meta calls |
| `lost_reason_cluster.nightly` | LLM cost | LLM calls, writes themes |
| `classify_intent.run` (routing) | LLM cost | LLM job never run before |

Retention dry run (counts only, run on a copy if you can):
```sql
SELECT 'transcripts' AS t, count(*) FROM transcripts WHERE created_at < now() - interval '24 months'
UNION ALL SELECT 'messages', count(*) FROM messages WHERE created_at < now() - interval '36 months'
UNION ALL SELECT 'audit_events', count(*) FROM audit_events WHERE created_at < now() - interval '24 months'
UNION ALL SELECT 'calls with recording', count(*) FROM calls WHERE created_at < now() - interval '12 months' AND recording_s3_key IS NOT NULL;
```
Add the DPDP side (counts only):
```sql
SELECT count(*) AS tombstoned_guests_past_grace FROM guests WHERE is_deleted AND deleted_at <= now() - interval '90 days';
SELECT count(*) AS revoked_tokens_past_grace FROM refresh_tokens WHERE is_revoked AND created_at <= now() - interval '90 days';
-- rows that would block a guest purge (foreign keys to guests that the erasure flow does not clear)
SELECT count(*) AS subscribers_pointing_at_tombstoned_guests
FROM wa_subscribers s JOIN guests g ON g.id = s.guest_id WHERE g.is_deleted;
```
Expected for a deployment that went live in 2026: 0 everywhere. A non-zero count means turning the purge on will delete that
many rows on its first run — confirm that is intended before the beat entry is fixed.

Recovery to confirm before any purge is enabled: the Supabase **point-in-time-recovery window** (Dashboard, Database,
Backups) and whether the S3/R2 bucket has **versioning** on. Record both; do not paste credentials.

## 7. Deploying the Phase 0 code changes

The branch changes **application behaviour** in the places below. Phase 0.1 adds one schema change, **migration 117 (widen
`calls.ai_score_status`), which the deploy applies automatically** (see step 9).
1. `core/audit.py` — correct hash chaining. Existing rows are untouched; new events chain correctly.
2. `workers/celery_app.py` — inbox rewrite tasks now route to `whatsapp`. After deploy, click "rewrite" in the inbox once and confirm the
   task runs: `$dc logs worker | grep -E "rewrite_draft|composer_rewrite"`.
3. Hostaway sync — only reachable by connecting Hostaway or `POST /integrations/hostaway/sync`; no scheduled run (D-B1).

4. `core/audit.py` (Phase 0.1) takes a per-tenant PostgreSQL advisory lock inside each audit append and stamps `created_at` strictly after the
   chain tail. Visible effect: audit appends for one tenant now queue behind each other until their transactions commit; a wait longer than 10 s
   raises instead of hanging. Watch for new `lock timeout` errors in the API logs after deploy (`$dc logs api | grep -i "lock timeout"`); a few
   mean a slow transaction is holding the chain, many mean a caller appends audit events early in a long transaction.
5. The inbox send endpoint (Phase 0.1) releases an expired idempotency key before inserting. Effect: a retry with the same `Idempotency-Key`
   more than 24 h later now succeeds instead of failing with HTTP 500.

Deploy exactly as usual (`git pull`, `up -d --build api worker beat`). **Rollback:** `git revert` the commit and redeploy; no data is
changed by any of the three.

## 9. Is the `ai_score_status` width bug hitting production? (register P-1)

`judge.py` writes the 21-character value `skipped_no_transcript` into a `varchar(20)` column. Read-only checks:
```sql
-- 1. the column width in production (expected: 20; if it is already 40 or more, the bug is not live)
SELECT character_maximum_length FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'calls' AND column_name = 'ai_score_status';
-- 2. calls stuck in a state that this bug would produce
SELECT ai_score_status, count(*) FROM calls GROUP BY 1 ORDER BY 2 DESC;
-- 3. transcript-less calls that never reached "skipped"
SELECT count(*) FROM calls c
WHERE c.ai_score_status IN ('pending', 'failed')
  AND NOT EXISTS (SELECT 1 FROM transcripts t WHERE t.call_id = c.id);
```
```bash
$dc logs --since 7d worker 2>&1 | grep -c "StringDataRightTruncation"
```
**Interpretation:** width 20 and a non-zero count in query 3 or in the log search means the October "stop re-dispatching
transcript-less calls" fix is failing in production and those calls loop through `failed` and recovery. Zero everywhere
means no such calls have occurred yet (the bug is latent, not absent). Do not alter the column as part of checking.

**Fixed in the branch (Phase 0.1) by migration 117**, which widens the column to `varchar(40)`. It is forward-only, only ever
widens, changes no rows and takes a brief lock without rewriting the table. **Because the API container runs
`alembic upgrade head` on start, deploying this branch applies it.** After the deploy: query 1 must return 40 (or more);
`SELECT version_num FROM alembic_version` must return `117`; calls stuck at `failed` are retried by recovery and the
`StringDataRightTruncation` count in the logs must stop growing. **Rollback:** none needed or provided (a wider column is
harmless); if the deploy itself must be reverted, redeploy the previous image, the column stays wide.

## 10. Does `meta_quality_snapshots` exist in production? (register P-2)

```sql
SELECT to_regclass('public.meta_quality_snapshots') AS table_exists;
SELECT relrowsecurity FROM pg_class WHERE relname = 'meta_quality_snapshots';
```
`NULL` means the table was never created there (it exists only where `create_all` imported its module), so there is nothing to
protect yet. If it exists and `relrowsecurity` is `false`, it holds per-tenant WhatsApp quality data without RLS; it is covered by
proposed migration 118.

## 8. After release

- `$dc logs --since 15m worker 2>&1 | grep -iE "error|unregistered"` — nothing new.
- Re-run step 2; the table list must be unchanged unless 118 was promoted.
- Update `docs/HAIP_Module_Audit_M0.md` statuses with the evidence collected here.

## 11. Deploying migration 117: mechanics, order and recovery (verified against a throwaway PostgreSQL)

**How it is applied.** The backend image's `CMD` is `alembic upgrade head && gunicorn ...`, and **only the `api` service uses it**; `worker` and `beat` have their own
commands and do not run migrations or wait for `api` (`docker-compose.prod.yml`). There is a single `api` container with `restart: unless-stopped`. `alembic upgrade head` on the
current branch applies exactly one migration, `116 -> 117`.

**Recommended order** (the usual command recreates all three at once, which is acceptable because the migration is backward compatible, but this order makes a failure obvious):
1. `$dc up -d --build api` and wait until `$dc ps api` shows healthy and `$dc logs api | grep "Running upgrade"` shows `116 -> 117`.
2. `$dc up -d --build worker beat`.
3. Verify (section 9): width 40, `alembic_version = 117`.

**What the migration does and does not do.** It only widens `calls.ai_score_status` (a static check and a PostgreSQL test pin this), changes no rows, never narrows, and is a no-op if
the column is already 40 or wider. Timing: a widening `ALTER` is metadata-only but takes a brief `ACCESS EXCLUSIVE` lock on `calls`. The migration sets `lock_timeout = 10s`, so if a long
transaction is holding `calls` it **fails fast and rolls back** instead of queueing behind it and freezing every query on the table (a test proves a blocked ALTER gives up in well under 5 s
and changes nothing).

**If the migration fails** (lock timeout, or anything else): the `api` container exits, docker restarts it, and it **retries the migration on every restart**, so the API is down until it
succeeds. Forward recovery: find and end the blocking transaction (`SELECT pid, state, xact_start, query FROM pg_stat_activity WHERE state <> 'idle' ORDER BY xact_start;`), or simply wait for
the next restart attempt. Run off-peak to avoid the problem. Nothing is half-applied: PostgreSQL DDL is transactional.

**If the new code must be rolled back after the migration succeeded.** The wider column is harmless to old code, but the database now says `alembic_version = 117` and an **older image does not
contain revision 117, so its startup `alembic upgrade head` fails with `Can't locate revision identified by '117'` and the API will not start** (reproduced). The documented sequence, verified:
1. With the **new** image: `$dc run --rm api alembic downgrade 116` (the downgrade only moves the version marker back; it deliberately does not narrow the column).
2. Start the older image: its `alembic upgrade head` is then a no-op and it starts cleanly; the column stays 40.
Do not run `alembic downgrade` against any database without taking a backup first.

## 12. Observability: what can be monitored after this release

**What exists today.** `structlog` writes JSON to stdout (`app/core/logging.py`), collected by `docker logs`; gunicorn writes access and error logs to stdout/stderr. Sentry is initialised
only when `SENTRY_DSN` is set (check that it is set in production: `$dc exec api printenv SENTRY_DSN | wc -c` prints 1 if empty; do not print the value). An unhandled `OperationalError` becomes
a generic HTTP 500 plus a traceback in the error log (and a Sentry event if enabled); no handler maps database errors to named events, and there are no metrics counters.

**Added in this release:** when the audit-chain lock cannot be taken, `append_audit` logs one structured warning, `audit_chain_lock_failed`, with `tenant_id`, `pgcode` (`55P03` = waited
longer than 10 s, `40P01` = deadlock victim) and the wait, then re-raises the original exception unchanged. It carries no personal data.

| Signal | Where | Command / query | Healthy | Act when |
|---|---|---|---|---|
| Audit lock timeouts and deadlocks (named) | API/worker logs | `$dc logs --since 1h api worker 2>&1 \| grep -c audit_chain_lock_failed` | 0 | more than a handful per hour, or the same `tenant_id` repeatedly (a slow transaction is holding that tenant's chain; look for the holder below) |
| Same, as raw PostgreSQL errors | logs, Sentry | `grep -E "LockNotAvailable\|DeadlockDetected\|canceling statement due to lock timeout\|deadlock detected"` | none | any |
| Deadlocks since statistics reset | PostgreSQL | `SELECT deadlocks FROM pg_stat_database WHERE datname = current_database();` (take two readings and compare) | flat | rising |
| Who holds an audit chain right now | PostgreSQL | `SELECT l.pid, a.state, a.xact_start, now() - a.xact_start AS open_for, left(a.query, 80) FROM pg_locks l JOIN pg_stat_activity a USING (pid) WHERE l.locktype = 'advisory' AND l.granted ORDER BY a.xact_start;` | rows only for milliseconds | a row open for more than a few seconds, especially `state = 'idle in transaction'` |
| Who is waiting for one | PostgreSQL | `SELECT pid, wait_event_type, wait_event, now() - xact_start AS waiting FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND wait_event = 'advisory';` | none | rows lasting several seconds |
| Migration problems at start | api logs | `$dc logs --since 15m api \| grep -iE "alembic\|Running upgrade\|lock timeout"` and `$dc ps api` (a restarting container) | one `Running upgrade 116 -> 117` then healthy | repeated restarts |
| Dead-letter queue (failed Celery tasks after retries) | Redis | `$dc exec redis redis-cli --scan --pattern 'dlq:*'` then `LLEN dlq:<task>`; or `GET /api/v1/admin/dlq` (owner/admin) | empty | any growth |
| Pool exhaustion (waiters hold a connection) | api logs | `grep -c "QueuePool limit"` | 0 | any: lock waiters (up to 10 s each) can occupy the small pool (`DB_POOL_SIZE=3` + overflow 2) |

**Not configured, recommended (needs your approval; nothing was changed):** a role-level `idle_in_transaction_session_timeout` (for example 60 s) so a transaction that hangs between
appending an audit event and committing cannot hold a tenant's chain indefinitely. It also ends legitimately idle transactions, so try it on staging first. Supabase shows PostgreSQL
errors (including deadlocks and lock timeouts) under Logs, Postgres; a log alert on `deadlock detected` and on the app-side `audit_chain_lock_failed` is the lowest-effort monitor.

**Your message was cut off at item 6 ("Dead…").** The table covers deadlocks and dead-letter queues; if you meant something else (dead tuples/vacuum, dead connections), say so.
