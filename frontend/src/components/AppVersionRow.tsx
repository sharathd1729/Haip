"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useAppUpdateStore } from "@/store/appUpdate";

// Reachable, self-serve diagnostic for exactly the class of bug that
// prompted it: an installed PWA silently stuck on a stale build with no
// obvious way for the user (or anyone helping them over the phone) to tell
// "is this the old broken version" or force a check without knowing to dig
// into browser internals. Mounted in both MobileNav's "More" sheet and
// Sidebar's bottom section so it's one tap away regardless of device.
export function AppVersionRow({ dark = false }: { dark?: boolean }) {
  const [version, setVersion] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const updateAvailable = useAppUpdateStore((s) => s.updateAvailable);

  useEffect(() => {
    fetch("/build-id.json", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setVersion(d.version ?? null))
      .catch(() => {});
  }, []);

  async function checkNow() {
    setChecking(true);
    try {
      const reg = await navigator.serviceWorker?.getRegistration();
      await reg?.update();
      // build-id.json is fetched no-store, so this always reflects reality
      const res = await fetch("/build-id.json", { cache: "no-store" });
      const d = await res.json();
      setVersion(d.version ?? null);
    } catch {
      // offline or SW unsupported -- nothing more to do here
    } finally {
      setChecking(false);
    }
  }

  const mutedColor = dark ? "rgba(255,255,255,0.35)" : "var(--haip-sidebar-fg-subtle)";
  const textColor = dark ? "rgba(255,255,255,0.55)" : "var(--haip-sidebar-fg)";

  return (
    <div className="flex items-center justify-between px-2.5 py-1.5 text-[10.5px]" style={{ color: mutedColor }}>
      <span style={{ color: textColor }}>
        {version ? `v${version}` : "…"}
        {updateAvailable && (
          <span className="ml-1.5 font-semibold" style={{ color: "var(--haip-sidebar-accent, #14b8a6)" }}>
            · update ready
          </span>
        )}
      </span>
      <button
        onClick={checkNow}
        disabled={checking}
        className="flex items-center gap-1 font-medium disabled:opacity-50"
        style={{ color: mutedColor }}
      >
        <RefreshCw size={10} className={checking ? "animate-spin" : ""} />
        Check
      </button>
    </div>
  );
}
