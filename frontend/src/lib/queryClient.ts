import { QueryClient, defaultShouldDehydrateQuery, type Query } from "@tanstack/react-query";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";

// PWA-blank-data-fix plan, Fix 4: PII scope decision made explicitly by
// Sharath (not defaulted) -- persist everything, wipe on sign-out. New
// dependency justification (CLAUDE.md requires one): this is the official
// TanStack persistence package; hand-rolling cache
// serialization/hydration/versioning ourselves is more code and more bugs
// than the ~3kb official package for the one thing it does.
//
// gcTime must be >= the persister's maxAge (react-query v5 requirement --
// data restored from a persisted snapshot older than gcTime would be
// garbage-collected before ever rendering). 24h matches PERSIST_MAX_AGE_MS
// below; ResumeRevalidator's Fix 3 already quietly refetches on every
// resume regardless, so a same-day-old instant paint is never the final
// state the user sees, just the first one.
const PERSIST_MAX_AGE_MS = 24 * 60 * 60 * 1000;
export const QUERY_PERSIST_STORAGE_KEY = "haip-query-cache";

// Module-level singleton so api.ts's response interceptor can invalidate
// every query the instant connectivity is restored, without either module
// importing the other (Providers restores/persists it after mount).
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,          // 1 min — don't refetch if data is fresh
      gcTime: PERSIST_MAX_AGE_MS, // must be >= persister maxAge, see above
      retry: 1,
      refetchOnWindowFocus: false, // stop the refetch flood on tab switch
      refetchOnReconnect: false,   // don't refetch everything on reconnect
    },
  },
});

// SSR/build-time guard — localStorage doesn't exist outside the browser.
export const queryPersister = typeof window !== "undefined"
  ? createSyncStoragePersister({ storage: window.localStorage, key: QUERY_PERSIST_STORAGE_KEY })
  : undefined;

// Live dashboard numbers are never written to the persisted cache (owner dashboard, 19 Oct 2026). A restored snapshot of
// "today" or "this month" is yesterday's (or another tenant's, on a shared phone) figures under the same key, and on a resumed
// phone it can sit on screen until the refetch lands -- which is how the phone could show zeros the laptop did not. These
// queries always load fresh; everything else keeps the instant-paint behaviour above.
export const NEVER_PERSIST = new Set(["business-overview", "dashboard-overview", "work-queue", "impact-since-haip", "portfolio-calendar"]);

export function shouldPersistQuery(query: Query): boolean {
  const root = Array.isArray(query.queryKey) ? query.queryKey[0] : undefined;
  if (typeof root === "string" && NEVER_PERSIST.has(root)) return false;
  return defaultShouldDehydrateQuery(query);
}

export const queryPersistOptions = {
  persister: queryPersister!,
  maxAge: PERSIST_MAX_AGE_MS,
  // Bumped so snapshots written before this rule (with dashboard numbers in them) are discarded on the next load.
  buster: "dash-2026-10-19",
  dehydrateOptions: { shouldDehydrateQuery: shouldPersistQuery },
};
