// Self-hosted fonts for v2 sites (website phase 3). next/font downloads these at BUILD time and serves them from the
// site's own origin: no request to Google at runtime (faster first paint, nothing to consent to). Every font is OFL.
// preload: false, so a page downloads only the two faces its theme uses. Imported by the root layout ONLY: next/font
// needs literal options in each call (no spread) and must stay out of the Edge middleware's imports (lib/haip.ts uses
// lib/fonts.ts). The --hf-* names must match the keys in lib/fonts.ts.
import {
  Bricolage_Grotesque, Cormorant_Garamond, DM_Sans, DM_Serif_Display, Figtree, Fraunces, Instrument_Serif, Inter, Karla,
  Manrope, Playfair_Display, Source_Sans_3,
} from "next/font/google";

const fraunces = Fraunces({ subsets: ["latin"], display: "swap", preload: false, style: ["normal", "italic"], variable: "--hf-fraunces" });
const bricolage = Bricolage_Grotesque({ subsets: ["latin"], display: "swap", preload: false, variable: "--hf-bricolage" });
const instrument = Instrument_Serif({ subsets: ["latin"], display: "swap", preload: false, weight: "400", style: ["normal", "italic"], variable: "--hf-instrument-serif" });
const dmSerif = DM_Serif_Display({ subsets: ["latin"], display: "swap", preload: false, weight: "400", style: ["normal", "italic"], variable: "--hf-dm-serif" });
const cormorant = Cormorant_Garamond({ subsets: ["latin"], display: "swap", preload: false, weight: ["500", "600"], style: ["normal", "italic"], variable: "--hf-cormorant" });
const playfair = Playfair_Display({ subsets: ["latin"], display: "swap", preload: false, style: ["normal", "italic"], variable: "--hf-playfair" });
const figtree = Figtree({ subsets: ["latin"], display: "swap", preload: false, variable: "--hf-figtree" });
const inter = Inter({ subsets: ["latin"], display: "swap", preload: false, variable: "--hf-inter" });
const karla = Karla({ subsets: ["latin"], display: "swap", preload: false, variable: "--hf-karla" });
const manrope = Manrope({ subsets: ["latin"], display: "swap", preload: false, variable: "--hf-manrope" });
const sourceSans = Source_Sans_3({ subsets: ["latin"], display: "swap", preload: false, variable: "--hf-source-sans" });
const dmSans = DM_Sans({ subsets: ["latin"], display: "swap", preload: false, variable: "--hf-dm-sans" });

/** Class names that define every --hf-* variable (put on <html>). */
export const FONT_VARS = [fraunces, bricolage, instrument, dmSerif, cormorant, playfair, figtree, inter, karla, manrope,
  sourceSans, dmSans].map(f => f.variable).join(" ");
