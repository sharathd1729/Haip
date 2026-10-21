"use client";
// Outside creative tools (agency M2b, backend endpoints/marketing_creative.py): Canva brand templates and Higgsfield
// video. Each workspace connects its own account; videos need the owner to switch them on and are approved like AI images.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, when, type Asset } from "./types";

interface Job { id: string; provider: "canva" | "higgsfield"; kind: string; status: string; error: string | null; external_url: string | null; duration: number | null; created_at: string }
export interface Creative {
  canva: { available: boolean; connected: boolean };
  higgsfield: { connected: boolean; key_hint: string | null };
  video: { enabled: boolean; monthly_seconds: number; used_seconds: number; models: { key: string; label: string; durations: number[]; max_images: number; default: boolean }[] };
  jobs: Job[];
}

const JOB_TONE: Record<string, Tone> = { pending: "neutral", running: "info", ready: "success", failed: "danger" };

export function useCreative() {
  return useQuery<Creative>({ queryKey: ["studio-creative"], queryFn: () => api.get(`${STUDIO}/creative`).then(r => r.data),
    refetchInterval: d => (d.state.data?.jobs.some(j => j.status === "pending" || j.status === "running") ? 8000 : false) });
}

function canvaConnectUrl(token: string | null): string | null {
  if (!token) return null;
  const raw = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
  const base = raw.endsWith("/api/v1") ? raw : `${raw}/api/v1`;
  return `${base}/marketing/studio/canva/oauth-start?token=${encodeURIComponent(token)}`;
}

export function CreativePanel({ photos }: { photos: Asset[] }) {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const isOwner = role === "owner";
  const canConnect = role === "owner" || role === "manager";
  const token = (session as unknown as { accessToken?: string })?.accessToken ?? null;
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useCreative();
  const [keyId, setKeyId] = useState("");
  const [secret, setSecret] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState(5);
  const done = () => qc.invalidateQueries({ queryKey: ["studio-creative"] });
  const fail = (title: string) => (e: unknown) => toast({ variant: "error", title, description: studioError(e, "Try again.") });
  const saveKey = useMutation({ mutationFn: () => api.put(`${STUDIO}/higgsfield`, { key_id: keyId, key_secret: secret }),
    onSuccess: () => { setKeyId(""); setSecret(""); done(); toast({ variant: "success", title: "Higgsfield connected" }); }, onError: fail("Not saved") });
  const settings = useMutation({ mutationFn: (body: { enabled?: boolean; monthly_seconds?: number }) => api.put(`${STUDIO}/video-settings`, body),
    onSuccess: done, onError: fail("Not saved") });
  const make = useMutation({ mutationFn: () => api.post(`${STUDIO}/videos`, { asset_ids: picked, prompt, duration }),
    onSuccess: () => { setPicked([]); setPrompt(""); done(); toast({ variant: "success", title: "Making the video", description: "It appears in the library for approval in a few minutes." }); },
    onError: fail("Not started") });

  const c = q.data;
  if (!c) return null;
  const model = c.video.models.find(m => m.default) ?? c.video.models[0];
  const usable = photos.filter(p => p.status !== "pending_review" && p.mime_type.startsWith("image/") && !(p.tags?.people && !p.people_ok));
  const connectUrl = canvaConnectUrl(token);

  return (
    <Card>
      <CardHeader title="Creative tools" description="Your own Canva brand templates, and short videos made from your photos." />
      <CardBody className="space-y-5">
        <section className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-sm font-semibold">Canva {c.canva.connected ? <StatusPill tone="success" className="ml-1">Connected</StatusPill> : null}</p>
            <p className="text-xs text-[var(--haip-fg-subtle)]">{!c.canva.available ? "Not set up on this HAIP server yet."
              : c.canva.connected ? "Open a draft and choose “Make in Canva” to fill one of your brand templates."
              : "Needs Canva Pro, Teams or Enterprise with brand templates."}</p>
          </div>
          {c.canva.available && !c.canva.connected && canConnect && connectUrl && <a className={btnPrimary} href={connectUrl}>Connect Canva</a>}
        </section>

        <section className="space-y-2 border-t border-[var(--haip-border)] pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold">Video from photos (Higgsfield) {c.higgsfield.connected && <StatusPill tone="success" className="ml-1">Key {c.higgsfield.key_hint}</StatusPill>}</p>
            {isOwner && c.higgsfield.connected && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="size-4" checked={c.video.enabled} onChange={e => settings.mutate({ enabled: e.target.checked })} />
                Switched on · {c.video.used_seconds}/{c.video.monthly_seconds} s this month
              </label>)}
          </div>
          {!c.higgsfield.connected ? (isOwner ? (
            <form className="grid gap-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end" onSubmit={e => { e.preventDefault(); saveKey.mutate(); }}>
              <label className="space-y-1"><span className="text-xs font-semibold">Key id</span><input className={inputCls} value={keyId} onChange={e => setKeyId(e.target.value)} autoComplete="off" /></label>
              <label className="space-y-1"><span className="text-xs font-semibold">Key secret</span><input className={inputCls} type="password" value={secret} onChange={e => setSecret(e.target.value)} autoComplete="off" /></label>
              <button type="submit" className={btn} disabled={keyId.length < 8 || secret.length < 8 || saveKey.isPending}>Save key</button>
              <p className="text-xs text-[var(--haip-fg-subtle)] sm:col-span-3">From your Higgsfield Cloud account. Videos are billed to that account; the key is stored encrypted and never shown again.</p>
            </form>
          ) : <p className="text-xs text-[var(--haip-fg-subtle)]">The owner can connect a Higgsfield account here.</p>) : !c.video.enabled ? (
            <p className="text-xs text-[var(--haip-fg-subtle)]">Video is switched off. The owner can switch it on above.</p>
          ) : model && (
            <form className="space-y-2" onSubmit={e => { e.preventDefault(); make.mutate(); }}>
              <p className="text-xs text-[var(--haip-fg-subtle)]">Pick up to {model.max_images} photos ({picked.length} picked). Photos showing people need the OK first.</p>
              <ul className="flex gap-2 overflow-x-auto pb-1">
                {usable.slice(0, 40).map(p => { const on = picked.includes(p.id); return (
                  <li key={p.id} className="shrink-0">
                    <button type="button" aria-pressed={on} onClick={() => setPicked(on ? picked.filter(x => x !== p.id) : picked.length < model.max_images ? [...picked, p.id] : picked)}
                      className={`block size-16 overflow-hidden rounded-lg border-2 ${on ? "border-primary" : "border-transparent"}`}>
                      {p.url ? <img src={p.url} alt={p.alt_text ?? ""} className="size-full object-cover" /> : null}
                    </button>
                  </li>); })}
              </ul>
              <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto] sm:items-end">
                <label className="space-y-1"><span className="text-xs font-semibold">Movement</span>
                  <input className={inputCls} maxLength={1000} placeholder="slow push in over the pool at sunset" value={prompt} onChange={e => setPrompt(e.target.value)} /></label>
                <label className="space-y-1"><span className="text-xs font-semibold">Length</span>
                  <select className={inputCls} value={duration} onChange={e => setDuration(Number(e.target.value))}>
                    {model.durations.map(d => <option key={d} value={d}>{d} s</option>)}
                  </select></label>
                <button type="submit" className={btnPrimary} disabled={!picked.length || prompt.trim().length < 3 || make.isPending}>Make video</button>
              </div>
            </form>
          )}
        </section>

        {c.jobs.length > 0 && (
          <section className="space-y-2 border-t border-[var(--haip-border)] pt-4">
            <p className="text-sm font-semibold">Recent</p>
            <ul className="space-y-1 text-sm">
              {c.jobs.slice(0, 8).map(j => (
                <li key={j.id} className="flex flex-wrap items-center gap-2">
                  <StatusPill tone={JOB_TONE[j.status] ?? "neutral"}>{j.status}</StatusPill>
                  {j.provider === "canva" ? "Canva design" : `Video, ${j.duration} s`} · {when(j.created_at)}
                  {j.external_url && <a className="font-semibold text-primary" href={j.external_url} target="_blank" rel="noreferrer">Open in Canva</a>}
                  {j.error && <span className="text-xs text-[var(--haip-status-danger-fg)]">{j.error}</span>}
                </li>))}
            </ul>
          </section>
        )}
      </CardBody>
    </Card>
  );
}

