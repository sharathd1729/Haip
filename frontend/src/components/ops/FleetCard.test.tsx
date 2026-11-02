import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FleetCard } from "./FleetCard";
import type { FleetCardData } from "@/lib/ops";

const card: FleetCardData = {
  property_id: "p1", name: "Ratha 1", km: 88792, tone: "red", problems: ["Defect: AC compressor dead", "Restock Towels (5 of 8)"],
  papers: [{ id: "pp1", kind: "insurance", name: "Insurance", number: "POL-1", expires_on: "2026-11-01", level: "red", words: "Expires in 4 days", has_file: true }],
  missing_papers: ["Permit"],
  defects: [{ id: "d1", title: "AC compressor dead", detail: null, severity: "critical", source: "photo", file_id: "f1", reported_at: null }],
  services: [{ id: "s1", name: "Engine oil", due_on: null, due_km: 89500, status: "open", level: "amber", words: "Due in 708 km" }],
  inventory: [{ id: "i1", name: "Towels", par: 8, count: 5, low: true, counted_at: null }],
};

afterEach(cleanup);

describe("FleetCard", () => {
  it("shows the problems first and what blocks the vehicle in plain words", () => {
    render(<FleetCard v={card} canWrite canManage busy={false} onAction={vi.fn()} />);
    expect(screen.getByText("Needs you now")).toBeTruthy();
    expect(screen.getAllByText(/AC compressor dead/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Off sale, cannot leave · from a helper's photo/)).toBeTruthy();
    expect(screen.getByText("Not entered yet: Permit.")).toBeTruthy();
    expect(screen.getByText("5 of 8, restock")).toBeTruthy();
  });

  it("only a manager can mark a defect fixed; counts step by one", async () => {
    const onAction = vi.fn();
    const { rerender } = render(<FleetCard v={card} canWrite canManage={false} busy={false} onAction={onAction} />);
    expect(screen.queryByRole("button", { name: "Fixed" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "One more Towels" }));
    expect(onAction).toHaveBeenLastCalledWith({ kind: "count", id: "i1", count: 6 });
    rerender(<FleetCard v={card} canWrite canManage busy={false} onAction={onAction} />);
    await userEvent.click(screen.getByRole("button", { name: "Fixed" }));
    expect(onAction).toHaveBeenLastCalledWith({ kind: "close_defect", id: "d1", title: "AC compressor dead" });
  });
});
