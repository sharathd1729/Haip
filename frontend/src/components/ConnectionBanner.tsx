"use client";

import { useEffect } from "react";
import { WifiOff } from "@/lib/icons";
import { useConnectionStatusStore } from "@/store/connectionStatus";
import { queryClient } from "@/lib/queryClient";
import { API_ROOT } from "@/lib/api";

// Pairs with api.ts's response interceptor, which flips `offline` to true
// the moment a request times out / fails with no response (e.g. the API
// container mid-restart during a VPS redeploy) and back to false the moment
// any request succeeds again. That alone only recovers when *something*
// happens to fire a new request -- a user idle on a page with
// refetchOnWindowFocus/refetchOnReconnect both off (see queryClient.ts)
// would otherwise sit on a dead page indefinitely. This polls the
// unauthenticated /health endpoint every few seconds while offline so
// recovery doesn't depend on user action.
export function ConnectionBanner() {
  const offline = useConnectionStatusStore((s) => s.offline);
  const setOffline = useConnectionStatusStore((s) => s.setOffline);

  useEffect(() => {
    if (!offline) return;
    const id = setInterval(async () => {
      try {
        const res = await fetch(`${API_ROOT}/health`, { cache: "no-store" });
        if (res.ok) {
          setOffline(false);
          queryClient.invalidateQueries();
        }
      } catch {
        // still down — keep polling
      }
    }, 4_000);
    return () => clearInterval(id);
  }, [offline, setOffline]);

  if (!offline) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed top-0 inset-x-0 z-50 flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium"
      style={{ background: "#B45309", color: "#fff" }}
    >
      <WifiOff size={14} className="flex-shrink-0 animate-pulse" />
      Trouble reaching HAIP — retrying automatically…
    </div>
  );
}
