"use client";
// Settings > Workspace: the type of business. It picks the segment the whole portal is designed for (lib/segments.ts) and the
// ops pack behind it (backend ops_pack_catalog: checklists, staff duties, message timings). Owner only (PATCH /tenants/me
// refuses anyone else); the page reloads after a change so every screen switches to the new segment at once.
import { useState } from "react";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { Card, CardHeader } from "@/components/ui/kit";
import { BUSINESS_TYPE_OPTIONS, segmentFor } from "@/lib/segments";
import { cn } from "@/lib/utils";

export function BusinessTypeCard({ current }: { current: string | null | undefined }) {
  const owner = useSession().data?.user?.role === "owner";
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const value = picked ?? current ?? "";
  const changed = !!picked && picked !== current;

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api.patch("/tenants/me", { business_type: picked });
      window.location.reload();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Couldn't save the type of business. Try again.");
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Type of business" description="HAIP's screens, words and ops checklists follow it." tone="plain" />
      <div className="space-y-3 px-4 pb-4 sm:px-5">
        <div role="radiogroup" aria-label="Type of business" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {BUSINESS_TYPE_OPTIONS.map(o => {
            const on = value === o.value;
            return (
              <button key={o.value} type="button" role="radio" aria-checked={on} disabled={!owner || busy}
                onClick={() => setPicked(o.value)}
                className={cn("flex min-h-11 items-center gap-2 rounded-xl border px-3 text-left text-[15px] transition-colors disabled:cursor-not-allowed",
                  on ? "border-primary bg-[var(--haip-primary-tint)] font-semibold text-[var(--haip-fg)]"
                     : "border-[var(--haip-border)] text-[var(--haip-fg-2)] enabled:hover:border-primary")}>
                <span aria-hidden>{o.emoji}</span>
                <span className="min-w-0 flex-1">{o.label}</span>
                <span className="text-xs text-[var(--haip-fg-subtle)]">{segmentFor(o.value).unit.many}</span>
              </button>
            );
          })}
        </div>
        {!owner && <p className="text-sm text-[var(--haip-fg-subtle)]">Only the owner can change the type of business.</p>}
        {changed && (
          <p className="text-sm text-[var(--haip-fg-2)]">
            Your {segmentFor(current).unit.many} will be called {segmentFor(picked).unit.many}, and the ops checklists for{" "}
            {BUSINESS_TYPE_OPTIONS.find(o => o.value === picked)?.label.toLowerCase()} are added. Checklists you edited stay as they are.
          </p>
        )}
        {error && <p role="alert" className="text-sm text-[var(--haip-status-danger-fg)]">{error}</p>}
        {owner && (
          <button type="button" onClick={save} disabled={!changed || busy} className="haip-btn-primary min-h-11 px-5 disabled:opacity-50">
            {busy ? "Saving…" : "Save type of business"}
          </button>
        )}
      </div>
    </Card>
  );
}
