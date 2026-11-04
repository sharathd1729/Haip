// v2 sites self-host their fonts (lib/font-faces.ts defines the --hf-* variables). Keys = the v2 catalogue's font keys
// (backend/app/services/website_spec_v2.json "fonts"); a key missing here falls back to the catalogue's own stack.
// No next/font import here: lib/haip.ts (and so the Edge middleware) imports this file.
const KEYS = new Set(["fraunces", "bricolage", "instrument-serif", "dm-serif", "cormorant", "playfair", "figtree", "inter",
  "karla", "manrope", "source-sans", "dm-sans"]);

/** The theme's font stack with the self-hosted face first: var(--hf-fraunces), "Fraunces", Georgia, serif. */
export function selfHosted(key: string | undefined, stack: string | undefined): string | undefined {
  return key && KEYS.has(key) ? `var(--hf-${key}), ${stack || "serif"}` : stack;
}
