import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { KnowledgeHistoryDrawer } from "./KnowledgeHistoryDrawer";

const events = [
  { id: "e2", action: "updated", at: "2026-10-13T10:00:00Z", changes: { content: { from: "Wi-Fi is free.", to: "Wi-Fi is free for guests only." } } },
  { id: "e1", action: "created", at: "2026-10-12T10:00:00Z", changes: null, values: { content: "Wi-Fi is free." } },
];

function wrap(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><KnowledgeHistoryDrawer entryId="k1" onClose={onClose} /></QueryClientProvider>);
  return onClose;
}

beforeEach(() => { get.mockReset(); post.mockReset(); vi.spyOn(window, "confirm").mockReturnValue(true); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Knowledge entry history", () => {
  it("shows each change with what it said before, and only edits can be undone", async () => {
    get.mockResolvedValue({ data: events });
    wrap();
    expect(await screen.findByText("Edited")).toBeTruthy();
    expect(screen.getByText("Wi-Fi is free.")).toBeTruthy();
    expect(screen.getByText("Added")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /Undo this edit/ })).toHaveLength(1);
  });

  it("restores the earlier wording through the rollback endpoint after a confirmation", async () => {
    get.mockResolvedValue({ data: events });
    post.mockResolvedValue({ data: {} });
    const onClose = wrap();
    await userEvent.click(await screen.findByRole("button", { name: /Undo this edit/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/knowledge/k1/rollback", { event_id: "e2" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("does nothing when the person cancels the confirmation", async () => {
    get.mockResolvedValue({ data: events });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    wrap();
    await userEvent.click(await screen.findByRole("button", { name: /Undo this edit/ }));
    expect(post).not.toHaveBeenCalled();
  });

  it("says so when the history cannot be loaded", async () => {
    get.mockRejectedValue(new Error("boom"));
    wrap();
    expect(await screen.findByText(/Couldn.t load the history/, {}, { timeout: 4000 })).toBeTruthy();
  });
});
