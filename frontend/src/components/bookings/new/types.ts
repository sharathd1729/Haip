// Hand-written types for the new-booking flow, mirroring backend/app/api/v1/endpoints/booking_compose.py and
// services/booking_compose_*.py. Money arrives as strings ("70000.00"). The server prices everything; the page never adds up money.
import type { CalcPackage, CalcSetup, CalcLine, Unit } from "@/components/quotes/calc/types";

export type Section = "guest" | "trip" | "veh" | "addons" | "price" | "pay" | "confirm";
export type SourceKey = "instagram" | "whatsapp" | "phone_call" | "meta_ad" | "website" | "referral" | "walk_in" | "airbnb" | "other";

export interface ComposeSetup {
  today: string;
  brand: string;
  settings: CalcSetup["settings"];
  gst_slabs: string[];
  discount_options: string[];
  /** nights: how long the package is (0 = same day; null = the package does not say). Check-out follows it. */
  packages: (CalcPackage & { nights?: number | null })[];
  unpriced: number;
  unpublished: number;
  custom: CalcSetup["custom"];
  addons: { name: string; price: string; unit: Unit }[];
  sources: { value: SourceKey; label: string }[];
  vehicles: { id: string; name: string }[];
  payments: { razorpay_connected: boolean; confirmation_template: string | null };
  user: { id: string; name: string; privileged: boolean };
  advance_days: number;
}

export interface LeadView {
  inquiry_id: string; stage_label: string; source: string | null; source_label: string; open: boolean; trip: string;
  /** The lead's live booking: one lead = one trip, so a new booking for this person starts a new lead. */
  booking?: { booking_id: string; ref: string; check_in: string; check_out: string; span: string } | null;
}

export interface GuestCard {
  guest_id: string;
  name: string;
  phone_last4: string | null;
  tag: string;
  info: string;
  open_lead: LeadView | null;
  quotes_count: number;
  wrote: string | null;
  window_open: boolean;
}

export interface QuotePrefill {
  check_in: string | null; check_out: string | null; check_in_time: string; check_out_time: string; guests: number | null;
  total: string; calculator: boolean; mode?: "fixed" | "custom"; package_key?: string | null;
  custom?: { title?: string; rate_per_day?: string | number } | null;
  addons?: { name: string; price: string | number; unit: Unit }[]; discount_percent?: string; gst_percent?: string | null;
  prices_include_gst?: boolean | null;
}

export interface QuoteCard {
  quote_id: string; number: string; total: string; label: string; check_in: string | null; check_out: string | null;
  guests: number | null; addons_count: number; status: string; sent: string; latest: boolean;
  booked: { booking_id: string; ref: string; automatic: boolean } | null; usable: boolean; why_not: string | null; prefill: QuotePrefill;
}

export interface ComposeContext {
  guest: GuestCard | null;
  lead: LeadView | null;
  quotes: QuoteCard[];
  quote_id: string | null;
  trip: { check_in?: string; check_out?: string; guests?: number; package_key?: string };
}

export interface Problem { section: Section; message: string; live: boolean }
/** Why Create was refused (any non-2xx), shown in the side card and the review sheet until something changes. */
export interface CreateError { status: number | null; message: string; problems: Problem[] }
export interface Warning { section: Section; message: string }

export interface VehicleRow {
  property_id: string; name: string; state: "free" | "tight" | "booked"; message: string | null;
  other: { type: string; guest?: string | null; from: string; to: string; from_time?: string | null; to_time?: string | null } | null;
}

export interface Preview {
  problems: Problem[];
  warnings: Warning[];
  price: null | {
    title: string; lines: CalcLine[]; subtotal: string; discount: { percent: string; amount: string } | null; net: string; taxable: string;
    gst_percent: string; gst: string; prices_include_gst: boolean; total: string; suggested_total: string;
    override: { price: string; below_percent: string; reason: string | null } | null;
  };
  vehicles: { vehicles: VehicleRow[]; auto: { property_id: string; name: string; state: string } | null; message: string | null } | null;
  vehicle: { property_id: string; name: string; state: string | null } | null;
  schedule: { total: string; advance: string; advance_due: string | null; balance: string; balance_due: string | null; paid: string; deposit: string };
  nights: number | null;
  message_text: string | null;
  window_open: boolean;
  quote_match: { number: string; quoted: string; same: boolean } | null;
  lead: LeadView | null;
  existing_guest: GuestCard | null;
  staff_notes: string;
}

export interface ReceiptItem { done: boolean; text: string; kind: string }
export interface ComposeReceipt {
  booking_id: string; ref: string; vehicle: string; guest_name: string | null; total: string; inquiry_id: string | null; items: ReceiptItem[];
  new_trip_lead?: boolean;
}

export interface AddonRow { id: string; name: string; price: string; unit: Unit; on: boolean; custom: boolean }

/** What the agent has typed. Turned into the request body by toPayload(). */
export interface BookingForm {
  guest: GuestCard | null;
  newGuest: { phone: string; name: string; source: SourceKey } | null;   // added in this flow (not saved until Create)
  adding: boolean;
  ng: { phone: string; name: string; source: SourceKey | "" };
  guestQ: string;
  inquiryId: string | null;
  fromLead: boolean;
  start: string | null;            // "scratch" | a quote id | null (not chosen yet)
  mode: "fixed" | "custom";
  packageKey: string;
  customTitle: string;
  ratePerDay: string;
  checkIn: string;
  checkInTime: string;
  checkOut: string;
  checkOutTime: string;
  guests: number;
  pickup: string;
  vehicle: string;                 // "auto" | a property id
  interior: "" | "Black" | "White";
  notes: string;
  addons: AddonRow[];
  discount: string;
  slab: string;
  inclusive: boolean;
  overrideOn: boolean;
  overridePrice: string;
  overrideReason: string;
  advance: "25" | "50" | "100" | "other";
  advanceAmount: string;
  advanceDue: string;              // "" = HAIP's default (2 days, never after check-in)
  balanceRule: "pickup" | "7_days";
  deposit: string;
  depositCollect: "pickup" | "balance";
  payNow: "none" | "paid" | "link";
  payMethod: "upi" | "cash" | "bank_transfer" | "razorpay";
  payAmount: string;
  payRef: string;
  confirm: "now" | "later";
  invoice: boolean;
}
