import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
const toast = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast }) }));
vi.mock("next/link", () => ({ default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));

import type React from "react";
import { setup as calcSetup } from "@/components/quotes/calc/testFixtures";
import { NewBookingFlow } from "./NewBookingFlow";
import { defaultForm, sectionMark, toPayload } from "./helpers";
import { Receipt, ReviewSheet, SummaryAside } from "./Summary";
import { VehicleSection } from "./VehicleSection";
import type { ComposeSetup, Preview, Problem } from "./types";

const setup: ComposeSetup = {
  today: "2026-10-19", brand: "Ratha", settings: calcSetup.settings, gst_slabs: calcSetup.gst_slabs, discount_options: calcSetup.discount_options,
  packages: calcSetup.packages, unpriced: 0, unpublished: 0, custom: calcSetup.custom, addons: calcSetup.addons,
  sources: [{ value: "instagram", label: "Instagram" }, { value: "whatsapp", label: "WhatsApp" }],
  vehicles: [{ id: "v1", name: "Ratha 1" }, { id: "v2", name: "Ratha 2" }],
  payments: { razorpay_connected: true, confirmation_template: "approved" }, user: { id: "u1", name: "Jishanth", privileged: false }, advance_days: 2,
};

const guest = { guest_id: "g1", name: "Sharath N.", phone_last4: "2321", tag: "Lead · Active", info: "Kabini, 8 guests.",
  open_lead: { inquiry_id: "i1", stage_label: "Active", source: "meta_ig", source_label: "Instagram", open: true, trip: "Kabini" },
  quotes_count: 0, wrote: "wrote 25 min ago", window_open: true };

function preview(patch: Partial<Preview> = {}): Preview {
  return {
    problems: [], warnings: [], price: { title: "Coorg 48-hour Retreat", lines: [{ label: "Coorg 48-hour Retreat", amount: "70000.00", detail: "", kind: "base" }],
      subtotal: "70000.00", discount: null, net: "70000.00", taxable: "59322.00", gst_percent: "18", gst: "10678", prices_include_gst: true,
      total: "70000.00", suggested_total: "70000.00", override: null },
    vehicles: { vehicles: [{ property_id: "v1", name: "Ratha 1", state: "free", message: null, other: null },
                           { property_id: "v2", name: "Ratha 2", state: "free", message: null, other: null }],
                auto: { property_id: "v1", name: "Ratha 1", state: "free" }, message: null },
    vehicle: { property_id: "v1", name: "Ratha 1", state: "free" },
    schedule: { total: "70000.00", advance: "35000", advance_due: "2026-10-21", balance: "35000", balance_due: "2026-11-01", paid: "0", deposit: "10000" },
    nights: 2, message_text: "Namaskara Sharath, your Ratha booking is confirmed.", window_open: true, quote_match: null, lead: null,
    existing_guest: null, staff_notes: "", ...patch,
  };
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  cleanup(); get.mockReset(); post.mockReset(); toast.mockReset();
  Element.prototype.scrollIntoView = vi.fn();
});

describe("section marks", () => {
  const P: Problem[] = [{ section: "trip", message: "Pick a check-in date.", live: false }];
  it("a section with nothing missing ticks once a guest is picked; a problem shows '!' only after Create", () => {
    expect(sectionMark("guest", P, false, true)).toBe("ok");
    expect(sectionMark("guest", P, false, false)).toBe("todo");
    expect(sectionMark("trip", P, false, true)).toBe("todo");
    expect(sectionMark("trip", P, true, true)).toBe("bad");
  });
});

describe("toPayload", () => {
  it("sends first-free as no vehicle, only switched-on add-ons, and the advance as a percent", () => {
    const f = { ...defaultForm(setup), guest, start: "scratch", packageKey: "coorg-48", checkIn: "2026-11-01", checkOut: "2026-11-03" };
    f.addons[0].on = true;
    const b = toPayload(f);
    expect(b).toMatchObject({ guest_id: "g1", start_scratch: true, property_id: null, package_key: "coorg-48", advance: { percent: "50" },
      addons: [{ name: "Culinary kit", price: "5000", unit: "one_time" }], payment: { kind: "none" }, confirmation: "now" });
  });
});

