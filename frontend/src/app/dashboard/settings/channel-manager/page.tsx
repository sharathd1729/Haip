"use client";
// Settings > Channel manager (owner / manager, module channel_manager). Connect Channex with an API key, map each HAIP unit
// to a Channex room type (and rate plan), choose which units send prices, and sync now. HAIP's calendar is the source of
// truth: availability goes out every 15 minutes, OTA bookings come back as HAIP bookings (backend services/channex_service.py).
// Backend: GET /channex/status, POST|DELETE /channex/connect, GET /channex/remote, PUT /channex/mappings, POST /channex/sync.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Loader2, RefreshCw } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, EmptyState, PageHeader, StatusPill } from "@/components/ui/kit";

interface Unit {
  property_id: string;
  name: string;
  mapped: boolean;
  channex_property_id: string | null;
  channex_room_type_id: string | null;
  channex_rate_plan_id: string | null;
  push_rates: boolean;
  last_pushed_at: string | null;
  last_push_error: string | null;
}
interface Status { connected: boolean; base_url: string | null; units: Unit[] }
interface Remote {
  properties: { id: string; title: string | null; room_types: { id: string; title: string | null }[];
    rate_plans: { id: string; title: string | null; room_type_id?: string | null }[] }[];
}
type Row = { channex_property_id: string; channex_room_type_id: string; channex_rate_plan_id: string; push_rates: boolean };

const field = "min-h-[44px] w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] outline-none focus-visible:ring-2 focus-visible:ring-primary sm:text-sm";

