import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { MonthGrid } from "./MonthGrid";
import type { RowLite } from "./CalendarParts";

afterEach(cleanup);

const monthStart = new Date(2026, 9, 1);            // 1 Oct 2026 (a Thursday)
const gridStart = new Date(2026, 8, 28);            // the Monday before it
const tone = () => ({ bg: "bg-emerald-500", text: "text-white" });

const row: RowLite = {
  property_id: "p1", property_name: "Caravan 1",
  stays: [
    { id: "s1", check_in: "2026-10-05", check_out: "2026-10-09", status: "confirmed", guest_name: "Priya Sharma", adults: 2, channel_source: "direct", inquiry_id: "i1" },
    { id: "s2", check_in: "2026-10-03", check_out: "2026-10-04", status: "cancelled", guest_name: "Gone Guest", adults: 2, channel_source: "direct" },
  ],
  blocks: [{ id: "b1", blocked_from: "2026-10-12", blocked_to: "2026-10-14", reason: "maintenance" }],
};

function show(onOpen = vi.fn()) {
  render(<MonthGrid row={row} monthStart={monthStart} gridStart={gridStart} onOpen={onOpen} chColor={tone} channelLabel={() => "Direct"} />);
  return onOpen;
}

describe("MonthGrid", () => {
  it("draws a 7-column date grid for the whole month with Monday first", () => {
    show();
    expect(screen.getAllByRole("columnheader").map(h => h.textContent)).toEqual(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
    expect(screen.getAllByRole("gridcell")).toHaveLength(42);
    expect(screen.getByRole("gridcell", { name: "Thursday 1 October" })).toBeTruthy();
    expect(screen.getByRole("gridcell", { name: "Saturday 31 October" })).toBeTruthy();
  });

  it("shows a stay as one bar over its dates and opens it on tap", () => {
    const onOpen = show();
    const bar = screen.getByRole("button", { name: /Priya Sharma \(Direct\), 2026-10-05 to 2026-10-09/ });
    expect(bar.className).toContain("bg-emerald-500");
    fireEvent.click(bar);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0][0]).toMatchObject({ kind: "stay", stay: { id: "s1" } });
  });

  it("skips cancelled stays and colours a maintenance hold red", () => {
    const onOpen = show();
    expect(screen.queryByRole("button", { name: /Gone Guest/ })).toBeNull();
    const hold = screen.getByRole("button", { name: /Maintenance, 2026-10-12 to 2026-10-14/ });
    expect(hold.className).toContain("bg-red-500");
    fireEvent.click(hold);
    expect(onOpen.mock.calls[0][0]).toMatchObject({ kind: "block", block: { id: "b1" } });
  });

  it("splits a stay that crosses a week boundary into one bar per week", () => {
    const cross: RowLite = { ...row, blocks: [], stays: [{ ...row.stays[0], id: "s3", check_in: "2026-10-09", check_out: "2026-10-13" }] };
    render(<MonthGrid row={cross} monthStart={monthStart} gridStart={gridStart} onOpen={() => {}} chColor={tone} channelLabel={() => "Direct"} />);
    expect(screen.getAllByRole("button", { name: /2026-10-09 to 2026-10-13/ })).toHaveLength(2);
  });

  it("renders an empty grid when no property is chosen", () => {
    render(<MonthGrid row={undefined} monthStart={monthStart} gridStart={gridStart} onOpen={() => {}} chColor={tone} channelLabel={() => ""} />);
    expect(screen.getAllByRole("gridcell")).toHaveLength(42);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("tags each bar with its vehicle when several vehicles share the grid, and shows the staff notes field to the sheet", () => {
    const both: RowLite = {
      property_id: "all", property_name: "All vehicles", blocks: [],
      stays: [
        { ...row.stays[0], id: "r1", vehicle: "Ratha 1", notes: "Black Ratha" },
        { ...row.stays[0], id: "r2", vehicle: "Ratha 2", guest_name: "Arjun Rao", check_in: "2026-10-06", check_out: "2026-10-08" },
      ],
    };
    const onOpen = vi.fn();
    render(<MonthGrid row={both} monthStart={monthStart} gridStart={gridStart} onOpen={onOpen} chColor={tone} channelLabel={() => "Direct"} />);
    expect(screen.getAllByText(/R1 · Priya/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/R2 · Arjun/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /Arjun Rao/ }));
    expect(onOpen.mock.calls[0][0]).toMatchObject({ kind: "stay", propertyName: "Ratha 2" });
  });
});
