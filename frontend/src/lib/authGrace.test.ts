import { describe, it, expect, vi, afterEach } from "vitest";
import { isWithinRefreshErrorGrace, REFRESH_ERROR_GRACE_MS } from "./authGrace";

describe("isWithinRefreshErrorGrace", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("is true for a RefreshAccessTokenError that just started", () => {
    expect(isWithinRefreshErrorGrace("RefreshAccessTokenError", Date.now())).toBe(true);
  });

  it("is true right up until the grace window elapses", () => {
    vi.useFakeTimers();
    const start = Date.now();
    vi.setSystemTime(start + REFRESH_ERROR_GRACE_MS - 1);
    expect(isWithinRefreshErrorGrace("RefreshAccessTokenError", start)).toBe(true);
  });

  it("is false once the grace window has elapsed -- the error must have persisted, not self-healed", () => {
    vi.useFakeTimers();
    const start = Date.now();
    vi.setSystemTime(start + REFRESH_ERROR_GRACE_MS + 1);
    expect(isWithinRefreshErrorGrace("RefreshAccessTokenError", start)).toBe(false);
  });

  it("is false without an errorSince timestamp, even if the error is set", () => {
    expect(isWithinRefreshErrorGrace("RefreshAccessTokenError", undefined)).toBe(false);
    expect(isWithinRefreshErrorGrace("RefreshAccessTokenError", null)).toBe(false);
  });

  it("never grants grace to SessionExpired -- the deliberate 12h cutoff has nothing to self-heal", () => {
    expect(isWithinRefreshErrorGrace("SessionExpired", Date.now())).toBe(false);
  });

  it("is false when there is no error at all", () => {
    expect(isWithinRefreshErrorGrace(undefined, Date.now())).toBe(false);
    expect(isWithinRefreshErrorGrace(null, Date.now())).toBe(false);
  });
});
