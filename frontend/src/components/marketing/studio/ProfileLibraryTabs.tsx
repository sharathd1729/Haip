"use client";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, StatusPill } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, type Asset } from "./types";

interface Profile {
  tagline: string | null; description: string | null; audience: string | null; tone: string | null;
  usps: string[]; avoid: string[]; city: string | null; region: string | null; default_hashtags: string[];
  [k: string]: unknown;
}

const TEXT: { key: keyof Profile; label: string; max: number; rows?: number; hint?: string }[] = [
  { key: "tagline", label: "Tagline", max: 160 },
  { key: "description", label: "What you offer", max: 2000, rows: 4 },
  { key: "audience", label: "Who your guests are", max: 600, rows: 2 },
  { key: "tone", label: "How you sound", max: 300, hint: "e.g. warm, understated, never salesy" },
  { key: "city", label: "City", max: 80 },
  { key: "region", label: "Region", max: 80 },
];
const LISTS: { key: "usps" | "avoid" | "default_hashtags"; label: string; hint: string }[] = [
  { key: "usps", label: "What makes you different", hint: "One per line." },
  { key: "avoid", label: "Words and claims never to use", hint: "One per line. Content using them is refused." },
  { key: "default_hashtags", label: "Your usual hashtags", hint: "Separate with spaces." },
];

export function ProfileTab() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<{ brand_name: string; profile: Profile }>({ queryKey: ["studio-profile"], queryFn: () => api.get(`${STUDIO}/profile`).then(r => r.data) });
  const [p, setP] = useState<Profile | null>(null);
  const [lists, setLists] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!q.data) return;
    setP(q.data.profile);
    setLists({ usps: q.data.profile.usps.join("\n"), avoid: q.data.profile.avoid.join("\n"), default_hashtags: q.data.profile.default_hashtags.join(" ") });
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => api.put(`${STUDIO}/profile`, {
      ...p,
      usps: lists.usps.split("\n").map(s => s.trim()).filter(Boolean),
      avoid: lists.avoid.split("\n").map(s => s.trim()).filter(Boolean),
      default_hashtags: lists.default_hashtags.split(/\s+/).filter(Boolean),
    }),
    onSuccess: r => { qc.setQueryData(["studio-profile"], r.data); toast({ variant: "success", title: "Profile saved" }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: studioError(e, "Check the fields.") }),
  });
  if (q.isLoading || !p) return q.isError ? <Card><EmptyState title="Could not load the profile" hint={studioError(q.error, "Try again.")} /></Card> : <Skeleton className="h-64 w-full" />;

  return (
    <Card>
      <CardHeader title={q.data?.brand_name ?? "Business profile"} description="What the AI may say about you. It never invents anything beyond this and your property details." />
      <CardBody>
        <form className="grid gap-4 md:grid-cols-2" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
          {TEXT.map(f => (
            <label key={f.key} className={f.rows ? "space-y-1 md:col-span-2" : "space-y-1"}>
              <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">{f.label}</span>
              {f.rows ? (
                <textarea className={inputCls} rows={f.rows} maxLength={f.max} value={(p[f.key] as string) ?? ""} onChange={e => setP({ ...p, [f.key]: e.target.value || null })} />
              ) : (
                <input className={inputCls} maxLength={f.max} value={(p[f.key] as string) ?? ""} onChange={e => setP({ ...p, [f.key]: e.target.value || null })} />
              )}
              {f.hint && <span className="block text-xs text-[var(--haip-fg-subtle)]">{f.hint}</span>}
            </label>
          ))}
          {LISTS.map(f => (
            <label key={f.key} className="space-y-1">
              <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">{f.label}</span>
              <textarea className={inputCls} rows={3} value={lists[f.key] ?? ""} onChange={e => setLists({ ...lists, [f.key]: e.target.value })} />
              <span className="block text-xs text-[var(--haip-fg-subtle)]">{f.hint}</span>
            </label>
          ))}
          <div className="md:col-span-2"><button type="submit" className={btnPrimary} disabled={save.isPending}>{save.isPending ? "Saving…" : "Save profile"}</button></div>
        </form>
      </CardBody>
    </Card>
  );
}

