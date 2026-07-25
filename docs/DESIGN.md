# HAIP Design System

**Status**: Phase 0 of HAIP V2. This document is the single source of truth for colour, spacing, radius, and typography tokens in the app UI. It must be read before any module visual redesign (V2 Phase 4).

---

## 1. Current State — Five Token Layers Coexist

Audited against `frontend/src/app/globals.css` (575 lines) and all `.tsx`/`.ts` under `frontend/src`. Usage counts are real occurrences, not estimates.

| Layer | Defined at | Usage | Verdict |
|---|---|---|---|
| **shadcn semantic** — `--background`, `--foreground`, `--card`, `--primary`, `--border`, `--muted`, `--sidebar-*`, `--chart-1..5`, `--radius` | `globals.css:52-156` (`:root` + `.dark`), mapped to Tailwind utilities via `@theme inline` (`globals.css:7-50`) | Consumed idiomatically through Tailwind classes (`bg-card`, `text-primary`, `border-border`) | **Canonical. Keep.** |
| **`--haip-*`** — `--haip-fg`, `--haip-card`, `--haip-border`, `--haip-primary`, `--haip-surface`, `--haip-green/amber/red`, `--haip-shadow-*` | `globals.css:359-418` (`:root` + `.dark`) | **549 occurrences across 46 files** — dominant, almost all via inline `style={{ }}` | **Keep the names, re-point the values** (§2) |
| **`--mkt-*`** — marketing palette | `globals.css:98-108` (light), `145-155` (dark) | 31 occurrences / 13 files, marketing pages only | **Keep, separate concern.** Marketing site ≠ app UI; do not merge. |
| **`--brand-teal*`, `--brand-mimosa*`** (static) | `globals.css:89-96` | **0 occurrences anywhere** | **Dead. Delete.** |
| **adaptive** — `--page-bg`, `--panel-bg`, `--text-primary`, `--text-secondary`, `--input-bg`, `--hover-bg` | `globals.css:162-187` | Live, but mostly consumed **from inside `globals.css` itself** (the `!important` remap block, §4) rather than from components: `--page-bg` ×2, `--panel-bg` ×1, `--text-primary` ×1, `--text-secondary` ×1 in CSS; `--input-bg` ×3 and `--hover-bg` ×3 in TSX | **Keep for now.** Retires with the remap block (§4), not before. |
| **`--brand-*`** (runtime, white-label) — `--brand-primary`, `--brand-sidebar-bg`, `--brand-font`, `--brand-radius-*` | injected at runtime by `frontend/src/lib/brandTheme.ts::applyTheme()` | **2 occurrences in 1 file** (`components/layout/MobileNav.tsx`) | **Keep the mechanism, fix the wiring** (§3) |

### Two problems this creates

**a) The same colour is defined twice, and it had already drifted.** `--haip-primary` was `#0F766E` while `--primary` was `oklch(0.47 0.085 175)` — whose own code comment claimed it was "HAIP teal #0F766E". It was not: that oklch resolves to **`rgb(13,106,88)`**, a duller, darker teal than `#0F766E` = `rgb(15,118,110)`. So the app was rendering two different "brand teals" side by side — the correct one on the 549 `--haip-*` call sites, the wrong one on every Tailwind `bg-primary`/`text-primary`/`ring-*` utility. Same double-definition existed for `--haip-fg`/`--foreground`, `--haip-card`/`--card`, `--haip-border`/`--border`.

Fixed by making the canonical tokens hold the real brand hex (§2).

**b) `--brand-*` is an overloaded prefix.** It means both "static marketing brand colour" (`--brand-teal`, dead) and "runtime per-tenant white-label override" (`--brand-primary`, live). Two unrelated concepts, one namespace.

---

## 2. Target — One Source of Truth, Zero Call-Site Churn *(implemented)*

**Do not rewrite 549 call sites.** That is a mass refactor with high regression risk across 46 files and no user-visible benefit. Instead, `--haip-*` is now a **thin alias layer over the canonical tokens**:

```css
:root {
  --haip-fg:      var(--foreground);
  --haip-card:    var(--card);
  --haip-border:  var(--border);
  --haip-fg-muted:var(--muted-foreground);
  --haip-primary: var(--primary);
  /* accent, status, shadows, *-subtle stay literal — no canonical equivalent */
}
```

Defined **once in `:root`**. CSS custom properties resolve lazily at computed-value time, so `.dark`'s overrides of the canonical tokens flow through the aliases automatically — no duplicate `.dark` block for aliased tokens.

Why this was safe: **dark mode was already byte-identical** between the two layers (`--haip-fg`/`--foreground` both `#e8edf8`, `--haip-card`/`--card` both `#161e30`, borders both `rgba(255,255,255,0.07)`). Only light mode had drifted, so the canonical light neutrals were set to the HAIP hex palette (`--foreground: #111827`, `--border: #E5E7EB`, `--muted-foreground: #475569`, `--secondary-foreground: #374151`) to make aliasing faithful.

### Deliberate visual changes

| Token | Before | After | Note |
|---|---|---|---|
| `--primary`, `--ring`, `--chart-1`, `--sidebar-primary` (light) | `rgb(13,106,88)` | `rgb(15,118,110)` | Corrects the drift bug — Tailwind utilities now render the real brand teal |
| `--haip-primary` (dark) | `#0F766E` teal | `#4f8ef7` blue | Dark mode previously showed teal *and* blue accents at once; now consistently the intended dark-mode blue. To revert, set `--primary` in `.dark`. |
| `--haip-card` (light) | `#FFFFFF` | `#fdfdfd` | Imperceptible; serves the documented "card visible against background" intent |
| `--haip-text-muted` (light) | `#64748B` | `#475569` | Legacy alias had drifted from `--haip-fg-muted`; unified. Slightly higher contrast. |
| `--muted-foreground` (light) | `rgb(138,138,138)` | `#475569` | Tailwind `text-muted-foreground` darkens — accessibility improvement |

