// Shared test data for the rate calculator tests (not a test file itself).
import type { CalcSetup, LeadRow } from "./types";

export const setup: CalcSetup = {
  today: "2026-10-19", brand: "Ratha",
  settings: { gst_percent: "18", prices_include_gst: true, advance_percent: "50", valid_days: 3, approval_threshold_percent: "10",
    max_discount_percent: "10", greeting: "Namaskara" },
  gst_slabs: ["0", "5", "18", "40"], discount_options: ["0", "2.5", "5", "7.5", "10"],
  packages: [
    { key: "coorg-48", record_key: "coorg-48", version: 1, name: "Coorg 48-hour Retreat", summary: "", product: "route", basis: "flat",
      price: "70000.00", max_guests: 8, min_days: null, kits_included: false, free_guests: 6 },
    { key: "day-rate", record_key: "day-rate", version: 1, name: "Day rate", summary: "", product: "multiday", basis: "per_day",
      price: "25000.00", max_guests: 8, min_days: null, kits_included: false, free_guests: 4 },
  ],
  unpriced: 1, unpublished: 2,
  custom: { rate_per_day: "25000.00", included_km_per_day: "250", free_guests: 4, extra_guest_per_day: "2500.00", extra_guest_unit: "day",
    km_rates: ["100", "90", "80", "70", "60"], at_actuals: ["Tolls and parking"], source: "package" },
  addons: [{ name: "Culinary kit", price: "5000.00", unit: "one_time" }, { name: "Breakfast", price: "450", unit: "per_guest_day" }],
  send_setup: { razorpay_connected: true, template_status: "approved" },
  permissions: { user_id: "u1", privileged: false, is_owner: false, can_manage: false },
  lead_sources: ["whatsapp", "phone_call", "instagram", "referral", "walk_in", "website", "other"],
};

export const lead: LeadRow = {
  kind: "lead", inquiry_id: "i1", guest_id: "g1", guest_name: "Kiran Reddy", phone_last4: "5678", source: "wa_direct",
  source_label: "WhatsApp", stage_label: "General Enquiry", stage_category: "valid", open: true, check_in: null, check_out: null,
  adults: null, children: null, route: null,
};

