import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { RevenueChart } from "./RevenueChart";

const original = window.matchMedia;
afterEach(() => { cleanup(); window.matchMedia = original; });
const months = [
  { month: "2026-09-01", from: "2026-09-01", to: "2026-09-30", bookings: 3, booked_value: 125000, collected: 90000, refunded: 0 },
  { month: "2026-10-01", from: "2026-10-01", to: "2026-10-24", bookings: 1, booked_value: 45000, collected: 0, refunded: 0 },
];

describe("Impact revenue on a phone", () => {
  it("lists each month with both figures instead of the two-series chart and table", async () => {
    window.matchMedia = ((q: string) => ({ matches: true, media: q, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia;
    render(<RevenueChart months={months} goLiveMonth="2026-10-01" />);
    await waitFor(() => expect(screen.getByRole("list", { name: /per month/ })).toBeTruthy());
    expect(screen.getByText("₹1,25,000")).toBeTruthy();
    expect(screen.getByText("go-live")).toBeTruthy();
    expect(screen.queryByRole("tablist")).toBeNull();
  });
});
