"use client";
import { SessionProvider } from "next-auth/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { ThemeProvider } from "next-themes";
import { ToastProvider } from "@/components/ui/toast";
import { queryClient, queryPersister, queryPersistOptions } from "@/lib/queryClient";

export function Providers({ children }: { children: React.ReactNode }) {
  // queryPersister is only created client-side (localStorage doesn't exist
  // during Next's server render pass) -- fall back to the plain provider
  // for that one SSR pass; the client bundle re-evaluates queryClient.ts
  // fresh after hydration, where the persister is always available.
  const content = (
    <SessionProvider>
      <ToastProvider>
        {children}
      </ToastProvider>
    </SessionProvider>
  );

  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      storageKey="haip_color_scheme"
    >
      {queryPersister ? (
        <PersistQueryClientProvider client={queryClient} persistOptions={queryPersistOptions}>
          {content}
        </PersistQueryClientProvider>
      ) : (
        <QueryClientProvider client={queryClient}>
          {content}
        </QueryClientProvider>
      )}
    </ThemeProvider>
  );
}
