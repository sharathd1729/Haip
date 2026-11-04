import { describe, expect, it } from "vitest";
import { resourceLink } from "./auditLinks";

describe("resourceLink", () => {
  it("sends a user to the team list with the member highlighted, not a missing detail page", () => {
    expect(resourceLink("user", "u-1")).toBe("/dashboard/settings/team?member=u-1");
  });
  it("keeps the existing detail routes", () => {
    expect(resourceLink("guest", "g")).toBe("/dashboard/guests/g");
    expect(resourceLink("call", "c")).toBe("/dashboard/calls/c");
    expect(resourceLink("inquiry", "i")).toBe("/dashboard/leads/i");
  });
  it("has no link for unknown types or a missing id", () => {
    expect(resourceLink("tenant", "t")).toBeNull();
    expect(resourceLink("user", undefined)).toBeNull();
  });
});
