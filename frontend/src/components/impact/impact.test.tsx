import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImpactTile } from "./ImpactTile";
import { RevenueChart } from "./RevenueChart";
import { CaseStudyView } from "@/components/marketing/CaseStudyView";
import { formatChange, formatPeriod, formatValue, type PublicSnapshot, type Tile } from "./types";

afterEach(cleanup);

const period = { from: "2026-09-19", to: "2026-10-18", days: 30 };
const before = { from: "2026-08-20", to: "2026-09-18", days: 30 };

function tile(over: Partial<Extract<Tile, { restricted: false }>> = {}): Tile {
  return {
    key: "first_reply_median_minutes", label: "Median first reply", unit: "minutes", definition: "Half of guest turns got a reply faster.",
    lower_is_better: true, restricted: false,
    before: { owner: null, measured: { value: null, n: 0, period: before } },
    with: { value: 9, n: 42, period }, change: null, change_against: null, ...over,
  };
}

describe("impact formatting", () => {
  it("never turns a missing value into zero", () => {
    expect(formatValue(null, "minutes")).toBe("—");
    expect(formatValue(null, "%")).toBe("—");
    expect(formatValue(9, "minutes")).toBe("9m");
    expect(formatValue(250, "minutes")).toBe("4h 10m");
    expect(formatValue(57.1, "%")).toBe("57.1%");
    expect(formatValue(125000, "inr")).toBe("₹1,25,000");
  });

  it("shows no change without a baseline and colours by improvement", () => {
    expect(formatChange(null)).toBeNull();
    expect(formatChange({ kind: "pct", value: -96.2, better: true })).toEqual({ text: "−96.2%", tone: "success" });
    expect(formatChange({ kind: "points", value: 30, better: true })).toEqual({ text: "+30 pts", tone: "success" });
    expect(formatChange({ kind: "pct", value: 12, better: false })?.tone).toBe("danger");
  });

  it("names IST calendar days", () => {
    expect(formatPeriod(period)).toBe("19 Sep 2026 – 18 Oct 2026");
  });
});

describe("ImpactTile", () => {
  it("says there is nothing to compare with instead of a -100%", () => {
    render(<ImpactTile tile={tile()} />);
    expect(screen.getByText("Not entered yet")).toBeTruthy();
    expect(screen.getByText(/nothing to compare with yet/)).toBeTruthy();
    expect(screen.queryByText(/100%/)).toBeNull();
  });

  it("labels the owner-entered baseline with its period and shows the change", async () => {
    render(<ImpactTile tile={tile({
      before: { owner: { metric: "first_reply_median_minutes", value: 240, period_label: "Q1 2026", source_note: null, updated_at: null, source: "owner_entered" },
        measured: { value: null, n: 0, period: before } },
      change: { kind: "pct", value: -96.2, better: true }, change_against: "owner_entered",
    })} />);
    expect(screen.getByText(/Owner-entered · Q1 2026/)).toBeTruthy();
    expect(screen.getByText("−96.2%")).toBeTruthy();
    expect(screen.getByText(/19 Sep 2026 – 18 Oct 2026/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /What "Median first reply" counts/ }));
    expect(screen.getByText("Half of guest turns got a reply faster.")).toBeTruthy();
  });

  it("hides a money figure from a viewer without revenue access", () => {
    render(<ImpactTile tile={{ key: "revenue_booked_per_30d", label: "Bookings value per 30 days", unit: "inr", definition: "d", lower_is_better: false, restricted: true }} />);
    expect(screen.getByText("Needs revenue access to show.")).toBeTruthy();
    expect(screen.queryByText(/₹/)).toBeNull();
  });
});

describe("RevenueChart", () => {
  it("has a table view with every month and marks go-live", async () => {
    render(<RevenueChart goLiveMonth="2026-09" months={[
      { month: "2026-08", from: "2026-08-20", to: "2026-08-31", bookings: 1, booked_value: 50000, collected: 0, refunded: 0 },
      { month: "2026-09", from: "2026-09-01", to: "2026-09-30", bookings: 0, booked_value: 0, collected: 20000, refunded: 0 },
    ]} />);
    expect(screen.getByText("Bookings value")).toBeTruthy();      // legend
    await userEvent.click(screen.getByRole("tab", { name: "Table" }));
    expect(screen.getByText("₹50,000")).toBeTruthy();
    expect(screen.getByText("₹20,000")).toBeTruthy();
    expect(screen.getByText("go-live")).toBeTruthy();
  });
});

describe("CaseStudyView", () => {
  it("renders the published snapshot with sources and periods", () => {
    const s: PublicSnapshot = {
      version: 1, brand_name: "Ratha", headline: "Every enquiry answered", summary: null, go_live: "2026-09-19",
      windows: { before, with: period }, includes_revenue: false, measured_through: "2026-10-18",
      tiles: [{ key: "first_reply_median_minutes", label: "Median first reply", unit: "minutes", definition: "d",
        before: { value: 240, source: "owner_entered", period: "Q1 2026" }, with: { value: 9, period: "2026-09-19 to 2026-10-18" },
        change: { kind: "pct", value: -96.2, better: true } }],
      channels: [{ channel: "personal_whatsapp", label: "WhatsApp (team phones)", turns: 12, answered_pct: 91.7, median_minutes: 14, within_15_pct: 50 }],
      after_hours: { turns: 3, within_15_pct: 100, ai_share_pct: 100 },
    };
    render(<CaseStudyView s={s} />);
    expect(screen.getByRole("heading", { name: "Ratha" })).toBeTruthy();
    expect(screen.getByText(/reported by the owner, Q1 2026/)).toBeTruthy();
    expect(screen.getByText("WhatsApp (team phones)")).toBeTruthy();
    expect(screen.getByText(/HAIP live since 19 Sep 2026/)).toBeTruthy();
  });
});
