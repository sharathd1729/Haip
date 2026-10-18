"use client";
// Opt-in AI images (NVIDIA catalog, commercially licensed models only). Results land in the library as
// "AI image · needs approval" and cannot be used in content until approved.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Card, StatusPill } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, when } from "./types";

interface ImageModel { key: string; label: string; enabled: boolean; licence: string; blocked_reason: string | null; shapes: string[] }
interface ImageJob { id: string; prompt: string; model: string; shape: string; status: "pending" | "ready" | "failed"; error: string | null; created_at: string }

const SHAPE_LABEL: Record<string, string> = { portrait: "Feed 4:5", square: "Square", story: "Story 9:16", landscape: "Landscape" };

export function AiImagesPanel() {
  const { data: session } = useSession();
  const isOwner = session?.user?.role === "owner";
  const qc = useQueryClient();
  const { toast } = useToast();
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("flux.1-schnell");
  const [shape, setShape] = useState("portrait");

  const settings = useQuery<{ ai_images_enabled: boolean }>({ queryKey: ["studio-settings"], queryFn: () => api.get(`${STUDIO}/settings`).then(r => r.data) });
  const models = useQuery<ImageModel[]>({ queryKey: ["studio-image-models"], queryFn: () => api.get(`${STUDIO}/image-models`).then(r => r.data) });
  const jobs = useQuery<ImageJob[]>({
    queryKey: ["studio-image-jobs"], enabled: !!settings.data?.ai_images_enabled,
    queryFn: () => api.get(`${STUDIO}/images`).then(r => r.data),
    refetchInterval: q => (q.state.data?.some(j => j.status === "pending") ? 5000 : false),
  });
  const toggle = useMutation({
    mutationFn: (on: boolean) => api.put(`${STUDIO}/settings`, { ai_images_enabled: on }),
    onSuccess: r => qc.setQueryData(["studio-settings"], r.data),
    onError: e => toast({ variant: "error", title: "Not changed", description: studioError(e, "Try again.") }),
  });
  const create = useMutation({
    mutationFn: () => api.post(`${STUDIO}/images`, { prompt, model, shape }),
    onSuccess: () => { setPrompt(""); qc.invalidateQueries({ queryKey: ["studio-image-jobs"] }); },
    onError: e => toast({ variant: "error", title: "Not started", description: studioError(e, "Try again.") }),
  });

  const on = !!settings.data?.ai_images_enabled;
  const current = models.data?.find(m => m.key === model);
  // A job that just finished adds an image to the library; refresh it once.
  const finished = jobs.data?.filter(j => j.status === "ready").length ?? 0;
  useEffect(() => { if (finished) qc.invalidateQueries({ queryKey: ["studio-media"] }); }, [finished, qc]);

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-[var(--haip-fg)]">AI images <StatusPill tone="info" className="ml-1">Opt-in</StatusPill></p>
          <p className="text-xs text-[var(--haip-fg-subtle)]">Made by AI, not real photos. Each one needs approval before it can be used.</p>
        </div>
        {isOwner ? (
          <button type="button" className={on ? btn : btnPrimary} disabled={toggle.isPending || settings.isLoading} onClick={() => toggle.mutate(!on)}>
            {on ? "Switch off" : "Switch on"}
          </button>
        ) : !on && <span className="text-xs text-[var(--haip-fg-subtle)]">Off. The owner can switch it on.</span>}
      </div>

      {on && (
        <>
          <form className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end" onSubmit={e => { e.preventDefault(); if (prompt.trim().length >= 3) create.mutate(); }}>
            <label className="space-y-1 sm:col-span-3"><span className="text-[13px] font-semibold">Describe the image</span>
              <input className={inputCls} maxLength={600} placeholder="e.g. misty ghat road at sunrise, caravan in the distance" value={prompt} onChange={e => setPrompt(e.target.value)} /></label>
            <label className="space-y-1"><span className="text-[13px] font-semibold">Model</span>
              <select className={inputCls} value={model} onChange={e => setModel(e.target.value)}>
                {(models.data ?? []).map(m => <option key={m.key} value={m.key} disabled={!m.enabled}>{m.label}{m.enabled ? "" : " (unavailable)"}</option>)}
              </select></label>
            <label className="space-y-1"><span className="text-[13px] font-semibold">Shape</span>
              <select className={inputCls} value={shape} onChange={e => setShape(e.target.value)}>
                {(current?.shapes ?? []).map(s => <option key={s} value={s}>{SHAPE_LABEL[s] ?? s}</option>)}
              </select></label>
            <button type="submit" className={btnPrimary} disabled={create.isPending || prompt.trim().length < 3}>Generate</button>
          </form>
          <p className="text-xs text-[var(--haip-fg-subtle)]">
            Only commercially licensed models are offered. {(models.data ?? []).filter(m => !m.enabled).map(m => `${m.label}: ${m.blocked_reason}`).join(" ")}
          </p>
          {!!jobs.data?.length && (
            <ul className="divide-y divide-[var(--haip-border)] rounded-xl border border-[var(--haip-border)] text-sm">
              {jobs.data.slice(0, 5).map(j => (
                <li key={j.id} className="flex flex-col gap-1 p-3 sm:flex-row sm:items-center sm:justify-between">
                  <span className="min-w-0 truncate">{j.prompt}</span>
                  <span className="flex shrink-0 items-center gap-2 text-xs text-[var(--haip-fg-subtle)]">
                    {when(j.created_at)}
                    <StatusPill tone={j.status === "ready" ? "success" : j.status === "failed" ? "danger" : "info"}>
                      {j.status === "ready" ? "In library" : j.status === "failed" ? "Failed" : "Generating…"}
                    </StatusPill>
                  </span>
                  {j.status === "failed" && j.error && <span className="text-xs text-[var(--haip-status-danger-fg)] sm:basis-full">{j.error}</span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}
