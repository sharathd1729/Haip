import { afterEach, describe, expect, it, vi } from "vitest";
import { failureMessage, newSubmissionId, submitPublicLead } from "./publicLeads";

const body = {
  kind: "demo" as const, submission_id: "abc12345", name: "Asha", email: "a@b.in", phone: "9845012345",
  company: "Asha Villas", consent: true,
};

afterEach(() => vi.unstubAllGlobals());

describe("submitPublicLead", () => {
  it("is ok only on a 2xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "x", kind: "demo" }), { status: 201 })));
    const r = await submitPublicLead(body);
    expect(r.ok).toBe(true);
    const sent = JSON.parse((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1].body);
    expect(sent.notice_version).toBe("web-v1");
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/v1/public/leads");
  });

  it("never reports success when the route is missing (the old bug)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Not found", { status: 404 })));
    const r = await submitPublicLead(body);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.message).toMatch(/couldn't send/i);
  });

  it("reports a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const r = await submitPublicLead(body);
    expect(r.ok).toBe(false);
  });
});

describe("failureMessage", () => {
  it("explains validation, rate limits and size", () => {
    expect(failureMessage(422, { detail: [{ msg: "Value error, Please enter a valid phone number." }] })).toBe("Please enter a valid phone number.");
    expect(failureMessage(422, { detail: "Unknown privacy notice version." })).toBe("Unknown privacy notice version.");
    expect(failureMessage(429, null)).toMatch(/too many/i);
    expect(failureMessage(413, null)).toMatch(/too long/i);
    expect(failureMessage(500, null)).toMatch(/WhatsApp/);
  });
});

describe("newSubmissionId", () => {
  it("matches the server's id rule and is unique", () => {
    const a = newSubmissionId();
    expect(a).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(newSubmissionId()).not.toBe(a);
  });
});
