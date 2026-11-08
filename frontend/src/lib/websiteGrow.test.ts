import { describe, expect, it } from "vitest";
import { allowed, growRow, inr } from "./websiteGrow";

describe("growRow", () => {
  it("a late checklist step says Late and opens its checklist", () => {
    const r = growRow({ kind: "sop_step", role: "local_profile", instance_id: "i1", checklist: "Google Business Profile", title: "Add photos",
      due_at: "2026-11-02T04:00:00Z", overdue: true }, 0);
    expect(r).toMatchObject({ tag: "Late", tone: "danger", href: "/dashboard/marketing/sops/i1" });
  });
  it("a step due later names the day in IST", () => {
    const r = growRow({ kind: "sop_step", role: "listings", instance_id: "i2", checklist: "Airbnb", title: "Refresh",
      due_at: "2026-11-11T20:00:00Z", overdue: false }, 0);
    expect(r.tag).toBe("Thu");  // 01:30 IST Thursday, not Wednesday in UTC
  });
  it("outreach copies the message; fixes can be applied; ads only suggest", () => {
    expect(growRow({ kind: "outreach", role: "links_citations", creator_id: "c", handle: "@coorg.diaries", platform: "instagram",
      text: "Hi", ai: true }, 0)).toMatchObject({ title: "Ask @coorg.diaries for a link", copy: "Hi" });
    expect(growRow({ kind: "fixes", role: "technical_checker", alt: 1, titles: 2 }, 0)).toMatchObject({ apply: true,
      subtitle: "1 photo, 2 titles · titles go to your draft" });
    const ad = growRow({ kind: "ads", role: "ads_analyst", campaign: "Brand", action: "pause" }, 0);
    expect(ad.href).toBeUndefined();
    expect(ad.copy).toBeUndefined();
  });
});

describe("levels and money", () => {
  it("a role cannot go above its cap", () => {
    expect(allowed("autopilot", "suggest")).toBe(false);
    expect(allowed("suggest", "suggest")).toBe(true);
  });
  it("rupees in lakh style", () => expect(inr(184000)).toBe("₹1,84,000"));
});
