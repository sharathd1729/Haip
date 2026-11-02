import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { act, render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));

import { LeadComposer } from "./LeadComposer";
import type { FeedChannel } from "./types";

const NOW = Date.parse("2026-10-19T07:40:00Z");
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString();
const wa = (lastInbound: string | null): FeedChannel => ({ conversation_id: "cwa", channel: "whatsapp", last_inbound_at: lastInbound, can_send: true, ai_enabled: true });
const ig: FeedChannel = { conversation_id: "cig", channel: "instagram", last_inbound_at: hoursAgo(4), can_send: true, ai_enabled: true };

function renderComposer(channels: FeedChannel[], extra: Partial<Parameters<typeof LeadComposer>[0]> = {}) {
  const run = vi.fn();
  const onSent = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>
    <LeadComposer channels={channels} name="Sharath" canSend canQuote canBook hasPhone run={run} onSent={onSent} onError={vi.fn()} now={NOW} {...extra} />
  </QueryClientProvider>);
  return { run, onSent };
}

beforeEach(() => { get.mockReset(); post.mockReset(); });
afterEach(cleanup);

describe("LeadComposer", () => {
  it("sends free text inside the WhatsApp 24-hour window", async () => {
    post.mockResolvedValue({ data: {} });
    const { onSent } = renderComposer([wa(hoursAgo(3))]);
    expect(screen.queryByTestId("template-picker")).toBeNull();
    await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "Calling you in 5 min");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/conversations/cwa/messages", { body: "Calling you in 5 min", direction: "outbound" }, expect.anything()));
    expect(onSent).toHaveBeenCalledWith("whatsapp");
  });

  it("switches to an approved template once the window has closed", async () => {
    get.mockResolvedValue({ data: [
      { id: "t1", name: "callback_followup", language: "en", status: "approved", components: [{ type: "BODY", text: "Hi {{1}}, we tried calling you." }] },
      { id: "t2", name: "draft_one", language: "en", status: "pending", components: [{ type: "BODY", text: "Not approved" }] },
    ] });
    post.mockResolvedValue({ data: {} });
    renderComposer([wa(hoursAgo(30))]);

    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
    expect(screen.getByTestId("window-hint").textContent).toMatch(/only allows an approved template/);
    await userEvent.click(screen.getByRole("button", { name: /window closed · pick a template/ }));
    expect(await screen.findByText("callback followup")).toBeTruthy();
    expect(screen.queryByText("draft one")).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: /callback followup/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Value 1" }), "Sharath");
    expect(screen.getByText("Hi Sharath, we tried calling you.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Send template/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/conversations/cwa/send-template", { template_id: "t1", variables: ["Sharath"] }));
  });

  it("starts on the channel that can deliver: Instagram with an open window before a closed WhatsApp window", async () => {
    renderComposer([wa(hoursAgo(30)), ig]);
    expect(screen.getByRole("textbox", { name: "Message" }).getAttribute("placeholder")).toBe("Message Sharath on Instagram…");
    await userEvent.click(screen.getByRole("button", { name: /Reply on Instagram, switch channel/ }));
    expect(screen.getByRole("button", { name: /WhatsApp window closed · pick a template/ })).toBeTruthy();
  });

  it("Instagram window closed: no doomed send, offers Start on WhatsApp to the guest's number", async () => {
    get.mockResolvedValue({ data: [{ id: "t1", name: "hello_lead", language: "en", status: "approved", components: [{ type: "BODY", text: "Hi {{1}}" }] }] });
    post.mockResolvedValue({ data: { conversation_id: "cnew" } });
    const igOld: FeedChannel = { ...ig, last_inbound_at: hoursAgo(40) };
    const { onSent } = renderComposer([igOld], { startWhatsApp: { guestId: "g1", inquiryId: "i1" } });
    // the best channel is WhatsApp (a template to the number), not the closed Instagram chat
    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
    expect(screen.getByTestId("window-hint").textContent).toMatch(/No WhatsApp chat with Sharath yet/);
    await userEvent.click(screen.getByRole("button", { name: /Start on WhatsApp · pick a template/ }));
    await userEvent.click(await screen.findByRole("radio", { name: /hello lead/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Value 1" }), "Neha");
    await userEvent.click(screen.getByRole("button", { name: /Send template/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/guests/g1/whatsapp/start", { template_id: "t1", variables: ["Neha"], inquiry_id: "i1" }, expect.anything()));
    expect(onSent).toHaveBeenCalledWith("whatsapp");
    // switching back to Instagram shows why it cannot send, with the way out
    await userEvent.click(screen.getByRole("button", { name: /switch channel/ }));
    expect(screen.getByRole("button", { name: /Instagram window closed · message on WhatsApp/ })).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
  });

  it("the WhatsApp button opens WhatsApp, not the Instagram chat", async () => {
    get.mockResolvedValue({ data: [] });
    const ref = { current: null as null | { focus: (c?: "whatsapp") => void } };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}>
      <LeadComposer ref={ref} channels={[ig]} name="Sharath" canSend canQuote canBook hasPhone run={vi.fn()} onSent={vi.fn()} onError={vi.fn()} now={NOW}
        startWhatsApp={{ guestId: "g1" }} />
    </QueryClientProvider>);
    expect(screen.getByRole("textbox", { name: "Message" }).getAttribute("placeholder")).toBe("Message Sharath on Instagram…");
    act(() => ref.current!.focus("whatsapp"));
    expect(await screen.findByTestId("window-hint")).toBeTruthy();
    expect(screen.getByTestId("window-hint").textContent).toMatch(/No WhatsApp chat with Sharath yet/);
  });

  it("has the phone action row and says when there is no chat yet", async () => {
    const { run } = renderComposer([]);
    expect(screen.getByText(/No WhatsApp or Instagram chat with Sharath yet/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Book" }));
    expect(run).toHaveBeenCalledWith("book");
  });
});
