// SYNTHETIC DEMO DATA for the design lab only. Every name, number and message here is invented so the six concepts can be
// compared on identical content. Nothing in this file is read from or written to the HAIP backend. Dates are fixed (the
// lab's "today" is Sat 17 Oct 2026, IST) so server and browser renders always agree.

export type Channel = "whatsapp" | "instagram" | "call" | "website";
export type Urgency = "now" | "soon" | "calm";

export const TODAY_LABEL = "Sat, 17 Oct";
export const PERIOD_LABEL = "Last 7 days";

export const KPIS = {
  newLeads: { value: 14, change: 27, label: "New leads", note: "people who shared a number" },
  bookings: { value: 6, change: 20, label: "Bookings made", note: "1 cancelled" },
  bookedValue: { value: 342500, change: 12, label: "Booked value", note: "stay charge" },
  cash: { value: 218000, change: -8, label: "Cash collected", note: "₹12,000 refunded" },
  occupancy: { value: 68, change: 5, label: "Occupancy", note: "nights sold, both caravans" },
  response: { value: 6, change: -33, label: "First reply", note: "median minutes" },
};

// Booked value per day, oldest first (14 days; the last 7 are the selected period).
export const TREND = [42000, 0, 61000, 26500, 0, 45500, 32000, 18000, 61000, 0, 88000, 26500, 45500, 103500];
export const TREND_DAYS = ["4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17"];

export const QUEUE = [
  { kind: "missed", label: "Missed calls to return", count: 3, oldest: "2h 10m", urgency: "now" as Urgency },
  { kind: "lead", label: "New leads nobody has called", count: 5, oldest: "48m", urgency: "now" as Urgency },
  { kind: "reply", label: "Guests waiting for a reply", count: 4, oldest: "22m", urgency: "soon" as Urgency },
  { kind: "task", label: "Follow-ups due today", count: 2, oldest: "due 4pm", urgency: "calm" as Urgency },
];

export const SOURCES = [
  { label: "Instagram", value: 6, channel: "instagram" as Channel },
  { label: "WhatsApp", value: 5, channel: "whatsapp" as Channel },
  { label: "Calls", value: 2, channel: "call" as Channel },
  { label: "Website", value: 1, channel: "website" as Channel },
];

export const ALERTS = [
  { tone: "danger" as const, text: "Priya Nair has waited 2h 10m for a call back", action: "Call" },
  { tone: "warning" as const, text: "Balance of ₹18,550 due in 3 days for Rohan Kumar", action: "Remind" },
  { tone: "info" as const, text: "AI: 3 enquiries asked about pets this week. Add a pet policy to the knowledge base?", action: "Review" },
];

export interface Agent { id: string; name: string; initials: string }
export const AGENTS: Agent[] = [
  { id: "asha", name: "Asha Menon", initials: "AM" },
  { id: "bala", name: "Bala Iyer", initials: "BI" },
  { id: "sharath", name: "Sharath D", initials: "SD" },
];

export interface Conversation {
  id: string; name: string; initials: string; channel: Channel; preview: string; time: string;
  unread: number; waiting?: string; agent?: string; stage: string; hot?: boolean; aiDraft?: boolean;
}
export const CONVERSATIONS: Conversation[] = [
  { id: "c1", name: "Priya Nair", initials: "PN", channel: "whatsapp", preview: "Is Ratha 1 free 24–26 Oct for 4 of us?", time: "4m", unread: 2, waiting: "22m", agent: "Asha Menon", stage: "Active", hot: true, aiDraft: true },
  { id: "c2", name: "Rahul Sharma", initials: "RS", channel: "instagram", preview: "Saw your Coorg reel 😍 what's the price for 2 nights?", time: "18m", unread: 1, waiting: "18m", stage: "General", aiDraft: true },
  { id: "c3", name: "Meera Reddy", initials: "MR", channel: "whatsapp", preview: "Perfect, sending the advance now.", time: "41m", unread: 0, agent: "Bala Iyer", stage: "Quoted" },
  { id: "c4", name: "Kabir Shah", initials: "KS", channel: "call", preview: "Missed call · 2h 10m ago", time: "2h", unread: 0, waiting: "2h 10m", stage: "General", hot: true },
  { id: "c5", name: "Ananya Rao", initials: "AR", channel: "instagram", preview: "Can we bring our golden retriever?", time: "3h", unread: 0, agent: "Asha Menon", stage: "Active" },
  { id: "c6", name: "Vikram Pillai", initials: "VP", channel: "whatsapp", preview: "Thanks! See you on the 20th.", time: "5h", unread: 0, agent: "Bala Iyer", stage: "Sold" },
  { id: "c7", name: "Isha Gupta", initials: "IG", channel: "website", preview: "Booking enquiry: anniversary trip, Wayanad", time: "1d", unread: 0, stage: "Active" },
  { id: "c8", name: "Arjun Menon", initials: "AM", channel: "whatsapp", preview: "We'll decide by the weekend.", time: "2d", unread: 0, agent: "Asha Menon", stage: "Quoted" },
];

