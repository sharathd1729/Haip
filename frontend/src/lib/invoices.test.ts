import { describe, expect, it } from "vitest";
import { deliveryPill, docTitle, gstinProblem, templatePill } from "./invoices";

const STATES = { "27": "Maharashtra", "29": "Karnataka" };

describe("gstinProblem", () => {
  it("accepts valid GSTINs and blank", () => {
    expect(gstinProblem("29AAGCB7383J1Z4", STATES)).toBeNull();
    expect(gstinProblem("27aapfu0939f1zv", STATES)).toBeNull();
    expect(gstinProblem("", STATES)).toBeNull();
  });
  it("explains what is wrong", () => {
    expect(gstinProblem("29AAGCB7383J1Z", STATES)).toMatch(/15 characters/);
    expect(gstinProblem("29AAGCB738XJ1Z4", STATES)).toMatch(/format/);
    expect(gstinProblem("98AAGCB7383J1Z4", STATES)).toMatch(/state code/);
    expect(gstinProblem("29AAGCB7383J1Z5", STATES)).toMatch(/last character/);
  });
});

describe("labels", () => {
  it("names documents and states in plain words", () => {
    expect(docTitle({ kind: "invoice", number: "INV/2026-27/0001" })).toBe("INV/2026-27/0001 · Tax invoice");
    expect(docTitle({ kind: "receipt", number: "RCPT/2026-27/0002" })).toBe("RCPT/2026-27/0002 · Payment receipt");
    expect(deliveryPill("read")).toEqual({ label: "Read", tone: "success" });
    expect(deliveryPill("failed").tone).toBe("danger");
    expect(templatePill(null).label).toBe("Not created");
    expect(templatePill("pending").label).toBe("In review at Meta");
  });
});
