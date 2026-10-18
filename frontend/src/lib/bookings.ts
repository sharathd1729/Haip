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

// Tone per state. Words carry the meaning; colour only reinforces it (StatusPill in components/ui/page.tsx).
export type PillTone = "neutral" | "info" | "success" | "warning" | "danger" | "brand";
export const STATUS_TONE: Record<string, PillTone> = {
  confirmed: "info", checked_in: "success", checked_out: "neutral", cancelled: "danger",
};
export const PAYMENT_TONE: Record<string, PillTone> = { unpaid: "danger", partial: "warning", paid: "success" };

export const STATUS_STYLE: Record<string, { label: string; cls: string }> = {
  confirmed:   { label: "Confirmed",   cls: "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)] border-[var(--haip-status-info-border)]" },
  checked_in:  { label: "Checked in",  cls: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)] border-[var(--haip-status-success-border)]" },
  checked_out: { label: "Checked out", cls: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-status-neutral-fg)] border-[var(--haip-status-neutral-border)]" },
  cancelled:   { label: "Cancelled",   cls: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)] border-[var(--haip-status-danger-border)]" },
};

export const PAYMENT_STYLE: Record<string, { label: string; cls: string }> = {
  unpaid:  { label: "Unpaid",       cls: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)] border-[var(--haip-status-danger-border)]" },
  partial: { label: "Part paid",    cls: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)] border-[var(--haip-status-warning-border)]" },
  paid:    { label: "Paid",         cls: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)] border-[var(--haip-status-success-border)]" },
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
  property: { id: string; name: string; type: string; image?: string | null } | null;
  next_payment_due_date: string | null;
  next_payment_amount: number;
  payment_overdue: boolean;
  main_guest: { id: string | null; first_name: string; last_name: string; phone: string | null; email: string | null } | null;
  channel: string | null;
  created_at: string | null;
}

export interface Instalment { id: string; label: string; amount: number; due_date: string; paid: number; status: "paid" | "partial" | "due" | "overdue" }
export interface NextDue { amount: number; due_date: string; overdue: boolean; label: string }
export interface Deposit {
  id: string; amount: number; status: "pending" | "held" | "released" | "forfeited"; deducted: number; refundable: number;
  method: PayMethod | null; collected_on: string | null; resolved_on: string | null; notes: string | null;
}
export interface ServiceRequest {
  id: string; title: string; notes: string | null; status: "open" | "done"; assigned_to: string | null;
  assignee_name: string | null; due_date: string | null; completed_at: string | null;
}

export interface BookingList {
  data: BookingRow[];
  meta: { current_page: number; last_page: number; per_page: number; total: number; from: number; to: number };
}

export interface AddOnLine { id: string; addon_id: string | null; name: string; quantity: number; unit_price: number; line_total: number; notes: string | null }
export interface PaymentEntry { id: string; kind: "payment" | "refund"; amount: number; method: PayMethod; reference: string | null; paid_on: string; notes: string | null; via_gateway: boolean }
export interface PaymentLink {
  id: string; short_url: string; amount: number; status: string; expires_at: string | null; created_at: string | null;
  whatsapp?: { status: "queued" | "duplicate" | "skipped"; reason: string | null };   // only when sent with send_whatsapp
}
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
  concierge_notes: string;
  schedule: Instalment[];
  next_due: NextDue | null;
  deposit: Deposit | null;
  service_requests: ServiceRequest[];
  assignees: { id: string; name: string }[];
  inquiry_id: string | null;
  calendar_sync: { linked: boolean; locked: boolean } | null;   // booking made from / tied to a Google Calendar event
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

export const CHANNEL_STYLE: Record<string, { label: string; cls: string }> = {
  direct:   { label: "Direct",       cls: "bg-primary/10 text-primary border-primary/20" },
  airbnb:   { label: "Airbnb",       cls: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-status-neutral-fg)] border-[var(--haip-status-neutral-border)]" },
  booking:  { label: "Booking.com",  cls: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-status-neutral-fg)] border-[var(--haip-status-neutral-border)]" },
  vrbo:     { label: "Vrbo",         cls: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-status-neutral-fg)] border-[var(--haip-status-neutral-border)]" },
};

export const CHANNEL_OPTIONS = [
  { value: "direct", label: "Direct" }, { value: "airbnb", label: "Airbnb" },
  { value: "booking", label: "Booking.com" }, { value: "vrbo", label: "Vrbo" },
];

export const PRICE_TYPE_LABEL: Record<string, string> = {
  per_stay: "per stay", per_night: "per night", per_person: "per person", per_unit: "each",
};

/** Answers that will not change on retry: signed out, no permission, no such booking. */
export const LOAD_FAILURES = new Set([401, 403, 404]);
export const httpStatus = (e: unknown): number | undefined => (e as { response?: { status?: number } })?.response?.status;

/** Say what actually went wrong when a booking will not open: only a 404 means it is missing. */
export function loadFailure(e: unknown): { title: string; body: string; retry: boolean } {
  const status = httpStatus(e);
  if (status === 404) return { title: "Booking not found", body: "It may have been deleted, or the link belongs to another workspace.", retry: false };
  if (status === 403) return { title: "You don't have access to bookings", body: "Ask an owner or manager to give your role the Bookings permission.", retry: false };
  if (status === 401) return { title: "You've been signed out", body: "Sign in again to open this booking.", retry: false };
  if (status === undefined) return { title: "Couldn't reach the server", body: "Check your connection and try again.", retry: true };
  return { title: "Couldn't load this booking", body: `The server answered with an error (${status}). Try again in a moment.`, retry: true };
}

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
    case "booking.invoice_issued": return `Invoice ${p.number} issued`;
    case "booking.invoice_reissued": return `Invoice ${p.number} issued, replacing ${p.replaces}`;
    case "booking.receipt_issued": return `Receipt ${p.number} issued`;
    case "booking.invoice_not_issued": return `No invoice issued: ${p.reason}`;
    case "booking.message_queued": return "WhatsApp message sent";
    case "booking.message_not_sent": return `WhatsApp message not sent: ${p.reason}`;
    case "booking.schedule_set": return `Payment schedule set (${p.instalments} instalment${p.instalments === 1 ? "" : "s"})`;
    case "booking.deposit_updated": return `Deposit ${inr(p.amount)} marked ${p.to}`;
    case "booking.deposit_removed": return "Deposit removed";
    case "booking.request_added": return `Service request added: ${p.title}`;
    case "booking.request_done": return `Service request done: ${p.title}`;
    case "booking.request_reopened": return `Service request reopened: ${p.title}`;
    case "booking.request_removed": return `Service request removed: ${p.title}`;
    case "booking.guest_changed": return "Booking moved to a different guest";
    case "booking.guest_edited": return "Guest details corrected";
    case "dpdp.delete_requested": return "Guest data erasure requested";
    default: return a.action.replace(/[._]/g, " ");
  }
}
