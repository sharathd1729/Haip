"use client";
import { useEffect } from "react";
import { SessionProvider } from "next-auth/react";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  persistQueryClientRestore,
  persistQueryClientSubscribe,
} from "@tanstack/react-query-persist-client";
import { ThemeProvider } from "next-themes";
import { ToastProvider } from "@/components/ui/toast";
import { queryClient, queryPersister, queryPersistOptions } from "@/lib/queryClient";

export function Providers({ children }: { children: React.ReactNode }) {
  // Restore + persist the query cache after mount instead of through
  // <PersistQueryClientProvider>. That provider marks every query
  // "restoring" on the client's first render (fetchStatus "idle", so
  // isLoading is false), while the server render has no persister and
  // reports isLoading true. Pages that branch on isLoading then rendered a
  // skeleton on the server and an empty state on the client: React #418
  // (hydration mismatch) on most dashboard pages. With one plain provider
  // in both renders, the first client render matches the server; the cached
  // snapshot is hydrated a tick later (hydrate() keeps an in-flight fetch's
  // status), so the PWA instant paint from cache still happens.
  useEffect(() => {
    if (!queryPersister) return;
    const options = { ...queryPersistOptions, queryClient };
    let cancelled = false;
    let unsubscribe: (() => void) | undefined;
    persistQueryClientRestore(options)
      .catch((err) => {
        // The restore helper has already discarded the unreadable snapshot.
        console.warn("[query-cache] restore failed; starting with an empty cache", err);
      })
      .finally(() => {
        if (!cancelled) unsubscribe = persistQueryClientSubscribe(options);
      });
    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, []);

  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      storageKey="haip_color_scheme"
    >
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <ToastProvider>
            {children}
          </ToastProvider>
        </SessionProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
