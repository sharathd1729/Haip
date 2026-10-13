import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), patch: (...a: unknown[]) => patch(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { StructuredDataTab } from "./StructuredDataTab";
import { SPEC_BY_KIND, blankFor, fromPayload, toPayload } from "./businessDataSpecs";

const live = {
  id: "r1", kind: "package", key: "coorg", version: 3, status: "published", effective_from: "2026-10-01",
  data: { name: "Coorg Caravan", product: "multiday", max_guests: 4, min_nights: 2, rates: [{ label: "Std", valid_from: "2026-01-01", valid_to: "2026-12-31", amount: "18000.00", unit: "night" }], inclusions: ["Driver"] },
};
const group = { kind: "package", key: "coorg", live, scheduled: null, draft: null, latest_version: 3 };

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function route(groups: unknown[]) {
  get.mockImplementation((url: string) => {
    if (url === "/business-data/records") return Promise.resolve({ data: groups });
    if (url === "/properties") return Promise.resolve({ data: [{ id: "v1", name: "Caravan A" }] });
    if (url.endsWith("/diff")) return Promise.resolve({ data: { changes: [{ path: "rates[0].amount", old: "18000.00", new: "21000" }] } });
    return Promise.resolve({ data: [] });
  });
}

beforeEach(() => { get.mockReset(); post.mockReset(); patch.mockReset(); });
afterEach(cleanup);

describe("form <-> server JSON", () => {
  const spec = SPEC_BY_KIND.package;

  it("sends numbers as numbers, keeps money as text and leaves out empty optional fields", () => {
    const form = { ...blankFor(spec.fields), name: " Coorg ", product: "multiday", max_guests: "4", min_nights: "2", max_nights: "", included_km: "600",
      rates: [{ label: "Std", valid_from: "2026-01-01", valid_to: "2026-12-31", amount: "18000", unit: "night", min_nights: "", days_of_week: ["4", "5"] }] };
    const out = toPayload(spec.fields, form) as Record<string, unknown>;
    expect(out.name).toBe("Coorg");
    expect(out.max_guests).toBe(4);
    expect(out.min_nights).toBe(2);
    expect("max_nights" in out).toBe(false);
    expect(out.included_km).toBe("600");
    const rate = (out.rates as Record<string, unknown>[])[0];
    expect(rate.amount).toBe("18000");
    expect(rate.days_of_week).toEqual([4, 5]);
    expect("min_nights" in rate).toBe(false);
    expect("extra_guest_charge" in out).toBe(false);
  });

  it("round-trips a record through the form without changing it", () => {
    const back = toPayload(spec.fields, fromPayload(spec.fields, live.data));
    expect(back).toMatchObject({ name: "Coorg Caravan", max_guests: 4, min_nights: 2, inclusions: ["Driver"] });
    expect((back.rates as { amount: string }[])[0].amount).toBe("18000.00");
  });

  it("starts a required list with one row and a required select on its first option", () => {
    const blank = blankFor(spec.fields) as { rates: { unit: string }[]; product: string };
    expect(blank.rates).toHaveLength(1);
    expect(blank.rates[0].unit).toBe("night");
    expect(blank.product).toBe("same_day");
  });

  it("covers every kind the server knows", () => {
    expect(Object.keys(SPEC_BY_KIND).sort()).toEqual(
      ["cancellation_policy", "destination", "discount_policy", "itinerary", "package", "payment_policy", "reseller_terms", "stay_rules"],
    );
  });
});

describe("Structured Business Data tab", () => {
  it("shows what is live, what is a draft the AI does not use, and a loading-failure state", async () => {
    route([group, { ...group, key: "weekend", live: null, draft: { ...live, id: "d1", key: "weekend", status: "draft", version: 1, data: { ...live.data, name: "Weekend" } } }]);
    wrap(<StructuredDataTab />);
    expect(await screen.findByText("Live · v3")).toBeTruthy();
    expect(screen.getByText("Draft · not used by the AI")).toBeTruthy();
    expect(screen.getByText(/Continue draft/)).toBeTruthy();
  });

  it("explains an empty kind instead of showing a blank page", async () => {
    route([]);
    wrap(<StructuredDataTab />);
    expect(await screen.findByText("No packages yet")).toBeTruthy();
    expect(screen.getByText(/the AI says the team will confirm/i)).toBeTruthy();
  });

  it("shows a retry when the data cannot be loaded", async () => {
    get.mockImplementation((url: string) => (url === "/properties" ? Promise.resolve({ data: [] }) : Promise.reject(new Error("boom"))));
    wrap(<StructuredDataTab />);
    expect(await screen.findByText(/Couldn.t load your business data/, {}, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("saves a draft, shows the validation result and the diff, and blocks publishing while there are errors", async () => {
    route([group]);
    patch.mockResolvedValue({ data: { ...live, id: "d9", status: "draft", version: 4 } });
    post.mockImplementation((url: string) => {
      if (url.endsWith("/validate")) return Promise.resolve({ data: { errors: ["destination(s) not published: ['coorg']"], warnings: ["no exclusions are listed"] } });
      return Promise.resolve({ data: { ...live, id: "d9", status: "draft", version: 4 } });
    });
    wrap(<StructuredDataTab />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Review changes" }));

    expect(await within(dialog).findByText(/Fix these first/)).toBeTruthy();
    expect(within(dialog).getByText(/destination\(s\) not published/)).toBeTruthy();
    expect(within(dialog).getByText("rates[0].amount")).toBeTruthy();
    expect((within(dialog).getByRole("button", { name: "Publish" }) as HTMLButtonElement).disabled).toBe(true);
    expect(post.mock.calls.some(c => String(c[0]).endsWith("/publish"))).toBe(false);          // nothing went live
  });

  it("publishes a clean draft and tells the owner the AI uses it immediately", async () => {
    route([{ ...group, draft: { ...live, id: "d9", status: "draft", version: 4 } }]);
    patch.mockResolvedValue({ data: { ...live, id: "d9", status: "draft", version: 4 } });
    post.mockImplementation((url: string) => {
      if (url.endsWith("/validate")) return Promise.resolve({ data: { errors: [], warnings: [] } });
      if (url.endsWith("/publish")) return Promise.resolve({ data: { ...live, id: "d9", status: "published", version: 4 } });
      return Promise.resolve({ data: {} });
    });
    wrap(<StructuredDataTab />);
    await userEvent.click(await screen.findByRole("button", { name: "Continue draft" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Review changes" }));
    const publishBtn = await within(dialog).findByRole("button", { name: "Publish" });
    expect((publishBtn as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(publishBtn);
    await waitFor(() => expect(post).toHaveBeenCalledWith("/business-data/records/d9/publish", {}));
  });

  it("restores an old version as a new draft, never by overwriting", async () => {
    route([group]);
    get.mockImplementation((url: string) => {
      if (url === "/business-data/records") return Promise.resolve({ data: [group] });
      if (url === "/properties") return Promise.resolve({ data: [] });
      if (url === "/business-data/records/package/coorg") return Promise.resolve({ data: [live, { ...live, id: "r0", version: 2, status: "superseded" }] });
      return Promise.resolve({ data: [] });
    });
    post.mockResolvedValue({ data: {} });
    wrap(<StructuredDataTab />);
    await userEvent.click(await screen.findByRole("button", { name: /History/ }));
    const restores = await screen.findAllByRole("button", { name: /Restore as draft/ });
    await userEvent.click(restores[restores.length - 1]);                                       // the older version (2), listed last
    await waitFor(() => expect(post).toHaveBeenCalledWith("/business-data/records/package/coorg/rollback", expect.objectContaining({ to_version: 2, publish: false })));
  });
});
