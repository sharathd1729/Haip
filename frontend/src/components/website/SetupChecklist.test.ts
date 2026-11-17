import { describe, expect, it } from "vitest";
import type { SiteOut } from "@/lib/website";
import type { SpecV2 } from "@/site-blocks/v2/types";
import { setupSteps } from "./SetupChecklist";

const site = (over: Partial<SiteOut> = {}) => ({ live: null, domains: [], ...over }) as unknown as SiteOut;
const doc = (site: Partial<SpecV2["site"]> = {}) => ({ site: { name: "N", contact: { phone: "", whatsapp: "", email: "", address: "" }, ...site } }) as unknown as SpecV2;

describe("website setup checklist (W6)", () => {
  it("reads every step from the draft and the site", () => {
    const steps = setupSteps(doc(), site(), true);
    expect(steps.map(s => s.key)).toEqual(["logo", "contact", "menu", "design", "publish", "domain"]);
    expect(steps.every(s => !s.done)).toBe(true);
    const done = setupSteps(doc({ brand: { logo: "asset:x", show_name: true }, contact: { phone: "1", whatsapp: "", email: "", address: "" },
      menus: { main: [], footer: [] } }), site({ live: { id: "v", number: 2, published_at: null },
      domains: [{ id: "d", hostname: "www.x.in", kind: "custom", status: "active", error: null, verify_token: null, cname_target: "" }] }), false);
    expect(done.map(s => s.key)).not.toContain("design");
    expect(done.every(s => s.done)).toBe(true);
  });

  it("a domain waiting for DNS is not done and says so", () => {
    const d = setupSteps(doc(), site({ domains: [{ id: "d", hostname: "www.x.in", kind: "custom", status: "pending", error: null, verify_token: null, cname_target: "" }] }), false)
      .find(s => s.key === "domain")!;
    expect(d.done).toBe(false);
    expect(d.hint).toContain("www.x.in");
  });
});
