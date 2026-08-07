import { QueryClient } from "@tanstack/react-query";
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
// importing the other (Providers still owns mounting <PersistQueryClientProvider>).
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

export const queryPersistOptions = { persister: queryPersister!, maxAge: PERSIST_MAX_AGE_MS };
