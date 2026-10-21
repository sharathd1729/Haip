"use client";
// Agency M3. Brand kit (GET/PUT /brand-kit): logo, colours and typeface drawn on every post. It is copied into a draft
// when its photos are picked, so an approved post keeps the look it was approved with. Writer (GET/PUT /creative-model):
// the owner may switch drafting to the stronger model; it falls back to the standard one if that fails.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState } from "@/components/ui/kit";
import { STUDIO, btnPrimary, inputCls, studioError, type Asset } from "./types";

interface Kit { logo_asset_id: string | null; primary: string | null; accent: string | null; font: "plain" | "sans" | "serif"; logo_position: "top_left" | "top_right" | "none" }
const HEX = /^#[0-9a-fA-F]{6}$/;

function Colour({ label, value, onChange }: { label: string; value: string | null; onChange: (v: string | null) => void }) {
  return (
    <label className="space-y-1">
      <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">{label}</span>
      <span className="flex items-center gap-2">
        <input type="color" aria-label={`${label} picker`} className="size-11 shrink-0 cursor-pointer rounded-lg border border-[var(--haip-border)]"
          value={value && HEX.test(value) ? value : "#1E7A5A"} onChange={e => onChange(e.target.value.toUpperCase())} />
        <input className={inputCls} placeholder="Workspace colour" maxLength={7} value={value ?? ""} onChange={e => onChange(e.target.value || null)} />
      </span>
    </label>
  );
}

export function BrandKitPanel() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canEdit = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<Kit>({ queryKey: ["studio-brand-kit"], queryFn: () => api.get(`${STUDIO}/brand-kit`).then(r => r.data) });
  const media = useQuery<Asset[]>({ queryKey: ["studio-media"], queryFn: () => api.get(`${STUDIO}/media`).then(r => r.data), staleTime: 60_000 });
  const writer = useQuery<{ model: string }>({ queryKey: ["studio-creative-model"], queryFn: () => api.get(`${STUDIO}/creative-model`).then(r => r.data) });
  const [kit, setKit] = useState<Kit | null>(null);
  useEffect(() => { if (q.data) setKit(q.data); }, [q.data]);
  const save = useMutation({
    mutationFn: () => api.put(`${STUDIO}/brand-kit`, kit),
    onSuccess: r => { qc.setQueryData(["studio-brand-kit"], r.data); toast({ variant: "success", title: "Brand kit saved", description: "New drafts use it; approved posts keep their look." }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: studioError(e, "Check the colours (#RRGGBB).") }),
  });
  const setWriter = useMutation({
    mutationFn: (model: string) => api.put(`${STUDIO}/creative-model`, { model }),
    onSuccess: r => qc.setQueryData(["studio-creative-model"], r.data),
    onError: e => toast({ variant: "error", title: "Not changed", description: studioError(e, "Only the owner can change this.") }),
  });
  if (q.isError) return <Card><EmptyState title="Could not load the brand kit" hint={studioError(q.error, "Try again.")} /></Card>;
  if (!kit) return <Skeleton className="h-48 w-full" />;
  const images = (media.data ?? []).filter(a => (a.status ?? "active") === "active" && a.mime_type.startsWith("image/") && a.source === "upload");
  const logo = images.find(a => a.id === kit.logo_asset_id);
  const bad = [kit.primary, kit.accent].some(c => c && !HEX.test(c));

  return (
    <Card>
      <CardHeader title="Brand kit" description="Your logo, colours and typeface, drawn on every post the agency makes." />
      <CardBody>
        <form className="grid gap-4 md:grid-cols-2" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
          <fieldset disabled={!canEdit || save.isPending} className="contents">
            <label className="space-y-1 md:col-span-2">
              <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Logo</span>
              <span className="flex items-center gap-2">
                {logo?.url ? <img src={logo.url} alt="Logo" className="size-11 shrink-0 rounded-lg bg-[var(--haip-surface)] object-contain" />
                  : <span className="size-11 shrink-0 rounded-lg bg-[var(--haip-surface)]" />}
                <select className={inputCls} value={kit.logo_asset_id ?? ""} onChange={e => setKit({ ...kit, logo_asset_id: e.target.value || null })}>
                  <option value="">No logo</option>
                  {images.map(a => <option key={a.id} value={a.id}>{a.mime_type === "image/png" ? "PNG" : "Image"}{a.alt_text ? ` · ${a.alt_text.slice(0, 40)}` : ""}</option>)}
                </select>
              </span>
              <span className="block text-xs text-[var(--haip-fg-subtle)]">Upload it to the library first; a PNG keeps its transparent background. It is never used as a post photo.</span>
            </label>
            <Colour label="Brand colour" value={kit.primary} onChange={v => setKit({ ...kit, primary: v })} />
            <Colour label="Accent (buttons and bars)" value={kit.accent} onChange={v => setKit({ ...kit, accent: v })} />
            <label className="space-y-1">
              <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Typeface</span>
              <select className={inputCls} value={kit.font} onChange={e => setKit({ ...kit, font: e.target.value as Kit["font"] })}>
                <option value="plain">Plain</option><option value="sans">Noto Sans</option><option value="serif">Noto Serif</option>
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Logo position</span>
              <select className={inputCls} value={kit.logo_position} onChange={e => setKit({ ...kit, logo_position: e.target.value as Kit["logo_position"] })}>
                <option value="top_right">Top right</option><option value="top_left">Top left</option><option value="none">Don't show</option>
              </select>
            </label>
          </fieldset>
          <div className="flex flex-wrap items-center justify-between gap-3 md:col-span-2">
            <label className="flex min-h-11 items-center gap-2 text-sm text-[var(--haip-fg-2)]">
              <input type="checkbox" className="size-4" disabled={role !== "owner" || setWriter.isPending || !writer.data}
                checked={writer.data?.model === "premium"} onChange={e => setWriter.mutate(e.target.checked ? "premium" : "standard")} />
              Write drafts with the stronger model{role !== "owner" ? " (owner only)" : ""}
            </label>
            {canEdit && <button type="submit" className={btnPrimary} disabled={save.isPending || bad}>{save.isPending ? "Saving…" : "Save brand kit"}</button>}
          </div>
        </form>
      </CardBody>
    </Card>
  );
}
