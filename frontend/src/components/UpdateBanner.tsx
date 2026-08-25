"use client";

import { RefreshCw, X } from "@/lib/icons";
import { useAppUpdateStore } from "@/store/appUpdate";

// C3: bottom-centre toast prompting a reload once PWARegister (C2) detects
// a new deploy -- replaces the previous behavior of silently force-reloading
// every open tab the instant a new service worker finished installing.
export function UpdateBanner() {
  const updateAvailable = useAppUpdateStore((s) => s.updateAvailable);
  const dismissed = useAppUpdateStore((s) => s.dismissed);
  const dismiss = useAppUpdateStore((s) => s.dismiss);
  const applyUpdate = useAppUpdateStore((s) => s.applyUpdate);

  if (!updateAvailable || dismissed) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-3 rounded-lg"
      style={{
        background: "var(--haip-card)",
        border: "1px solid var(--haip-border)",
        boxShadow: "var(--haip-shadow-lg)",
      }}
    >
      <span
        className="flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center"
        style={{ background: "color-mix(in srgb, var(--primary) 12%, transparent)" }}
      >
        <RefreshCw size={13} style={{ color: "var(--primary)" }} />
      </span>

      <div className="min-w-0">
        <p className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>
          A new version of HAIP is available
        </p>
        <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>
          Updates automatically in a few seconds if you're not typing — reload now to do it right away.
        </p>
      </div>

      <button
        onClick={applyUpdate}
        className="flex-shrink-0 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors duration-150"
        style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
      >
        Reload
      </button>

      <button
        onClick={dismiss}
        aria-label="Dismiss"
        className="flex-shrink-0 -ml-1"
        style={{ color: "var(--haip-fg-subtle)" }}
      >
        <X size={14} />
      </button>
    </div>
  );
}
