// Design lab: six UI directions for HAIP on the same synthetic data. Development only (each page 404s in production), not
// linked from the app, and never talks to the backend.
import type { Metadata } from "next";
import "./design-lab.css";
import {
  Archivo, Barlow_Semi_Condensed, Bricolage_Grotesque, Figtree, Geist, Geist_Mono, JetBrains_Mono, Manrope, Onest,
  Public_Sans, Spectral,
} from "next/font/google";

export const metadata: Metadata = { title: "HAIP design lab", robots: { index: false, follow: false } };

const publicSans = Public_Sans({ subsets: ["latin"], variable: "--lab-public-sans", display: "swap" });
const barlowSemi = Barlow_Semi_Condensed({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--lab-barlow-semi", display: "swap" });
const archivo = Archivo({ subsets: ["latin"], axes: ["wdth"], variable: "--lab-archivo", display: "swap" });
const spectral = Spectral({ subsets: ["latin"], weight: ["400", "500", "600"], style: ["normal", "italic"], variable: "--lab-spectral", display: "swap" });
const manrope = Manrope({ subsets: ["latin"], variable: "--lab-manrope", display: "swap" });
const geist = Geist({ subsets: ["latin"], variable: "--lab-geist", display: "swap" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--lab-geist-mono", display: "swap" });
const onest = Onest({ subsets: ["latin"], variable: "--lab-onest", display: "swap" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--lab-jetbrains", display: "swap" });
const bricolage = Bricolage_Grotesque({ subsets: ["latin"], variable: "--lab-bricolage", display: "swap" });
const figtree = Figtree({ subsets: ["latin"], variable: "--lab-figtree", display: "swap" });

const FONT_VARS = [publicSans, barlowSemi, archivo, spectral, manrope, geist, geistMono, onest, jetbrains, bricolage, figtree]
  .map(f => f.variable).join(" ");

export default function DesignLabLayout({ children }: { children: React.ReactNode }) {
  return <div className={FONT_VARS}>{children}</div>;
}
