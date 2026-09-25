"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { AlertCircle, CheckCircle2, Loader2, RefreshCw } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface Check { key: string; status: "ok" | "warn" | "fail"; title: string; detail: string; fix: string | null }
interface Health {
  status: "ok" | "warn" | "fail"; checks: Check[]; webhook_url: string; suggested_waba_id?: string | null;
  facts: { last_inbound_at?: string | null; stuck_sent?: number };
}

const TONE = {
  fail: { box: "border-red-200 bg-red-50/60", icon: "text-red-600", head: "text-red-800" },
  warn: { box: "border-amber-200 bg-amber-50/60", icon: "text-amber-600", head: "text-amber-800" },
  ok: { box: "border-green-200 bg-green-50/50", icon: "text-green-600", head: "text-green-800" },
} as const;

/** Can Meta tell us about replies and delivery? Silent when everything is fine. */
export function WhatsAppHealthCard() {
  const useWaba = useMutation({
    mutationFn: (wabaId: string) => api.post("/messaging/whatsapp/use-waba", { waba_id: wabaId }),
    onSuccess: () => refetch(),
  });
  const { data, isLoading, isFetching, refetch, isError } = useQuery<Health>({
    queryKey: ["wa-health"],
    queryFn: () => api.get("/messaging/whatsapp/health").then(r => r.data),
    staleTime: 60_000,
    retry: false,
  });

  if (isError) return null;                       // the health check is advisory; never block the page
  if (isLoading) {
    return <p className="text-xs text-[var(--haip-fg-muted)] flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" /> Checking the WhatsApp connection…</p>;
  }
  if (!data) return null;

  if (data.status === "ok") {
    return (
      <p className="text-xs text-green-700 flex items-center gap-1.5">
        <CheckCircle2 size={13} /> Replies and delivery updates are coming through.
        <button onClick={() => refetch()} className="text-[var(--haip-fg-muted)] hover:underline ml-1">Check again</button>
      </p>
    );
  }

  const tone = TONE[data.status];
  const problems = data.checks.filter(c => c.status !== "ok");
  return (
    <section className={cn("rounded-2xl border p-4", tone.box)} role="alert" aria-label="WhatsApp connection needs attention">
      <div className="flex items-start gap-3">
        <AlertCircle size={20} className={cn("mt-0.5 flex-shrink-0", tone.icon)} />
        <div className="min-w-0 flex-1">
          <h3 className={cn("text-sm font-semibold", tone.head)}>
            {data.status === "fail" ? "WhatsApp replies and delivery updates aren't reaching you" : "WhatsApp needs a look"}
          </h3>
          <p className="text-xs text-[var(--haip-fg-2)] mt-0.5">
            Messages can still go out, but guests' replies and “delivered / read” marks can be lost until this is fixed.
          </p>
          <ul className="mt-3 space-y-3">
            {problems.map(c => (
              <li key={c.key} className="text-xs">
                <p className="font-semibold text-[var(--haip-fg)]">{c.title}</p>
                <p className="text-[var(--haip-fg-2)] mt-0.5 leading-snug">{c.detail}</p>
                {c.fix && <p className="mt-1 text-[var(--haip-fg)] leading-snug"><strong>Fix:</strong> {c.fix}</p>}
              </li>
            ))}
          </ul>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {data.suggested_waba_id && (
              <button onClick={() => useWaba.mutate(data.suggested_waba_id as string)} disabled={useWaba.isPending}
                className="text-xs font-semibold bg-teal-500 text-white px-3 py-1.5 rounded-lg hover:bg-teal-600 disabled:opacity-60">
                {useWaba.isPending ? "Saving…" : `Use account ${data.suggested_waba_id}`}
              </button>
            )}
            {useWaba.isError && <span className="text-xs text-red-700">Couldn&apos;t save that ID. Try Settings instead.</span>}
            <Link href="/dashboard/settings/integrations" className="text-xs font-semibold bg-teal-500 text-white px-3 py-1.5 rounded-lg hover:bg-teal-600">Open WhatsApp settings</Link>
            <button onClick={() => refetch()} disabled={isFetching}
              className="flex items-center gap-1.5 text-xs font-medium border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-1.5 rounded-lg hover:bg-[var(--haip-surface)] disabled:opacity-60">
              {isFetching ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Check again
            </button>
          </div>
          <p className="mt-3 text-[10px] text-[var(--haip-fg-muted)] break-all">Meta should call: <span className="font-mono">{data.webhook_url}</span></p>
        </div>
      </div>
    </section>
  );
}
