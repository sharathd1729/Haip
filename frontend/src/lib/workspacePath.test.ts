import { describe, expect, it } from "vitest";
import { hasPublicAddress, toAppPath, toWorkspacePath, workspaceSlugOf } from "./workspacePath";

describe("workspace addresses", () => {
  it("maps both ways", () => {
    expect(toAppPath("/w/neelgiri")).toBe("/dashboard");
    expect(toAppPath("/w/neelgiri/bookings/BK-1")).toBe("/dashboard/bookings/BK-1");
    expect(toWorkspacePath("/dashboard", "neelgiri")).toBe("/w/neelgiri");
    expect(toWorkspacePath("/dashboard/inbox", "neelgiri")).toBe("/w/neelgiri/inbox");
  });
  it("leaves other paths alone", () => {
    expect(toAppPath("/pricing")).toBe("/pricing");
    expect(toAppPath("/wrong/x")).toBe("/wrong/x");
    expect(toWorkspacePath("/dashboardx", "a")).toBe("/dashboardx");
    expect(workspaceSlugOf("/w/demo-villas/inbox")).toBe("demo-villas");
  });
  it("gives personal and odd slugs no address", () => {
    expect(hasPublicAddress("me-1a2b3c")).toBe(false);
    expect(hasPublicAddress("Bad Slug")).toBe(false);
    expect(hasPublicAddress(undefined)).toBe(false);
    expect(hasPublicAddress("neelgiri")).toBe(true);
  });
});
