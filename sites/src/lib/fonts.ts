// Self-hosted fonts for v2 sites (website phase 3). next/font downloads these at BUILD time and serves them from the
// site's own origin: no request to Google at runtime (faster first paint, nothing to consent to). Every font is OFL.
// preload: false, so a page downloads only the two faces its theme uses. Keys = the v2 catalogue's font keys
// (backend/app/services/website_spec_v2.json "fonts"); a key missing here falls back to the catalogue's own stack.
import {
  Bricolage_Grotesque, Cormorant_Garamond, DM_Sans, DM_Serif_Display, Figtree, Fraunces, Instrument_Serif, Inter, Karla,
  Manrope, Playfair_Display, Source_Sans_3,
} from "next/font/google";

const o = { subsets: ["latin" as const], display: "swap" as const, preload: false };
const both = ["normal", "italic"] as ("normal" | "italic")[];

const fraunces = Fraunces({ ...o, style: both, variable: "--hf-fraunces" });
const bricolage = Bricolage_Grotesque({ ...o, variable: "--hf-bricolage" });
const instrument = Instrument_Serif({ ...o, weight: "400", style: both, variable: "--hf-instrument-serif" });
const dmSerif = DM_Serif_Display({ ...o, weight: "400", style: both, variable: "--hf-dm-serif" });
const cormorant = Cormorant_Garamond({ ...o, weight: ["500", "600"], style: both, variable: "--hf-cormorant" });
const playfair = Playfair_Display({ ...o, style: both, variable: "--hf-playfair" });
const figtree = Figtree({ ...o, variable: "--hf-figtree" });
const inter = Inter({ ...o, variable: "--hf-inter" });
const karla = Karla({ ...o, variable: "--hf-karla" });
const manrope = Manrope({ ...o, variable: "--hf-manrope" });
const sourceSans = Source_Sans_3({ ...o, variable: "--hf-source-sans" });
const dmSans = DM_Sans({ ...o, variable: "--hf-dm-sans" });

/** Class names that define every --hf-* variable (put on <html>). */
export const FONT_VARS = [fraunces, bricolage, instrument, dmSerif, cormorant, playfair, figtree, inter, karla, manrope,
  sourceSans, dmSans].map(f => f.variable).join(" ");

const KEYS = new Set(["fraunces", "bricolage", "instrument-serif", "dm-serif", "cormorant", "playfair", "figtree", "inter",
  "karla", "manrope", "source-sans", "dm-sans"]);

/** The theme's font stack with the self-hosted face first: var(--hf-fraunces), "Fraunces", Georgia, serif. */
export function selfHosted(key: string | undefined, stack: string | undefined): string | undefined {
  return key && KEYS.has(key) ? `var(--hf-${key}), ${stack || "serif"}` : stack;
}
