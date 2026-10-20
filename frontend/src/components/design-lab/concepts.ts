// The six directions the lab compares. Descriptions say what each one is for, so the choice is about fit, not swatches.
export type Screen = "home" | "inbox" | "leads" | "calendar";
export type ConceptId = "atlas" | "milestone" | "atelier" | "calm" | "command" | "hybrid";

export const SCREENS: { id: Screen; label: string }[] = [
  { id: "home", label: "Home" },
  { id: "inbox", label: "Inbox" },
  { id: "leads", label: "Leads 360" },
  { id: "calendar", label: "Calendar" },
];

export interface ConceptMeta {
  id: ConceptId; letter: string; name: string; thesis: string; detail: string;
  swatches: string[]; type: string; nav: string; signature: string;
}

export const CONCEPTS: ConceptMeta[] = [
  {
    id: "atlas", letter: "A", name: "Field Atlas",
    thesis: "Indian road-atlas cartography for a company that lives on the road.",
    detail: "Warm map-paper ground, forest-ink sidebar, ochre for actions, river blue for information and laterite red only when it is urgent. Contour-thin rules instead of boxes.",
    swatches: ["#F3F0E8", "#1E3A2B", "#9A5A0C", "#2563A0", "#A63D2A"],
    type: "Public Sans + Barlow Semi Condensed labels", nav: "Forest sidebar · phone: top bar + bottom tabs",
    signature: "Every guest's story drawn as a route with stops; bookings as road segments with milestone dots.",
  },
  {
    id: "milestone", letter: "B", name: "Milestone",
    thesis: "Highway signage: read at a glance, in sunlight, at speed.",
    detail: "Crisp white, road-black chrome, signage blue for actions and milestone yellow kept only for what needs you now. Big tabular numerals, compact rows, maximum contrast.",
    swatches: ["#FFFFFF", "#0F0F0F", "#1747C9", "#F5C400", "#C21F1F"],
    type: "Archivo, condensed numerals", nav: "Black top bar · phone: black bottom bar with yellow-cap counts",
    signature: "Milestone counters: queue numbers set like a highway stone with a yellow cap.",
  },
  {
    id: "atelier", letter: "C", name: "Indigo Atelier",
    thesis: "Heritage-hotel stationery and Jaipur indigo, made practical.",
    detail: "Linen ground, deep indigo shell, brass for small highlights and madder only for urgency. Serif headings over a crisp sans; fine ruled lists instead of heavy cards.",
    swatches: ["#F4F2EC", "#1E2353", "#2F3A8F", "#9C7A33", "#A8402E"],
    type: "Spectral headings + Manrope", nav: "Indigo sidebar · phone: top bar + drawer",
    signature: "A booking register: the calendar and lists read like a hotel's folio, with serif dates.",
  },
  {
    id: "calm", letter: "D", name: "Calm SaaS",
    thesis: "The category standard, played straight and very well.",
    detail: "Neutral zinc surfaces, one accent (HAIP teal), quiet borders, dense tables and a command bar. Nothing themed; everything consistent and fast.",
    swatches: ["#FAFAFA", "#FFFFFF", "#18181B", "#0F766E", "#E4E4E7"],
    type: "Geist + Geist Mono figures", nav: "Light sidebar + command bar · phone: bottom tabs",
    signature: "Speed: ⌘K everywhere, keyboard hints, compact density.",
  },
  {
    id: "command", letter: "E", name: "AI Command Center",
    thesis: "A live operations room where the AI shows its working.",
    detail: "Low-glare dark surfaces, one cool blue for actions, violet reserved for AI. Multi-panel layout with a live status strip and an insight rail that explains every suggestion.",
    swatches: ["#0B0E14", "#131926", "#E6EAF2", "#6E8BFF", "#9D86F5"],
    type: "Onest + JetBrains Mono data", nav: "Icon rail + insight rail · phone: bottom bar + AI sheet",
    signature: "Live status strip and AI cards that say why, with confidence and one-tap actions.",
  },
  {
    id: "hybrid", letter: "F", name: "Hospitality Hybrid",
    thesis: "Built around today's guests: arrivals, conversations and the calendar.",
    detail: "Stone-white surfaces, jamun plum for the brand and actions, marigold for highlights. Friendly radii, guest photos and stay cards, an Airbnb-grade calendar and a phone-first 'Now' button.",
    swatches: ["#F5F5F4", "#FFFFFF", "#5A2D6B", "#D9930D", "#1C1917"],
    type: "Bricolage Grotesque headings + Figtree", nav: "Top bar with 'Today' · phone: bottom bar with a raised Now button",
    signature: "The Today strip and stay cards: every guest shown as a stay, not a ticket.",
  },
];

export const CONCEPT_BY_ID = Object.fromEntries(CONCEPTS.map(c => [c.id, c])) as Record<ConceptId, ConceptMeta>;

export function isConcept(v: unknown): v is ConceptId {
  return typeof v === "string" && v in CONCEPT_BY_ID;
}
export function isScreen(v: unknown): v is Screen {
  return v === "home" || v === "inbox" || v === "leads" || v === "calendar";
}
