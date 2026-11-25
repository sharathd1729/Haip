import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const patch = vi.fn();
vi.mock("@/lib/api", () => ({ default: { patch: (...a: unknown[]) => patch(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { EditableName } from "./EditableName";

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => { patch.mockReset(); patch.mockResolvedValue({ data: {} }); });
afterEach(cleanup);

describe("EditableName", () => {
  it("renames the guest through the lead, trimmed", async () => {
    wrap(<EditableName inquiryId="i1" name="Unknown Guest" canEdit />);
    await userEvent.click(screen.getByRole("button", { name: "Edit the guest's name" }));
    const box = screen.getByLabelText("Guest name");
    await userEvent.clear(box);
    await userEvent.type(box, "  Harshitha N {Enter}");
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/inquiries/i1", { guest_name: "Harshitha N" }));
  });

  it("never saves an empty name, and Escape changes nothing", async () => {
    wrap(<EditableName inquiryId="i1" name="Sindhu" canEdit />);
    await userEvent.click(screen.getByRole("button", { name: "Edit the guest's name" }));
    await userEvent.clear(screen.getByLabelText("Guest name"));
    await userEvent.keyboard("{Enter}");
    await userEvent.click(screen.getByRole("button", { name: "Edit the guest's name" }));
    await userEvent.type(screen.getByLabelText("Guest name"), " Rao{Escape}");
    expect(patch).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Sindhu" })).toBeTruthy();
  });

  it("shows no pencil to someone who cannot edit the lead", () => {
    wrap(<EditableName inquiryId="i1" name="Sindhu" canEdit={false} />);
    expect(screen.queryByRole("button", { name: "Edit the guest's name" })).toBeNull();
  });
});
