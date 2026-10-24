import { describe, it, expect, vi } from "vitest";

vi.mock("@/lib/api", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: null }) }));

import { uploadError } from "./ProfileLibraryTabs";

describe("uploadError", () => {
  it("uses the server's own reason when it sent one", () => {
    expect(uploadError({ response: { status: 400, data: { detail: { message: "Not a photo" } } } })).toBe("Not a photo");
  });
  it("names a proxy size limit (413 with no JSON)", () => {
    expect(uploadError({ response: { status: 413, data: "<html>" } })).toMatch(/^too big for the server's upload limit/);
  });
  it("says the upload never arrived when there is no response", () => {
    expect(uploadError(new Error("Network Error"))).toMatch(/^the upload didn't reach the server/);
  });
});
