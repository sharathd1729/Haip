// Guest add-ons page (backend services/guest_addons.py): types + the pure maths the page shows. The server prices again on
// submit (published add-on prices only); these numbers are only what the guest sees while picking.

export interface AddonOffer {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  price: number;
  price_type: string;
  unit: string;
  default_quantity: number;
  max_quantity: number;
  needs_approval: boolean;
  stay_change: string | null;
  available: boolean;
  unavailable_reason: string | null;
}

export interface AddonOrderItem { addon_id: string; name: string; quantity: number; unit_price: number; line_total: number }

export interface AddonOrder {
  id: string;
  status: "awaiting_approval" | "awaiting_payment" | "paid" | "declined" | "cancelled";
  amount: number;
  items: AddonOrderItem[];
  pay_url: string | null;
  decline_reason: string | null;
  created_at: string | null;
  paid_at: string | null;
}

export interface AddonsView {
  business_name: string;
  guest_first_name: string;
  property_name: string;
  check_in: string;
  check_out: string;
  nights: number;
  guests: number;
  open: boolean;
  offers: AddonOffer[];
  orders: AddonOrder[];
}

export type Picks = Record<string, number>; // addon_id -> quantity

export interface ReceiptLine { id: string; name: string; detail: string; amount: number; later: boolean }

export const inr = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function quantityWord(o: AddonOffer, q: number): string {
  if (o.price_type === "per_night") return plural(q, "night", "nights");
  if (o.price_type === "per_person") return plural(q, "person", "people");
  if (o.price_type === "per_unit") return `${q} ×`;
  return "Once";
}

/** The lines the guest has picked, what they pay now (no staff OK needed) and what waits for the team. */
export function receipt(offers: AddonOffer[], picks: Picks): { lines: ReceiptLine[]; payNow: number; later: number } {
  const lines: ReceiptLine[] = [];
  for (const o of offers) {
    const q = picks[o.id];
    if (!q || !o.available) continue;
    const amount = o.price * q;
    lines.push({ id: o.id, name: o.name, detail: o.needs_approval ? `${quantityWord(o, q)} · we confirm first` : quantityWord(o, q),
      amount, later: o.needs_approval });
  }
  const payNow = lines.filter(l => !l.later).reduce((a, l) => a + l.amount, 0);
  const later = lines.filter(l => l.later).reduce((a, l) => a + l.amount, 0);
  return { lines, payNow, later };
}

/** Whole days from today (YYYY-MM-DD, the guest's own date) to check-in; 0 on the day, negative once it started. */
export function daysToGo(checkIn: string, today: string): number {
  return Math.round((Date.parse(`${checkIn}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
}

export function greeting(name: string, days: number): string {
  if (days > 1) return `Hi ${name}, ${days} days to go`;
  if (days === 1) return `Hi ${name}, see you tomorrow`;
  if (days === 0) return `Hi ${name}, welcome today`;
  return `Hi ${name}, enjoy your stay`;
}

export function payLabel(payNow: number, later: number): string {
  if (payNow > 0) return `Pay ${inr(payNow)}`;
  if (later > 0) return "Send request";
  return "Pick an add-on";
}
