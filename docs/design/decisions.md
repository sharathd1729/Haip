# Design decisions log

Newest first. One entry per decision that changes how the UI is built. Rule from `HAIP_UI_Redesign_Plan.md`: when two sources disagree, follow `docs/DESIGN.md`; if it is silent, follow the plan; log the choice here.

## 2026-10-22

**Palette: Greens + terracotta replaces Sea Green & Coral (owner-approved mockup "Option 1").** Green carries almost all colour: forest top bar and phone header (lime logo tile, mint active pill, icons on every nav item), mint page canvas (#EEF7F0) with white, green-bordered cards, mint/olive card header bands, sea-green icon tiles beside page titles. ONE warm accent, terracotta #C2603E, for primary buttons, counts, today and money due. Choices made while building it:
- `--primary` stays the sea-green BRAND (459 `text-primary`, 187 ring uses: links, focus, selected states). Turning it terracotta would have made the accent the dominant colour. Instead a single unlayered rule in `globals.css` repaints `button`/`a` elements that carry `bg-primary` + white/primary-foreground text with `--haip-action`, so every page's main button follows without page edits; switches, progress bars and dots (bg-primary without text) stay green. Side effect: a few hand-rolled segmented tabs that mark the active segment `bg-primary text-white` without `role="tab"` (Billing, Compliance, Channel manager, Campaigns) now show it in terracotta until they move to kit `Tabs`.
- The same rule fixed an old bug: the light-mode "invisible white text" remap was turning `bg-primary text-white` buttons' labels dark; `bg-primary` is now excluded from it.
- White-label: the house theme leaves `--brand-action` unset (terracotta); a tenant with its own brand colour gets it back on buttons (`brandTheme.ts`). Workspaces still on the sea-green default (#1E7A5A + white) follow the new default (`LEGACY_DEFAULTS`).
- Contrast: white on #C2603E is about 4.2:1, below AA 4.5:1 for normal-size text, accepted by the owner for semibold button labels and counts; dark mode puts forest ink on #D9785A.
- The house wordmark (teal PNG) is unreadable on forest, so the bar shows the lime letter tile; a tenant's uploaded logo still shows (its dark variant, else on a white plate).

## 2026-10-20

**CRM Bookings shows one card per booking (layout A · Cards by date); the agenda is reserved for the Ops module.** Separate check-in and check-out rows confused agents and the owner. The CRM page now groups one card per booking under its check-in day (Staying now: one "On a trip now" group; Past and Cancelled newest first), keeping the 14-day strip, month summary, tabs, Filters, detail pane and sheets. The agenda (check-in/check-out rows: `components/bookings/agenda/AgendaDays`, `lib/bookingAgenda.buildEvents`) stays in the codebase, unused, for the Ops module.

## 2026-10-19

**Bookings is an agenda (owner chose layout B).** Segments Upcoming / Staying now / Past / Cancelled, a month summary, search + one Filters sheet, a 14-day strip per caravan, then each day's check-ins and check-outs. The Split/Table views and bulk "move to property" are gone (move one booking at a time with Edit). Two new tokens tint the caravans in the strip and on vehicle tags: `--haip-cal-vehicle-1` / `--haip-cal-vehicle-2` (+ `--haip-cal-vehicle-fg`), light and dark. A one-day block in the strip is about 21px wide on a 375px phone: accepted from the mock-up, the same booking is also a full-size row below.

## 2026-10-18

**Palette: Sea Green & Coral replaces plum & marigold.** The owner wanted the theme closer to the brand (green/cyan family, not teal). Four combinations were compared on the real app with a temporary per-browser palette switcher (A Emerald & Marigold, B Sea Green & Coral, C Ocean Cyan & Sand, D Lagoon; screenshots in `docs/design/palette-lab/`, not committed). B was chosen: sea green `#1E7A5A` (dark `#5CC9A0`) for actions, coral `#E0694A` for highlights, sand-white canvas, green-charcoal dark mode; every pair AA in both themes. The lab was removed. Workspaces still on an old house default (teal + navy, or plum + white) follow the new default automatically (`brandTheme.ts` `LEGACY_DEFAULTS`); the Jamun preset was replaced by "Sea Green (HAIP)".

## 2026-10-17

**Hospitality Hybrid replaces "Calm operations room".** Six directions were built side by side on synthetic data in a dev-only lab (`/design-lab`, 4 screens each, layout-checked at 320-1440px); the owner chose F, Hospitality Hybrid. Teal, the navy sidebar and Outfit are retired; plum `#5A2D6B` + marigold, Figtree + Bricolage Grotesque, light top bar on desktop, bottom bar with a raised "Now" on phones. `docs/DESIGN.md` section 7.

**Calendar colours keep their taught meanings.** Owners were told green = direct, gray = blocked, red = maintenance, so calendar bars stay green/gray/red (theme-safe `--haip-cal-*` tokens) rather than becoming plum.

**Old colour systems swept, not hand-edited.** A scripted pass replaced 2,902 teal and raw-gray classes in the CRM app with tokens (marketing site, auth pages and the lab excluded); the separate indigo accents on Leads, Inbox and Calls now resolve to the brand primary.

**Skills.** impeccable (guidance read directly; its launcher binary is absent and was not downloaded), Replica (11 skills copied into `~/.claude/skills` after reading them; its contrast script checked the palettes), taste-skill / emil-design-eng / ui-ux-pro-max for hierarchy and motion restraint, dataviz for chart colour checks. No hooks enabled.

## 2026-10-12

**The five design skills are now installed locally (user-level); how the Owner Command Center used them.**
They sit in `~/.claude/skills` (impeccable, taste-skill, ui-ux-pro-max, emil-design-eng, shaders), which supersedes the 11 Oct "not installed" note for this machine. Nothing was installed or downloaded for this work. Used: impeccable's operate-mode and craft-floor guidance (read directly; its launcher binary is not present and would need a download, so it was not run, and the detector hook was not enabled); ui-ux-pro-max's local chart-domain search (its Python scripts were checked for network and shell use first); emil-design-eng and taste-skill for motion restraint and hierarchy. Not used: shaders (no decorative effect on a data screen), and ui-ux-pro-max's `--design-system` output (a landing-page pattern with a glass style) because `docs/DESIGN.md` section 5 already sets the direction. Spec: `docs/design/owner-command-center.md`.

**Owners and managers land on the Owner Command Center; everyone else keeps the operations view.**
`/dashboard` renders the Command Center for owner and manager and the former Home page for other roles; the former Home page stays reachable at `/dashboard/operations` for everyone. No route was removed. Bookings and Targets links are hidden for roles without `bookings.read` / `revenue.read` by default (display only; the server enforces).

## 2026-10-11

**Third-party design skills are not installed; their ideas are applied directly.**
The five repos named in the plan (impeccable, taste-skill, ui-ux-pro-max-skill, emilkowalski/skills, shaders) all install through `npx`, and impeccable additionally installs hooks that run a downloaded program after every UI edit; shaders links a project to an account. Code from unverified third parties running with shell access is a supply-chain risk this project does not take. What we use from them is the *guidance*, written into `docs/DESIGN.md` section 5: ease-out motion, tinted neutrals, fewer nested cards, visible focus, 16px inputs on touch, worst-case data testing, no colour-only meaning. If a skill is wanted later, install it deliberately from a terminal after reading its files, and never its auto-run hooks.

**Verify tokens: one per workspace per channel, hidden by default.**
The single shared Meta webhook verify token was printed on the Integrations page for every user and was identical for WhatsApp and Instagram. Now each workspace/channel has its own, stored encrypted, shown only to an owner on request (logged), rotatable. The old shared token still verifies until `ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN=false`.

**Dev gallery route is `/dashboard/dev-kit`, not `/_kit`.** In the Next.js app router a folder starting with an underscore is private and cannot be routed.

**Defaults taken for the plan's open decisions** (revisit any time): Dashboard before Inbox; Reports stays an export wizard for now (rename and a separate Insights page decided in Phase 6); dark mode is a launch requirement; white-label stays a requirement (token-only styling); Ratha and Jade both see the redesign first.
