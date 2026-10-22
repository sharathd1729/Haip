/**
 * HAIP Brand Theme System
 *
 * CSS variables injected into :root at runtime by BrandThemeProvider.
 * Components reference these via style props or var() in CSS.
 *
 * Variable naming:
 *   --brand-primary        main accent (buttons, active states)
 *   --brand-primary-light  10% tint  (subtle bg)
 *   --brand-primary-muted  20% tint  (hover bg)
 *   --brand-primary-text   readable text on light bg
 *   --brand-sidebar-bg     sidebar + topbar background
 *   --brand-sidebar-text   sidebar body text
 *   --brand-sidebar-active active nav item text / icon
 *   --brand-logo-url       tenant logo url ('' = use default text mark)
 *   --brand-font           font-family stack
 *   --brand-radius-card    card border-radius
 *   --brand-radius-btn     button border-radius
 */

export interface BrandTheme {
  primaryColor: string;        // hex, e.g. "#1E7A5A"
  sidebarColor: string;        // hex, e.g. "#FFFFFF"
  logoUrl?: string;            // uploaded logo URL
  logoDarkUrl?: string;        // dark-bg variant
  fontFamily: string;          // Google Font name or "Inter"
  radiusScale: "sharp" | "rounded" | "pill";
  companyName: string;
  tagline?: string;
}

// Greens + terracotta (22 Oct 2026): sea green brand, forest shell, terracotta actions on a mint canvas, Figtree. The shell
// colours come from globals.css (--haip-nav-*), so "sidebarColor" stays white for older readers.
export const DEFAULT_THEME: BrandTheme = {
  primaryColor: "#235347",
  sidebarColor: "#FFFFFF",
  logoUrl: "/logo-wordmark.png",
  logoDarkUrl: "/logo-wordmark.png",
  fontFamily: "Figtree",
  radiusScale: "rounded",
  companyName: "HAIP",
  tagline: "Hospitality AI",
};

export const PRESET_THEMES: { name: string; primaryColor: string; sidebarColor: string }[] = [
  { name: "Greens & Terracotta (HAIP)", primaryColor: "#235347", sidebarColor: "#FFFFFF" },
  { name: "Teal",           primaryColor: "#0F766E", sidebarColor: "#0B1F3A" },
  { name: "Ocean Blue",     primaryColor: "#3b82f6", sidebarColor: "#1e3a5f" },
  { name: "Indigo",         primaryColor: "#6366f1", sidebarColor: "#1e1b4b" },
  { name: "Violet",         primaryColor: "#8b5cf6", sidebarColor: "#1d0f3b" },
  { name: "Rose Gold",      primaryColor: "#f43f5e", sidebarColor: "#3b0d1f" },
  { name: "Sunset Orange",  primaryColor: "#f97316", sidebarColor: "#1c1008" },
  { name: "Forest Green",   primaryColor: "#22c55e", sidebarColor: "#052e16" },
  { name: "Emerald",        primaryColor: "#10b981", sidebarColor: "#064e3b" },
  { name: "Amber",          primaryColor: "#f59e0b", sidebarColor: "#1c1400" },
  { name: "Slate",          primaryColor: "#64748b", sidebarColor: "#0f172a" },
  { name: "Charcoal",       primaryColor: "#6b7280", sidebarColor: "#111827" },
  { name: "Black & Gold",   primaryColor: "#d97706", sidebarColor: "#000000" },
];

export const FONT_OPTIONS = [
  "Figtree",
  "Inter",
  "Poppins",
  "Nunito",
  "DM Sans",
  "Plus Jakarta Sans",
  "Outfit",
  "Montserrat",
  "Raleway",
  "Lato",
  "Open Sans",
];

// ---------------------------------------------------------------------------
// Color utilities
// ---------------------------------------------------------------------------

/** Parse hex #rrggbb → {r, g, b} */
export function hexToRgb(hex: string | null | undefined): { r: number; g: number; b: number } | null {
  if (!hex || typeof hex !== "string") return null;
  const clean = hex.replace("#", "");
  if (clean.length !== 6) return null;
  return {
    r: parseInt(clean.slice(0, 2), 16),
    g: parseInt(clean.slice(2, 4), 16),
    b: parseInt(clean.slice(4, 6), 16),
  };
}

