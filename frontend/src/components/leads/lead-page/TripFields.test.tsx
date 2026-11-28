import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const patch = vi.fn();
vi.mock("@/lib/api", () => ({ default: { patch: (...a: unknown[]) => patch(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { TripFields } from "./TripFields";
import type { LeadDetail } from "./types";

// What the Inbox guest panel has: the lead detail with its own `trip`, and no feed.
const lead = { inquiry_id: "i1", guest_id: "g1", display_name: "Ravi", inquiry_stage: "new", check_in: "2026-12-14", check_out: "2026-12-16",
  adults: 2, trip: { route: "Misty Hills Loop", pickup: null, special_requests: "jain food" } } as unknown as LeadDetail;

function wrap(ui: React.ReactNode) {
  const client = new QueryClient();
  const spy = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return spy;
}

beforeEach(() => { patch.mockReset(); patch.mockResolvedValue({ data: {} }); });
afterEach(cleanup);

describe("TripFields without a feed (the Inbox guest panel)", () => {
  it("shows the requests from the lead detail itself", () => {
    // (the route and pickup rows come from the same `trip`, but only a caravan workspace has them)
    wrap(<TripFields lead={lead} canEdit />);
    expect(screen.getByRole("button", { name: "Special requests: jain food, edit" })).toBeTruthy();
  });

  it("saves a corrected value through the lead and refreshes the panel's copy", async () => {
    const invalidated = wrap(<TripFields lead={lead} canEdit />);
    await userEvent.click(screen.getByRole("button", { name: "Adults: 2, edit" }));
    const box = screen.getByRole("spinbutton", { name: "Adults" });
    await userEvent.clear(box);
    await userEvent.type(box, "3{Enter}");
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/inquiries/i1", { adults: 3 }));
    await waitFor(() => expect(invalidated).toHaveBeenCalledWith({ queryKey: ["lead-detail", "i1"] }));
  });

  it("is read-only for a role that cannot edit leads", () => {
    wrap(<TripFields lead={lead} canEdit={false} />);
    expect(screen.queryByRole("button", { name: /edit$/ })).toBeNull();
    expect(screen.getByText("jain food")).toBeTruthy();
  });
});
