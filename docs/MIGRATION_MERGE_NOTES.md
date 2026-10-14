# Merging the three local branches: migration chain and conflicts (rehearsed 14 Oct 2026)

Nothing was merged. The merge of `feat/ratha-business-data` (which already contains `feat/mai3-reliability`) into `phase0-reliability`
was rehearsed in a throwaway worktree (deleted afterwards) and the migration chain was applied to a fresh PostgreSQL 16 database.

## Revision numbers

| Revision | Branch | Parent | What |
|---|---|---|---|
| 121 | all | 120 | iCal event bookings |
| 122 | mai3 / ratha | 121 | lead identification |
| 123 | mai3 / ratha | 122 | knowledge index health |
| 124 | ratha | 123 | business records |
| 125 | ratha | 124 | issued-quote snapshot |
| 126 | phase0 | 121 | `organic_call` inquiry source (was 122 here; renumbered so it cannot collide) |
| 127 | merge | 125, 126 | no-op merge revision, kept in `backend/alembic/proposed/127_merge_heads.py` |

On `phase0-reliability` alone the head is 126 (single head, chain 117→119→120→121→126). After merging, two heads exist (125 and 126):
move `alembic/proposed/127_merge_heads.py` to `alembic/versions/` in the merge commit.

Verified on PostgreSQL (fresh DB): `upgrade head` through 127, `downgrade 121`, `upgrade head` again, all without error;
`organic_call` present in the enum. PostgreSQL cannot drop an enum value, so 126's downgrade is a documented no-op.

## Conflicts the merge hits (resolve at merge time)

| File | Conflict | Resolution |
|---|---|---|
| `backend/tests/test_migration_117_postgres.py` | head pin (126 here, 125 there) | pin `["127"]`, `127.down_revision == ("125", "126")`, keep the 121-125 parent checks |
| `CLAUDE.md` | header, migration paragraph | one head `127`, list 122-127; keep under 500 lines |
| `backend/app/services/business_overview_service.py` | `_source_rows`: this branch regroups sources on `Inquiry.source`; the other branch replaced it with first-touch channels (`lead_metrics.by_first_touch`) | take the other branch's version; then add `organic_call` handling where first-touch channels are derived (a lead whose first contact was an inbound call stays under "Phone calls"; "Organic calls" remains a lead-level source in Leads 360 filters and the lead report) |
| `backend/tests/api/test_business_overview.py` | both branches appended tests | keep both |

After the merge also check: `dashboard_service._SOURCE_GROUPS` / `UNKNOWN_SOURCE` still used by `lead_sources`; `tests/test_lead_attribution_and_counts.py`
and the business-overview tests on PostgreSQL.