export interface Message { id: string; from: "guest" | "agent" | "ai" | "note"; text: string; time: string; author?: string }
export const THREAD: Message[] = [
  { id: "m1", from: "guest", text: "Hi! Saw your caravan on Instagram. Is Ratha 1 free 24–26 Oct?", time: "10:02" },
  { id: "m2", from: "ai", text: "Hi Priya, thanks for writing to Ratha! Ratha 1 is free on 24–26 Oct. How many of you are travelling?", time: "10:03", author: "Sent by AI" },
  { id: "m3", from: "guest", text: "4 of us, 2 adults and 2 kids. Can we do Coorg?", time: "10:11" },
  { id: "m4", from: "note", text: "Family trip, kids 6 and 9. Offer the Coorg 2-night route.", time: "10:14", author: "Asha · internal" },
  { id: "m5", from: "guest", text: "Is Ratha 1 free 24–26 Oct for 4 of us? And what's the total?", time: "10:41" },
];
export const AI_DRAFT = "Yes, Ratha 1 is held for you on 24–26 Oct. For 2 adults and 2 children on the Coorg route, I'll call you in 5 minutes with the full quote. Is this number good?";

export const GUEST = {
  name: "Priya Nair", phone: "+91 98•••• 4310", city: "Bengaluru", firstTouch: "Instagram ad · 15 Oct",
  trip: { dates: "24 – 26 Oct", party: "2 adults, 2 children", route: "Coorg", occasion: "Family holiday" },
  owner: "Asha Menon", stage: "Active", value: "₹45,500 (estimate)",
  journey: [
    { label: "Instagram ad reply", when: "15 Oct, 9:40", done: true },
    { label: "Shared phone number", when: "15 Oct, 9:52", done: true },
    { label: "Call · 3 min, quoted", when: "16 Oct, 11:05", done: true },
    { label: "Waiting for our reply", when: "Today, 10:41", done: false },
    { label: "Booking", when: "", done: false },
  ],
};

export type StageKey = "general" | "active" | "quoted" | "sold" | "lost";
export const STAGES: { key: StageKey; label: string; count: number; value: string }[] = [
  { key: "general", label: "General enquiry", count: 21, value: "" },
  { key: "active", label: "Active", count: 12, value: "₹4,82,000" },
  { key: "quoted", label: "Quoted", count: 6, value: "₹2,61,500" },
  { key: "sold", label: "Sold", count: 9, value: "₹3,42,500" },
  { key: "lost", label: "Lost", count: 7, value: "" },
];

export interface Lead {
  id: string; name: string; initials: string; stage: StageKey; channel: Channel; dates?: string; party?: string;
  value?: number; owner?: string; next: string; due?: string; priority: "hot" | "warm" | "cold"; waiting?: string;
}
export const LEADS: Lead[] = [
  { id: "l1", name: "Priya Nair", initials: "PN", stage: "active", channel: "whatsapp", dates: "24–26 Oct", party: "2 + 2 kids", value: 45500, owner: "Asha Menon", next: "Call with quote", due: "now", priority: "hot", waiting: "22m" },
  { id: "l2", name: "Kabir Shah", initials: "KS", stage: "general", channel: "call", next: "Return missed call", due: "now", priority: "hot", waiting: "2h 10m" },
  { id: "l3", name: "Rahul Sharma", initials: "RS", stage: "general", channel: "instagram", dates: "7–9 Nov", party: "2 adults", next: "Ask for phone number", due: "today", priority: "warm" },
  { id: "l4", name: "Ananya Rao", initials: "AR", stage: "active", channel: "instagram", dates: "31 Oct–2 Nov", party: "2 + dog", value: 32000, owner: "Asha Menon", next: "Confirm pet policy", due: "today", priority: "warm" },
  { id: "l5", name: "Isha Gupta", initials: "IG", stage: "active", channel: "website", dates: "14–16 Nov", party: "2 adults", value: 61000, next: "Assign an owner", due: "today", priority: "warm" },
  { id: "l6", name: "Meera Reddy", initials: "MR", stage: "quoted", channel: "whatsapp", dates: "20–22 Oct", party: "4 adults", value: 88000, owner: "Bala Iyer", next: "Collect advance", due: "today", priority: "hot" },
  { id: "l7", name: "Arjun Menon", initials: "AM", stage: "quoted", channel: "whatsapp", dates: "1–3 Nov", party: "3 adults", value: 45500, owner: "Asha Menon", next: "Follow up Saturday", due: "Sat", priority: "cold" },
  { id: "l8", name: "Vikram Pillai", initials: "VP", stage: "sold", channel: "whatsapp", dates: "20–22 Oct", party: "2 adults", value: 26500, owner: "Bala Iyer", next: "Send pre-trip checklist", due: "Mon", priority: "cold" },
  { id: "l9", name: "Divya Kumar", initials: "DK", stage: "sold", channel: "call", dates: "25–27 Oct", party: "2 + 1 kid", value: 61000, owner: "Asha Menon", next: "Collect balance", due: "21 Oct", priority: "warm" },
  { id: "l10", name: "Rohan Iyer", initials: "RI", stage: "lost", channel: "instagram", next: "Lost: chose a resort", priority: "cold" },
];

