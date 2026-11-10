import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
let role = "manager";
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a) } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { role } } }) }));
vi.mock("@/components/ops/TripCards", () => ({
  GuestFormCard: ({ f, canWrite }: { f: { id: string }; canWrite: boolean }) => <p>guest form {f.id} {canWrite ? "edit" : "view"}</p>,
}));
vi.mock("@/components/ops/AddonsCard", () => ({ AddonsCard: ({ fileId }: { fileId: string }) => <p>add-ons {fileId}</p> }));

import { BookingGuestCards } from "./BookingGuestCards";

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><BookingGuestCards bookingId="b1" /></QueryClientProvider>);
}

beforeEach(() => { cleanup(); get.mockReset(); role = "manager"; });

describe("BookingGuestCards", () => {
  it("shows the guest form and add-ons of the booking's ops file", async () => {
    get.mockImplementation((url: string) =>
      Promise.resolve({ data: url.endsWith("/by-stay/b1") ? { id: "f1" } : { id: "f1", guest_form: {} } }));
    renderIt();
    await screen.findByText("guest form f1 edit");
    expect(screen.getByText("add-ons f1")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/ops/files/by-stay/b1");
  });

  it("shows nothing when the booking has no ops file", async () => {
    get.mockRejectedValue({ response: { status: 404 } });
    const { container } = renderIt();
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });

  it("does not even ask for roles without Ops access", () => {
    role = "marketing";
    const { container } = renderIt();
    expect(get).not.toHaveBeenCalled();
    expect(container.textContent).toBe("");
  });
});
