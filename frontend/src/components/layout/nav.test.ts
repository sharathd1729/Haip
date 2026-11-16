import { describe, expect, it } from "vitest";
import { NAV_SECTIONS, areaFor, linkActive } from "./nav";

const key = (path: string, search = "") => areaFor(NAV_SECTIONS, path, search)?.key;

describe("workspace areas", () => {
  it("puts each page in the area that holds its most specific link", () => {
    expect(key("/dashboard")).toBe("home");
    expect(key("/dashboard/my-day")).toBe("home");
    expect(key("/dashboard/calls/abc")).toBe("inbox");
    expect(key("/dashboard/bookings/123")).toBe("bookings");
    expect(key("/dashboard/settings/knowledge")).toBe("ai");
    expect(key("/dashboard/settings/team")).toBe("settings");
    expect(key("/dashboard/messaging/flows")).toBe("automations");
    expect(key("/dashboard/messaging/campaigns")).toBe("marketing");
  });
  it("counts a link with a query only when the query matches", () => {
    expect(key("/dashboard/settings")).toBe("settings");
    expect(key("/dashboard/settings", "tab=ai")).toBe("ai");
    expect(linkActive("/dashboard/inbox", "/dashboard/inbox?ch=ai", "")).toBe(false);
    expect(linkActive("/dashboard/inbox", "/dashboard/inbox?ch=ai", "ch=ai")).toBe(true);
  });
  it("has eight areas plus settings, and no page in two areas", () => {
    expect(NAV_SECTIONS.map(s => s.key)).toEqual(["home", "inbox", "leads", "bookings", "ops", "marketing", "automations", "ai", "settings"]);
    const hrefs = NAV_SECTIONS.flatMap(s => s.links.map(l => l.href));
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});
