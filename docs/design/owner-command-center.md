# Owner Command Center — design specification

Page: `/dashboard` for owners and managers. Code: `frontend/src/components/dashboard/command/`. Direction follows
`docs/DESIGN.md` section 5 ("Calm operations room"); this file only records what is specific to this page. Where a skill's
advice disagreed with HAIP's own system, HAIP won (see `decisions.md`, 12 Oct 2026).

## Purpose and mode
An Operate surface: an owner opens it to learn, in a few seconds, whether the business is healthy and what needs them.
Order of reading: what is waiting on the team -> the three numbers (leads, bookings, revenue) -> how leads become paid
bookings -> the trend -> where leads come from and who converts them. Dials: variance 3, motion 2, density 7. The signature
move is the **lead-to-payment band**: one proportional strip, not a row of cards.

## Layout
| Region | Treatment |
|---|---|
| Header | Display-face greeting, one-line purpose, "As of hh:mm IST", link to the operations view |
| Controls | Period tabs (Today, Last 7 days, This month, Last month, Custom), then channel / property / agent selects. The period is spelled out below with its time zone |
| Needs you now | One bordered strip. Only items that exist; calm "nothing waiting" line otherwise. Red only for overdue payments, missed calls and a failed integration |
| Ledger | **One** surface divided by hairlines into Leads / Bookings / Revenue columns. Each column: small label, a 34px display number, its comparison, then a plain label-and-value list. No nested cards |
| Journey | The four stages as bars scaled to leads received, the rate from the previous stage between them, and the cohort and unlinked-booking notes in words |
| Day by day + Pipeline | A tabbed bar chart (one measure at a time, one hue) beside the pipeline stage list |
| Sources, Team, Meta Ads | Tables with inline bars; Meta splits "reported by Meta" from "verified in HAIP" |
| Footer | "How these numbers are defined" (server-supplied definitions) |

Desktop 1440: three equal ledger columns, four journey stages on one baseline, trend two-thirds beside pipeline one-third.
Below `md` the ledger stacks; below `sm` the journey stacks (label reserves two lines so counts align). Nothing scrolls sideways;
tables scroll inside their own container.

## Type, colour, space
- Display: Outfit (existing `--font-display`) for the greeting, section titles and the headline numbers, with tabular figures.
  Body and tables: Inter. No new fonts.
- Colour: tokens only. Primary teal `#0F766E` (via `--primary`) for the current period and positive bars; neutral
  `--haip-fg*` for text; status triplets for state. Days before the period and "previous" context use the muted border tone.
  One hue per chart; Leads, Bookings and Revenue are told apart by column, heading and icon, not by three competing colours.
- Money: full Indian grouping (₹12,50,000) for figures; lakh/crore short form (₹12.5L) only on chart axes.
- Space: 20-24px inside surfaces, 20px between sections, 44px minimum touch targets on small screens, 16px date inputs on touch.

## Charts
Bar chart for per-day counts and values (discrete days, comparison by length); period days teal, context days muted, with a
legend in words. The funnel is bars plus text rates because a funnel needs the numbers more than the shape. The pipeline is a
ranked bar list. No dual axes, no 3D, no chart animation. Each chart has a text summary (`role="img"` label), a total, a
useful tooltip, and an empty, loading and error state. Every stage, row and figure that has a module behind it links there
(`/dashboard/leads`, `/dashboard/bookings?quick=due`, `/dashboard/my-day?kind=unassigned`, `/dashboard/targets`, `/dashboard/marketing`).

## States
Loading: skeletons shaped like the page. Reload on a filter change: previous numbers stay, dimmed, with "Updating…".
Failed refresh: previous numbers stay with a warning and the as-of time. First-load failure: message and retry. Empty period:
sentences, not zeros. Restricted: an explanatory note naming the permission; no number, no zero, no link to a page the viewer
cannot open. Not computable (pending bookings, net revenue, target): the reason is on the page.

## Motion
Only to explain a change: bar-width and opacity transitions of 150-300ms on the house ease-out
`cubic-bezier(0.23, 1, 0.32, 1)`, behind `motion-safe:` and the global reduced-motion rule. No entrance animation, no
count-up, no chart animation, nothing that delays a figure.

## Accessibility
Real headings per section, a labelled period tab list (arrow keys), labelled selects, visible focus rings on every control,
meaning carried by words as well as colour (the integration dot is paired with "has stopped syncing"), screen-reader text
for comparisons, progress bars with `role="progressbar"`, contrast from the token set. Verified in a browser: keyboard focus
rings, no horizontal overflow at phone and desktop widths, 44px targets after the touch-target pass.

## Not used, and why
- **WebGPU / shader effects:** no decorative effect earns its cost on a data screen (PRODUCT.md anti-goal; speed and
  readability on phones come first). None added.
- **A generated design system (UI Pro Max):** its output for this brief was a landing-page pattern with a glass style
  and a different palette; HAIP's own tokens and `DESIGN.md` direction were kept. Its chart guidance (funnel with rates and a
  text fallback, trend as time series with direct labels, no colour-only encoding) was used.
- **Sparklines and hero-metric tiles:** the older home page keeps them; this page leads with the plain ledger instead.
