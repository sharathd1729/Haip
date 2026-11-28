import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const open = vi.fn();
vi.mock("@/components/quotes/QuoteSheetProvider", () => ({ useQuoteSheet: () => ({ open, close: vi.fn() }) }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { role: "concierge" } }, status: "authenticated" }) }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api", () => ({ default: { post: vi.fn(), get: vi.fn() } }));

import { ThreadHeader } from "./ThreadHeader";
import { forgetChoices } from "@/components/contact/ContactChoice";
import type { ConversationDetail, Mut } from "./types";

if (typeof window.PointerEvent === "undefined") {
  (window as unknown as { PointerEvent: typeof MouseEvent }).PointerEvent = class extends MouseEvent {} as typeof MouseEvent;
}

afterEach(() => { cleanup(); open.mockReset(); forgetChoices(); });

const mut = { mutate: vi.fn(), isPending: false } as unknown as Mut;
const detail: ConversationDetail = {
  id: "c1", inquiry_id: "i1", guest_name: "Kiran Reddy", guest_phone: "+919876545678", channel: "whatsapp", status: "open", messages: [],
};

function renderHeader(over: Partial<Parameters<typeof ThreadHeader>[0]> = {}) {
  const props = { detail, setMobileView: vi.fn(), isOfficialWhatsApp: true, windowOpen: true, aiToggleMutation: mut, assignMutation: mut,
    teamMembers: [], currentUserId: "u1", clickToCallMutation: mut, resolveMutation: mut, setShowGuestSheet: vi.fn(), setShowSearch: vi.fn(),
    snoozeMutation: mut, ...over };
  render(<QueryClientProvider client={new QueryClient()}><ThreadHeader {...props} /></QueryClientProvider>);
  return props;
}

describe("Inbox conversation header", () => {
  it("has a Send quote button that opens the calculator sheet for this chat's lead", async () => {
    renderHeader();
    await userEvent.click(screen.getByRole("button", { name: "Send quote" }));
    expect(open).toHaveBeenCalledWith({ conversationId: "c1", inquiryId: "i1", from: "inbox", name: "Kiran Reddy" });
  });

  it("phone: the name opens the guest's details, and More holds Guest details, Send quote and Mark resolved", async () => {
    const resolve = { mutate: vi.fn(), isPending: false } as unknown as Mut;
    const p = renderHeader({ resolveMutation: resolve });
    await userEvent.click(screen.getByRole("button", { name: "Kiran Reddy, guest details" }));
    expect(p.setShowGuestSheet).toHaveBeenCalledWith(true);
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("menuitem", { name: "Guest details" })).toBeTruthy();
    await userEvent.click(screen.getByRole("menuitem", { name: "Send quote" }));
    expect(open).toHaveBeenCalledWith({ conversationId: "c1", inquiryId: "i1", from: "inbox", name: "Kiran Reddy" });
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Mark resolved" }));
    expect(resolve.mutate).toHaveBeenCalledTimes(1);
  });

  it("Call offers My phone or Office line; Office line uses click-to-call with the chat's number", async () => {
    const call = { mutate: vi.fn(), isPending: false } as unknown as Mut;
    renderHeader({ clickToCallMutation: call });
    await userEvent.click(screen.getByRole("button", { name: "Call" }));
    expect(await screen.findByRole("button", { name: /My phone/ })).toBeTruthy();
    expect(call.mutate).not.toHaveBeenCalled();                     // nothing dials until the person chooses
    await userEvent.click(screen.getByRole("button", { name: /Office line/ }));
    expect(call.mutate).toHaveBeenCalledWith("+919876545678");
  });
});
