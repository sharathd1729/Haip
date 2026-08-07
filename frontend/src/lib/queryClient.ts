import { QueryClient } from "@tanstack/react-query";

// Module-level singleton so api.ts's response interceptor can invalidate
// every query the instant connectivity is restored, without either module
// importing the other (Providers still owns mounting <QueryClientProvider>).
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,          // 1 min — don't refetch if data is fresh
      gcTime: 5 * 60_000,         // 5 min — keep in cache longer
      retry: 1,
      refetchOnWindowFocus: false, // stop the refetch flood on tab switch
      refetchOnReconnect: false,   // don't refetch everything on reconnect
    },
  },
});