function detail(e: unknown, fallback: string): string {
  const r = (e as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
  if (r?.status === 403) return "The channel manager is not on this workspace's plan, or you are not an owner or manager.";
  return typeof r?.data?.detail === "string" ? r.data.detail : fallback;
}

function when(iso: string | null): string {
  if (!iso) return "not yet";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 2880 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`;
}

function Connect({ onDone }: { onDone: () => void }) {
  const { toast } = useToast();
  const [key, setKey] = useState("");
  const [base, setBase] = useState("");
  const connect = useMutation({
    mutationFn: () => api.post("/channex/connect", { api_key: key.trim(), base_url: base.trim() || null }).then(r => r.data),
    onSuccess: d => { toast({ variant: "success", title: "Channex connected", description: `${d.channex_properties} properties found.` }); setKey(""); onDone(); },
    onError: e => toast({ variant: "error", title: "Couldn't connect", description: detail(e, "Check the key and try again.") }),
  });
  return (
    <Card>
      <CardHeader title="Connect Channex" description="Create an API key in your Channex user profile and paste it here. HAIP stores it encrypted." tone="plain" />
      <CardBody>
        <form className="grid gap-3" onSubmit={e => { e.preventDefault(); if (key.trim().length >= 8) connect.mutate(); }}>
          <label className="grid gap-1 text-sm font-medium text-[var(--haip-fg)]">API key
            <input className={field} type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} />
          </label>
          <label className="grid gap-1 text-sm font-medium text-[var(--haip-fg)]">Channex address <span className="font-normal text-[var(--haip-fg-subtle)]">(leave empty for the Channex test server; use the production address Channex gives you after certification)</span>
            <input className={field} placeholder="https://staging.channex.io/api/v1" value={base} onChange={e => setBase(e.target.value)} />
          </label>
          <button type="submit" disabled={connect.isPending || key.trim().length < 8}
            className="inline-flex min-h-[44px] w-fit items-center gap-2 rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground disabled:opacity-60">
            {connect.isPending && <Loader2 size={14} className="animate-spin" />} Connect
          </button>
        </form>
      </CardBody>
    </Card>
  );
}

function Mapping({ status }: { status: Status }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const remote = useQuery<Remote>({ queryKey: ["channex-remote"], queryFn: () => api.get("/channex/remote").then(r => r.data), staleTime: 5 * 60_000 });
  const [rows, setRows] = useState<Record<string, Row>>({});
  useEffect(() => {
    setRows(Object.fromEntries(status.units.map(u => [u.property_id, {
      channex_property_id: u.channex_property_id ?? "", channex_room_type_id: u.channex_room_type_id ?? "",
      channex_rate_plan_id: u.channex_rate_plan_id ?? "", push_rates: u.push_rates,
    }])));
  }, [status]);
  const save = useMutation({
    mutationFn: () => api.put("/channex/mappings", {
      mappings: Object.entries(rows).filter(([, r]) => r.channex_room_type_id).map(([property_id, r]) => ({
        property_id, channex_property_id: r.channex_property_id, channex_room_type_id: r.channex_room_type_id,
        channex_rate_plan_id: r.channex_rate_plan_id || null, push_rates: r.push_rates,
      })),
    }).then(r => r.data),
    onSuccess: d => { toast({ variant: "success", title: "Saved", description: `${d.mapped} units mapped.` }); qc.invalidateQueries({ queryKey: ["channex-status"] }); },
    onError: e => toast({ variant: "error", title: "Couldn't save", description: detail(e, "Try again.") }),
  });
  const sync = useMutation({
    mutationFn: () => api.post("/channex/sync"),
    onSuccess: () => { toast({ variant: "success", title: "Syncing", description: "Bookings and availability update in a minute." }); setTimeout(() => qc.invalidateQueries({ queryKey: ["channex-status"] }), 30_000); },
    onError: e => toast({ variant: "error", title: "Couldn't start the sync", description: detail(e, "Try again.") }),
  });
  const rooms = (remote.data?.properties ?? []).flatMap(p => p.room_types.map(r => ({ ...r, property_id: p.id, property: p.title })));
  const plansFor = (pid: string, rt: string) => (remote.data?.properties.find(p => p.id === pid)?.rate_plans ?? [])
    .filter(r => !r.room_type_id || r.room_type_id === rt);

  return (
    <Card>
      <CardHeader title="Units" description="Link each villa or vehicle to its Channex room type. Only units you link are sent to the channels." tone="plain"
        actions={<button type="button" onClick={() => sync.mutate()} disabled={sync.isPending}
          className="inline-flex min-h-[44px] items-center gap-2 rounded-full border border-[var(--haip-border)] px-4 text-sm font-semibold text-[var(--haip-fg)] disabled:opacity-60">
          <RefreshCw size={14} className={sync.isPending ? "animate-spin" : ""} /> Sync now
        </button>} />
      <CardBody>
        {remote.isPending ? <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" /> Reading your Channex properties…</p>
          : remote.isError ? <p className="text-sm text-[var(--haip-fg-muted)]">{detail(remote.error, "Couldn't read Channex. Try again.")}</p>
          : status.units.length === 0 ? <EmptyState title="No units yet" hint="Add your villas or vehicles under Properties first." />
          : (
            <ul className="divide-y divide-[var(--haip-border)]">
              {status.units.map(u => {
                const r = rows[u.property_id] ?? { channex_property_id: "", channex_room_type_id: "", channex_rate_plan_id: "", push_rates: false };
                const set = (patch: Partial<Row>) => setRows(s => ({ ...s, [u.property_id]: { ...r, ...patch } }));
                return (
                  <li key={u.property_id} className="grid gap-2 py-4 md:grid-cols-[1fr_1.4fr_1.2fr_auto] md:items-center">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-[var(--haip-fg)]">{u.name}</p>
                      <p className="text-xs text-[var(--haip-fg-subtle)]">
                        {u.last_push_error ? <StatusPill tone="danger">{u.last_push_error}</StatusPill> : u.mapped ? `Sent ${when(u.last_pushed_at)}` : "Not linked"}
                      </p>
                    </div>
                    <select aria-label={`Channex room type for ${u.name}`} className={field} value={r.channex_room_type_id}
                      onChange={e => { const room = rooms.find(x => x.id === e.target.value); set({ channex_room_type_id: e.target.value, channex_property_id: room?.property_id ?? "", channex_rate_plan_id: "" }); }}>
                      <option value="">Not linked</option>
                      {rooms.map(x => <option key={x.id} value={x.id}>{x.property ? `${x.property} · ` : ""}{x.title ?? x.id}</option>)}
                    </select>
                    <select aria-label={`Channex rate plan for ${u.name}`} className={field} value={r.channex_rate_plan_id} disabled={!r.channex_room_type_id}
                      onChange={e => set({ channex_rate_plan_id: e.target.value })}>
                      <option value="">No rate plan</option>
                      {plansFor(r.channex_property_id, r.channex_room_type_id).map(x => <option key={x.id} value={x.id}>{x.title ?? x.id}</option>)}
                    </select>
                    <label className="flex min-h-[44px] items-center gap-2 text-sm text-[var(--haip-fg)]">
                      <input type="checkbox" role="switch" className="size-5 accent-[var(--primary)]" checked={r.push_rates}
                        disabled={!r.channex_rate_plan_id} onChange={e => set({ push_rates: e.target.checked })} />
                      Send prices
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        <button type="button" onClick={() => save.mutate()} disabled={save.isPending || remote.isPending}
          className="mt-4 inline-flex min-h-[44px] items-center gap-2 rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground disabled:opacity-60">
          {save.isPending && <Loader2 size={14} className="animate-spin" />} Save links
        </button>
      </CardBody>
    </Card>
  );
}

export default function ChannelManagerPage() {
  const { toast } = useToast();
  const qc = useQueryClient();
  const status = useQuery<Status>({ queryKey: ["channex-status"], queryFn: () => api.get("/channex/status").then(r => r.data) });
  const disconnect = useMutation({
    mutationFn: () => api.delete("/channex/connect"),
    onSuccess: () => { toast({ variant: "success", title: "Disconnected" }); qc.invalidateQueries({ queryKey: ["channex-status"] }); },
    onError: e => toast({ variant: "error", title: "Couldn't disconnect", description: detail(e, "Try again.") }),
  });
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-4 px-4 py-6 sm:px-6">
        <PageHeader title="Channel manager" subtitle="Send HAIP's calendar to Airbnb, Booking.com and other channels through Channex, and get their bookings back in HAIP."
          actions={status.data?.connected &&
            <button type="button" onClick={() => { if (window.confirm("Disconnect Channex? Availability stops going to the channels.")) disconnect.mutate(); }}
              className="min-h-[44px] rounded-full border border-[var(--haip-border)] px-4 text-sm font-semibold text-[var(--haip-fg)]">Disconnect</button>} />
        {status.isPending ? <p className="flex items-center gap-2 p-6 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={16} className="animate-spin" /> Loading…</p>
          : status.isError ? (
            <Card><CardBody className="pt-4"><p className="text-sm text-[var(--haip-fg-muted)]">{detail(status.error, "Couldn't load. Refresh to try again.")}</p></CardBody></Card>
          ) : status.data!.connected ? <Mapping status={status.data!} />
          : <Connect onDone={() => qc.invalidateQueries({ queryKey: ["channex-status"] })} />}
      </div>
    </div>
  );
}
