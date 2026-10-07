// Types and small helpers for the Bookings list and booking page.
// Shapes mirror backend/app/api/v1/endpoints/booking_detail.py and bookings.py.

export type BookingStatus = "confirmed" | "checked_in" | "checked_out" | "cancelled";
export type PaymentStatus = "unpaid" | "partial" | "paid";
export type PayMethod = "upi" | "cash" | "card" | "bank_transfer" | "razorpay" | "other";

export const STATUS_OPTIONS: { value: BookingStatus; label: string }[] = [
  { value: "confirmed", label: "Confirmed" },
  { value: "checked_in", label: "Checked in" },
  { value: "checked_out", label: "Checked out" },
  { value: "cancelled", label: "Cancelled" },
];

export const STATUS_STYLE: Record<string, { label: string; cls: string }> = {
  confirmed:   { label: "Confirmed",   cls: "bg-blue-50 text-blue-700 border-blue-100" },
  checked_in:  { label: "Checked in",  cls: "bg-emerald-50 text-emerald-700 border-emerald-100" },
  checked_out: { label: "Checked out", cls: "bg-gray-100 text-gray-600 border-gray-200" },
  cancelled:   { label: "Cancelled",   cls: "bg-red-50 text-red-700 border-red-100" },
};

export const PAYMENT_STYLE: Record<string, { label: string; cls: string }> = {
  unpaid:  { label: "Unpaid",       cls: "bg-red-50 text-red-700 border-red-100" },
  partial: { label: "Part paid",    cls: "bg-amber-50 text-amber-800 border-amber-100" },
  paid:    { label: "Paid",         cls: "bg-emerald-50 text-emerald-700 border-emerald-100" },
};

export const METHOD_LABEL: Record<string, string> = {
  upi: "UPI", cash: "Cash", card: "Card", bank_transfer: "Bank transfer", razorpay: "Razorpay", other: "Other",
};

export interface Financials {
  stay_charge: number;
  addons_total: number;
  total: number;
  paid: number;
  outstanding: number;
  payment_status: PaymentStatus;
}

export interface BookingRow {
  id: string;
  external_id: string;
  checkin: string;
  checkout: string;
  adults: number;
  children: number;
  status: string;
  payment_status: PaymentStatus;
  total: number;
  total_paid: number;
  total_outstanding: number;
  property: { id: string; name: string; type: string } | null;
  main_guest: { id: string | null; first_name: string; last_name: string; phone: string | null; email: string | null } | null;
  channel: string | null;
  created_at: string | null;
}

export interface BookingList {
  data: BookingRow[];
  meta: { current_page: number; last_page: number; per_page: number; total: number; from: number; to: number };
}

export interface AddOnLine { id: string; addon_id: string | null; name: string; quantity: number; unit_price: number; line_total: number; notes: string | null }
export interface PaymentEntry { id: string; kind: "payment" | "refund"; amount: number; method: PayMethod; reference: string | null; paid_on: string; notes: string | null; via_gateway: boolean }
export interface PaymentLink { id: string; short_url: string; amount: number; status: string; expires_at: string | null; created_at: string | null }
export interface CatalogAddOn { id: string; name: string; description: string | null; category: string; price: number; price_type: string; suggested_quantity: number }
export interface ActivityEntry { id: string; action: string; at: string | null; by: string | null; payload: Record<string, unknown> }

export interface BookingDetail {
  id: string;
  status: BookingStatus;
  channel: string | null;
  pms_managed: boolean;
  check_in: string;
  check_out: string;
  nights: number;
  check_in_time: string | null;
  check_out_time: string | null;
  adults: number;
  children: number;
  occasion: string | null;
  special_requests: string;
  internal_notes: string;
  inquiry_id: string | null;
  created_at: string | null;
  property: { id: string; name: string; type: string } | null;
  guest: { id: string; name: string | null; phone: string; email: string | null } | null;
  financials: Financials;
  addons: AddOnLine[];
  payments: PaymentEntry[];
  payment_links: PaymentLink[];
  available_addons: CatalogAddOn[];
  activity: ActivityEntry[];
}

export const PRICE_TYPE_LABEL: Record<string, string> = {
  per_stay: "per stay", per_night: "per night", per_person: "per person", per_unit: "each",
};

export function errorMessage(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && "message" in d && typeof (d as { message: unknown }).message === "string") {
    return (d as { message: string }).message;
  }
  return fallback;
}

export function fmtDate(iso: string | null | undefined, withYear = true): string {
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", ...(withYear ? { year: "numeric" } : {}) });
}

export function describeActivity(a: ActivityEntry): string {
  const p = a.payload as Record<string, unknown> & { changes?: Record<string, { from: unknown; to: unknown }> };
  const inr = (n: unknown) => `₹${Number(n).toLocaleString("en-IN")}`;
  switch (a.action) {
    case "booking.created": return "Booking created";
    case "booking.cancelled": return "Booking cancelled";
    case "booking.updated": {
      const keys = Object.keys(p.changes ?? {});
      const label = keys.map(k => k.replace(/_/g, " ")).join(", ");
      return keys.length ? `Changed ${label}${p.forced ? " (overrode a date conflict)" : ""}` : "Notes updated";
    }
    case "booking.addon_added": return `Added ${p.name} × ${p.quantity}`;
    case "booking.addon_updated": return `Updated ${p.name}`;
    case "booking.addon_removed": return `Removed ${p.name}`;
    case "booking.payment_recorded": return `Payment of ${inr(p.amount)} recorded (${METHOD_LABEL[String(p.method)] ?? p.method})`;
    case "booking.refund_recorded": return `Refund of ${inr(p.amount)} recorded`;
    case "booking.payment_deleted": return `Removed a ${inr(p.amount)} ${p.kind} entry`;
    case "booking.payment_link_created": return `Payment link for ${inr(p.amount)} created`;
    case "booking.payment_received_razorpay": return `${inr(p.amount)} received through Razorpay`;
    case "dpdp.delete_requested": return "Guest data erasure requested";
    default: return a.action.replace(/[._]/g, " ");
  }
}
