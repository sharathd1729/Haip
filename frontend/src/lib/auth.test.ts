import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// auth.ts calls NextAuth(...) at module load, which needs a bunch of
// provider/env wiring we don't want to drag into a unit test -- mock just
// enough of next-auth for the module to import cleanly. We only exercise
// the exported refreshAccessToken helper, not the NextAuth handlers.
vi.mock("next-auth", () => ({
  default: () => ({ handlers: {}, auth: vi.fn(), signIn: vi.fn(), signOut: vi.fn() }),
}));
vi.mock("next-auth/providers/credentials", () => ({ default: vi.fn(() => ({})) }));
vi.mock("next-auth/providers/google", () => ({ default: vi.fn(() => ({})) }));

import { refreshAccessToken } from "./auth";

describe("refreshAccessToken retry behavior", () => {
  const originalEnv = process.env.BACKEND_URL;

  beforeEach(() => {
    process.env.BACKEND_URL = "https://backend.example.test";
    vi.useFakeTimers();
  });

  afterEach(() => {
    process.env.BACKEND_URL = originalEnv;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("succeeds immediately on a healthy response, no retry", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: "a.b.c", refresh_token: "new-refresh" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const resultPromise = refreshAccessToken("old-refresh");
    await vi.runAllTimersAsync();
    const result = await resultPromise;

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect("accessToken" in result && result.accessToken).toBe("a.b.c");
  });

  it("retries a thrown network error (e.g. a deploy briefly dropping the connection) and succeeds on retry", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ access_token: "a.b.c", refresh_token: "new-refresh" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const resultPromise = refreshAccessToken("old-refresh-2");
    await vi.runAllTimersAsync();
    const result = await resultPromise;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect("accessToken" in result && result.accessToken).toBe("a.b.c");
  });

  it("retries a 503 from the proxy/backend and succeeds on retry", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503, text: async () => "Service Unavailable" })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ access_token: "a.b.c", refresh_token: "new-refresh" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const resultPromise = refreshAccessToken("old-refresh-3");
    await vi.runAllTimersAsync();
    const result = await resultPromise;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect("accessToken" in result && result.accessToken).toBe("a.b.c");
  });

  it("does NOT retry a genuine 401 (revoked/invalid token) -- one call, immediate error", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 401, text: async () => "Token revoked or not found" });
    vi.stubGlobal("fetch", fetchMock);

    const resultPromise = refreshAccessToken("dead-refresh");
    await vi.runAllTimersAsync();
    const result = await resultPromise;

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect("error" in result && result.error).toBe("RefreshAccessTokenError");
  });

  it("gives up and errors after exhausting all retries on persistent failure", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    vi.stubGlobal("fetch", fetchMock);

    const resultPromise = refreshAccessToken("old-refresh-4");
    await vi.runAllTimersAsync();
    const result = await resultPromise;

    expect(fetchMock).toHaveBeenCalledTimes(3); // REFRESH_RETRY_ATTEMPTS
    expect("error" in result && result.error).toBe("RefreshAccessTokenError");
  });
});
