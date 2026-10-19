import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, renderHook, act, waitFor } from "@testing-library/react";
import { PeriodBar, PERIOD_PRESETS, useDashboardPeriod } from "./PeriodBar";

beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear(); });
afterEach(cleanup);

describe("PeriodBar", () => {
  it("offers exactly Today, Yesterday, Last 7 days, This month and Last month, and marks the chosen one", () => {
    render(<PeriodBar value="last_7d" onChange={() => {}} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map(t => t.textContent)).toEqual(["Today", "Yesterday", "Last 7 days", "This month", "Last month"]);
    expect(tabs.find(t => t.getAttribute("aria-selected") === "true")?.textContent).toBe("Last 7 days");
    expect(PERIOD_PRESETS.map(p => p.value)).toEqual(["today", "yesterday", "last_7d", "this_month", "last_month"]);
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

describe("useDashboardPeriod", () => {
  it("starts on Today on every load, even if an old per-device choice is stored, and wipes that old choice", async () => {
    window.localStorage.setItem("haip_dashboard_period", "last_month");
    const { result } = renderHook(() => useDashboardPeriod());
    expect(result.current[0]).toBe("today");
    await waitFor(() => expect(window.localStorage.getItem("haip_dashboard_period")).toBeNull());
    expect(result.current[0]).toBe("today");
  });

  it("remembers a pick only for this tab's session", async () => {
    const first = renderHook(() => useDashboardPeriod());
    act(() => first.result.current[1]("this_month"));
    expect(first.result.current[0]).toBe("this_month");
    expect(window.sessionStorage.getItem("haip_dashboard_period_session")).toBe("this_month");
    expect(window.localStorage.getItem("haip_dashboard_period")).toBeNull();
    const again = renderHook(() => useDashboardPeriod());          // same tab, another page view
    await waitFor(() => expect(again.result.current[0]).toBe("this_month"));
    window.sessionStorage.clear();                                  // a new session (new tab, app relaunch)
    const fresh = renderHook(() => useDashboardPeriod());
    await waitFor(() => expect(fresh.result.current[0]).toBe("today"));
  });

  it("ignores a stored value it does not know", async () => {
    window.sessionStorage.setItem("haip_dashboard_period_session", "custom");
    const { result } = renderHook(() => useDashboardPeriod());
    await waitFor(() => expect(result.current[0]).toBe("today"));
  });
});
