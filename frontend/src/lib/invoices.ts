// Types and helpers for invoices, booking messages and invoice settings.
// Shapes mirror backend/app/api/v1/endpoints/invoices.py and services/invoice_service.py (invoice_out).
import type { PillTone } from "@/lib/bookings";

export type InvoiceKind = "invoice" | "receipt" | "credit_note";
export type InvoiceStatus = "issued" | "superseded" | "void";

export interface InvoiceDoc {
  id: string; kind: InvoiceKind; number: string; status: InvoiceStatus; financial_year: string; issued_at: string | null;
  total: number; taxable_value: number; cgst: number; sgst: number; igst: number; gst_rate: number;
  amount_received: number; balance_due: number; place_of_supply: string | null; booking_ref: string | null;
  supersedes_id: string | null; invoice_id: string | null; payment_id: string | null; pdf_ready: boolean; notes: string | null;
}
export interface InvoiceList { invoices: InvoiceDoc[]; can_reissue: boolean }

export type TemplateStatus = "approved" | "pending" | "draft" | "rejected" | "submission_failed" | null;
export interface BookingMessage {
  id: string; template: string | null; label: string | null; event: string | null; status: string | null;
  error: string | null; conversation_id: string; at: string | null; has_document: boolean;
}
export interface BookingMessages { messages: BookingMessage[]; templates: Record<string, TemplateStatus> }

export interface InvoiceProfile {
  legal_name: string | null; gstin: string | null; address: string | null; state_code: string | null; sac_code: string | null;
  gst_rate: number; invoice_prefix: string; receipt_prefix: string; logo_key: string | null; use_branding_logo: boolean;
}
export interface InvoiceSettings {
  profile: InvoiceProfile; payments: { auto_balance_reminder: boolean }; logo_url: string | null;
  logo_source: "uploaded" | "branding" | null; missing: string[]; states: Record<string, string>;
}
export interface PackTemplate {
  name: string; label: string; when: string; header: string; body: string; buttons: string[];
  template_id: string | null; status: TemplateStatus; rejection_reason: string | null;
}

export const BALANCE_TEMPLATE = "ratha_balance_due_v1";

export function docTitle(d: Pick<InvoiceDoc, "kind" | "number">): string {
  const what = d.kind === "receipt" ? "Payment receipt" : d.kind === "credit_note" ? "Credit note" : "Tax invoice";
  return `${d.number} · ${what}`;
}

const DELIVERY: Record<string, { label: string; tone: PillTone }> = {
  queued: { label: "Sending", tone: "info" }, pending: { label: "Sending", tone: "info" },
  sent: { label: "Sent", tone: "info" }, delivered: { label: "Delivered", tone: "success" },
  read: { label: "Read", tone: "success" }, failed: { label: "Not delivered", tone: "danger" },
};
export function deliveryPill(status: string | null | undefined): { label: string; tone: PillTone } {
  return DELIVERY[status ?? ""] ?? { label: "Sending", tone: "neutral" };
}

const TEMPLATE: Record<string, { label: string; tone: PillTone }> = {
  approved: { label: "Approved by Meta", tone: "success" }, pending: { label: "In review at Meta", tone: "warning" },
  draft: { label: "Draft", tone: "neutral" }, rejected: { label: "Rejected", tone: "danger" },
  submission_failed: { label: "Could not submit", tone: "danger" },
};
export function templatePill(status: TemplateStatus | undefined): { label: string; tone: PillTone } {
  return status ? TEMPLATE[status] ?? { label: status, tone: "neutral" } : { label: "Not created", tone: "neutral" };
}

const GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";

/** Same rule as the server (schemas/invoice.py gstin_problem): format, state code and the check character. */
export function gstinProblem(value: string, states: Record<string, string>): string | null {
  const v = value.trim().toUpperCase();
  if (!v) return null;
  if (v.length !== 15) return "A GSTIN has exactly 15 characters.";
  if (!/^(\d{2})([A-Z]{5}\d{4}[A-Z])([1-9A-Z])Z([0-9A-Z])$/.test(v)) return "That is not the GSTIN format.";
  if (!states[v.slice(0, 2)]) return `${v.slice(0, 2)} is not a GST state code.`;
  let total = 0;
  for (let i = 0; i < 14; i++) {
    const p = GSTIN_CHARS.indexOf(v[i]) * (i % 2 ? 2 : 1);
    total += Math.floor(p / 36) + (p % 36);
  }
  if (GSTIN_CHARS[(36 - (total % 36)) % 36] !== v[14]) return "The last character does not match the rest. Check for a typing mistake.";
  return null;
}
