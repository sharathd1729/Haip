"use client";
// Ops Fleet: one card per vehicle (papers with expiry, open defects, services by date or km, stock kept on board). One read,
// GET /ops/fleet (ops_fleet_view); every add or change posts to /ops/fleet/... and the server answers with the fresh cards.
// A critical defect keeps the vehicle off sale and stops Dispatch until a manager marks it fixed.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useHydrated } from "@/lib/bookingAgenda";
import { canManageOps, canWriteOps, VEHICLE_PAPERS, type FleetCardData } from "@/lib/ops";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, EmptyState, PageHeader } from "@/components/ui/kit";
import { OpsNav } from "@/components/ops/OpsNav";
import { FleetCard, type FleetAction } from "@/components/ops/FleetCard";
import { input, label, Shell } from "@/components/ops/TripSheets";

type Sheet = { kind: "paper" | "defect" | "service" | "stock"; propertyId: string } | { kind: "close_defect"; id: string; title: string } | null;

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Check your connection and try again.";
}

export default function OpsFleetPage() {
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const { toast } = useToast();
  const role = useSession().data?.user?.role;
  const [sheet, setSheet] = useState<Sheet>(null);
  const [f, setF] = useState<Record<string, string>>({});
  const [file, setFile] = useState<File | null>(null);
  const set = (k: string) => (e: { target: { value: string } }) => setF(p => ({ ...p, [k]: e.target.value }));

  const { data, isPending, isError, refetch } = useQuery<FleetCardData[]>({
    queryKey: ["ops-fleet"], queryFn: () => api.get("/ops/fleet").then(r => r.data), staleTime: 30_000,
  });
  const act = useMutation({
    mutationFn: async ({ method, path, body }: { method: "post" | "patch"; path: string; body?: object }) =>
      (await (method === "patch" ? api.patch(path, body ?? {}) : api.post(path, body ?? {}))).data,
    onSuccess: res => {
      if (Array.isArray(res)) qc.setQueryData(["ops-fleet"], res);
      else qc.invalidateQueries({ queryKey: ["ops-fleet"] });
      qc.invalidateQueries({ queryKey: ["ops-today"] });
    },
  });
  const run = async (method: "post" | "patch", path: string, body?: object, done = "Saved") => {
    try { const res = await act.mutateAsync({ method, path, body }); toast({ title: done, variant: "success" }); return res; }
    catch (e) { toast({ title: "Not saved", description: errorText(e), variant: "error" }); return null; }
  };
  const open = (s: Sheet) => { setF(s?.kind === "paper" ? { kind: "insurance" } : s?.kind === "defect" ? { severity: "normal" } : {}); setFile(null); setSheet(s); };
  const close = () => setSheet(null);

  const onAction = async (a: FleetAction) => {
    if (a.kind === "count") await run("patch", `/ops/fleet/inventory/${a.id}`, { count: a.count }, "Count saved");
    else if (a.kind === "service_done") await run("post", `/ops/fleet/services/${a.id}/done`, {}, "Service marked done");
    else if (a.kind === "view_paper") {
      try { window.open((await api.get(`/ops/fleet/papers/${a.id}/file`)).data.url, "_blank", "noopener"); }
      catch (e) { toast({ title: "Couldn't open the file", description: errorText(e), variant: "error" }); }
    } else open(a);
  };

  const submitPaper = async (propertyId: string) => {
    const res = await run("post", "/ops/fleet/papers", {
      property_id: propertyId, kind: f.kind, number: f.number || undefined, expires_on: f.expires_on || undefined,
      name: f.kind === "other" ? f.name || undefined : undefined,
    }, "Paper saved");
    if (!res) return;
    if (file) {
      const form = new FormData();
      form.append("file", file);
      try { await api.post(`/ops/fleet/papers/${res.id}/file`, form); }
      catch (e) { toast({ title: "Paper saved, file not uploaded", description: errorText(e), variant: "error" }); }
    }
    qc.invalidateQueries({ queryKey: ["ops-fleet"] });
    close();
  };
  const done = async (p: Promise<unknown>) => { if (await p) close(); };

  const write = canWriteOps(role), manage = canManageOps(role);
  const busy = act.isPending;
  const s = sheet;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5 p-4 sm:p-6">
      <PageHeader title="Fleet" subtitle="Papers, defects, services and what is on board, per vehicle" />
      <OpsNav />
      {!hydrated || isPending ? (
        <div className="grid gap-3 md:grid-cols-2" aria-busy="true"><Skeleton className="h-80" /><Skeleton className="h-80" /></div>
      ) : isError || !data ? (
        <Card><EmptyState title="Couldn't load the fleet" hint="Check your connection, then try again."
          action={<button type="button" className="haip-btn-primary min-h-12" onClick={() => refetch()}>Try again</button>} /></Card>
      ) : data.length === 0 ? (
        <Card><EmptyState title="No vehicles yet" hint="Add your vehicles as properties first; they show up here." /></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {data.map(v => <FleetCard key={v.property_id} v={v} canWrite={write} canManage={manage} busy={busy} onAction={onAction} />)}
        </div>
      )}

      <Shell open={s?.kind === "paper"} onClose={close} title="Add or renew a paper" busy={busy} submitLabel="Save paper"
        description="A new paper replaces the old one of the same kind."
        onSubmit={() => s?.kind === "paper" && submitPaper(s.propertyId)}>
        <label className={label}>Which paper
          <select className={input} value={f.kind ?? "insurance"} onChange={set("kind")}>
            {Object.entries(VEHICLE_PAPERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {f.kind === "other" && <label className={label}>Name<input className={input} required value={f.name ?? ""} onChange={set("name")} /></label>}
        <label className={label}>Number (optional)<input className={input} value={f.number ?? ""} onChange={set("number")} /></label>
        <label className={label}>Valid until<input className={input} type="date" value={f.expires_on ?? ""} onChange={set("expires_on")} /></label>
        <label className={label}>Photo or PDF (optional, up to 5 MB)
          <input className={input} type="file" accept="image/jpeg,image/png,image/webp,application/pdf"
            onChange={e => setFile(e.target.files?.[0] ?? null)} />
        </label>
      </Shell>

      <Shell open={s?.kind === "defect"} onClose={close} title="Report a defect" busy={busy} submitLabel="Report"
        description="Critical = the vehicle cannot leave and is taken off sale until it is fixed."
        onSubmit={() => s?.kind === "defect" && done(run("post", "/ops/fleet/defects",
          { property_id: s.propertyId, title: f.title, detail: f.detail || undefined, severity: f.severity }, "Defect reported"))}>
        <label className={label}>What is wrong<input className={input} required value={f.title ?? ""} onChange={set("title")} placeholder="AC not cooling" /></label>
        <label className={label}>More detail (optional)<input className={input} value={f.detail ?? ""} onChange={set("detail")} /></label>
        <label className={label}>How bad
          <select className={input} value={f.severity ?? "normal"} onChange={set("severity")}>
            <option value="normal">Minor: fix when the vehicle is free</option>
            <option value="critical">Critical: must not leave</option>
          </select>
        </label>
      </Shell>

      <Shell open={s?.kind === "close_defect"} onClose={close} title={s?.kind === "close_defect" ? `Fixed: ${s.title}` : ""} busy={busy}
        submitLabel="It is fixed" description="The vehicle goes back on sale and can be dispatched again."
        onSubmit={() => s?.kind === "close_defect" && done(run("post", `/ops/fleet/defects/${s.id}/close`, { note: f.note || undefined }, "Defect closed"))}>
        <label className={label}>What was done (optional)<input className={input} value={f.note ?? ""} onChange={set("note")} /></label>
      </Shell>

      <Shell open={s?.kind === "service"} onClose={close} title="Plan a service" busy={busy} submitLabel="Add service"
        description="Due by date, by odometer km, or both: whichever comes first."
        onSubmit={() => s?.kind === "service" && done(run("post", "/ops/fleet/services", {
          property_id: s.propertyId, name: f.name, due_on: f.due_on || undefined, due_km: f.due_km ? Number(f.due_km) : undefined,
        }, "Service added"))}>
        <label className={label}>What<input className={input} required value={f.name ?? ""} onChange={set("name")} placeholder="Engine oil and filters" /></label>
        <label className={label}>Due date<input className={input} type="date" value={f.due_on ?? ""} onChange={set("due_on")} /></label>
        <label className={label}>Due at odometer (km)<input className={input} inputMode="numeric" pattern="[0-9]*" value={f.due_km ?? ""} onChange={set("due_km")} /></label>
      </Shell>

      <Shell open={s?.kind === "stock"} onClose={close} title="Something kept on board" busy={busy} submitLabel="Add item"
        description="Below the level you keep = a restock reminder on Ops today."
        onSubmit={() => s?.kind === "stock" && done(run("post", "/ops/fleet/inventory", {
          property_id: s.propertyId, name: f.name, par: Number(f.par || 0), count: f.count ? Number(f.count) : undefined,
        }, "Item added"))}>
        <label className={label}>Item<input className={input} required value={f.name ?? ""} onChange={set("name")} placeholder="Towels" /></label>
        <label className={label}>Keep on board<input className={input} required inputMode="numeric" pattern="[0-9]*" value={f.par ?? ""} onChange={set("par")} /></label>
        <label className={label}>On board now (optional)<input className={input} inputMode="numeric" pattern="[0-9]*" value={f.count ?? ""} onChange={set("count")} /></label>
      </Shell>
    </div>
  );
}
