import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { SendPackageSheet, blockedReason } from "./SendPackageSheet";

const pkg = { key: "mysuru-coorg", name: "Mysuru and Coorg", summary: "", length: "2 nights / 3 days", days: ["Mysuru"], price: null, link: null,
  text: "Hi Kiran, here is Mysuru and Coorg (2 nights / 3 days).\nDay 1: Mysuru" };
const base = { packages: [pkg], window_open: true, template_approved: false, personal_bridge_only: false, has_phone: true, price_shown: false };

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
beforeEach(() => { get.mockReset(); post.mockReset(); });
afterEach(cleanup);

describe("SendPackageSheet", () => {
  it("previews the exact message and sends the picked package", async () => {
    get.mockResolvedValue({ data: base });
    post.mockResolvedValue({ data: { status: "queued", how: "text" } });
    wrap(<SendPackageSheet open onClose={vi.fn()} inquiryId="i1" name="Kiran" />);
    await userEvent.click(await screen.findByRole("radio", { name: /Mysuru and Coorg/ }));
    expect(screen.getByLabelText("Message preview").textContent).toContain("Day 1: Mysuru");
    await userEvent.click(screen.getByRole("button", { name: /Send on WhatsApp/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/leads/i1/package-share", { package_key: "mysuru-coorg" }));
  });

  it("explains a closed window with no approved template and offers only Copy", async () => {
    get.mockResolvedValue({ data: { ...base, window_open: false } });
    wrap(<SendPackageSheet open onClose={vi.fn()} inquiryId="i1" name="Kiran" />);
    await userEvent.click(await screen.findByRole("radio", { name: /Mysuru and Coorg/ }));
    expect(screen.getByText(/Template waiting for Meta approval/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Send on WhatsApp/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Copy text/ })).toBeTruthy();
  });

  it("knows every reason it cannot send", () => {
    expect(blockedReason({ ...base, has_phone: false }, pkg)).toMatch(/no phone/);
    expect(blockedReason({ ...base, window_open: false, personal_bridge_only: true }, pkg)).toMatch(/personal WhatsApp/);
    expect(blockedReason({ ...base, window_open: false, template_approved: true }, pkg)).toMatch(/no page to link/);
    expect(blockedReason({ ...base, window_open: false, template_approved: true }, { ...pkg, link: "https://x/links#pkg-a" })).toBeNull();
  });
});
