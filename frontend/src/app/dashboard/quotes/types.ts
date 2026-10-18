// Hand-written types for the quote builder, mirroring backend/app/services/quote_builder_service.py and
// package_pricing_service.PackageQuote.to_api(). Money and kilometres arrive as strings ("89880.00"); never do arithmetic on
// prices here -- the server prices every option.

export type Json = Record<string, unknown>;

export interface CatalogRecord {
  record_id: string;
  version: number;
  status: string;
  data: Json;
  change_note: string | null;
  effective_from: string | null;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string | null;
  published_at: string | null;
}

/** One route or package: what is live (published) and the draft waiting for approval, if any. */
export interface CatalogEntry { key: string; live: CatalogRecord | null; draft: CatalogRecord | null }

export interface Kit { name: string; amount: string; unit: string; package_keys: string[] }

export interface Catalog {
  today: string;
  packages: CatalogEntry[];
  destinations: CatalogEntry[];
  kits: Kit[];
  reseller_terms: { version: number; data: { tiers: ResellerTier[] } } | null;
  advance_percent: string | null;
  vehicles: { id: string; name: string }[];
  /** What "Send quote + payment link" needs from the workspace. */
  send_setup: { razorpay_connected: boolean; template_status: string | null };
  permissions: {
    user_id: string; is_owner: boolean; can_quote: boolean; can_draft: boolean; can_publish: boolean; can_manage_templates: boolean;
  };
}

export interface ResellerTier {
  name: string;
  commission_percent: string;
  min_commission_percent?: string | null;
  max_commission_percent?: string | null;
  applies_to_package_keys?: string[];
  min_days?: number | null;
  min_billing?: string | null;
}

export type StayCheck = "not_checked" | "checking" | "confirmed";
export type Channel = "direct" | "reseller";

/** What the agent has chosen for one option (sent to /quotes/preview and /quotes). */
export interface OptionForm {
  package_key: string;
  start_date: string;
  nights: number;
  adults: number;
  children: number;
  level: string | null;
  destination_key: string | null;
  sights: string[];
  km_rate: string | null;
  extra_hours: number;
  kits: string[];
  discount_percent: string | null;
  vehicle_property_id: string | null;
  channel: Channel;
  reseller_tier: string | null;
  commission_percent: string | null;
}

export interface QuoteLine { label: string; amount: string; detail: string }

export interface KmDetail {
  planned_km: string | null;
  route_km: string | null;
  sights: { name: string; km: string }[];
  stops: { name: string; km_from_previous: string | null; overnight: boolean }[];
  included_km: string | null;
  extra_km: string;
  rate_mode: "fixed" | "range" | null;
  suggested_rate: string | null;
  applied_rate: string | null;
  min_rate: string | null;
  max_rate: string | null;
}

export interface Vehicle { property_id: string; property_name: string; status: "available" | "unavailable" | "over_capacity" }

export interface PricedOption {
  status: "ok" | "refused";
  reason: string | null;
  message: string;
  fix: Json | null;
  package_key: string | null;
  package_name: string | null;
  lines: QuoteLine[];
  subtotal: string | null;
  discount: { status: string; reason: string; amount: string | null; requested_percent: string } | null;
  taxable: string | null;
  gst_percent: string | null;
  gst: string | null;
  total: string | null;
  advance_percent: string | null;
  advance: string | null;
  valid_until: string | null;
  warnings: string[];
  inclusions: string[];
  exclusions: string[];
  nights: number | null;
  days: number | null;
  level: string | null;
  duration_hours: number | null;
  destination: { key: string; name: string; version: number; status: string } | null;
  km: KmDetail | null;
  commission: { tier: string; percent: string; amount: string; on_amount: string; net_to_business: string } | null;
  at_actuals: string[];
  availability: Vehicle[];
  uses_drafts: boolean;
  start_date: string;
  end_date: string;
}

export interface Preview {
  primary: PricedOption;
  fallback: PricedOption | null;
  stay_check: StayCheck;
  can_save: boolean;
  save_blockers: string[];
  send_blockers: string[];
}

export interface LeadHit {
  inquiry_id: string;
  guest_name: string;
  phone_last4: string | null;
  source: string | null;
  check_in: string | null;
  adults: number | null;
  children: number | null;
  created_at: string | null;
}

export interface SavedQuote {
  id: string;
  inquiry_id: string;
  amount: string;
  status: string;
  option_rank: number;
  option_group_id: string | null;
  valid_until: string | null;
}

export interface IssueResult { quotes: SavedQuote[]; next_step: { task_id: string; due_date: string | null } | null }

// ─── Sending (POST /quotes/{id}/send) and where a sent quote stands (GET /quotes/{id} -> send) ─────────────

export type LinkStatus = "created" | "paid" | "expired" | "cancelled";
export interface PaymentLinkOut {
  id: string; external_id: string; short_url: string; amount: number; status: LinkStatus;
  expires_at: string | null; booking_id: string | null; created_at: string | null; paid_at: string | null;
}
export interface MessageState { status: string; error: string | null; at: string | null; message_id: string | null; conversation_id: string | null }
export interface Journey {
  quote_number: string;
  group_id: string;
  options: { quote_id: string; option_rank: number; status: string; amount: string; advance: string | null; link: PaymentLinkOut | null }[];
  message: MessageState | null;
  fallback_message: MessageState | null;
  paid: { quote_id: string; option_rank: number; amount: number; at: string | null } | null;
  booking_id: string | null;
  invoice: { number: string; id: string } | null;
  confirmation: { status: string; error: string | null } | null;
  needs_staff: string | null;
  polling: boolean;
}
export interface Problem { code: string; message: string }
export interface SendReadiness { can_send: boolean; blockers: Problem[]; warnings: Problem[] }
export interface QuoteDetail extends SavedQuote {
  quote_number: string;
  payment_link: PaymentLinkOut | null;
  send: Journey;
  send_readiness: SendReadiness;
}
export interface SendResult {
  quote_id: string;
  message: { status: "queued" | "not_sent" | "already_sent"; code: string | null; message: string };
  journey: Journey;
}

/** The route editor's working copy (turned into a destination record by routeToData). */
export interface RouteForm {
  key: string | null;
  name: string;
  description: string;
  usual_nights: string;
  hours_from_base: string;
  km_from_base: string;
  places: { name: string; km: string; overnight: boolean }[];
  sights: { name: string; km: string }[];
}
