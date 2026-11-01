import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NeedCard } from "./TodayParts";
import type { OpsNeed } from "@/lib/ops";

const need = (patch: Partial<OpsNeed> = {}): OpsNeed => ({
  key: "item:i1", level: "red", unit: "Ratha 1", title: "Off the planned route", detail: "5.4 km from the planned road",
  file_id: "f1", item_id: "i1", action: "resolve_item", item_kind: "gps_off_route", ...patch,
});

describe("NeedCard GPS detour", () => {
  it("asks why, then approves the detour with the reason", async () => {
    const onDetour = vi.fn();
    render(<NeedCard need={need()} onResolve={vi.fn()} onDetour={onDetour} />);
    await userEvent.click(screen.getByRole("button", { name: "Approved detour" }));
    expect(screen.getByRole("button", { name: "Save detour" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Why is the new road fine?"), "Road closed at Hosur");
    await userEvent.click(screen.getByRole("button", { name: "Save detour" }));
    expect(onDetour).toHaveBeenCalledWith("i1", "Road closed at Hosur");
  });

  it("offers no detour for other alerts or without the manager's right", () => {
    const { rerender } = render(<NeedCard need={need({ item_kind: "gps_overspeed" })} onDetour={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Approved detour" })).toBeNull();
    rerender(<NeedCard need={need()} />);
    expect(screen.queryByRole("button", { name: "Approved detour" })).toBeNull();
  });
});
