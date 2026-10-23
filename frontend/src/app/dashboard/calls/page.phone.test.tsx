import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api", () => ({ default: { get: vi.fn().mockResolvedValue({ data: [] }), post: vi.fn() } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { id: "u1", name: "Asha", role: "owner" } }, status: "authenticated" }) }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/dashboard/calls" }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
const uploadOpened = vi.fn();
vi.mock("next/dynamic", () => ({ default: () => () => { uploadOpened(); return <div>upload-modal</div>; } }));

import CallsPage from "./page";

afterEach(cleanup);

describe("Calls page, adding a call record", () => {
  it("shows the Upload button on every width (labelled 'Add call' on phones) and it opens the existing upload modal", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><CallsPage /></QueryClientProvider>);
    const btn = screen.getByRole("button", { name: /Add call\s*Upload/ });
    expect(btn.className).not.toContain("hidden");
    expect(btn.className).toContain("max-sm:min-h-11");
    expect(screen.queryByText("upload-modal")).toBeNull();
    await userEvent.click(btn);
    expect(await screen.findByText("upload-modal")).toBeTruthy();
  });
});
