import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const post = vi.fn();
const toast = vi.fn();
vi.mock("@/lib/api", () => ({ default: { post: (...a: unknown[]) => post(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast }) }));

import { canRevealNumbers, contactHref, forgetChoices, hasRememberedChoice, rememberedVia, useContactChoice, type ContactKind } from "./ContactChoice";

if (typeof window.PointerEvent === "undefined") {
  (window as unknown as { PointerEvent: typeof MouseEvent }).PointerEvent = class extends MouseEvent {} as typeof MouseEvent;
}

const office = vi.fn();
function Harness({ kind = "call", canReveal = true }: { kind?: ContactKind; canReveal?: boolean }) {
  const c = useContactChoice({ kind, inquiryId: "i1", name: "Ravi", canReveal, phoneMasked: "+91 ••••• ••210", onOffice: office });
  return <><button type="button" onClick={c.start}>go</button>{c.sheet}</>;
}
function wrap(ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

let went = "";
beforeEach(() => {
  post.mockReset(); toast.mockReset(); office.mockReset(); forgetChoices(); went = "";
  post.mockResolvedValue({ data: { phone: "+91 98765 43210" } });
  Object.defineProperty(window, "location", { configurable: true, value: { get href() { return went; }, set href(v: string) { went = v; } } });
});
afterEach(cleanup);

describe("contactHref", () => {
  it("keeps the + for the dialer and uses digits only for WhatsApp", () => {
    expect(contactHref("call", "+91 98765 43210")).toBe("tel:+919876543210");
    expect(contactHref("whatsapp", "+91 98765-43210")).toBe("https://wa.me/919876543210");
  });
  it("knows which roles may see numbers by default", () => {
    expect(canRevealNumbers("concierge")).toBe(true);
    expect(canRevealNumbers("foh")).toBe(false);
    expect(canRevealNumbers(undefined)).toBe(false);
  });
});

describe("Call / WhatsApp choice", () => {
  it("asks first; Office line runs the HAIP action and no number is fetched", async () => {
    wrap(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    expect(await screen.findByText("Call Ravi")).toBeTruthy();
    expect(screen.getByText("+91 ••••• ••210")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Office line/ }));
    expect(office).toHaveBeenCalledTimes(1);
    expect(post).not.toHaveBeenCalled();
  });

  it("My phone gets the number through the audited reveal and opens the dialer", async () => {
    wrap(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await userEvent.click(await screen.findByRole("button", { name: /My phone/ }));
    await waitFor(() => expect(went).toBe("tel:+919876543210"));
    expect(post).toHaveBeenCalledWith("/leads/i1/contact/reveal");
    expect(office).not.toHaveBeenCalled();
  });

  it("My WhatsApp opens the chat by number", async () => {
    wrap(<Harness kind="whatsapp" />);
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await userEvent.click(await screen.findByRole("button", { name: /My WhatsApp/ }));
    await waitFor(() => expect(went).toBe("https://wa.me/919876543210"));
  });

  it("shows the number on request, and remembers the choice so the next tap acts at once", async () => {
    wrap(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await userEvent.click(await screen.findByRole("button", { name: /Show number/ }));
    expect(await screen.findByText("+91 98765 43210")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Copy/ })).toBeTruthy();
    await userEvent.click(screen.getByRole("checkbox", { name: /Remember my choice/ }));
    await userEvent.click(screen.getByRole("button", { name: /Office line/ }));
    expect(rememberedVia("call")).toBe("office");
    expect(hasRememberedChoice()).toBe(true);
    await waitFor(() => expect(screen.queryByText("Call Ravi")).toBeNull());
    await userEvent.click(screen.getByRole("button", { name: "go" }));          // no sheet this time
    expect(office).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Call Ravi")).toBeNull();
  });

  it("a role that cannot see numbers gets the office line only, with the reason", async () => {
    wrap(<Harness canReveal={false} />);
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    expect((await screen.findByRole("button", { name: /My phone/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Your role cannot see guest numbers/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Show number/ })).toBeNull();
  });

  it("says so when the server refuses the number", async () => {
    post.mockRejectedValue(new Error("403"));
    wrap(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await userEvent.click(await screen.findByRole("button", { name: /My phone/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({ variant: "error", title: "Couldn't get the number" })));
    expect(went).toBe("");
  });
});
