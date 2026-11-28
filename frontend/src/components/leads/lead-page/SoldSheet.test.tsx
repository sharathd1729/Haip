import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
const role = vi.hoisted(() => ({ value: "reservations" }));
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), patch: vi.fn() } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { role: role.value } } }) }));

import { SoldSheet } from "./SoldSheet";

const sold = { id: "s-sold", key: "sold", label: "Sold", order: 8, category: "valid", is_closed_lost: false, is_closed_won: true, is_default_entry: false };
const outcome = { reason: null, note: null, source: null, catalogue: { lost: [], won: [{ key: "package_fit", label: "The package fit" }] }, proposal: null };

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  role.value = "reservations";
  get.mockReset(); post.mockReset();
  get.mockResolvedValue({ data: outcome }); post.mockResolvedValue({ data: outcome });
});
afterEach(cleanup);

describe("SoldSheet", () => {
  it("sends a lead with no booking to the booking form, filled in for that lead", () => {
    wrap(<SoldSheet open onClose={vi.fn()} inquiryId="i 1" name="Ravi" stage={sold} hasBooking={false} />);
    expect(screen.getByText("Ravi moves to Sold when the booking is saved.")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Add the booking/ }).getAttribute("href")).toBe("/dashboard/bookings/new?inquiry=i%201");
    expect(post).not.toHaveBeenCalled();          // nothing is asked of the server until the person decides
  });

  it("goes on to why they booked when the booking already exists", async () => {
    wrap(<SoldSheet open onClose={vi.fn()} inquiryId="i1" name="Ravi" stage={sold} />);
    await userEvent.click(screen.getByRole("button", { name: "The booking already exists" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/leads/i1/outcome/propose", { kind: "won" }));
    expect(screen.queryByRole("link", { name: /Add the booking/ })).toBeNull();
  });

  it("skips the question for a lead that has its booking, and for a role that cannot add bookings", async () => {
    wrap(<SoldSheet open onClose={vi.fn()} inquiryId="i1" name="Ravi" stage={sold} hasBooking />);
    await waitFor(() => expect(post).toHaveBeenCalledWith("/leads/i1/outcome/propose", { kind: "won" }));
    cleanup(); post.mockClear();
    role.value = "concierge";
    wrap(<SoldSheet open onClose={vi.fn()} inquiryId="i2" name="Ravi" stage={sold} hasBooking={false} />);
    await waitFor(() => expect(post).toHaveBeenCalledWith("/leads/i2/outcome/propose", { kind: "won" }));
    expect(screen.queryByRole("link", { name: /Add the booking/ })).toBeNull();
  });
});
