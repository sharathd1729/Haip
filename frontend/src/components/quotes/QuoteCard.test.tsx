import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api", () => ({ default: { get: vi.fn(() => Promise.resolve({ data: [] })) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { QuoteCard, type SentState } from "./QuoteCard";
import { sendGate } from "@/app/dashboard/quotes/sendHelpers";
import type { Catalog, Journey, OptionForm, PricedOption, Preview } from "@/app/dashboard/quotes/types";

afterEach(cleanup);

const catalog: Catalog = {
  today: "2026-10-18", packages: [], destinations: [], kits: [], reseller_terms: null, advance_percent: "50.00", vehicles: [],
  send_setup: { razorpay_connected: true, template_status: "approved" },
  permissions: { user_id: "u1", is_owner: false, can_quote: true, can_draft: true, can_publish: false, can_manage_templates: false },
};
const form: OptionForm = {
  package_key: "coorg-48", start_date: "2026-10-30", nights: 2, adults: 5, children: 1, level: null, destination_key: "coorg", sights: [],
  km_rate: null, extra_hours: 0, kits: [], discount_percent: null, vehicle_property_id: null, channel: "direct", reseller_tier: null, commission_percent: null,
};
const base: PricedOption = {
  status: "ok", reason: null, message: "", fix: null, package_key: "coorg-48", package_name: "Coorg 48-hour Retreat",
  lines: [{ label: "Coorg 48-hour Retreat - 48 hours", amount: "70000.00", detail: "48 hours, package price" }, { label: "Extra kilometres", amount: "5250.00", detail: "75 km @ 70.00" }],
  subtotal: "75250.00", discount: null, taxable: "75250.00", gst_percent: "12.00", gst: "9030", total: "84280.00", advance_percent: "50.00", advance: "42140",
  valid_until: "2026-10-21", warnings: [], inclusions: [], exclusions: [], nights: 2, days: 2, level: null, duration_hours: 48,
  destination: { key: "coorg", name: "Coorg", version: 1, status: "published" }, km: null, commission: null, at_actuals: ["Tolls and parking"],
  availability: [{ property_id: "v1", property_name: "Ratha 1", status: "available" }], uses_drafts: false, start_date: "2026-10-30", end_date: "2026-11-01",
};
const preview = (p: Partial<PricedOption>, extra: Partial<Preview> = {}): Preview =>
  ({ primary: { ...base, ...p }, fallback: null, stay_check: "not_checked", can_save: true, save_blockers: [], send_blockers: [], ...extra });

function show(pv: Preview, onFix = vi.fn(), sent: SentState | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const gate = sendGate({ canQuote: true, preview: pv, lead: null, nextAt: "", saved: false, setup: catalog.send_setup });
  render(<QueryClientProvider client={qc}>
    <QuoteCard catalog={catalog} form={form} preview={pv} loading={false} failed={false} onFix={onFix} fallbackKey="" onFallback={vi.fn()}
      lead={null} onLead={vi.fn()} nextAt="" onNextAt={vi.fn()} onSave={vi.fn()} saving={false} saved={null}
      gate={gate} onSend={vi.fn()} sending={false} sent={sent} onNewQuote={vi.fn()} />
  </QueryClientProvider>);
  return onFix;
}

const link = (n: number, status: "created" | "paid", amount: number) => ({
  id: `l${n}`, external_id: `plink_${n}`, short_url: `https://rzp.io/i/L${n}`, amount, status, expires_at: "2026-10-21T18:29:59+00:00",
  booking_id: status === "paid" ? "stay-1" : null, created_at: null, paid_at: null,
});
const journey = (over: Partial<Journey> = {}): Journey => ({
  quote_number: "Q-1A2B3C4D", group_id: "g1",
  options: [{ quote_id: "q1", option_rank: 1, status: "issued", amount: "84280.00", advance: "42140", link: link(1, "created", 42140) },
            { quote_id: "q2", option_rank: 2, status: "issued", amount: "41440.00", advance: "20720", link: link(2, "created", 20720) }],
  message: { status: "delivered", error: null, at: null, message_id: "m1", conversation_id: "c1" }, fallback_message: null, paid: null,
  booking_id: null, invoice: null, confirmation: null, needs_staff: null, polling: false, ...over,
});

describe("QuoteCard", () => {
  it("shows every line, the total in lakh format, the advance and tolls outside the total", () => {
    show(preview({}));
    expect(screen.getAllByText("₹84,280").length).toBeGreaterThan(0);
    expect(screen.getByText("Extra kilometres")).toBeTruthy();
    expect(screen.getByText("Balance ₹42,140 before travel begins")).toBeTruthy();
    expect(screen.getByText("Tolls and parking")).toBeTruthy();
    expect(screen.getByText("Billed at actuals, not in the total.")).toBeTruthy();
  });

  it("offers the one-click fix for a refusal and shows no price", async () => {
    const onFix = show(preview({ status: "refused", reason: "below_min_days", message: "Travel only needs at least 3 days; this is 2.", fix: { nights: 3 }, total: null, lines: [] }, { can_save: false }));
    expect(screen.getByText("Can't price yet")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Make it 3 nights" }));
    expect(onFix).toHaveBeenCalledWith({ nights: 3 });
  });

  it("keeps saving and sending off until a lead is chosen, and says why", () => {
    show(preview({}));
    expect((screen.getByRole("button", { name: "Save to lead" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: /Send quote \+ payment link/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Pick the lead to save this quote to/)).toBeTruthy();
    expect(screen.getByText("To send: Pick the lead to send this quote to.")).toBeTruthy();
  });

  it("after sending shows the journey with a copy button per option", () => {
    show(preview({}), vi.fn(), { quoteId: "q1", journey: journey(), notice: null });
    expect(screen.getByText("Quote Q-1A2B3C4D")).toBeTruthy();
    expect(screen.getByText("Payment links created")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /Copy the option \d payment link/ })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Save to lead" })).toBeNull();
  });

  it("links to the booking once the advance is paid", () => {
    const paid = journey({ options: [{ quote_id: "q1", option_rank: 1, status: "accepted", amount: "84280.00", advance: "42140", link: link(1, "paid", 42140) }],
      paid: { quote_id: "q1", option_rank: 1, amount: 42140, at: null }, booking_id: "stay-1", invoice: { number: "INV/2026-27/0001", id: "i1" } });
    show(preview({}), vi.fn(), { quoteId: "q1", journey: paid, notice: null });
    expect(screen.getByRole("link", { name: "Open the booking" }).getAttribute("href")).toBe("/dashboard/bookings/stay-1");
    expect(screen.getByText("INV/2026-27/0001")).toBeTruthy();
  });
});