// Calendar: 21 days from Mon 12 Oct 2026; day index 0 = 12 Oct. Bars run check-in (afternoon) to check-out (morning).
export const CAL_START_DAY = 12;
export const CAL_DAYS = 21;
export const CAL_TODAY_INDEX = 5; // 17 Oct
export const CAL_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const PROPERTIES = [
  { id: "r1", name: "Ratha 1", note: "Black · sleeps 4" },
  { id: "r2", name: "Ratha 2", note: "White · sleeps 6" },
];
export type ResKind = "direct" | "ota" | "blocked" | "maintenance" | "hold";
export interface Reservation {
  id: string; property: "r1" | "r2"; guest: string; start: number; end: number; kind: ResKind; source: string;
  amount?: number; paid?: number; party?: string; route?: string; status: string;
}
export const RESERVATIONS: Reservation[] = [
  { id: "b1", property: "r1", guest: "Sneha Reddy", start: 1, end: 3, kind: "direct", source: "WhatsApp", amount: 32000, paid: 32000, party: "2 adults", route: "Sakleshpur", status: "Checked out" },
  { id: "b2", property: "r1", guest: "Vikram Pillai", start: 8, end: 10, kind: "direct", source: "WhatsApp", amount: 26500, paid: 7950, party: "2 adults", route: "Chikmagalur", status: "Confirmed" },
  { id: "b3", property: "r1", guest: "Priya Nair", start: 12, end: 14, kind: "hold", source: "WhatsApp", amount: 45500, paid: 0, party: "2 + 2 kids", route: "Coorg", status: "Held for quote" },
  { id: "b4", property: "r2", guest: "Divya Kumar", start: 13, end: 15, kind: "direct", source: "Phone", amount: 61000, paid: 18300, party: "2 + 1 kid", route: "Wayanad", status: "Confirmed" },
  { id: "b5", property: "r2", guest: "Maintenance", start: 3, end: 5, kind: "maintenance", source: "Ops", status: "Generator service" },
  { id: "b6", property: "r2", guest: "Meera Reddy", start: 8, end: 10, kind: "direct", source: "Instagram", amount: 88000, paid: 26400, party: "4 adults", route: "Coorg", status: "Confirmed" },
  { id: "b7", property: "r2", guest: "Airbnb guest", start: 11, end: 13, kind: "ota", source: "Airbnb", amount: 41000, paid: 41000, party: "3 adults", route: "Kabini", status: "Confirmed" },
  { id: "b8", property: "r2", guest: "Owner use", start: 16, end: 18, kind: "blocked", source: "Owner", status: "Blocked" },
];

export const SELECTED_RES = "b2";

export const CHANNEL_LABEL: Record<Channel, string> = { whatsapp: "WhatsApp", instagram: "Instagram", call: "Call", website: "Website" };

export function inr(n: number): string {
  return "₹" + Math.round(n).toLocaleString("en-IN");
}
export function inrShort(n: number): string {
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(1)}Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(2)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(1)}k`;
  return `₹${n}`;
}
export function dayLabel(index: number): { dow: string; day: number; month: string } {
  const d = CAL_START_DAY + index;
  const month = d > 31 ? "Nov" : "Oct";
  return { dow: CAL_WEEKDAYS[index % 7], day: d > 31 ? d - 31 : d, month };
}