describe("still needed + side card", () => {
  it("lists what is missing and each line jumps to its section", async () => {
    const onJump = vi.fn();
    const f = defaultForm(setup);
    wrap(<SummaryAside form={f} setup={setup} preview={preview()} showErr={false} onCreate={vi.fn()} creating={false} onJump={onJump}
      problems={[{ section: "guest", message: "Pick the guest, or add a new one with their phone number.", live: false },
                 { section: "pay", message: "The advance due date is in the past.", live: true }]} />);
    const list = screen.getByTestId("still-needed");
    expect(within(list).getAllByRole("button").map(b => b.textContent)).toEqual([
      "Pick the guest, or add a new one with their phone number.", "The advance due date is in the past."]);
    await userEvent.click(within(list).getByText("The advance due date is in the past."));
    expect(onJump).toHaveBeenCalledWith("pay");
  });

  it("says Ready when nothing is missing", () => {
    wrap(<SummaryAside form={defaultForm(setup)} setup={setup} preview={preview()} showErr={false} onCreate={vi.fn()} creating={false} onJump={vi.fn()} problems={[]} />);
    expect(screen.getByText("Ready. Ratha 1 is free and held while you create.")).toBeTruthy();
  });
});

describe("phone review sheet", () => {
  it("shows the summary, the WhatsApp text and Create; problems link back to their section", async () => {
    const onJump = vi.fn();
    const onCreate = vi.fn();
    const f = { ...defaultForm(setup), guest, checkIn: "2026-11-01", checkOut: "2026-11-03", packageKey: "coorg-48" };
    wrap(<ReviewSheet form={f} setup={setup} preview={preview()} onJump={onJump} onClose={vi.fn()} onCreate={onCreate} creating={false}
      problems={[{ section: "veh", message: "Ratha 2 is booked 21–22 Oct (Manisha Rao). Pick Ratha 1 or other dates.", live: true }]} />);
    const dialog = screen.getByRole("dialog", { name: "Review booking" });
    expect(within(dialog).getByTestId("summary").textContent).toContain("Sharath N.");
    expect(within(dialog).getByText("Namaskara Sharath, your Ratha booking is confirmed.")).toBeTruthy();
    expect(within(dialog).getByText("Fix before creating")).toBeTruthy();
    await userEvent.click(within(dialog).getByText(/Ratha 2 is booked/));
    expect(onJump).toHaveBeenCalledWith("veh");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create booking" }));
    expect(onCreate).toHaveBeenCalled();
  });
});

