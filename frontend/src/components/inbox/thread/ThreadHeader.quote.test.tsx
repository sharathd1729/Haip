import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const open = vi.fn();
vi.mock("@/components/quotes/QuoteSheetProvider", () => ({ useQuoteSheet: () => ({ open, close: vi.fn() }) }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { role: "concierge" } }, status: "authenticated" }) }));

import { ThreadHeader } from "./ThreadHeader";
import type { ConversationDetail, Mut } from "./types";

afterEach(() => { cleanup(); open.mockReset(); });

const mut = { mutate: vi.fn(), isPending: false } as unknown as Mut;
const detail: ConversationDetail = {
  id: "c1", inquiry_id: "i1", guest_name: "Kiran Reddy", guest_phone: "+919876545678", channel: "whatsapp", status: "open", messages: [],
};

describe("Inbox conversation header", () => {
  it("has a Send quote button that opens the calculator sheet for this chat's lead", async () => {
    render(<ThreadHeader detail={detail} setMobileView={vi.fn()} isOfficialWhatsApp windowOpen aiToggleMutation={mut} assignMutation={mut}
      teamMembers={[]} currentUserId="u1" clickToCallMutation={mut} resolveMutation={mut} setShowGuestSheet={vi.fn()} setShowSearch={vi.fn()}
      snoozeMutation={mut} />);
    await userEvent.click(screen.getByRole("button", { name: "Send quote" }));
    expect(open).toHaveBeenCalledWith({ conversationId: "c1", inquiryId: "i1", from: "inbox", name: "Kiran Reddy" });
  });
});
