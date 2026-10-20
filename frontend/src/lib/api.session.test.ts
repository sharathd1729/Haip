// The 401 handler in lib/api.ts: after a refresh fails for good the session still carries the EXPIRED access token.
// That used to keep every request 401ing quietly while pages showed stale cached data (owner, 20 Oct 2026); it must sign
// out instead. A refresh failure still inside its grace window must not.
import { describe, it, expect, vi, beforeEach } from "vitest";

const getSession = vi.fn();
const signOut = vi.fn(() => Promise.resolve());
vi.mock("next-auth/react", () => ({ getSession: () => getSession(), signOut: (...a: unknown[]) => signOut(...a) }));

import api, { getToken } from "./api";
import { clearTokenCache } from "./api";

// A syntactically valid JWT whose exp is in the past.
const expired = `x.${btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) - 600 }))}.y`;

function always401() {
  api.defaults.adapter = async (config) => {
    const err = Object.assign(new Error("401"), {
      config, response: { status: 401, data: {}, headers: {}, config, statusText: "Unauthorized" }, isAxiosError: true,
    });
    throw err;
  };
}

beforeEach(() => {
  getSession.mockReset();
  signOut.mockClear();
  clearTokenCache();
  always401();
});

describe("api 401 handling", () => {
  it("signs out when the refresh failed past its grace window, even though an expired token is still in the session", async () => {
    getSession.mockResolvedValue({ accessToken: expired, error: "RefreshAccessTokenError", errorSince: Date.now() - 120_000 });
    await expect(api.get("/work-queue")).rejects.toBeTruthy();
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("does not sign out inside the grace window (a transient refresh failure can still heal)", async () => {
    getSession.mockResolvedValue({ accessToken: expired, error: "RefreshAccessTokenError", errorSince: Date.now() - 5_000 });
    await expect(api.get("/work-queue")).rejects.toBeTruthy();
    expect(signOut).not.toHaveBeenCalled();
  });

  it("does not sign out on a plain 401 from a healthy session", async () => {
    const valid = `x.${btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 600 }))}.y`;
    getSession.mockResolvedValue({ accessToken: valid });
    await expect(api.get("/admin-only")).rejects.toBeTruthy();
    expect(signOut).not.toHaveBeenCalled();
    expect(await getToken()).toBe(valid);
  });
});
