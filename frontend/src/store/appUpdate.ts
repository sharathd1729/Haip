/**
 * C2/C3 (perf/auth plan, Workstream C) — tracks whether a new deploy is
 * available so UpdateBanner can prompt the user, instead of the previous
 * behavior of silently force-reloading every open tab the moment a new
 * service worker finished installing.
 */
import { create } from "zustand";

// Holds the actual ServiceWorker reference outside the store -- it's not
// meaningful to serialize/diff as React state, just needs to be reachable
// from applyUpdate().
let waitingWorker: ServiceWorker | null = null;

export function setWaitingWorker(worker: ServiceWorker | null) {
  waitingWorker = worker;
}

interface AppUpdateState {
  updateAvailable: boolean;
  dismissed: boolean;
  setUpdateAvailable: (v: boolean) => void;
  dismiss: () => void;
  applyUpdate: () => void;
}

export const useAppUpdateStore = create<AppUpdateState>((set) => ({
  updateAvailable: false,
  dismissed: false,

  setUpdateAvailable: (v) => set({ updateAvailable: v }),

  dismiss: () => set({ dismissed: true }),

  applyUpdate: () => {
    // Reload is triggered by PWARegister's existing `controllerchange`
    // listener once this new worker actually takes over -- not here
    // directly, since skipWaiting() is async and activation isn't
    // guaranteed to complete synchronously after postMessage.
    if (waitingWorker) {
      waitingWorker.postMessage({ type: "SKIP_WAITING" });
    } else {
      // No waiting worker reference (e.g. update was detected via the
      // build-id.json poll rather than the SW lifecycle) -- a plain reload
      // still picks up the new deploy since the browser will fetch fresh
      // HTML/JS on next navigation regardless.
      window.location.reload();
    }
  },
}));
