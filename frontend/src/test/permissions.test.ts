import { describe, it, expect } from "vitest";
import { hasPermission, canSeeNav, navByRole } from "@/lib/permissions";

describe("permissions", () => {
  describe("navByRole", () => {
    it("owner can see all nav items", () => {
      const ownerNav = navByRole["owner"];
      expect(ownerNav).toContain("dashboard");
      expect(ownerNav).toContain("calls");
      expect(ownerNav).toContain("compliance");
      expect(ownerNav).toContain("settings");
    });

    it("concierge cannot see compliance or settings", () => {
      const conciergeNav = navByRole["concierge"];
      expect(conciergeNav).not.toContain("compliance");
      expect(conciergeNav).not.toContain("settings");
    });

    it("compliance role can see compliance but not calls detail", () => {
      const complianceNav = navByRole["compliance"];
      expect(complianceNav).toContain("compliance");
    });
  });

  describe("canSeeNav", () => {
    it("owner can see calls nav", () => {
      expect(canSeeNav("owner", "calls")).toBe(true);
    });

    it("concierge cannot see analytics nav", () => {
      expect(canSeeNav("concierge", "analytics")).toBe(false);
    });

    it("reservations can see inquiries nav", () => {
      expect(canSeeNav("reservations", "inquiries")).toBe(true);
    });
  });

  describe("hasPermission", () => {
    it("owner can write calls and users, and manage (but not write) compliance", () => {
      expect(hasPermission("owner", "calls", "write")).toBe(true);
      expect(hasPermission("owner", "compliance", "manage")).toBe(true);
      expect(hasPermission("owner", "compliance", "write")).toBe(false);
      expect(hasPermission("owner", "users", "write")).toBe(true);
    });

    it("read-only role has read but not write", () => {
      expect(hasPermission("read_only", "calls", "read")).toBe(true);
      expect(hasPermission("read_only", "calls", "write")).toBe(false);
    });

    it("concierge cannot write to compliance", () => {
      expect(hasPermission("concierge", "compliance", "write")).toBe(false);
    });
  });
});
