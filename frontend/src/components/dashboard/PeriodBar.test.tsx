import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, renderHook, act, waitFor } from "@testing-library/react";
import { PeriodBar, PERIOD_PRESETS, usePersistedPeriod } from "./PeriodBar";

beforeEach(() => window.localStorage.clear());
afterEach(cleanup);

describe("PeriodBar", () => {
  it("offers exactly Today, Last 7 days, This month and Last month, and marks the chosen one", () => {
    render(<PeriodBar value="last_7d" onChange={() => {}} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map(t => t.textContent)).toEqual(["Today", "Last 7 days", "This month", "Last month"]);
    expect(tabs.find(t => t.getAttribute("aria-selected") === "true")?.textContent).toBe("Last 7 days");
    expect(PERIOD_PRESETS.map(p => p.value)).toEqual(["today", "last_7d", "this_month", "last_month"]);
  });

  it("stays pinned while the page scrolls and reports the choice", () => {
    let picked = "";
    const { container } = render(<PeriodBar value="today" onChange={v => { picked = v; }} />);
    expect(container.firstElementChild?.className).toContain("sticky");
    fireEvent.click(screen.getByRole("tab", { name: "Last month" }));
    expect(picked).toBe("last_month");
  });

  it("adds a Custom choice only when asked for", () => {
    const { rerender } = render(<PeriodBar value="today" onChange={() => {}} />);
    expect(screen.queryByRole("tab", { name: "Custom" })).toBeNull();
    rerender(<PeriodBar custom value="today" onChange={() => {}} />);
    expect(screen.getByRole("tab", { name: "Custom" })).toBeTruthy();
  });
});

describe("usePersistedPeriod", () => {
  it("starts on the default, then adopts and remembers the choice on this device", async () => {
    window.localStorage.setItem("haip_dashboard_period", "last_month");
    const { result } = renderHook(() => usePersistedPeriod("this_month"));
    await waitFor(() => expect(result.current[0]).toBe("last_month"));
    act(() => result.current[1]("today"));
    expect(result.current[0]).toBe("today");
    expect(window.localStorage.getItem("haip_dashboard_period")).toBe("today");
  });

  it("ignores a stored value it does not know", async () => {
    window.localStorage.setItem("haip_dashboard_period", "custom");
    const { result } = renderHook(() => usePersistedPeriod("this_month"));
    await waitFor(() => expect(result.current[0]).toBe("this_month"));
  });
});
