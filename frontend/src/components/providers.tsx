"use client";
import { SessionProvider } from "next-auth/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ToastProvider } from "@/components/ui/toast";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,          // 1 min — don't refetch if data is fresh
        gcTime: 5 * 60_000,         // 5 min — keep in cache longer
        retry: 1,
        refetchOnWindowFocus: false, // stop the refetch flood on tab switch
        refetchOnReconnect: false,   // don't refetch everything on reconnect
      },
    },
  }));

  return (
    <SessionProvider>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          {children}
        </ToastProvider>
      </QueryClientProvider>
    </SessionProvider>
  );
}
