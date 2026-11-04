import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a) } }));

import { SecurityStatusCards } from "./SecurityStatusCards";

const STATUS = {
  storage: { provider: "cloudflare_r2", encryption: "provider_default", text: "Cloudflare R2, encrypted at rest by Cloudflare (AES-256, keys managed by Cloudflare)" },
  transcription_provider: "sarvam",
  keys: [
    { name: "AWS_ACCESS_KEY_ID", status: "set", note: "file storage key (Cloudflare R2)" },
    { name: "DEEPGRAM_API_KEY", status: "not_used", note: "call transcription" },
    { name: "GEMINI_API_KEY", status: "missing", note: "guest replies + fallback" },
  ],
  session: { access_token_minutes: 15, refresh_token_days: 30, login_rate_limit: "10 sign-in attempts a minute per IP address",
             mfa_rule: "A code is asked at sign-in for everyone who has turned on two-step sign-in. No role is forced to.", mfa_enabled_for_you: false },
  legacy_webhook_verify_token_allowed: true,
};

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><SecurityStatusCards /></QueryClientProvider>);
}

beforeEach(() => { cleanup(); get.mockReset(); });

describe("SecurityStatusCards", () => {
  it("shows the server's real configuration, not fixed claims", async () => {
    get.mockResolvedValue({ data: STATUS });
    renderIt();
    expect(await screen.findByText(/Cloudflare R2, encrypted at rest/)).toBeTruthy();
    expect(screen.queryByText(/KMS per tenant/)).toBeNull();
    expect(screen.queryByText(/Owner \+ Compliance/)).toBeNull();
    expect(screen.getByText("Not used")).toBeTruthy();            // Deepgram: optional, Sarvam transcribes
    expect(screen.getByText("Missing")).toBeTruthy();
    expect(screen.getByText(/Off: turn it on above/)).toBeTruthy();
    expect(screen.getByText(/old shared Meta webhook verify token/)).toBeTruthy();
  });

  it("has an error state", async () => {
    get.mockRejectedValue(new Error("boom"));
    renderIt();
    expect(await screen.findByText(/Couldn.t load/)).toBeTruthy();
  });
});