export function LibraryTab() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const file = useRef<HTMLInputElement>(null);
  const [render, setRender] = useState<Asset | null>(null);
  const [headline, setHeadline] = useState("");
  const [subline, setSubline] = useState("");
  const [template, setTemplate] = useState("portrait_panel");
  const assets = useQuery<Asset[]>({ queryKey: ["studio-media"], queryFn: () => api.get(`${STUDIO}/media`).then(r => r.data) });
  const templates = useQuery<{ key: string; label: string }[]>({ queryKey: ["studio-templates"], queryFn: () => api.get(`${STUDIO}/templates`).then(r => r.data) });
  const upload = useMutation({
    mutationFn: (f: File) => { const fd = new FormData(); fd.append("file", f); return api.post(`${STUDIO}/media`, fd); },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["studio-media"] }),
    onError: e => toast({ variant: "error", title: "Upload failed", description: studioError(e, "Use a JPEG, PNG or WebP up to 10 MB.") }),
  });
  const make = useMutation({
    mutationFn: () => api.post(`${STUDIO}/media/${render?.id}/render`, { template, headline, subline: subline || null }),
    onSuccess: () => { setRender(null); setHeadline(""); setSubline(""); qc.invalidateQueries({ queryKey: ["studio-media"] }); toast({ variant: "success", title: "Creative added to the library" }); },
    onError: e => toast({ variant: "error", title: "Not made", description: studioError(e, "Try again.") }),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-[var(--haip-fg-muted)]">Your own photos, and creatives made from them. No AI-generated images.</p>
        <input ref={file} type="file" accept="image/jpeg,image/png,image/webp" className="sr-only"
          onChange={e => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
        <button type="button" className={btnPrimary} disabled={upload.isPending} onClick={() => file.current?.click()}>{upload.isPending ? "Uploading…" : "Upload photo"}</button>
      </div>
      {render && (
        <Card className="p-4">
          <form className="grid gap-3 sm:grid-cols-[auto_1fr_1fr_auto] sm:items-end" onSubmit={e => { e.preventDefault(); make.mutate(); }}>
            <label className="space-y-1"><span className="text-[13px] font-semibold">Shape</span>
              <select className={inputCls} value={template} onChange={e => setTemplate(e.target.value)}>
                {(templates.data ?? []).map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select></label>
            <label className="space-y-1"><span className="text-[13px] font-semibold">Headline</span>
              <input className={inputCls} maxLength={80} value={headline} onChange={e => setHeadline(e.target.value)} /></label>
            <label className="space-y-1"><span className="text-[13px] font-semibold">Second line</span>
              <input className={inputCls} maxLength={120} value={subline} onChange={e => setSubline(e.target.value)} /></label>
            <span className="flex gap-2">
              <button type="submit" className={btnPrimary} disabled={!headline.trim() || make.isPending}>Make creative</button>
              <button type="button" className={btn} onClick={() => setRender(null)}>Cancel</button>
            </span>
          </form>
        </Card>
      )}
      {assets.isLoading ? <Skeleton className="h-40 w-full" /> : assets.isError ? (
        <Card><EmptyState title="Could not load the library" hint={studioError(assets.error, "Try again.")} /></Card>
      ) : !assets.data?.length ? (
        <Card><EmptyState title="No photos yet" hint="Upload property photos to build posts and creatives from." /></Card>
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {assets.data.map(a => (
            <li key={a.id} className="overflow-hidden rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)]">
              {a.url ? <img src={a.url} alt={a.alt_text ?? ""} className="aspect-square w-full object-cover" loading="lazy" /> : <div className="aspect-square bg-[var(--haip-surface)]" />}
              <div className="flex items-center justify-between gap-2 p-2">
                <StatusPill tone={a.source === "template" ? "brand" : "neutral"}>{a.source === "template" ? "Creative" : "Photo"}</StatusPill>
                {a.source === "upload" && <button type="button" className="min-h-11 px-1 text-xs font-semibold text-primary sm:min-h-0" onClick={() => setRender(a)}>Make creative</button>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
