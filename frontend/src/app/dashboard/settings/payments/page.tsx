"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy } from "@/lib/icons";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/ui/page";
import { errorMessage } from "@/lib/bookings";

interface Status { connected: boolean; mode?: string; key_id_hint?: string; webhook_url?: string | null; events?: string[]; warning?: string }
interface ConnectResult { mode: string; webhook_url: string | null; webhook_secret: string; events: string[]; warning?: string }
interface ReconcileResult { checked?: number; recorded?: number; skipped?: string; error?: number }

const input = "w-full text-sm border border-[var(--haip-border)] rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary";

function CopyField({ label, value }: { label: string; value: string }) {
  const { toast } = useToast();
  return (
    <div>
      <p className="text-xs font-semibold text-[var(--haip-fg-subtle)] mb-1">{label}</p>
      <div className="flex gap-2">
        <input readOnly value={value} onFocus={e => e.currentTarget.select()} className="flex-1 min-w-0 text-xs font-mono bg-[var(--haip-surface)] border border-[var(--haip-border)] rounded-lg px-2.5 py-2 text-[var(--haip-fg-2)]" />
        <button
          onClick={() => navigator.clipboard?.writeText(value).then(() => toast({ variant: "success", title: "Copied" }), () => toast({ variant: "error", title: "Could not copy" }))}
          className="flex items-center gap-1 text-xs font-semibold border border-[var(--haip-border)] px-3 rounded-lg hover:bg-[var(--haip-surface)]"
        >
          <Copy size={12} /> Copy
        </button>
      </div>
    </div>
  );
}

export default function PaymentsSettingsPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [keyId, setKeyId] = useState("");
  const [keySecret, setKeySecret] = useState("");
  const [fresh, setFresh] = useState<ConnectResult | null>(null);

  const { data, isLoading } = useQuery<Status>({
    queryKey: ["razorpay-status"],
    queryFn: () => api.get("/payments/razorpay").then(r => r.data),
  });

  const connect = useMutation({
    mutationFn: () => api.post<ConnectResult>("/payments/razorpay/connect", { key_id: keyId.trim(), key_secret: keySecret.trim() }),
    onSuccess: res => {
      setFresh(res.data); setKeySecret(""); setKeyId("");
      queryClient.invalidateQueries({ queryKey: ["razorpay-status"] });
    },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not connect Razorpay") }),
  });
  const reconcile = useMutation({     // asks Razorpay about open links now; the server also does this every 10 minutes
    mutationFn: () => api.post<ReconcileResult>("/payments/razorpay/reconcile").then(r => r.data),
    onSuccess: r => toast(r.skipped ? { variant: "error", title: r.skipped }
      : { variant: "success", title: r.recorded ? `${r.recorded} payment${r.recorded === 1 ? "" : "s"} recorded` : "No new payments",
          description: `Checked ${r.checked ?? 0} open payment link${r.checked === 1 ? "" : "s"}.${r.error ? ` ${r.error} could not be checked.` : ""}` }),
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not check payments") }),
  });

  const disconnect = useMutation({
    mutationFn: () => api.delete("/payments/razorpay"),
    onSuccess: () => { setFresh(null); queryClient.invalidateQueries({ queryKey: ["razorpay-status"] }); toast({ variant: "success", title: "Razorpay disconnected" }); },
  });

  const connected = !!data?.connected;
  const webhookUrl = fresh?.webhook_url ?? data?.webhook_url;
  const events = fresh?.events ?? data?.events ?? [];
  const warning = fresh?.warning ?? data?.warning;

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <PageHeader title="Payments" subtitle="Collect booking payments online with your own Razorpay account" />

      {isLoading ? <Skeleton className="h-40 rounded-xl" /> : (
        <>
          {connected && (
            <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-100 rounded-xl px-4 py-3 text-sm text-emerald-900">
              <CheckCircle2 size={16} className="text-emerald-600" />
              <span>Connected to Razorpay ({data?.mode} mode, key ending {data?.key_id_hint}).</span>
              <button onClick={() => { if (confirm("Disconnect Razorpay? Existing payment links stop updating bookings.")) disconnect.mutate(); }}
                className="ml-auto text-xs font-semibold text-red-700 hover:underline">Disconnect</button>
            </div>
          )}

          {connected && warning && (
            <p role="alert" className="rounded-xl border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-4 py-3 text-sm text-[var(--haip-status-warning-fg)]">{warning}</p>
          )}

          {connected && (
            <div className="haip-card p-4 flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-[var(--haip-fg-2)]">Paid but the booking still says unpaid? HAIP checks Razorpay every 10 minutes; check now to update it at once.</p>
              <button type="button" onClick={() => reconcile.mutate()} disabled={reconcile.isPending}
                className="min-h-11 text-sm font-semibold border border-[var(--haip-border)] px-4 rounded-xl hover:bg-[var(--haip-surface)] disabled:opacity-50">
                {reconcile.isPending ? "Checking..." : "Check payments now"}
              </button>
            </div>
          )}

          {fresh && (
            <div className="haip-card p-4 space-y-3 border-amber-200">
              <p className="text-sm font-semibold text-[var(--haip-fg)]">One more step: add the webhook in Razorpay</p>
              <ol className="text-xs text-[var(--haip-fg-muted)] list-decimal pl-4 space-y-1">
                <li>Open Razorpay Dashboard, then Account &amp; Settings, then Webhooks, then Add New Webhook.</li>
                <li>Paste the URL and secret below. Tick these events: {events.join(", ")}.</li>
                <li>Save. Payments made through a HAIP link will then appear on the booking by themselves.</li>
              </ol>
              {fresh.webhook_url && <CopyField label="Webhook URL" value={fresh.webhook_url} />}
              <CopyField label="Webhook secret (shown only now)" value={fresh.webhook_secret} />
            </div>
          )}

          {connected && !fresh && webhookUrl && (
            <div className="haip-card p-4 space-y-3">
              <p className="text-sm font-semibold text-[var(--haip-fg)]">Webhook</p>
              <CopyField label="Webhook URL" value={webhookUrl} />
              <p className="text-xs text-[var(--haip-fg-subtle)]">The secret was shown once when you connected. To get a new one, connect again with your keys.</p>
            </div>
          )}

          <div className="haip-card p-4 space-y-3">
            <p className="text-sm font-semibold text-[var(--haip-fg)]">{connected ? "Replace keys" : "Connect Razorpay"}</p>
            <p className="text-xs text-[var(--haip-fg-subtle)]">
              In Razorpay Dashboard open Account &amp; Settings, then API Keys, and generate a key. Use test keys (rzp_test_...) to try it first.
              Money goes straight to your Razorpay account, never through HAIP.
            </p>
            <label className="block text-xs font-semibold text-[var(--haip-fg-subtle)]">Key ID
              <input className={`${input} mt-1`} placeholder="rzp_live_..." value={keyId} onChange={e => setKeyId(e.target.value)} autoComplete="off" />
            </label>
            <label className="block text-xs font-semibold text-[var(--haip-fg-subtle)]">Key Secret
              <input className={`${input} mt-1`} type="password" value={keySecret} onChange={e => setKeySecret(e.target.value)} autoComplete="new-password" />
            </label>
            <button
              onClick={() => connect.mutate()}
              disabled={!keyId.trim() || !keySecret.trim() || connect.isPending}
              className="text-sm font-semibold bg-primary hover:bg-primary disabled:opacity-40 text-white px-4 py-2 rounded-xl"
            >
              {connect.isPending ? "Checking keys..." : connected ? "Verify and replace" : "Verify and connect"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
