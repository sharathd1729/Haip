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
  primaryColor: string;        // hex, e.g. "#14b8a6"
  sidebarColor: string;        // hex, e.g. "#0B1F3A"
  logoUrl?: string;            // uploaded logo URL
  logoDarkUrl?: string;        // dark-bg variant
  fontFamily: string;          // Google Font name or "Inter"
  radiusScale: "sharp" | "rounded" | "pill";
  companyName: string;
  tagline?: string;
}

export const DEFAULT_THEME: BrandTheme = {
  primaryColor: "#14b8a6",
  sidebarColor: "#0B1F3A",
  logoUrl: "/logo.png",
  logoDarkUrl: "/logo.png",
  fontFamily: "Inter",
  radiusScale: "rounded",
  companyName: "HAIP",
  tagline: "Hospitality AI",
};

export const PRESET_THEMES: { name: string; primaryColor: string; sidebarColor: string }[] = [
  { name: "HAIP Teal",      primaryColor: "#14b8a6", sidebarColor: "#0B1F3A" },
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

// "rounded" is the default scale and sets the app's overall corner language.
// 8px/7px per HAIP_Prototype.html (--radius:8px, .btn{border-radius:7px}) —
// tighter than the previous 12px/10px, which read softer and more consumer
// than the dense operator tooling this is.
const RADIUS_MAP = { sharp: "4px", rounded: "8px", pill: "9999px" };
const RADIUS_BTN_MAP = { sharp: "4px", rounded: "7px", pill: "9999px" };

/** Build the full CSS variable map from a BrandTheme */
export function buildCSSVars(theme: BrandTheme): Record<string, string> {
  const p = theme.primaryColor;
  const s = theme.sidebarColor;

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

    // ── Canonical token overrides ──────────────────────────────────────────
    // The --brand-* vars above are only read by a couple of components. These
    // override the canonical tokens in globals.css, which every Tailwind
    // utility (bg-primary, ring-*) and the whole --haip-* alias layer resolve
    // through — so a tenant's colours actually reach the UI. See docs/DESIGN.md.
    "--primary":            p,
    "--primary-foreground": brightness(p) > 160 ? "#111827" : "#ffffff",
    "--ring":               p,
    "--sidebar":            s,
    "--sidebar-primary":    p,
    "--sidebar-foreground": brightness(s) > 160 ? "#111827" : mixWithWhite(s, 0.65),
    "--radius":             RADIUS_MAP[theme.radiusScale],
    // NOTE: --font-sans is deliberately NOT set here. It is owned by next/font
    // (app/layout.tsx), which self-hosts an optimised Inter. applyTheme() only
    // overrides it when a tenant picks a different font — see below.
  };
}

/** Inject CSS variables into :root */
export function applyTheme(theme: BrandTheme): void {
  if (typeof document === "undefined") return;
  const vars = buildCSSVars(theme);
  const root = document.documentElement;
  Object.entries(vars).forEach(([k, v]) => root.style.setProperty(k, v));

  // Font injection (Google Fonts). Only a non-default font overrides
  // --font-sans; the "Inter" default stays on next/font's optimised copy.
  if (theme.fontFamily && theme.fontFamily !== "Inter") {
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
  }
}

/** Load saved theme from localStorage (instant, no flash) */
export function loadSavedTheme(): BrandTheme {
  if (typeof window === "undefined") return DEFAULT_THEME;
  try {
    const raw = localStorage.getItem("haip_brand_theme");
    if (raw) return { ...DEFAULT_THEME, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return DEFAULT_THEME;
}

/** Persist theme to localStorage */
export function saveThemeLocally(theme: BrandTheme): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("haip_brand_theme", JSON.stringify(theme));
}
