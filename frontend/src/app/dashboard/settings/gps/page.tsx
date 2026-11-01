"use client";
// Settings > GPS trackers (owner / manager). Pick where positions come from, see the webhook address and its secret ONCE,
// and map each tracker to a vehicle. Backend: GET/PUT /ops/gps/settings, POST /ops/gps/settings/rotate-secret,
// /ops/gps/devices (all audited). A tracker HAIP has heard from but nobody mapped shows here as "New tracker".
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Loader2 } from "@/lib/icons";
import { lastSeen, type GpsDevice, type GpsSettings } from "@/lib/gps";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, EmptyState, PageHeader, StatusPill } from "@/components/ui/kit";

interface Vehicle { id: string; name: string }

const input = "min-h-11 w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] sm:text-sm";

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Check your connection and try again.";
}

function minutesSince(iso: string | null): number | null {
  return iso ? Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000)) : null;
}

export default function GpsSettingsPage() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const conn = useQuery<GpsSettings>({ queryKey: ["ops-gps-settings"], queryFn: () => api.get("/ops/gps/settings").then(r => r.data) });
  const devices = useQuery<GpsDevice[]>({ queryKey: ["ops-gps-devices"], queryFn: () => api.get("/ops/gps/devices").then(r => r.data) });
  const vehicles = useQuery<Vehicle[]>({ queryKey: ["properties-min"], queryFn: () => api.get("/properties").then(r => r.data) });
  const [provider, setProvider] = useState("webhook");
  const [baseUrl, setBaseUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [newId, setNewId] = useState("");
  const [newVehicle, setNewVehicle] = useState("");
  useEffect(() => {
    if (!conn.data) return;
    setProvider(conn.data.provider ?? "webhook");
    setBaseUrl(conn.data.base_url ?? "");
    setUsername(conn.data.username ?? "");
  }, [conn.data]);

  const saved = (d: GpsSettings) => {
    qc.setQueryData(["ops-gps-settings"], { ...d, webhook_secret: undefined });
    if (d.webhook_secret) setSecret(d.webhook_secret);
    setPassword("");
  };
  const save = useMutation({
    mutationFn: () => api.put("/ops/gps/settings", provider === "traccar"
      ? { provider, base_url: baseUrl, username: username || null, password: password || null }
      : { provider }).then(r => r.data as GpsSettings),
    onSuccess: d => { saved(d); toast({ variant: "success", title: "Saved · logged" }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: errorText(e) }),
  });
  const rotate = useMutation({
    mutationFn: () => api.post("/ops/gps/settings/rotate-secret").then(r => r.data as GpsSettings),
    onSuccess: d => { saved(d); toast({ variant: "success", title: "New secret made. Update your tracker or app." }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: errorText(e) }),
  });
  const deviceAct = useMutation({
    mutationFn: ({ method, path, body }: { method: "post" | "patch" | "delete"; path: string; body?: object }) =>
      method === "delete" ? api.delete(path) : api[method](path, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ops-gps-devices"] }); qc.invalidateQueries({ queryKey: ["ops-gps-live"] }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: errorText(e) }),
  });

  const info = conn.data?.providers.find(p => p.key === provider);
  const copy = (text: string) => navigator.clipboard?.writeText(text).then(() => toast({ variant: "success", title: "Copied" }));

  return (
    <div className="grid gap-4">
      <PageHeader title="GPS trackers" subtitle="Where vehicle positions come from, and which tracker is in which vehicle." />

      <Card>
        <CardHeader title="Position feed" description="HAIP checks every trip against these positions and raises GPS alerts." />
        <CardBody className="grid gap-3">
          {conn.isPending ? (
            <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" aria-hidden /> Loading…</p>
          ) : conn.isError || !conn.data ? (
            <EmptyState title="Couldn't load the GPS settings" hint="Check your connection and try again."
              action={<button type="button" onClick={() => conn.refetch()} className="haip-btn-primary min-h-11">Try again</button>} />
          ) : (
            <>
              <fieldset className="grid gap-2">
                <legend className="mb-1 text-[14.5px] font-semibold text-[var(--haip-fg)]">Positions come from</legend>
                {conn.data.providers.map(p => (
                  <label key={p.key} className="flex min-h-11 items-start gap-2.5 text-[14.5px] text-[var(--haip-fg)]">
                    <input type="radio" name="gps-provider" className="mt-1 size-5 accent-[var(--primary)]" disabled={!p.enabled}
                      checked={provider === p.key} onChange={() => setProvider(p.key)} />
                    <span>{p.label}{p.blocked_reason && <span className="block text-[13px] text-[var(--haip-fg-subtle)]">{p.blocked_reason}</span>}</span>
                  </label>
                ))}
              </fieldset>

              {provider === "traccar" && (
                <div className="grid gap-2">
                  <label className="grid gap-1 text-[14px] font-semibold">Server address (https)
                    <input className={input} value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://traccar.example.com" inputMode="url" />
                  </label>
                  <label className="grid gap-1 text-[14px] font-semibold">Username (empty = use an API token)
                    <input className={input} value={username} onChange={e => setUsername(e.target.value)} autoComplete="off" />
                  </label>
                  <label className="grid gap-1 text-[14px] font-semibold">Password or API token
                    <input className={input} type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password"
                      placeholder={conn.data.has_password ? "Saved. Type a new one to change it." : ""} />
                  </label>
                </div>
              )}

              {provider === "webhook" && (
                <div className="grid gap-2 rounded-xl border border-[var(--haip-border)] p-3 text-[14px]">
                  <p className="font-semibold">Your tracker or app sends positions to:</p>
                  <code className="break-all rounded-lg bg-[var(--haip-surface)] px-2 py-1.5 text-[13px]">{conn.data.webhook_url}</code>
                  <button type="button" className="haip-btn-secondary min-h-11 justify-self-start" onClick={() => copy(conn.data!.webhook_url)}>Copy address</button>
                  {secret ? (
                    <div className="grid gap-2 rounded-lg border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] p-3">
                      <p className="font-semibold text-[var(--haip-status-warning-fg)]">Signing secret, shown only now. Copy it into your tracker or app.</p>
                      <code className="break-all text-[13px]">{secret}</code>
                      <button type="button" className="haip-btn-secondary min-h-11 justify-self-start" onClick={() => copy(secret)}>Copy secret</button>
                    </div>
                  ) : conn.data.has_webhook_secret ? (
                    <p className="text-[var(--haip-fg-muted)]">A signing secret is saved. It is never shown again; make a new one if it was lost.</p>
                  ) : null}
                  {conn.data.provider === "webhook" && (
                    <button type="button" className="haip-btn-secondary min-h-11 justify-self-start" disabled={rotate.isPending}
                      onClick={() => { if (window.confirm("Make a new secret? The old one stops working at once.")) rotate.mutate(); }}>
                      Make a new secret
                    </button>
                  )}
                </div>
              )}

              {conn.data.last_error && <p className="text-[14px] text-[var(--haip-status-danger-fg)]">Last check failed: {conn.data.last_error}</p>}
              <button type="button" className="haip-btn-primary min-h-12 justify-self-start" disabled={save.isPending || !info?.enabled} onClick={() => save.mutate()}>
                {save.isPending ? "Saving…" : "Save"}
              </button>
            </>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Trackers" description="One tracker per vehicle. Positions from a tracker with no vehicle are not kept." />
        <CardBody className="grid gap-3">
          {devices.isPending ? (
            <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" aria-hidden /> Loading…</p>
          ) : devices.isError || !devices.data ? (
            <EmptyState title="Couldn't load the trackers" hint="Check your connection and try again."
              action={<button type="button" onClick={() => devices.refetch()} className="haip-btn-primary min-h-11">Try again</button>} />
          ) : (
            <>
              {devices.data.length === 0 && <p className="text-[14px] text-[var(--haip-fg-subtle)]">No trackers yet. Add each vehicle&apos;s tracker id (IMEI) below.</p>}
              <ul className="grid gap-2">
                {devices.data.map(d => (
                  <li key={d.id} className="grid gap-2 rounded-xl border border-[var(--haip-border)] p-3 sm:grid-cols-[1fr_auto] sm:items-center">
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-2 text-[15px] font-semibold">
                        <span className="break-all">{d.label || d.external_id}</span>
                        {!d.property_id ? <StatusPill tone="warning">New tracker</StatusPill> : !d.active ? <StatusPill tone="neutral">Paused</StatusPill> : null}
                      </p>
                      <p className="text-[13px] text-[var(--haip-fg-subtle)]">Id {d.external_id} · last position {lastSeen(minutesSince(d.last_seen_at))}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <select aria-label={`Vehicle for tracker ${d.external_id}`} className={input + " sm:w-44"} value={d.property_id ?? ""}
                        onChange={e => deviceAct.mutate({ method: "patch", path: `/ops/gps/devices/${d.id}`,
                          body: { property_id: e.target.value || null, active: Boolean(e.target.value) } })}>
                        <option value="">No vehicle</option>
                        {(vehicles.data ?? []).map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
                      </select>
                      {d.property_id && (
                        <button type="button" className="haip-btn-secondary min-h-11" onClick={() => deviceAct.mutate({
                          method: "patch", path: `/ops/gps/devices/${d.id}`, body: { active: !d.active } })}>
                          {d.active ? "Pause" : "Resume"}
                        </button>
                      )}
                      <button type="button" className="haip-btn-secondary min-h-11" onClick={() => {
                        if (window.confirm("Remove this tracker and its stored positions?")) deviceAct.mutate({ method: "delete", path: `/ops/gps/devices/${d.id}` });
                      }}>Remove</button>
                    </div>
                  </li>
                ))}
              </ul>
              <form className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]" onSubmit={e => {
                e.preventDefault();
                if (!newId.trim()) return;
                deviceAct.mutate({ method: "post", path: "/ops/gps/devices", body: { external_id: newId.trim(), property_id: newVehicle || null, active: true } },
                  { onSuccess: () => { setNewId(""); setNewVehicle(""); } });
              }}>
                <input className={input} value={newId} onChange={e => setNewId(e.target.value)} placeholder="Tracker id (IMEI)" aria-label="Tracker id" />
                <select className={input} value={newVehicle} onChange={e => setNewVehicle(e.target.value)} aria-label="Vehicle">
                  <option value="">Pick a vehicle</option>
                  {(vehicles.data ?? []).map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
                </select>
                <button type="submit" className="haip-btn-primary min-h-11" disabled={!newId.trim() || deviceAct.isPending}>Add tracker</button>
              </form>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
