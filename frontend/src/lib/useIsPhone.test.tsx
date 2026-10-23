import { describe, it, expect, afterEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { PHONE_QUERY, useIsPhone } from "./useIsPhone";

const original = window.matchMedia;
afterEach(() => { window.matchMedia = original; });

describe("useIsPhone", () => {
  it("is true below 768px and asks the app's one breakpoint", async () => {
    const mm = vi.fn((q: string) => ({ matches: true, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    window.matchMedia = mm as unknown as typeof window.matchMedia;
    const { result } = renderHook(() => useIsPhone());
    await waitFor(() => expect(result.current).toBe(true));
    expect(mm).toHaveBeenCalledWith(PHONE_QUERY);
    expect(PHONE_QUERY).toBe("(max-width: 767px)");
  });

  it("stays false (desktop) when matchMedia is missing, as in jsdom", () => {
    (window as unknown as { matchMedia?: unknown }).matchMedia = undefined;
    const { result } = renderHook(() => useIsPhone());
    expect(result.current).toBe(false);
  });
});
