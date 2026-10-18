import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api", () => ({ default: { get: vi.fn(() => Promise.resolve({ data: [] })) } }));

import { QuoteCard } from "./QuoteCard";
import type { Catalog, OptionForm, PricedOption, Preview } from "@/app/dashboard/quotes/types";

afterEach(cleanup);

const catalog: Catalog = {
  today: "2026-10-18", packages: [], destinations: [], kits: [], reseller_terms: null, advance_percent: "50.00", vehicles: [],
  permissions: { user_id: "u1", is_owner: false, can_quote: true, can_draft: true, can_publish: false },
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

function show(pv: Preview, onFix = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>
    <QuoteCard catalog={catalog} form={form} preview={pv} loading={false} failed={false} onFix={onFix} fallbackKey="" onFallback={vi.fn()}
      lead={null} onLead={vi.fn()} nextAt="" onNextAt={vi.fn()} onSave={vi.fn()} saving={false} saved={null} />
  </QueryClientProvider>);
  return onFix;
}

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

  it("keeps saving off until a lead and a next step are chosen, and sending off until payments arrive", () => {
    show(preview({}));
    expect((screen.getByRole("button", { name: "Save to lead" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: /Send quote \+ payment link/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Pick the lead to save this quote to/)).toBeTruthy();
  });
});