describe("caravan clash", () => {
  it("a booked caravan says why in plain words and offers the free one", async () => {
    const set = vi.fn();
    const p = preview({ vehicles: { vehicles: [
      { property_id: "v1", name: "Ratha 1", state: "free", message: null, other: null },
      { property_id: "v2", name: "Ratha 2", state: "booked", message: "Ratha 2 is out with Manisha Rao until 12:00 pm on Thu 22 Oct. Pick Ratha 1 or other dates.",
        other: { type: "booking", guest: "Manisha Rao", from: "2026-10-21", to: "2026-10-22", from_time: "12:00", to_time: "12:00" } }],
      auto: { property_id: "v1", name: "Ratha 1", state: "free" }, message: null } });
    wrap(<VehicleSection form={{ ...defaultForm(setup), vehicle: "v2" }} set={set} setup={setup} preview={p} />);
    expect(screen.getByTestId("clash-message").textContent).toBe("Ratha 2 is out with Manisha Rao until 12:00 pm on Thu 22 Oct. Pick Ratha 1 or other dates.");
    expect(screen.getByText("Ratha 2 · Booked")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Use Ratha 1" }));
    expect(set).toHaveBeenCalledWith({ vehicle: "v1" });
  });
});

describe("receipt", () => {
  it("lists what HAIP did, open steps marked, with Open booking and New booking", async () => {
    const again = vi.fn();
    wrap(<Receipt onAgain={again} r={{ booking_id: "s1", ref: "#AB12CD34", vehicle: "Ratha 1", guest_name: "Sharath N.", total: "70000.00", inquiry_id: "i1",
      items: [{ done: true, kind: "booking", text: "Booking #AB12CD34 created on Ratha 1." },
              { done: false, kind: "payment", text: "Nothing paid yet. Reminder for Jishanth on Wed 21 Oct to collect the ₹35,000 advance." }] }} />);
    expect(screen.getByRole("heading", { name: "#AB12CD34 created on Ratha 1" })).toBeTruthy();
    const items = screen.getAllByRole("listitem");
    expect(items.map(i => i.getAttribute("data-done"))).toEqual(["true", "false"]);
    expect(screen.getByRole("link", { name: "Open booking" }).getAttribute("href")).toBe("/dashboard/bookings/s1");
    await userEvent.click(screen.getByRole("button", { name: "New booking" }));
    expect(again).toHaveBeenCalled();
  });
});

describe("NewBookingFlow", () => {
  it("opens from a lead, and Create with problems flags the section and scrolls to it instead of saving", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/bookings/compose/setup") return Promise.resolve({ data: setup });
      if (url === "/bookings/compose/context") return Promise.resolve({ data: { guest, lead: guest.open_lead, quotes: [], quote_id: null, trip: { check_in: "2026-11-01", check_out: "2026-11-02", guests: 8 } } });
      return Promise.resolve({ data: { results: [], recent: true } });
    });
    post.mockResolvedValue({ data: preview({ problems: [{ section: "trip", message: "Pick a package, or Custom trip.", live: false }] }) });
    wrap(<NewBookingFlow params={{ inquiry: "i1" }} />);
    expect(await screen.findByText("From lead")).toBeTruthy();
    expect(screen.getByText("This booking is tied to Sharath's open lead (Active). It moves to Sold when you create it.")).toBeTruthy();
    await waitFor(() => expect(post).toHaveBeenCalledWith("/bookings/compose/preview", expect.objectContaining({ guest_id: "g1", check_in: "2026-11-01", guests: 8 })));
    await waitFor(() => expect(screen.getByTestId("mark-sec-guest").textContent).toBe("✓"));
    expect(screen.getByTestId("mark-sec-trip").textContent).toBe("2");
    await userEvent.click(screen.getAllByRole("button", { name: "Create booking" })[0]);
    expect(screen.getByTestId("mark-sec-trip").textContent).toBe("!");
    expect(post).not.toHaveBeenCalledWith("/bookings/compose", expect.anything());
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ variant: "error", title: "Pick a package, or Custom trip." }));
    expect(screen.getByTestId("bottom-bar").textContent).toContain("1 to fix · Pick a package, or Custom trip.");
  });

  it("creates and shows the receipt", async () => {
    get.mockImplementation((url: string) => url === "/bookings/compose/setup" ? Promise.resolve({ data: setup })
      : Promise.resolve({ data: { guest, lead: guest.open_lead, quotes: [], quote_id: null, trip: {} } }));
    post.mockImplementation((url: string) => url === "/bookings/compose/preview" ? Promise.resolve({ data: preview() })
      : Promise.resolve({ data: { booking_id: "s1", ref: "#AB12CD34", vehicle: "Ratha 1", guest_name: "Sharath N.", total: "70000.00", inquiry_id: "i1",
          items: [{ done: true, kind: "booking", text: "Booking #AB12CD34 created on Ratha 1." }] } }));
    wrap(<NewBookingFlow params={{ guest: "g1" }} />);
    await screen.findAllByText("Sharath N.");
    await waitFor(() => expect(post).toHaveBeenCalledWith("/bookings/compose/preview", expect.anything()));
    await waitFor(() => expect(screen.getByTestId("mark-sec-trip").textContent).toBe("✓"));
    await userEvent.click(screen.getAllByRole("button", { name: "Create booking" })[0]);
    expect(await screen.findByTestId("receipt")).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/bookings/compose", expect.objectContaining({ guest_id: "g1" }));
  });
});
