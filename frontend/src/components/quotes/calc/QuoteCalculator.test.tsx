import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { QuoteCalculator } from "./QuoteCalculator";
import { lead, setup } from "./testFixtures";
import type { PriceResult } from "./types";

function priced(patch: Partial<PriceResult> = {}): PriceResult {
  return {
    ok: true, message: "", title: "Coorg 48-hour Retreat", product: "route",
    lines: [{ label: "Coorg 48-hour Retreat", amount: "70000.00", detail: "package price", kind: "base" }],
    subtotal: "70000.00", discount: null, net: "70000.00", taxable: "59322.00", gst_percent: "18", gst: "10678", prices_include_gst: true,
    total: "70000.00", suggested_total: "70000.00", override: null, advance_percent: "50", advance: "35000", valid_until: "2026-10-22",
    valid_days: 3, check_in: "2026-10-30", check_out: "2026-11-01", days: 2, warnings: [],
    availability: [{ property_id: "v1", property_name: "Ratha 1", status: "available" }, { property_id: "v2", property_name: "Ratha 2", status: "unavailable" }],
    approval: { needed: false, reasons: [], required_for_you: false },
    message_text: "Namaskara Kiran, here is your Ratha plan.\n\nCoorg 48-hour Retreat\n\nTotal ₹70,000 (incl. GST ₹10,678)",
    ...patch,
  };
}

function show(args?: Parameters<typeof QuoteCalculator>[0]["args"], onHeader = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><QuoteCalculator args={args} onHeader={onHeader} /></QueryClientProvider>);
  return onHeader;
}

beforeEach(() => {
  cleanup(); get.mockReset(); post.mockReset();
  get.mockImplementation((url: string) => {
    if (url === "/quote-calculator/setup") return Promise.resolve({ data: setup });
    if (url === "/quote-calculator/context") return Promise.resolve({ data: { lead, add: null, trip: { start_date: "2026-10-30", days: 2, guests: 5, package_key: "coorg-48" }, guest_name: "Kiran Reddy", filled: ["route", "dates", "guests"] } });
    return Promise.resolve({ data: { results: [], add: null } });
  });
});

describe("QuoteCalculator", () => {
  it("prices on the server, shows vacant / booked caravans and the exact message; copy works without a lead", async () => {
    post.mockResolvedValue({ data: priced() });
    show();
    expect((await screen.findByTestId("quote-message")).textContent).toContain("Namaskara Kiran, here is your Ratha plan.");
    expect(screen.getByText("Ratha 1 · Vacant")).toBeTruthy();
    expect(screen.getByText("Ratha 2 · Booked")).toBeTruthy();
    expect(post.mock.calls[0][0]).toBe("/quote-calculator/price");
    expect((screen.getByRole("button", { name: "Send on WhatsApp" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Copy quote" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText("Pick a lead to save this quote. Copy still works without one.")).toBeTruthy();
    expect(screen.queryByText(/packages? not published yet/)).toBeNull();      // only owners/managers see the Publish link
  });

  it("opens prefilled from a chat and sends; the receipt says what got recorded", async () => {
    post.mockImplementation((url: string) => url === "/quote-calculator/price" ? Promise.resolve({ data: priced() }) : Promise.resolve({ data: {
      quote_id: "q1", quote_number: "Q-ABC", status: "issued", how: "sent", lead: { inquiry_id: "i1", guest_id: "g1", guest_name: "Kiran Reddy" },
      lead_created: false, stage: { from: "General Enquiry", to: "Active", moved: true }, follow_up_at: "2026-10-22T18:29:59+00:00",
      total: "70000.00", advance: "35000", valid_until: "2026-10-22", shared_via: "sent", approval: null,
      message: { status: "queued", code: null, message: "Sending", channel: "text" }, message_text: "...", payment_link: "https://rzp.io/i/x" } }));
    const onHeader = show({ conversationId: "c1", from: "inbox", name: "Kiran Reddy" });
    expect(await screen.findByText("Kiran Reddy")).toBeTruthy();
    await waitFor(() => expect(onHeader).toHaveBeenCalledWith({ title: "Quote for Kiran Reddy",
      from: "Opened from Kiran Reddy's WhatsApp chat. Route, dates and guests filled in from the chat." }));
    expect(get).toHaveBeenCalledWith("/quote-calculator/context", { params: expect.objectContaining({ conversation_id: "c1" }) });
    expect((screen.getByLabelText("Guests") as HTMLInputElement).value).toBe("5");
    const send = await screen.findByRole("button", { name: "Send on WhatsApp" });
    await waitFor(() => expect((send as HTMLButtonElement).disabled).toBe(false));
    await userEvent.click(send);
    expect(await screen.findByText("Sent and saved to the lead")).toBeTruthy();
    expect(screen.getByText("Stage: General Enquiry → Active")).toBeTruthy();
    const body = post.mock.calls.find(c => c[0] === "/quote-calculator/quotes")![1];
    expect(body).toMatchObject({ action: "send", inquiry_id: "i1", package_key: "coorg-48", days: 2, guests: 5 });
  });

  it("shows the End date: Start + Days; picking an End sets Days, changing Days or Start moves End", async () => {
    post.mockResolvedValue({ data: priced() });
    show({ conversationId: "c1", from: "inbox", name: "Kiran Reddy" });
    const end = () => screen.getByLabelText("End") as HTMLInputElement;
    await waitFor(() => expect(end().value).toBe("2026-11-01"));                  // prefilled 30 Oct + 2 days
    fireEvent.change(end(), { target: { value: "2026-11-03" } });
    expect((screen.getByLabelText("Days") as HTMLInputElement).value).toBe("4");
    expect(screen.getByTestId("calc-when").textContent).toMatch(/noon to .*3 Nov noon/);
    fireEvent.change(screen.getByLabelText("Days"), { target: { value: "1" } });
    expect(end().value).toBe("2026-10-31");
    fireEvent.change(screen.getByLabelText("Start"), { target: { value: "2026-11-05" } });
    expect(end().value).toBe("2026-11-06");
    await waitFor(() => expect(post.mock.calls.at(-1)![1]).toMatchObject({ start_date: "2026-11-05", days: 1 }));
  });

  it("a price more than the limit below the suggested one becomes Send for owner OK and cannot be copied", async () => {
    post.mockResolvedValue({ data: priced({ override: { price: "60000", below_percent: "14.3", reason: null, show_usual: true }, total: "60000.00",
      approval: { needed: true, reasons: ["14.3% below the suggested price"], required_for_you: true } }) });
    show({ inquiryId: "i1", from: "lead" });
    await userEvent.click(await screen.findByLabelText("Change the price"));
    fireEvent.change(screen.getByLabelText("Your price, incl. GST (₹)"), { target: { value: "60000" } });
    expect(await screen.findByRole("button", { name: "Send for owner OK" })).toBeTruthy();
    await waitFor(() => expect((screen.getByRole("button", { name: "Copy quote" }) as HTMLButtonElement).disabled).toBe(true));
    expect(screen.getByText("14.3% below suggested")).toBeTruthy();
  });

  it("says when the rate card cannot load, and offers a retry", async () => {
    get.mockRejectedValue({ response: { status: 500 } });
    show();
    expect(await screen.findByText("Couldn't load the rate card.", {}, { timeout: 4000 })).toBeTruthy();
  });
});
