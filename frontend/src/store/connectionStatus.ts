/**
 * Tracks whether the API is currently reachable. api.ts flips this to
 * `false` on a network/timeout error (no HTTP response at all -- as opposed
 * to a normal 4xx/5xx) and back to `true` on the next successful response,
 * so ConnectionBanner can tell the user the app is retrying instead of
 * leaving every page stuck on an empty/skeleton state with no explanation
 * during a backend redeploy.
 */
import { create } from "zustand";

interface ConnectionStatusState {
  offline: boolean;
  setOffline: (v: boolean) => void;
}

export const useConnectionStatusStore = create<ConnectionStatusState>((set) => ({
  offline: false,
  setOffline: (v) => set({ offline: v }),
}));
