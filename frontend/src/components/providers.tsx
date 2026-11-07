"use client";
import { useEffect } from "react";
import { SessionProvider, useSession } from "next-auth/react";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  persistQueryClientRestore,
  persistQueryClientSubscribe,
} from "@tanstack/react-query-persist-client";
import { ThemeProvider } from "next-themes";
import { ToastProvider } from "@/components/ui/toast";
import { queryClient, queryPersister, queryPersistOptions, CACHE_OWNER_KEY } from "@/lib/queryClient";
import { clearTokenCache } from "@/lib/api";

/** Restores the persisted query cache only for the account that saved it. Runs inside SessionProvider so the signed-in
 *  account is known first: Ratha's snapshot is wiped, never painted, when Jade signs in on the same device. */
export function PersistedCache() {
  const { data: session, status } = useSession();
  const user = session?.user as { id?: string; tenantId?: string } | undefined;
  const owner = user?.id ? `${user.tenantId ?? ""}:${user.id}` : "";
  // Restore + persist after mount instead of through <PersistQueryClientProvider>. That provider marks every query
  // "restoring" on the client's first render while the server render reports isLoading true, so pages that branch on
  // isLoading hit React #418 (hydration mismatch). The snapshot is hydrated a tick later instead (hydrate() keeps an
  // in-flight fetch's status), so the PWA instant paint from cache still happens.
  useEffect(() => {
    if (!queryPersister || status !== "authenticated" || !owner) return;
    let saved: string | null = null;
    try { saved = window.localStorage.getItem(CACHE_OWNER_KEY); } catch { /* storage unavailable */ }
    if (saved !== owner) {
      clearTokenCache();   // another account's data: memory, snapshot and saved theme go
      try { window.localStorage.setItem(CACHE_OWNER_KEY, owner); } catch { /* storage unavailable */ }
    }
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
  }, [status, owner]);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      storageKey="haip_color_scheme"
    >
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <PersistedCache />
          <ToastProvider>
            {children}
          </ToastProvider>
        </SessionProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
