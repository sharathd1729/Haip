// Hand-written types for the rate calculator, mirroring backend/app/api/v1/endpoints/quote_calculator.py and
// services/rate_calculator.py. Money arrives as strings ("70000.00"). The server prices everything; the page never adds up money.

export type Unit = "one_time" | "per_day" | "per_guest" | "per_guest_day";
export type LeadSource = "whatsapp" | "phone_call" | "instagram" | "referral" | "walk_in" | "website" | "other";

export interface CalcPackage {
  key: string; record_key: string; version: number; name: string; summary: string; product: string;
  basis: "flat" | "per_day"; price: string; max_guests: number; min_days: number | null; kits_included: boolean;
  free_guests: number | null;
}

export interface CalcSetup {
  today: string;
  brand: string;
  settings: {
    gst_percent: string; prices_include_gst: boolean; advance_percent: string; valid_days: number;
    approval_threshold_percent: string; max_discount_percent: string; greeting: string;
  };
  gst_slabs: string[];
  discount_options: string[];
  packages: CalcPackage[];
  unpriced: number;
  unpublished: number;
  custom: {
    rate_per_day: string | null; included_km_per_day: string; free_guests: number; extra_guest_per_day: string;
    extra_guest_unit: "day" | "trip"; km_rates: string[]; at_actuals: string[]; source: "package" | "settings" | "default";
  };
  addons: { name: string; price: string; unit: Unit }[];
  send_setup: { razorpay_connected: boolean; template_status: string | null };
  permissions: { user_id: string; privileged: boolean; is_owner: boolean; can_manage: boolean };
  lead_sources: LeadSource[];
}

export interface AddonRow { id: string; name: string; price: string; unit: Unit; on: boolean; custom: boolean }

/** What the agent has typed. Turned into the request body by toPayload(). */
export interface CalcForm {
  mode: "fixed" | "custom";
  packageKey: string;
  customTitle: string;
  ratePerDay: string;
  plannedKm: string;
  kmRate: string;
  start: string;
  days: number;
  guests: number;
  addons: AddonRow[];
  discount: string;
  slab: string;            // "0" | "5" | "18" | "40" | "other"
  customRate: string;
  inclusive: boolean;
  overrideOn: boolean;
  overridePrice: string;
  overrideReason: string;
  showUsual: boolean;
  paymentLink: boolean;
}

export interface Vehicle { property_id: string; property_name: string; status: "available" | "unavailable" | "over_capacity" }
export interface CalcLine { label: string; amount: string; detail: string; kind: string }

export interface PriceResult {
  ok: boolean;
  message: string;
  title?: string;
  product?: string;
  lines?: CalcLine[];
  subtotal?: string;
  discount?: { percent: string; amount: string } | null;
  net?: string;
  taxable?: string;
  gst_percent?: string;
  gst?: string;
  prices_include_gst?: boolean;
  total?: string;
  suggested_total?: string;
  override?: { price: string; below_percent: string; reason: string | null; show_usual: boolean } | null;
  advance_percent?: string;
  advance?: string;
  valid_until?: string;
  valid_days?: number;
  check_in?: string;
  check_out?: string;
  days?: number;
  warnings: string[];
  availability: Vehicle[];
  approval?: { needed: boolean; reasons: string[]; required_for_you: boolean };
  message_text?: string | null;
}

/** A row of the "Send to" picker. kind "new_trip": the person's leads are all closed; saving makes a new lead for them. */
export interface LeadRow {
  kind: "lead" | "new_trip";
  inquiry_id: string;
  guest_id: string;
  guest_name: string;
  phone_last4: string | null;
  source: string | null;
  source_label: string;
  stage_label: string;
  stage_category: string | null;
  open: boolean;
  check_in: string | null;
  check_out: string | null;
  adults: number | null;
  children: number | null;
  route: string | null;
  /** Set when the lead was just added from the picker ("Add as new lead"). */
  created?: boolean;
  matched_existing?: boolean;
}

export interface AddOffer { phone: string | null; known_name: string | null; known: boolean }
export interface LeadSearch { results: LeadRow[]; add: AddOffer | null }

export interface Trip { start_date?: string; days?: number; guests?: number; route?: string; package_key?: string }
export interface CalcContext { lead: LeadRow | null; add: AddOffer | null; trip: Trip; guest_name: string | null; filled: string[] }

export interface Receipt {
  quote_id: string;
  quote_number: string;
  status: string;
  how: "sent" | "copied" | "saved" | "pending_approval";
  lead: { inquiry_id: string; guest_id: string; guest_name: string | null };
  lead_created: boolean;
  stage: { from: string; to: string; moved: boolean };
  follow_up_at: string | null;
  total: string;
  advance: string;
  valid_until: string;
  shared_via: string | null;
  approval: { needed: boolean; reasons: string[] } | null;
  message: { status: string; code: string | null; message: string; channel?: string } | null;
  message_text: string;
  payment_link: string | null;
}

export interface SavedQuoteView {
  quote_id: string;
  quote_number: string;
  status: string;
  kind: string | null;
  snapshot: Record<string, unknown> & { total?: string; package_name?: string; valid_until?: string; advance?: string;
    override?: { price: string; below_percent: string; reason: string | null } | null; approval?: { needed: boolean; reasons: string[] } };
  lead: LeadRow | null;
  message_text: string;
  shared_via: string | null;
  shared_at: string | null;
  created_by_name: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  can_approve: boolean;
  can_share: boolean;
  blocked_reason: string | null;
}

/** Where the calculator was opened from (the "Send quote" buttons). */
export type QuoteFrom = "inbox" | "call" | "calls" | "lead" | "leads" | "my_day" | "home" | "operations" | "quotes";
export interface QuoteOpenArgs {
  inquiryId?: string | null;
  guestId?: string | null;
  conversationId?: string | null;
  callId?: string | null;
  phone?: string | null;
  from?: QuoteFrom;
  /** The person's name as the opener knows it, for the title before the context loads. */
  name?: string | null;
}