/** In a draft: fill one of the workspace's Canva brand templates with this draft's text and photo. */
export function CanvaButton({ itemId }: { itemId: string }) {
  const c = useCreative();
  const qc = useQueryClient();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const templates = useQuery<{ templates: { id: string; title: string | null; thumbnail: string | null }[] }>({
    queryKey: ["studio-canva-templates"], enabled: open, staleTime: 10 * 60_000,
    queryFn: () => api.get(`${STUDIO}/canva/templates`).then(r => r.data) });
  const make = useMutation({ mutationFn: (template_id: string) => api.post(`${STUDIO}/content/${itemId}/canva`, { template_id }),
    onSuccess: () => { setOpen(false); qc.invalidateQueries({ queryKey: ["studio-creative"] });
      toast({ variant: "success", title: "Making it in Canva", description: "The design lands in the library in a minute; pick it as this post's photo with the “Photo only” look." }); },
    onError: e => toast({ variant: "error", title: "Not started", description: studioError(e, "Try again.") }) });
  if (!c.data?.canva.connected) return null;
  return (
    <div className="space-y-2">
      <button type="button" className={btn} onClick={() => setOpen(!open)}>{open ? "Close Canva templates" : "Make in Canva"}</button>
      {open && (templates.isLoading ? <p className="text-sm text-[var(--haip-fg-subtle)]">Loading your brand templates…</p>
        : templates.isError ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(templates.error, "Could not load templates.")}</p>
        : !templates.data?.templates.length ? <p className="text-sm text-[var(--haip-fg-subtle)]">No brand templates with data fields. In Canva, add fields named headline, body, cta and photo.</p>
        : <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">{templates.data.templates.map(t => (
            <li key={t.id}><button type="button" className="w-full overflow-hidden rounded-lg border border-[var(--haip-border)] text-left" disabled={make.isPending} onClick={() => make.mutate(t.id)}>
              {t.thumbnail ? <img src={t.thumbnail} alt="" className="aspect-square w-full object-cover" /> : <div className="aspect-square bg-[var(--haip-surface)]" />}
              <span className="block truncate p-1.5 text-xs">{t.title ?? "Untitled"}</span></button></li>))}</ul>)}
    </div>
  );
}
