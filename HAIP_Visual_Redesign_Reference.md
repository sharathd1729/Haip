# HAIP Visual Redesign Reference

**Sources — real, fetched, not guessed:**
- AppFlowy design tokens: `github.com/AppFlowy-IO/AppFlowy`, package
  `frontend/appflowy_flutter/packages/appflowy_ui/lib/src/theme/` — the
  actual auto-generated token source (`primitive.dart`, `semantic.dart`,
  `shared.dart`). These are the real numbers/hex values AppFlowy's own UI
  is built from, not a screenshot guess.
- mx-icons style spec: `github.com/ig-imanish/mx-icons` README — real
  documented defaults (24px standard size, `#292D32` default color,
  linear/bold/bulk variants). mx-icons itself is **not** used as a
  package (see `HAIP_MCP_Connector_Plan.md`-era notes / commit history —
  its single 1MB barrel file with no per-icon subpath exports OOM'd both
  Turbopack and webpack). This is a style reference only.

This is **not** a copy of either repo's UI. AppFlowy is a different
product (Notion-style workspace tool) with a different brand (blue
accent, near-black text). HAIP keeps its own teal/dark-navy identity —
what's adopted here is AppFlowy's *system*: how many radius/spacing
steps it uses, how it differentiates surfaces (borders over background
tinting), how its shadows are built, and its text-color hierarchy depth.
Every HAIP token below keeps HAIP's own hue, remapped onto AppFlowy's
scale and structure.

---

## 1. What AppFlowy actually does (real tokens, real values)

### Radius scale — 6 steps, tight range
```
xs   4px
s    6px
m    8px
l    12px
xl   16px
xxl  20px
```
Source: `AppFlowyBorderRadiusConstant` in `theme/data/shared.dart`.

### Spacing scale — 6 steps, same numbers as radius
```
xs   4px
s    6px
m    8px
l    12px
xl   16px
xxl  20px
```
Source: `AppFlowySpacingConstant`, same file. Notably AppFlowy reuses the
*exact same* 6-step scale for both radius and spacing — one ramp, not two
independently-tuned systems. That's a real, deliberate simplicity choice.

### Shadow — two depths, wide+soft, low opacity
```
small:  0 2px 16px rgba(0,0,0,0.122)
medium: 0 4px 32px rgba(0,0,0,0.122)
dark-mode small:  0 2px 16px rgba(0,0,0,0.478)
dark-mode medium: 0 4px 32px rgba(0,0,0,0.478)
```
Source: `AppFlowySharedTokens.buildShadow()`. Note the blur radius is 8x
the offset in both cases (2px offset / 16px blur, 4px offset / 32px
blur) — a soft, diffuse shadow, not a tight drop-shadow. Dark mode
doesn't disable shadows (HAIP's current `globals.css` does) — it just
raises the alpha from 0.122 to 0.478 so the same soft shadow still reads
against a dark surface.

### Color — real hex, neutral-heavy with one accent hue
```
neutral100   #F8FAFF   page background AND card background (same value —
                        surfaces are NOT distinguished by a bg-tint step)
neutral200   #E4E8F5   border (primary)
neutral300   #CED3E6   border hover
neutral500   #989EB7   tertiary text/icon
neutral600   #6F748C   secondary text
neutral1000  #21232A   primary text
white        #FFFFFF   surface/card fill
blue500      #00B5FF   accent (brand thick)
blue600      #0092D6   accent hover
blue700      #0078C0   accent active
```
Source: `AppFlowyPrimitiveTokens` (raw palette) + `AppFlowyDefaultTheme.light()`
(semantic mapping) in `semantic.dart`.

**The structurally important finding**: AppFlowy's page background and
its card `surfaceColorScheme.primary` are the *same* white/off-white —
cards are differentiated from the page by a 1px `neutral200` border and
a soft shadow, not by a darker/lighter fill. HAIP's current `--haip-card`
vs page background already does something similar, but HAIP's shadow is
currently tighter/harder (`0 1px 3px rgba(0,0,0,0.06)`) than AppFlowy's
soft wide spread.

### Text color — 3-step hierarchy (not counting quaternary/disabled)
```
primary    neutral1000  (#21232A) — near-black, not pure black
secondary  neutral600   (#6F748C) — a real mid-grey, not a tinted primary
tertiary   neutral500   (#989EB7) — for placeholders/hints
```

---

## 2. What mx-icons documents (style reference only — package not used)

