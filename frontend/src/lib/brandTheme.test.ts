import { describe, expect, it } from "vitest";
import { DEFAULT_THEME, buildCSSVars, withCurrentDefaultLogo } from "./brandTheme";

describe("brand theme: greens + terracotta", () => {
  it("leaves the action feeds unset for the house theme, so buttons stay terracotta", () => {
    const v = buildCSSVars(DEFAULT_THEME);
    expect(v["--brand-primary"]).toBe("#235347");
    expect(v["--brand-primary-on-dark"]).toBe("#8EB69B");
    expect(v["--brand-action"]).toBe("");
    expect(v["--brand-on-action"]).toBe("");
    expect(v["--brand-action-on-dark"]).toBe("");
  });

  it("gives a tenant with its own brand colour that colour on buttons too", () => {
    const v = buildCSSVars({ ...DEFAULT_THEME, primaryColor: "#3b82f6" });
    expect(v["--brand-action"]).toBe("#3b82f6");
    expect(v["--brand-on-action"]).toBe(v["--brand-on-primary"]);
    expect(v["--brand-action-on-dark"]).toBe(v["--brand-primary-on-dark"]);
  });

  it("moves a workspace still on the previous sea-green default onto the new house colours", () => {
    const t = withCurrentDefaultLogo({ ...DEFAULT_THEME, primaryColor: "#1E7A5A", sidebarColor: "#FFFFFF" });
    expect(t.primaryColor).toBe("#235347");
  });
});
