// Regional theme packs and personalities. A pack sets colours, the display face and the border pattern; a personality
// sets shape and tone (see site.css .p-*). Colours here are a CLIENT's site palette, not HAIP tokens.
export interface Pack {
  key: string; name: string; note: string;
  bg: string; ink: string; muted: string; card: string; line: string; a: string; b: string; bInk: string; soft: string;
  display: string; body: string; band: "tile" | "wave" | "jali" | "peaks";
}

export const PACKS: Record<string, Pack> = {
  goa: { key: "goa", name: "Goa / Konkan", note: "Azulejo blue, lime", bg: "#F8F5EF", ink: "#16222B", muted: "#55606A", card: "#FFFFFF",
    line: "#E3E0D8", a: "#1F7FC4", b: "#A6D23C", bInk: "#16222B", soft: "#E6F0F8", display: '"DM Serif Display", Georgia, serif',
    body: '"Karla", system-ui, sans-serif', band: "tile" },
  kerala: { key: "kerala", name: "Kerala backwaters", note: "Laterite, palm, brass", bg: "#F3F5EE", ink: "#14261C", muted: "#4F5D53",
    card: "#FFFFFF", line: "#DCE2D6", a: "#1F6B45", b: "#D9A630", bInk: "#14261C", soft: "#E3EEE6", display: '"Marcellus", Georgia, serif',
    body: '"Karla", system-ui, sans-serif', band: "wave" },
  rajasthan: { key: "rajasthan", name: "Rajasthan", note: "Rani pink, indigo", bg: "#FBF3EF", ink: "#2A1A22", muted: "#6A5660",
    card: "#FFFFFF", line: "#EDDCD6", a: "#B23A6B", b: "#2E4A9A", bInk: "#FFFFFF", soft: "#F6E2EA", display: '"Yeseva One", Georgia, serif',
    body: '"Karla", system-ui, sans-serif', band: "jali" },
  malnad: { key: "malnad", name: "Malnad / Coorg", note: "Coffee, forest, mist", bg: "#F4F1EC", ink: "#1F1A16", muted: "#5E564F",
    card: "#FFFFFF", line: "#E2DCD3", a: "#3E6A3A", b: "#9B5B2E", bInk: "#FFFFFF", soft: "#E5ECE2", display: '"DM Serif Display", Georgia, serif',
    body: '"Karla", system-ui, sans-serif', band: "wave" },
  himalaya: { key: "himalaya", name: "Himalaya", note: "Slate, apricot, snow", bg: "#F3F5F7", ink: "#1A222B", muted: "#56606B",
    card: "#FFFFFF", line: "#DDE2E8", a: "#3B5B7A", b: "#E79A55", bInk: "#1A222B", soft: "#E3EAF1", display: '"Marcellus", Georgia, serif',
    body: '"Karla", system-ui, sans-serif', band: "peaks" },
  chettinad: { key: "chettinad", name: "Chettinad", note: "Oxide red, ochre tile", bg: "#FAF4EC", ink: "#241712", muted: "#64534A",
    card: "#FFFFFF", line: "#EADDCF", a: "#A13E25", b: "#D6A237", bInk: "#241712", soft: "#F4E3D9", display: '"Yeseva One", Georgia, serif',
    body: '"Karla", system-ui, sans-serif', band: "tile" },
};

export const PERSONALITIES: Record<string, string> = { playful: "Playful pop", calm: "Calm luxury", heritage: "Heritage" };

export const FONTS_HREF =
  "https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=Karla:wght@400;500;700&family=Marcellus&family=Yeseva+One&display=swap";

export function pack(key: string | undefined): Pack {
  return PACKS[key || ""] || PACKS.malnad;
}

/** CSS custom properties for a pack, set on the site wrapper. */
export function packVars(p: Pack): Record<string, string> {
  return {
    "--k-bg": p.bg, "--k-ink": p.ink, "--k-muted": p.muted, "--k-card": p.card, "--k-line": p.line, "--k-a": p.a, "--k-b": p.b,
    "--k-b-ink": p.bInk, "--k-soft": p.soft, "--k-display": p.display, "--k-body": p.body, "--k-band": bandBg(p),
  };
}

export function bandBg(p: Pack): string {
  const a = encodeURIComponent(p.a), b = encodeURIComponent(p.b), g = encodeURIComponent(p.bg);
  const svg =
    p.band === "wave" ? `<svg xmlns='http://www.w3.org/2000/svg' width='24' height='9'><rect width='24' height='9' fill='${g}'/><path d='M0 6 Q6 0 12 6 T24 6' stroke='${a}' stroke-width='2' fill='none'/><circle cx='12' cy='6' r='1.6' fill='${b}'/></svg>`
    : p.band === "jali" ? `<svg xmlns='http://www.w3.org/2000/svg' width='18' height='9'><rect width='18' height='9' fill='${a}'/><path d='M9 0 L13.5 4.5 L9 9 L4.5 4.5Z' fill='${g}'/><circle cx='9' cy='4.5' r='1.5' fill='${b}'/></svg>`
    : p.band === "peaks" ? `<svg xmlns='http://www.w3.org/2000/svg' width='22' height='9'><rect width='22' height='9' fill='${g}'/><path d='M0 9 L6 2 L11 7 L16 1 L22 9Z' fill='${a}'/><path d='M14.5 2.7 L16 1 L17.5 2.7Z' fill='%23fff'/></svg>`
    : `<svg xmlns='http://www.w3.org/2000/svg' width='20' height='9'><rect width='20' height='9' fill='${a}'/><path d='M0 4.5h20M10 0v9' stroke='${g}' stroke-width='1.2'/><circle cx='10' cy='4.5' r='1.8' fill='${b}'/></svg>`;
  return `url("data:image/svg+xml,${svg}") repeat-x`;
}