/** Mix hex color with white at `amount` (0–1 = 0%–100% white) */
function mixWithWhite(hex: string, amount: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const r = Math.round(rgb.r + (255 - rgb.r) * amount);
  const g = Math.round(rgb.g + (255 - rgb.g) * amount);
  const b = Math.round(rgb.b + (255 - rgb.b) * amount);
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

/** Darken by mixing with black */
function mixWithBlack(hex: string, amount: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const r = Math.round(rgb.r * (1 - amount));
  const g = Math.round(rgb.g * (1 - amount));
  const b = Math.round(rgb.b * (1 - amount));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

/** Perceived brightness (0–255). > 128 = light color */
export function brightness(hex: string | null | undefined): number {
  const rgb = hexToRgb(hex);
  if (!rgb) return 128;
  return (rgb.r * 299 + rgb.g * 587 + rgb.b * 114) / 1000;
}

// "rounded" is the default scale and sets the app's corner language. Hospitality Hybrid uses 12px for controls (cards add
// 4px on top), friendlier than the old 8px without becoming pill-shaped.
const RADIUS_MAP = { sharp: "4px", rounded: "12px", pill: "9999px" };
const RADIUS_BTN_MAP = { sharp: "4px", rounded: "10px", pill: "9999px" };

// The app's own type and colour defaults. A theme that still carries the PREVIOUS defaults (teal + navy, Inter) was never
// customised by the tenant, so it follows the current house style instead of freezing the old one.
// Earlier house defaults, as [primary, sidebar] pairs. A workspace still on one never customised its colours, so it follows
// the current default: teal + navy (until Oct 2026), plum + white (Hybrid launch, 17-18 Oct 2026) and sea green + white
// (18-22 Oct 2026).
const LEGACY_DEFAULTS: [string, string][] = [["#14b8a6", "#0b1f3a"], ["#0f766e", "#0b1f3a"], ["#5a2d6b", "#ffffff"], ["#1e7a5a", "#ffffff"]];
const APP_FONTS = ["Figtree", "Inter"];

/** Primary as seen in dark mode: the house sea green lifts to sage; any other brand colour is lifted towards white
 *  until it reads on the dark canvas. */
function primaryOnDark(p: string): string {
  if (isHousePrimary(p)) return "#8EB69B";
  const b = brightness(p);
  return b < 90 ? mixWithWhite(p, 0.55) : b < 140 ? mixWithWhite(p, 0.35) : p;
}

function isHousePrimary(p: string): boolean {
  return (p || "").toLowerCase() === DEFAULT_THEME.primaryColor.toLowerCase();
}

/** Build the full CSS variable map from a BrandTheme. An empty string means "remove this property" (applyTheme). */
export function buildCSSVars(theme: BrandTheme): Record<string, string> {
  const p = theme.primaryColor;
  const s = theme.sidebarColor;
  const house = isHousePrimary(p);
  const onPrimary = brightness(p) > 160 ? "#1C1917" : "#FFFFFF";
  const onDark = primaryOnDark(p);
  const onPrimaryDark = brightness(onDark) > 150 ? "#1C1917" : "#FFFFFF";

  return {
    "--brand-primary":        p,
    "--brand-primary-light":  mixWithWhite(p, 0.88),   // very light tint
    "--brand-primary-muted":  mixWithWhite(p, 0.75),   // hover tint
    "--brand-primary-dark":   mixWithBlack(p, 0.20),   // darker for hover buttons
    "--brand-primary-text":   brightness(p) > 160
                                ? mixWithBlack(p, 0.35)
                                : mixWithWhite(p, 0.15),
    "--brand-sidebar-bg":     s,
    "--brand-sidebar-text":   mixWithWhite(s, 0.55),
    "--brand-sidebar-active": p,
    "--brand-topbar-bg":      s,
    "--brand-logo-url":       theme.logoUrl ? `url("${theme.logoUrl}")` : "",
    "--brand-font":           `"${theme.fontFamily}", ui-sans-serif, system-ui, sans-serif`,
    "--brand-radius-card":    RADIUS_MAP[theme.radiusScale],
    "--brand-radius-btn":     RADIUS_BTN_MAP[theme.radiusScale],
    "--brand-primary-rgb":    (() => {
      const rgb = hexToRgb(p);
      return rgb ? `${rgb.r}, ${rgb.g}, ${rgb.b}` : "20, 184, 166";
    })(),
    "--brand-sidebar-rgb":    (() => {
      const rgb = hexToRgb(s);
      return rgb ? `${rgb.r}, ${rgb.g}, ${rgb.b}` : "11, 31, 58";
    })(),

    // ── Canonical token feeds ───────────────────────────────────────────────
    // globals.css maps --primary, --ring, --radius and friends onto these per theme (light and dark), so a tenant's colour
    // reaches every Tailwind utility and the --haip-* layer, and dark mode can still lift it. They used to be written here
    // straight onto <html>, which beat the .dark rules and left a dark brand colour on a dark page.
    "--brand-on-primary":        onPrimary,
    "--brand-primary-on-dark":   onDark,
    "--brand-on-primary-dark":   onPrimaryDark,
    // Primary BUTTONS: the house theme paints them terracotta (--haip-action in globals.css), so these stay unset; a
    // tenant with its own brand colour gets its colour back on buttons.
    "--brand-action":            house ? "" : p,
    "--brand-on-action":         house ? "" : onPrimary,
    "--brand-action-on-dark":    house ? "" : onDark,
    "--brand-on-action-dark":    house ? "" : onPrimaryDark,
    "--brand-radius":            RADIUS_MAP[theme.radiusScale],
    // NOTE: --font-sans is deliberately NOT set here. It is owned by next/font (app/layout.tsx, Figtree); applyTheme()
    // only overrides it when a tenant picks a different font, see below.
  };
}

/** Inject CSS variables into :root */
export function applyTheme(theme: BrandTheme): void {
  if (typeof document === "undefined") return;
  const vars = buildCSSVars(theme);
  const root = document.documentElement;
  Object.entries(vars).forEach(([k, v]) => (v === "" ? root.style.removeProperty(k) : root.style.setProperty(k, v)));

  // Font injection (Google Fonts). Only a non-default font overrides --font-sans; the app font stays on next/font's
  // self-hosted copy. Choosing the app font again removes an earlier override.
  if (theme.fontFamily && !APP_FONTS.includes(theme.fontFamily)) {
    root.style.setProperty(
      "--font-sans",
      `"${theme.fontFamily}", ui-sans-serif, system-ui, sans-serif`,
    );
    const fontName = theme.fontFamily.replace(/ /g, "+");
    const existingLink = document.getElementById("brand-font-link");
    if (!existingLink) {
      const link = document.createElement("link");
      link.id = "brand-font-link";
      link.rel = "stylesheet";
      link.href = `https://fonts.googleapis.com/css2?family=${fontName}:wght@300;400;500;600;700&display=swap`;
      document.head.appendChild(link);
    } else {
      (existingLink as HTMLLinkElement).href =
        `https://fonts.googleapis.com/css2?family=${fontName}:wght@300;400;500;600;700&display=swap`;
    }
  } else {
    root.style.removeProperty("--font-sans");
  }
  // Themes applied by an older build wrote these straight onto <html>; clear them so globals.css owns the mapping.
  ["--primary", "--primary-foreground", "--ring", "--sidebar", "--sidebar-primary", "--sidebar-foreground", "--radius"]
    .forEach(k => root.style.removeProperty(k));
}

/** Themes saved before the wordmark was cropped still point at /logo.png,
 * whose letters fill only ~20% of the image height -- swap in the tight
 * crop so the logo is readable wherever it's shown. Uploaded logos are
 * left alone. */
export function withCurrentDefaultLogo(t: BrandTheme): BrandTheme {
  const fix = (u?: string) => (u === "/logo.png" ? "/logo-wordmark.png" : u);
  const legacyColours = LEGACY_DEFAULTS.some(([pr, sb]) => (t.primaryColor || "").toLowerCase() === pr && (t.sidebarColor || "").toLowerCase() === sb);
  return {
    ...t,
    logoUrl: fix(t.logoUrl),
    logoDarkUrl: fix(t.logoDarkUrl),
    // Never customised: follow the current house style (see LEGACY_DEFAULTS).
    ...(legacyColours ? { primaryColor: DEFAULT_THEME.primaryColor, sidebarColor: DEFAULT_THEME.sidebarColor } : {}),
    ...(t.fontFamily === "Inter" ? { fontFamily: DEFAULT_THEME.fontFamily } : {}),
  };
}

/** Load saved theme from localStorage (instant, no flash) */
export function loadSavedTheme(): BrandTheme {
  if (typeof window === "undefined") return DEFAULT_THEME;
  try {
    const raw = localStorage.getItem("haip_brand_theme");
    if (raw) return withCurrentDefaultLogo({ ...DEFAULT_THEME, ...JSON.parse(raw) });
  } catch { /* ignore */ }
  return DEFAULT_THEME;
}

/** Persist theme to localStorage */
export function saveThemeLocally(theme: BrandTheme): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("haip_brand_theme", JSON.stringify(theme));
}