```
default size:   24px
default color:  #292D32   (near-black, close to AppFlowy's neutral900/1000)
variants:       Linear (outline), Bold (filled), Bulk, Broken, Outline, Twotone
```
Source: mx-icons README's props table + Quick Start example. The
takeaway that's actually usable: **icon color defaulting to a near-black
neutral rather than pure black or the brand accent** — a small, real,
adoptable detail independent of which icon library ships it. HAIP's
`@heroicons/react` icons today mostly inherit `currentColor`/inline
`style={{ color: "var(--primary)" }}`, which is fine, but plain
structural/utility icons (chevrons, close buttons, kebab menus) reading
as teal everywhere is a small AppFlowy/mx-icons-style miss — those
should default to a neutral (`--haip-fg-subtle`), reserving teal for
icons that are actually actionable/branded.

---

## 3. Proposed new HAIP tokens (concrete `globals.css` diff)

Mapped onto HAIP's existing teal (`--primary`, `--haip-primary`) and
dark-navy sidebar identity — **not** replacing them with AppFlowy's blue.

```css
/* New: a real 6-step scale, replacing globals.css's current single
   --radius + multiplier hack (lines 43-49, 101) */
--haip-radius-xs:   4px;
--haip-radius-s:    6px;
--haip-radius-m:    8px;
--haip-radius-l:    12px;
--haip-radius-xl:   16px;
--haip-radius-xxl:  20px;

/* Same numbers reused for spacing, matching AppFlowy's one-ramp choice */
--haip-space-xs:   4px;
--haip-space-s:    6px;
--haip-space-m:    8px;
--haip-space-l:    12px;
--haip-space-xl:   16px;
--haip-space-xxl:  20px;

/* Softer, wider shadow -- replaces the current tight
   0 1px 3px rgba(0,0,0,0.06) / 0 1px 2px rgba(0,0,0,0.04) pair */
--haip-shadow-sm:  0 2px 16px rgba(0,0,0,0.08);   /* was 0.122 in AppFlowy's
                                                       pure-neutral UI; HAIP's
                                                       warmer canvas reads
                                                       better a touch lighter */
--haip-shadow-md:  0 4px 32px rgba(0,0,0,0.10);

/* Dark mode: raise alpha instead of disabling shadows outright
   (current globals.css sets all three --haip-shadow-* to `none` in .dark) */
--haip-shadow-sm (dark):  0 2px 16px rgba(0,0,0,0.40);
--haip-shadow-md (dark):  0 4px 32px rgba(0,0,0,0.45);

/* Neutral icon default for non-branded utility icons */
--haip-icon-neutral: var(--haip-fg-subtle);
```

**`.haip-card` becomes:**
```css
.haip-card {
  background: var(--haip-card);
  border: 1px solid var(--haip-border);
  border-radius: var(--haip-radius-l);      /* was var(--radius), i.e. 8px
                                                 today -- bumps to 12px */
  box-shadow: var(--haip-shadow-sm);         /* softer/wider, see above */
}
```

**`.haip-card-head` padding becomes** `var(--haip-space-xl) var(--haip-space-xxl)`
(16px 20px — already landed this in Round 2's conservative pass; this
formalizes it against the real scale instead of an ad-hoc number).

---

## 4. What this does NOT change

- HAIP's teal brand accent (`--primary`, `--haip-primary`) — stays teal,
  everywhere. AppFlowy's blue is not being copied.
- Dark-navy sidebar identity (`--haip-sidebar-*`) — untouched, it's
  HAIP's own visual signature, not something AppFlowy has an equivalent
  of (AppFlowy's sidebar is a light neutral, not dark).
- Icon *library* — stays `@heroicons/react` (Round 2, already shipped
  and verified against a real production build). mx-icons is a style
  reference only, per the note above, not a package dependency.
- Typography scale — AppFlowy's `default_text_style.dart` was fetched
  but not incorporated here; it's Flutter `TextStyle` definitions with a
  different sizing philosophy (mobile-first Flutter app) that doesn't
  translate directly to HAIP's existing `--font-display`/Tailwind text
  scale without a separate pass. Flagging as a deliberate scope cut, not
  an oversight.

## 5. Verification plan if this gets built
- `npx tsc --noEmit --skipLibCheck` (should be a no-op — pure CSS
  variable value changes, no new classes).
- `npm run build` — confirm no regression.
- Browser-verify: `.haip-card` corners visibly rounder (8px → 12px),
  shadow visibly softer/wider on cards across Leads360/Inbox/Reports;
  dark mode now shows a real (if subtle) shadow instead of none; confirm
  brand teal is unchanged everywhere it should be.
