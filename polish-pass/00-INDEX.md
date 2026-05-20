# HAIP V1 Polish Pass — Implementation Index

This directory contains six priority-tiered specs derived from `HAIP-V1-Polish-Pass.md` (in the repo root). Each file is sized for a focused Claude Code session: read the file, work through it top-to-bottom, ship, move to the next.

## How to use this with Claude Code

For each priority file:

1. Open Claude Code in the HAIP project root.
2. Tell it: `Read polish-pass/P0-Critical.md and execute the items in order. After each item, run tests and pause for review before continuing.`
3. Claude Code uses `CLAUDE.md` (already in the repo root) for project conventions; these files give it the *what*.
4. Each item has acceptance criteria as checkboxes — Claude Code should tick them as it goes.

Each file is self-contained: no need to read others first. Each item has file paths, current behavior, desired behavior, acceptance criteria, and technical notes where non-obvious.

## Priority order (ship in this sequence)

| File | Theme | # items | Effort | Why first/later |
|---|---|---|---|---|
| [P0-Critical.md](./P0-Critical.md) | Security + silent failures | 10 | ~1 week | Risk mitigation. Ship before anything else. |
| [P1-Top-Wins.md](./P1-Top-Wins.md) | User-felt daily | 15 | ~2-3 weeks | Visible polish; operators feel the product "got better." |
| [P2-Workflow-Depth.md](./P2-Workflow-Depth.md) | Power-user workflows | 20 | ~3-4 weeks | Adoption depth for daily heavy users. |
| [P3-Compliance.md](./P3-Compliance.md) | DPDP + Meta policy | 13 | ~2 weeks | Defensible compliance posture. Parallelizable with P2. |
| [P4-Onboarding-Discovery.md](./P4-Onboarding-Discovery.md) | Activation + discovery | 15 | ~2 weeks | Reduces churn at week 1; surfaces existing features. |
| [P5-Analytics-Mobile-TechDebt.md](./P5-Analytics-Mobile-TechDebt.md) | Drill-down, mobile, tests | 18 | ~3 weeks | Prepares for next 2× of customers. |

**Total:** ~91 items, ~13-15 weeks of focused engineering across a small team.

## Recommended sequencing

A practical 90-day plan (1-2 engineers):

```
Week 1     | P0-Critical (all 10)
Week 2-4   | P1-Top-Wins (15)
Week 5-7   | P2-Workflow-Depth (20)
Week 5-7   | P3-Compliance (parallel, can be a 0.25 FTE swimlane)
Week 8-9   | P4-Onboarding-Discovery (15)
Week 10-12 | P5-Analytics-Mobile-TechDebt (18)
```

## Conventions used in every spec file

Every item follows the same shape:

```
### CODE — Short title
**Priority:** P0/P1/... · **Effort:** S/M/L · **Module:** module name

**Files to modify:** (specific paths)
**Current behavior:** what V1 does today
**Desired behavior:** what to change to
**Acceptance criteria:** (checkboxes — testable)
**Technical notes:** hints where non-obvious
```

Item codes match the original polish memo: `W` = WhatsApp inbox, `K` = Kanban CRM, `C` = Call intelligence, `G` = Guest, `T` = Templates, `A` = Analytics, `O` = Onboarding, `S` = Settings, `D` = DPDP/Compliance, `M` = Mobile, `B` = Backend, `X` = Cross-cutting UX.

## Effort tags

- **S** — hours to 1 day
- **M** — 2-4 days
- **L** — week or more (consider further breakdown)

## Status tracking

Recommended: add a row per item to a tracking sheet (or use GitHub issues with labels `priority:p0..p5`, `effort:s/m/l`, `module:inbox/crm/...`). Each spec file's table of contents at the top can serve as a quick checklist.

## Notes for Claude Code sessions

- **Always read `CLAUDE.md` first** — it's in the repo root with project conventions.
- **Run tests after each item** — even if the item didn't touch tests directly.
- **Migration discipline:** any DB schema change → new Alembic migration + downgrade path + tested on a fresh DB.
- **Multi-tenancy is non-negotiable:** every new entity must have `tenant_id` FK, RLS policy, and tenant-scoped endpoints.
- **No new modules.** If an item drifts toward a new feature, stop and flag for human review.
- **Backwards-compatible** unless the spec explicitly says otherwise. V1 endpoints continue to work.

## Out of scope for this polish pass

These are explicitly *not* in any of the six files (they are V2 territory):

- New modules (Flow Studio, CTWA Ads Manager, Agent OS, Athena/AI Data Analyst)
- New entities (Touchpoint, Campaign, Booking-as-separate-from-Stay, LeadScore as model, LTVForecast, BrandTheme)
- Semantic layer (dbt + MetricFlow)
- LangGraph orchestration
- White-label / custom domains
- Voicebot integration (Vapi/Retell)
- Real-time agent assist
- LLM-as-judge replacement for rubric scoring (V1 keeps rubric)

If any item starts looking like one of these, it has slipped scope — stop and confirm with the founder.
