import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/components/quotes/QuoteSheetProvider", () => ({ useQuoteSheet: () => ({ open: vi.fn(), close: vi.fn() }) }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { role: "concierge" } }, status: "authenticated" }) }));

import { ThreadHeader } from "./ThreadHeader";
import type { ConversationDetail, Mut } from "./types";

afterEach(cleanup);

const base: ConversationDetail = {
  id: "c1", inquiry_id: "i1", guest_name: "Kiran Reddy", guest_phone: "+919876545678", channel: "whatsapp", status: "open", messages: [],
};

function renderHeader(detail: ConversationDetail, aiToggle: Mut) {
  const mut = { mutate: vi.fn(), isPending: false } as unknown as Mut;
  render(<ThreadHeader detail={detail} setMobileView={vi.fn()} isOfficialWhatsApp windowOpen aiToggleMutation={aiToggle} assignMutation={mut}
    teamMembers={[]} currentUserId="u1" clickToCallMutation={mut} resolveMutation={mut} setShowGuestSheet={vi.fn()} setShowSearch={vi.fn()}
    snoozeMutation={mut} />);
}

describe("Inbox header when the guest asked for a person", () => {
  it("says why the AI is off, shows the switch off, and a person can turn it back on", async () => {
    const toggle = { mutate: vi.fn(), isPending: false } as unknown as Mut;
    renderHeader({ ...base, ai_enabled: false, ai_off_reason: "guest asked for a person" }, toggle);
    expect(screen.getByText("AI turned off: guest asked for a person")).toBeTruthy();
    const sw = screen.getByRole("switch");
    expect(sw.getAttribute("aria-checked")).toBe("false");
    await userEvent.click(sw);
    expect(toggle.mutate).toHaveBeenCalledWith(true);
  });

  it("shows no banner when a person paused it or the AI is on", () => {
    const toggle = { mutate: vi.fn(), isPending: false } as unknown as Mut;
    renderHeader({ ...base, ai_enabled: false, ai_off_reason: null }, toggle);
    expect(screen.queryByText(/AI turned off/)).toBeNull();
    expect(screen.getByText("AI paused")).toBeTruthy();
  });
});
