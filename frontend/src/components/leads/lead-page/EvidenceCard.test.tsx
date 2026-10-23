import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { EvidenceCard, describeEvidence, type EvidenceItem } from "./EvidenceCard";

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const chat: EvidenceItem = { id: "e1", kind: "chat_export", status: "done", filename: "chat.zip", created_at: "2026-10-23T05:00:00Z",
  uploaded_by_name: "Asha", message_count: 12, duplicate_count: 3, media_count: 2, duration_seconds: null, summary: null };

beforeEach(() => { get.mockReset(); post.mockReset(); });
afterEach(cleanup);

describe("EvidenceCard", () => {
  it("lists uploads with what they added", async () => {
    get.mockResolvedValue({ data: { items: [chat, { ...chat, id: "e2", kind: "call_recording", status: "transcribing", duration_seconds: 125 }] } });
    wrap(<EvidenceCard inquiryId="i1" canEdit />);
    expect(await screen.findByText("12 messages added · 3 already here · 2 files")).toBeTruthy();
    expect(screen.getByText("Call recording · 2:05")).toBeTruthy();
    expect(screen.getByText("Transcribing")).toBeTruthy();
  });

  it("shows the empty state and hides uploads without edit rights", async () => {
    get.mockResolvedValue({ data: { items: [] } });
    wrap(<EvidenceCard inquiryId="i1" canEdit={false} />);
    expect(await screen.findByText(/Nothing uploaded yet/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Chat export/ })).toBeNull();
  });

  it("asks which name is the guest when HAIP cannot tell, then sends the pick", async () => {
    get.mockResolvedValue({ data: { items: [] } });
    post.mockRejectedValueOnce({ response: { status: 422, data: { detail: { code: "pick_guest_sender", senders: [{ name: "Ravi K", messages: 4 }, { name: "Team", messages: 3 }] } } } });
    post.mockResolvedValueOnce({ data: chat });
    wrap(<EvidenceCard inquiryId="i1" canEdit />);
    await userEvent.click(await screen.findByRole("button", { name: /Chat export/ }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["12/10/26, 2:35 pm - Ravi K: hi"], "chat.txt", { type: "text/plain" }));
    await userEvent.click(screen.getByRole("button", { name: /^Upload$/ }));
    await userEvent.click(await screen.findByRole("radio", { name: /Ravi K/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Upload$/ }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    const form = post.mock.calls[1][1] as FormData;
    expect(form.get("guest_sender")).toBe("Ravi K");
    expect(form.get("kind")).toBe("chat_export");
  });

  it("describes a recording without a known length", () => {
    expect(describeEvidence({ ...chat, kind: "call_recording", duration_seconds: null })).toBe("Call recording");
  });
});
