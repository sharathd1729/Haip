"use client";
// Website › Promo codes (website phase 4, backend website_promos): codes guests type at checkout. HAIP checks each code
// and takes it off the nights' price; on a site that doesn't show prices the code travels with the request instead.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Drawer, StatusPill } from "@/components/ui/kit";
import { btn, btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { webError } from "@/lib/website";
import { growthApi, type Promo, type PromoIn } from "@/lib/websiteGrowth";

const EMPTY: PromoIn = { code: "", kind: "percent", value: 10, starts_on: null, ends_on: null, min_nights: 1, max_uses: null,
  property_ids: [], label: null, active: true };
const what = (p: Promo) => `${p.kind === "percent" ? `${p.value}% off` : `₹${p.value.toLocaleString("en-IN")} off`}${p.min_nights > 1 ? `, ${p.min_nights}+ nights` : ""}`;

export function PromoSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const list = useQuery({ queryKey: ["web-promos"], queryFn: growthApi.promos, enabled: open });
  const [edit, setEdit] = useState<{ id?: string; v: PromoIn } | null>(null);
  const save = useMutation({
    mutationFn: (e: { id?: string; v: PromoIn }) => (e.id ? growthApi.savePromo(e.id, e.v) : growthApi.addPromo(e.v)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["web-promos"] }); setEdit(null); toast({ variant: "success", title: "Saved" }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: webError(e, "Check the details and try again.") }) });
  const set = <K extends keyof PromoIn>(k: K, val: PromoIn[K]) => edit && setEdit({ ...edit, v: { ...edit.v, [k]: val } });
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) { setEdit(null); onClose(); } }} title={edit ? (edit.id ? "Change code" : "New promo code") : "Promo codes"}
      footer={edit ? <div className="flex gap-2"><button className={btn} onClick={() => setEdit(null)}>Back</button>
        <button className={btnPrimary} disabled={save.isPending || edit.v.code.length < 3} onClick={() => save.mutate(edit)}>{save.isPending ? "Saving…" : "Save"}</button></div>
        : <button className={btnPrimary} onClick={() => setEdit({ v: { ...EMPTY } })}>New code</button>}>
      {edit ? (
        <div className="grid gap-4 text-[15px]">
          <label className="grid gap-1"><span className="text-sm font-semibold">Code guests type</span>
            <input className={inputCls} value={edit.v.code} maxLength={30} onChange={e => set("code", e.target.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase())} placeholder="MONSOON15" /></label>
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1"><span className="text-sm font-semibold">Type</span>
              <select className={inputCls} value={edit.v.kind} onChange={e => set("kind", e.target.value as PromoIn["kind"])}>
                <option value="percent">% off the nights</option><option value="flat">₹ off the stay</option></select></label>
            <label className="grid gap-1"><span className="text-sm font-semibold">{edit.v.kind === "percent" ? "Percent" : "Rupees"}</span>
              <input className={inputCls} type="number" inputMode="numeric" min={1} max={edit.v.kind === "percent" ? 90 : undefined} value={edit.v.value}
                onChange={e => set("value", Number(e.target.value))} /></label>
            <label className="grid gap-1"><span className="text-sm font-semibold">Check-in from</span>
              <input className={inputCls} type="date" value={edit.v.starts_on || ""} onChange={e => set("starts_on", e.target.value || null)} /></label>
            <label className="grid gap-1"><span className="text-sm font-semibold">Check-in until</span>
              <input className={inputCls} type="date" value={edit.v.ends_on || ""} onChange={e => set("ends_on", e.target.value || null)} /></label>
            <label className="grid gap-1"><span className="text-sm font-semibold">Minimum nights</span>
              <input className={inputCls} type="number" inputMode="numeric" min={1} max={60} value={edit.v.min_nights} onChange={e => set("min_nights", Number(e.target.value) || 1)} /></label>
            <label className="grid gap-1"><span className="text-sm font-semibold">Times it can be used</span>
              <input className={inputCls} type="number" inputMode="numeric" min={1} value={edit.v.max_uses ?? ""} placeholder="No limit"
                onChange={e => set("max_uses", e.target.value ? Number(e.target.value) : null)} /></label>
          </div>
          <label className="grid gap-1"><span className="text-sm font-semibold">Your name for it (optional)</span>
            <input className={inputCls} value={edit.v.label || ""} maxLength={80} onChange={e => set("label", e.target.value || null)} placeholder="Monsoon weekdays" /></label>
          <label className="flex min-h-11 items-center gap-3"><input type="checkbox" className="h-5 w-5 accent-[var(--primary)]" checked={edit.v.active} onChange={e => set("active", e.target.checked)} />
            <span>Guests can use it</span></label>
          <p className="text-sm text-[var(--haip-fg-muted)]">It works on every stay on your website. Guests see the amount only if your website shows prices; otherwise the code comes with their request.</p>
        </div>
      ) : list.isLoading ? <div className="h-32 animate-pulse rounded-xl bg-[var(--haip-border)]" />
        : list.isError ? <p className="text-sm">Couldn&apos;t load your codes. <button className="underline" onClick={() => list.refetch()}>Try again</button></p>
        : !list.data?.length ? <p className="text-[15px]">No promo codes yet. Add one, then show it with a &ldquo;Seasonal offer&rdquo; section.</p>
        : <ul className="grid gap-2">{list.data.map(p => (
          <li key={p.id}><button type="button" className="grid w-full gap-1 rounded-xl border border-[var(--haip-border)] p-3 text-left"
            onClick={() => setEdit({ id: p.id, v: { code: p.code, kind: p.kind, value: p.value, starts_on: p.starts_on, ends_on: p.ends_on,
              min_nights: p.min_nights, max_uses: p.max_uses, property_ids: p.property_ids, label: p.label, active: p.active } })}>
            <span className="flex items-center gap-2"><b className="font-semibold">{p.code}</b><StatusPill tone={p.active ? "success" : "neutral"}>{p.active ? "On" : "Off"}</StatusPill></span>
            <span className="text-sm text-[var(--haip-fg-muted)]">{what(p)}{p.ends_on ? `, until ${p.ends_on}` : ""} · used {p.used_count}{p.max_uses ? ` of ${p.max_uses}` : ""}{p.label ? ` · ${p.label}` : ""}</span>
          </button></li>))}</ul>}
    </Drawer>
  );
}
