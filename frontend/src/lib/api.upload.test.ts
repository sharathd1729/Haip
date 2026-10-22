// File uploads through lib/api.ts: the instance defaults to JSON, which made axios turn a FormData body into JSON, so the
// API never received the file and answered "Field required" (invoice logo, 22 Oct 2026). Uploads must arrive as FormData.
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { InternalAxiosRequestConfig } from "axios";

vi.mock("next-auth/react", () => ({ getSession: () => Promise.resolve({ accessToken: "t" }), signOut: vi.fn() }));

import api, { clearTokenCache } from "./api";

let seen: InternalAxiosRequestConfig | null = null;

beforeEach(() => {
  clearTokenCache();
  seen = null;
  api.defaults.adapter = async (config) => {
    seen = config;
    return { data: {}, status: 200, statusText: "OK", headers: {}, config };
  };
});

describe("api uploads", () => {
  it("sends a FormData body as FormData, not JSON, even without an explicit header", async () => {
    const body = new FormData();
    body.append("file", new Blob(["png"], { type: "image/png" }), "logo.png");
    await api.post("/settings/invoice-profile/logo", body);
    expect(seen?.data).toBeInstanceOf(FormData);
    expect(String(seen?.headers.get("Content-Type") ?? "")).not.toContain("application/json");
  });

  it("keeps an explicit multipart header and leaves JSON bodies alone", async () => {
    const body = new FormData();
    body.append("file", new Blob(["x"]), "a.txt");
    await api.post("/knowledge/upload", body, { headers: { "Content-Type": "multipart/form-data" } });
    expect(seen?.data).toBeInstanceOf(FormData);

    await api.post("/leads", { name: "A" });
    expect(seen?.data).toBe(JSON.stringify({ name: "A" }));
    expect(String(seen?.headers.get("Content-Type"))).toContain("application/json");
  });
});
