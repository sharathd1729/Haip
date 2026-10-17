"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Trash2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { errorMessage, fmtDate } from "@/lib/bookings";

interface Endpoint {
  id: string; url: string; description: string | null; events: string[]; is_active: boolean;
  disabled_reason: string | null; consecutive_failures: number; last_success_at: string | null; last_failure_at: string | null;
}
interface Delivery {
  id: string; event_type: string; status: "pending" | "success" | "failed"; attempts: number;
  response_status: number | null; error: string | null; created_at: string | null; next_attempt_at: string | null;
}
interface ListResponse { endpoints: Endpoint[]; events: { event: string; description: string }[] }

const field = "w-full text-sm border border-[var(--haip-border)] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary";
const DELIVERY_STYLE: Record<string, string> = {
  success: "bg-emerald-50 text-emerald-700 border-emerald-100",
  pending: "bg-amber-50 text-amber-800 border-amber-100",
  failed: "bg-red-50 text-red-700 border-red-100",
};

function Deliveries({ endpoint, canRetry }: { endpoint: Endpoint; canRetry: boolean }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const key = ["webhook-deliveries", endpoint.id];
  const { data, isLoading } = useQuery<{ deliveries: Delivery[] }>({
    queryKey: key,
    queryFn: () => api.get(`/webhook-endpoints/${endpoint.id}/deliveries`).then(r => r.data),
  });
  const retry = useMutation({
    mutationFn: (id: string) => api.post(`/webhook-endpoints/deliveries/${id}/retry`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not retry") }),
  });
  if (isLoading) return <Skeleton className="h-16 rounded-lg" />;
  const rows = data?.deliveries ?? [];
  if (rows.length === 0) return <p className="text-xs text-[var(--haip-fg-subtle)]">Nothing sent to this endpoint yet.</p>;
  return (
    <ul className="divide-y divide-[var(--haip-border)] text-xs">
      {rows.map(d => (
        <li key={d.id} className="py-2 flex items-center gap-2">
          <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-semibold", DELIVERY_STYLE[d.status])}>{d.status}</span>
          <span className="font-mono text-[var(--haip-fg-2)]">{d.event_type}</span>
          <span className="text-[var(--haip-fg-subtle)] truncate">
            {d.response_status ? `HTTP ${d.response_status}` : ""}{d.error ? ` ${d.error}` : ""} · {d.attempts} attempt{d.attempts === 1 ? "" : "s"}
          </span>
          <span className="ml-auto text-[var(--haip-fg-subtle)] whitespace-nowrap">{d.created_at ? new Date(d.created_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : ""}</span>
          {canRetry && d.status !== "success" && (
            <button onClick={() => retry.mutate(d.id)} disabled={retry.isPending} className="font-semibold text-primary hover:underline">Retry</button>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Webhook endpoints: where HAIP sends booking, payment and message events. */
export function WebhooksSection({ isOwner }: { isOwner: boolean }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [secret, setSecret] = useState<{ url: string; secret: string } | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["webhook-endpoints"] });
  const { data, isLoading } = useQuery<ListResponse>({
    queryKey: ["webhook-endpoints"],
    queryFn: () => api.get("/webhook-endpoints").then(r => r.data),
  });

  const create = useMutation({
    mutationFn: () => api.post("/webhook-endpoints", { url: url.trim(), events, description: description.trim() || undefined }),
    onSuccess: res => { setSecret({ url: res.data.url, secret: res.data.secret }); setUrl(""); setDescription(""); setEvents([]); refresh(); },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not add the endpoint") }),
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.patch(`/webhook-endpoints/${id}`, body),
    onSuccess: (res, vars) => {
      refresh();
      if (vars.body.rotate_secret) setSecret({ url: res.data.url, secret: res.data.secret });
    },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not update the endpoint") }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/webhook-endpoints/${id}`),
    onSuccess: () => { refresh(); toast({ variant: "success", title: "Endpoint removed" }); },
  });
  const test = useMutation({
    mutationFn: (id: string) => api.post(`/webhook-endpoints/${id}/test`),
    onSuccess: (res, id) => {
      queryClient.invalidateQueries({ queryKey: ["webhook-deliveries", id] });
      refresh();
      const d = res.data;
      if (d.status === "success") toast({ variant: "success", title: "Your server answered", description: `HTTP ${d.response_status}` });
      else toast({ variant: "error", title: "Your server did not accept the test", description: d.error ?? "No response" });
    },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not send the test") }),
  });

  const toggle = (e: string) => setEvents(cur => (cur.includes(e) ? cur.filter(x => x !== e) : [...cur, e]));
  const copy = (t: string) => navigator.clipboard?.writeText(t).then(
    () => toast({ variant: "success", title: "Copied" }), () => toast({ variant: "error", title: "Could not copy" }));

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-[var(--haip-fg)]">Webhooks</h2>
        <p className="text-xs text-[var(--haip-fg-subtle)]">HAIP calls your server the moment a booking, payment or message changes, so you never have to poll.</p>
      </div>

      {secret && (
        <div className="haip-card p-4 space-y-3 border-amber-200">
          <p className="text-sm font-semibold text-[var(--haip-fg)]">Copy the signing secret now, it won&apos;t be shown again</p>
          <div className="flex gap-2">
            <input readOnly value={secret.secret} onFocus={e => e.currentTarget.select()} className="flex-1 min-w-0 text-xs font-mono bg-[var(--haip-surface)] border border-[var(--haip-border)] rounded-lg px-2.5 py-2" />
            <button onClick={() => copy(secret.secret)} className="flex items-center gap-1 text-xs font-semibold border border-[var(--haip-border)] px-3 rounded-lg hover:bg-[var(--haip-surface)]"><Copy size={12} /> Copy</button>
          </div>
          <p className="text-xs text-[var(--haip-fg-subtle)]">Your server uses it to check that a request really came from HAIP. The documentation shows how.</p>
          <button onClick={() => setSecret(null)} className="text-xs font-semibold text-primary hover:underline">I have saved it</button>
        </div>
      )}

      {isLoading ? <Skeleton className="h-24 rounded-xl" /> : (
        <>
          <div className="haip-card divide-y divide-[var(--haip-border)]">
            {(data?.endpoints ?? []).length === 0 && <p className="p-4 text-sm text-[var(--haip-fg-subtle)]">No webhook endpoints yet.</p>}
            {(data?.endpoints ?? []).map(ep => (
              <div key={ep.id} className="p-4 space-y-2">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-[var(--haip-fg)] break-all">{ep.url}</p>
                    {ep.description && <p className="text-xs text-[var(--haip-fg-subtle)]">{ep.description}</p>}
                  </div>
                  <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap",
                    ep.is_active ? "bg-emerald-50 text-emerald-700 border-emerald-100" : "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-muted)] border-[var(--haip-border)]")}>
                    {ep.is_active ? "Active" : "Off"}
                  </span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {ep.events.map(e => <span key={e} className="text-[11px] font-mono bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-muted)] rounded px-1.5 py-0.5">{e}</span>)}
                </div>
                {ep.disabled_reason && <p className="text-xs text-red-600">{ep.disabled_reason}</p>}
                <p className="text-xs text-[var(--haip-fg-subtle)]">
                  {ep.last_success_at ? `Last success ${fmtDate(ep.last_success_at)}` : "No successful delivery yet"}
                  {ep.consecutive_failures > 0 ? ` · ${ep.consecutive_failures} failed in a row` : ""}
                </p>
                <div className="flex flex-wrap gap-2">
                  {isOwner && ep.is_active && (
                    <button onClick={() => test.mutate(ep.id)} disabled={test.isPending} className="text-xs font-semibold border border-[var(--haip-border)] px-3 py-1.5 rounded-lg hover:bg-[var(--haip-surface)] disabled:opacity-50">
                      {test.isPending && test.variables === ep.id ? "Sending..." : "Send test event"}
                    </button>
                  )}
                  <button onClick={() => setOpen(open === ep.id ? null : ep.id)} className="text-xs font-semibold border border-[var(--haip-border)] px-3 py-1.5 rounded-lg hover:bg-[var(--haip-surface)]">
                    {open === ep.id ? "Hide deliveries" : "Recent deliveries"}
                  </button>
                  {isOwner && (
                    <>
                      <button onClick={() => patch.mutate({ id: ep.id, body: { is_active: !ep.is_active } })} className="text-xs font-semibold border border-[var(--haip-border)] px-3 py-1.5 rounded-lg hover:bg-[var(--haip-surface)]">
                        {ep.is_active ? "Turn off" : "Turn on"}
                      </button>
                      <button
                        onClick={() => { if (confirm("Create a new signing secret? Your server must use the new one straight away.")) patch.mutate({ id: ep.id, body: { rotate_secret: true } }); }}
                        className="text-xs font-semibold border border-[var(--haip-border)] px-3 py-1.5 rounded-lg hover:bg-[var(--haip-surface)]"
                      >
                        New secret
                      </button>
                      <button
                        aria-label="Delete endpoint"
                        onClick={() => { if (confirm("Delete this endpoint and its delivery history?")) remove.mutate(ep.id); }}
                        className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--haip-fg-subtle)] hover:text-red-500 hover:bg-red-50"
                      >
                        <Trash2 size={14} />
                      </button>
                    </>
                  )}
                </div>
                {open === ep.id && <div className="pt-2"><Deliveries endpoint={ep} canRetry={isOwner} /></div>}
              </div>
            ))}
          </div>

          {isOwner && (
            <div className="haip-card p-4 space-y-4">
              <p className="text-sm font-semibold text-[var(--haip-fg)]">Add an endpoint</p>
              <label className="block text-xs font-semibold text-[var(--haip-fg-subtle)]">URL (HTTPS)
                <input className={cn(field, "mt-1")} placeholder="https://ops.example.com/haip-webhook" value={url} onChange={e => setUrl(e.target.value)} />
              </label>
              <label className="block text-xs font-semibold text-[var(--haip-fg-subtle)]">Note (optional)
                <input className={cn(field, "mt-1")} placeholder="e.g. Ratha operations platform" value={description} onChange={e => setDescription(e.target.value)} maxLength={200} />
              </label>
              <fieldset className="space-y-2">
                <legend className="text-xs font-semibold text-[var(--haip-fg-subtle)] mb-1">Send me</legend>
                {(data?.events ?? []).map(e => (
                  <label key={e.event} className="flex items-start gap-2.5 text-sm cursor-pointer">
                    <input type="checkbox" checked={events.includes(e.event)} onChange={() => toggle(e.event)} className="mt-1 h-4 w-4 rounded border-[var(--haip-border-strong)] text-primary focus:ring-primary" />
                    <span><span className="font-mono text-xs text-[var(--haip-fg)]">{e.event}</span><span className="block text-xs text-[var(--haip-fg-subtle)]">{e.description}</span></span>
                  </label>
                ))}
              </fieldset>
              <button
                onClick={() => create.mutate()}
                disabled={!url.trim() || events.length === 0 || create.isPending}
                className="text-sm font-semibold bg-primary hover:bg-primary disabled:opacity-40 text-white px-4 py-2 rounded-lg"
              >
                {create.isPending ? "Adding..." : "Add endpoint"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