### Rules going forward

1. **New code uses Tailwind utility classes** (`bg-card`, `text-muted-foreground`, `border-border`), not inline `style={{ var(--haip-*) }}`. The `--haip-*` aliases exist to keep 46 existing files working, not as the path for new work.
2. **Never add a new token family.** If a value is needed, it belongs in the shadcn semantic set or it is a one-off.
3. **`--mkt-*` is for marketing pages only** (`/`, pricing, etc.) and must not appear under `app/dashboard/**`.
4. **Status colours** (`--haip-green` `#10B981`, `--haip-amber` `#F59E0B`, `--haip-red` `#EF4444`) have no shadcn equivalent and stay literal. Use them for semantic state (success/warning/error), never for decoration.
5. **Radius** comes from `--radius` (`0.75rem`) and its derived `--radius-sm..4xl` scale (`globals.css:43-49`). Do not hardcode `border-radius`.

---

## 3. White-Label — Was a Hook Connected to Nothing *(fixed)*

`lib/brandTheme.ts` is a complete, working per-tenant theming engine: `buildCSSVars()` derives a full variable map (primary + tints + sidebar + font + radius) from a `BrandTheme`, `applyTheme()` injects it onto `document.documentElement`, with `localStorage` persistence and 12 preset palettes.

**But only `MobileNav.tsx` reads the output.** A tenant setting a custom primary colour today changes almost nothing in the UI, because every other surface reads `--haip-*` or Tailwind's shadcn-backed utilities — neither of which `applyTheme()` touches.

`buildCSSVars()` now additionally emits the **canonical** tokens — `--primary`, `--primary-foreground`, `--ring`, `--sidebar`, `--sidebar-primary`, `--sidebar-foreground`, `--radius` — alongside the existing `--brand-*` set. Combined with §2's aliasing, a tenant's colour now reaches every Tailwind utility and all 549 `--haip-*` call sites at once. Verified: setting `--primary` alone propagates to `--haip-primary` and to the derived `--haip-primary-hover`.

`--font-sans` is deliberately **not** overridden for the default "Inter" tenant — that variable is owned by `next/font` in `app/layout.tsx`, which self-hosts an optimised copy. `applyTheme()` only sets it when a tenant picks a different font, next to the Google Fonts injection.

This is the reusable hook for the white-label FUTURE MODULE (see root `CLAUDE.md`). Keep the mechanism; do not remove it.

**Naming**: once the dead static `--brand-teal`/`--brand-mimosa` tokens are deleted, `--brand-*` unambiguously means "runtime per-tenant override" and the prefix collision resolves itself.

---

## 4. The `!important` Dark-Mode Remap Block

`globals.css:193-260` contains a large `@layer utilities` block that force-remaps hardcoded Tailwind light utilities in dark mode (`.dark .bg-white { background-color: #161e30 !important }`, `.dark .text-gray-900 { … }`, etc.), plus attribute-selector hacks matching hardcoded hex classes and a light-mode `text-white` rescue selector.

This exists because pages were written with hardcoded `bg-white`/`text-gray-900` instead of semantic tokens. It works, and it is load-bearing for dark mode today — **do not delete it as part of Phase 0.**

Retire it incrementally: as each module is redesigned in V2 Phase 4, convert that module's hardcoded utilities to semantic ones (`bg-card`, `text-foreground`), and drop the corresponding remap rules only once no module depends on them.

---

## 5. Typography

- Body: `--font-sans` (Inter), mapped to Tailwind `font-sans` via `@theme inline` (`globals.css:10`).
- Display/headings: `--font-display`, exposed as `font-heading`/`font-display`, applied by the `.haip-heading` utility (`globals.css:421+`, weight 700, `letter-spacing: -0.02em`).
- Per-tenant font override arrives through `brandTheme.ts`'s `--brand-font` + Google Fonts injection (`applyTheme()`, `brandTheme.ts:156-170`), with 10 approved font options.

---

## 6. Phase 0 Checklist

- [x] Delete tokens with zero references across all `.css`/`.ts`/`.tsx`: `--brand-teal{,-dark,-light,-hover}`, `--brand-mimosa{,-dark,-light}`, `--panel-border`, `--text-tertiary`, `--icon-color`, `--input-border`, `--active-bg`.
- [x] Fix the `--primary` drift bug — canonical teal is now the literal `#0F766E`, matching what the `--haip-*` layer always used.
- [x] Re-point `--haip-*` colour tokens onto the canonical tokens (§2); status/accent/shadow/subtle tokens stay literal.
- [x] Re-target `brandTheme.ts::buildCSSVars()` to override canonical tokens so white-label propagates (§3), without clobbering `next/font`'s `--font-sans`.
- [x] Verify token resolution in both themes (computed-value check: every alias resolves to its canonical token; dark-mode values byte-identical to pre-change; white-label propagation confirmed).
- [ ] **Remaining gate** — visual pass over the five highest-density surfaces in both themes once dashboard credentials are available: `inbox/page.tsx` (51 uses), `calls/page.tsx` (41), `dashboard/overview.tsx` (39), `shell/TopBar.tsx` (32), `properties/page.tsx` (32). Computed values are verified; what is not yet verified is that no layout reads a token in a way the alias changes perceptibly.
