import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, cleanup } from "@testing-library/react";

const session = vi.hoisted(() => ({ current: { status: "authenticated", data: { user: { id: "u-jade", tenantId: "t-jade" } } } }));
vi.mock("next-auth/react", () => ({ useSession: () => session.current, SessionProvider: ({ children }: { children: unknown }) => children }));
vi.mock("@tanstack/react-query-persist-client", () => ({
  persistQueryClientRestore: () => Promise.resolve(),
  persistQueryClientSubscribe: () => () => {},
}));

import { PersistedCache } from "./providers";
import { CACHE_OWNER_KEY, QUERY_PERSIST_STORAGE_KEY } from "@/lib/queryClient";

beforeEach(() => { cleanup(); window.localStorage.clear(); });

describe("PersistedCache: one device, two workspaces", () => {
  it("wipes another account's snapshot and saved theme before restoring", () => {
    window.localStorage.setItem(CACHE_OWNER_KEY, "t-ratha:u-ratha");
    window.localStorage.setItem(QUERY_PERSIST_STORAGE_KEY, '{"ratha":"guests"}');
    window.localStorage.setItem("haip_brand_theme", '{"name":"ratha"}');
    render(<PersistedCache />);
    expect(window.localStorage.getItem(QUERY_PERSIST_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem("haip_brand_theme")).toBeNull();
    expect(window.localStorage.getItem(CACHE_OWNER_KEY)).toBe("t-jade:u-jade");
  });

  it("keeps the snapshot when the same account signs back in", () => {
    window.localStorage.setItem(CACHE_OWNER_KEY, "t-jade:u-jade");
    window.localStorage.setItem(QUERY_PERSIST_STORAGE_KEY, '{"jade":"guests"}');
    render(<PersistedCache />);
    expect(window.localStorage.getItem(QUERY_PERSIST_STORAGE_KEY)).toBe('{"jade":"guests"}');
  });
});
