import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { OpsFileFull, OpsToday } from "@/lib/ops";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
vi.mock("@/lib/api", () => ({ default: {
  get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), put: (...a: unknown[]) => put(...a),
} }));
const session = vi.hoisted(() => ({ role: "manager" }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { role: session.role } }, status: "authenticated" }) }));
vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard/ops", useParams: () => ({ id: "f1" }) }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import OpsTodayPage from "./page";
import { TripFile } from "@/components/ops/TripFile";

const unit = (name: string, patch = {}) => ({ property_id: name, name, tone: "ok", status: "Free", line: "", problem: null,
  file_id: null, ready_pct: null, ...patch });

function today(patch: Partial<OpsToday> = {}): OpsToday {
  return { date: "2026-10-25", pack: "caravan_rv", unit_word: "vehicle", file_word: "trip", units: [unit("Ratha 1"), unit("Ratha 2")] as OpsToday["units"],
    needs: [], day: [], counts: { leaving: 0, away: 0, back: 0 }, ...patch };
}

function file(patch: Partial<OpsFileFull> = {}): OpsFileFull {
  return {
    id: "f1", pack: "caravan_rv", state: "readiness", step: 2, step_name: "Prepare", next: "Vehicle checklist complete",
    stay: { id: "s1", status: "confirmed", check_in: "2026-10-26", check_out: "2026-10-28", check_in_time: "07:00", check_out_time: null,
            adults: 4, children: 2, guest_name: "Ananya Rao", property_id: "p1", property_name: "Ratha 2", concierge_notes: null },
    stage: { step: 2, step_name: "Prepare", step_names: ["Set up", "Prepare", "Dispatch", "On the road", "Return & bill", "Done"],
             tasks: [], next: "Vehicle checklist complete", next_key: "gate" },
    details: { route: "Bangalore → Coorg", stops: [], allowance_km: "700", extra_km_rate: "60", rate_includes_gst: false, rate_source: "quote_km",
               driver_staff_id: "d1", helper_staff_id: "h1", start_odometer: null, end_odometer: null, start_odometer_photo_km: null },
    crew: { driver: "Suresh", helper: "Raju" },
    gate: { blocking: ["water"], red: [], green: 9, total: 12, ready: false },
    checklist: [
      { key: "ac", label: "AC and cooling", critical: true, source: "staff", photo_required: true, status: "green", note: null, has_photo: true, ai_verdict: { ok: true, problems: [] }, set_at: null },
      { key: "water", label: "Water, leak test", critical: true, source: "staff", photo_required: true, status: "pending", note: null, has_photo: false, ai_verdict: null, set_at: null },
    ],
    account: { package_total: "126732", addons_total: "0", distance_km: null, allowance_km: "700", extra_km: 0, extra_km_rate: "60",
               rate_includes_gst: false, extra_km_charge: "0", total_revenue: "126732", gst_percent: "18", paid: "63366", outstanding: "63366",
               expenses_by_category: {}, total_expenses: "0", net_cash: "126732", deposit: null, extras_waiting: 1 },
    expenses: [], extras: [{ id: "x1", kind: "upsell", label: "Bonfire kit", amount: "2500", status: "proposed" }],
    timeline: [{ at: "2026-10-25T10:00:00Z", text: "Booking confirmed, trip file created", auto: true }], close_blockers: [],
    ...patch,
  };
}

const wrap = (ui: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);

beforeEach(() => { cleanup(); get.mockReset(); post.mockReset(); put.mockReset(); session.role = "manager"; });

describe("Ops today", () => {
  it("a calm day says so, with a unit card per vehicle", async () => {
    get.mockResolvedValue({ data: today() });
    wrap(<OpsTodayPage />);
    expect(await screen.findByText("All on track. Nothing needs you.")).toBeTruthy();
    expect(screen.getByText("Ratha 1")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/ops/files/today");
  });

  it("lists problems with one big button each, and resolves a staff flag", async () => {
    get.mockResolvedValue({ data: today({ needs: [
      { key: "a", level: "red", unit: "Ratha 1", title: "crew reported a problem", detail: "Suresh: flat tyre", file_id: "f1", item_id: "i1", action: "resolve_item" },
      { key: "b", level: "amber", unit: "Ratha 2", title: "3 checks still open", detail: "Leaves in 30 h.", file_id: "f2", item_id: null, action: "open_file" },
    ] }) });
    post.mockResolvedValue({ data: {} });
    wrap(<OpsTodayPage />);
    expect(await screen.findByText("crew reported a problem")).toBeTruthy();
    expect(screen.getByText("Needs you now")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "Open trip" }).map(a => a.getAttribute("href"))).toEqual(["/dashboard/ops/files/f1", "/dashboard/ops/files/f2"]);
    await userEvent.click(screen.getByRole("button", { name: "Mark as sorted" }));
    expect(post).toHaveBeenCalledWith("/ops/items/i1/resolve", {});
  });

  it("hides unit cards for businesses with more than six units", async () => {
    get.mockResolvedValue({ data: today({ units: Array.from({ length: 7 }, (_, i) => unit(`Room ${i + 1}`)) as OpsToday["units"] }) });
    wrap(<OpsTodayPage />);
    await screen.findByText("All on track. Nothing needs you.");
    expect(screen.queryByText("Room 1")).toBeNull();
  });

  it("shows a retry when today cannot load", async () => {
    get.mockRejectedValue(new Error("down"));
    wrap(<OpsTodayPage />);
    expect(await screen.findByText("Couldn't load today")).toBeTruthy();
  });
});

describe("Trip file", () => {
  it("shows the next step, the checklist, money and lets a manager approve an extra", async () => {
    get.mockResolvedValue({ data: file() });
    post.mockResolvedValue({ data: file({ extras: [{ id: "x1", kind: "upsell", label: "Bonfire kit", amount: "2500", status: "approved" }] }) });
    wrap(<TripFile id="f1" />);
    expect(await screen.findByText("Ananya Rao")).toBeTruthy();
    expect(screen.getByRole("button", { name: "See the checklist" })).toBeTruthy();
    expect(screen.getByText("Waiting for the helper's photo")).toBeTruthy();
    expect(screen.getByText("Driver: Suresh")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(post).toHaveBeenCalledWith("/ops/files/f1/extras/x1/approve", {});
    expect(await screen.findByText("On the bill")).toBeTruthy();
  });

  it("lets a manager download the trip account report", async () => {
    get.mockImplementation((url: string) => url.endsWith("report.pdf")
      ? Promise.resolve({ data: new Blob(["%PDF-"]), headers: { "content-type": "application/pdf" } })
      : Promise.resolve({ data: file() }));
    wrap(<TripFile id="f1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Trip account report (PDF)" }));
    expect(get).toHaveBeenCalledWith("/ops/files/f1/report.pdf", expect.objectContaining({ responseType: "blob" }));
  });

  it("keeps Dispatch for managers", async () => {
    session.role = "foh";
    get.mockResolvedValue({ data: file({ state: "dispatch_ready", stage: { ...file().stage, next: "Enter the start odometer and dispatch", next_key: "start" } }) });
    wrap(<TripFile id="f1" />);
    expect(await screen.findByText("A manager does this step.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Dispatch" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Trip account report (PDF)" })).toBeNull();
  });

  it("says not found plainly", async () => {
    get.mockRejectedValue({ response: { status: 404 } });
    wrap(<TripFile id="nope" />);
    expect(await screen.findByText("Trip not found")).toBeTruthy();
  });
});
