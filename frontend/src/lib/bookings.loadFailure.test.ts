import { describe, it, expect } from "vitest";
import { LOAD_FAILURES, loadFailure } from "./bookings";

const http = (status: number) => ({ response: { status } });

describe("loadFailure", () => {
  it("only a 404 says the booking is missing", () => {
    expect(loadFailure(http(404)).title).toBe("Booking not found");
    for (const s of [401, 403, 500, 502]) expect(loadFailure(http(s)).title).not.toBe("Booking not found");
    expect(loadFailure(new Error("Network Error")).title).not.toBe("Booking not found");
  });

  it("names the permission problem and the signed-out case", () => {
    expect(loadFailure(http(403)).title).toMatch(/access/i);
    expect(loadFailure(http(401)).title).toMatch(/signed out/i);
  });

  it("offers Try again only when a retry could help", () => {
    expect(loadFailure(http(404)).retry).toBe(false);
    expect(loadFailure(http(403)).retry).toBe(false);
    expect(loadFailure(http(500)).retry).toBe(true);
    expect(loadFailure(new Error("Network Error")).retry).toBe(true);
    expect(loadFailure(http(500)).body).toContain("500");
  });

  it("does not retry definite answers automatically", () => {
    expect([...LOAD_FAILURES].sort()).toEqual([401, 403, 404]);
  });
});
