import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
let role = "reservations";
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { name: "Asha", role } }, status: "authenticated" }) }));

import { QuoteSheetProvider } from "./QuoteSheetProvider";
import { SendQuoteButton } from "./SendQuoteButton";
import { lead, setup } from "./calc/testFixtures";

function page() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <QuoteSheetProvider>
        <p>Inbox</p>
        <SendQuoteButton args={{ conversationId: "c1", inquiryId: "i1", from: "inbox", name: "Kiran Reddy" }} />
      </QuoteSheetProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup(); get.mockReset(); post.mockReset(); role = "reservations";
  get.mockImplementation((url: string) => Promise.resolve({ data: url === "/quote-calculator/setup" ? setup
    : { lead, add: null, trip: { guests: 5 }, guest_name: "Kiran Reddy", filled: ["guests"] } }));
  post.mockResolvedValue({ data: { ok: false, message: "Pick a package", warnings: [], availability: [] } });
});

describe("the Send quote sheet", () => {
  it("opens the calculator on top of the page, titled for the guest, with where it came from; Esc closes it", async () => {
    page();
    await userEvent.click(screen.getByRole("button", { name: "Send quote" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Quote for Kiran Reddy");
    await waitFor(() => expect(dialog.textContent).toContain("Opened from Kiran Reddy's WhatsApp chat. Guests filled in from the chat."));
    expect(get).toHaveBeenCalledWith("/quote-calculator/context", { params: expect.objectContaining({ conversation_id: "c1", inquiry_id: "i1" }) });
    expect(screen.getByText("Inbox")).toBeTruthy();                                   // the page stays underneath
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("is hidden for a role that cannot quote", () => {
    role = "foh";
    page();
    expect(screen.queryByRole("button", { name: "Send quote" })).toBeNull();
  });
});
