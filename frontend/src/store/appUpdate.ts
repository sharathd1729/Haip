/**
 * C2/C3 (perf/auth plan, Workstream C) — tracks whether a new deploy is
 * available so UpdateBanner can prompt the user, instead of the previous
 * behavior of silently force-reloading every open tab the moment a new
 * service worker finished installing.
 *
 * A dismissible banner alone left installed PWAs stuck indefinitely on a
 * stale bundle if a user never noticed/acted on it -- confirmed live: a
 * mobile home-screen install kept rendering "no calls, no conversations"
 * (an old shell that had drifted off whatever the current backend
 * contract expects) while the exact same account in a normal mobile
 * browser tab, always network-fresh, worked fine. Reopening a PWA is
 * inherently a safe moment to refresh -- there's no in-progress typing to
 * interrupt right after launch -- so an update detected then gets applied
 * automatically after a short grace window, with a live-typing guard so
 * a user composing a reply is never interrupted mid-keystroke the way the
 * original unconditional skipWaiting()+reload was.
 */
import { create } from "zustand";

const AUTO_APPLY_GRACE_MS = 4_000;
const AUTO_APPLY_RECHECK_MS = 5_000;

function isActivelyTyping(): boolean {
  const el = typeof document !== "undefined" ? document.activeElement : null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || (el as HTMLElement).isContentEditable === true;
}

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

let autoApplyTimer: ReturnType<typeof setTimeout> | null = null;

export const useAppUpdateStore = create<AppUpdateState>((set, get) => ({
  updateAvailable: false,
  dismissed: false,

  setUpdateAvailable: (v) => {
    set({ updateAvailable: v });
    if (v && autoApplyTimer === null) {
      const attempt = () => {
        autoApplyTimer = null;
        if (!get().updateAvailable) return; // applied/cleared by some other path already
        if (isActivelyTyping()) {
          autoApplyTimer = setTimeout(attempt, AUTO_APPLY_RECHECK_MS);
          return;
        }
        get().applyUpdate();
      };
      autoApplyTimer = setTimeout(attempt, AUTO_APPLY_GRACE_MS);
    }
    if (!v && autoApplyTimer !== null) {
      clearTimeout(autoApplyTimer);
      autoApplyTimer = null;
    }
  },

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
