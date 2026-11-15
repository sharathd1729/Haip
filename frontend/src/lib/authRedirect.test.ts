import { describe, expect, it } from "vitest";
import { isYaadScreen, safeCallback } from "./authRedirect";

describe("sign-in redirects", () => {
  it("never treats HAIP's WhatsApp page as a Yaad screen", () => {
    expect(isYaadScreen("/dashboard/me")).toBe(true);
    expect(isYaadScreen("/dashboard/me/calendar")).toBe(true);
    expect(isYaadScreen("/dashboard/messaging")).toBe(false);
    expect(isYaadScreen("/dashboard/messaging/campaigns")).toBe(false);
  });
  it("Yaad's sign-in only returns to Yaad screens", () => {
    expect(safeCallback("/dashboard/messaging", "/dashboard/me", "/dashboard/me")).toBe("/dashboard/me");
    expect(safeCallback("/dashboard/me/calls/c1?t=42", "/dashboard/me", "/dashboard/me")).toBe("/dashboard/me/calls/c1?t=42");
    expect(safeCallback("//evil.example", "/dashboard", undefined)).toBe("/dashboard");
    expect(safeCallback("/dashboard/leads", "/dashboard", undefined)).toBe("/dashboard/leads");
  });
});
