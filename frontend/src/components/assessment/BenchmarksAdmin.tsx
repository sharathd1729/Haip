"use client";
// ROI benchmark versions for the public assessment (owner of HAIP's sales workspace only; backend /roi-benchmarks).
// A version is never edited: load one, change the JSON, give it a new version name, save, then make it active.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";

interface VersionRow { version: string; label?: string | null; sample: boolean; source: "seed" | "stored"; is_active: boolean; notes?: string | null }

function apiError(err: unknown): string {
  const r = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
  const d = r?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) return d.map(x => `${(x as { loc?: unknown[] }).loc?.slice(1).join(".")}: ${(x as { msg?: string }).msg}`).join("; ");
  return r?.status === 403 ? "Only the owner of HAIP's sales workspace can change benchmarks." : "That didn't work. Try again.";
}

export function BenchmarksAdmin() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["roi-benchmarks"],
    queryFn: async () => (await api.get<{ items: VersionRow[]; active: string }>("/roi-benchmarks")).data,
    retry: false,
  });
  const [draft, setDraft] = useState("");
  const [notes, setNotes] = useState("");
  const [message, setMessage] = useState<{ tone: "success" | "danger"; text: string } | null>(null);

  const load = useMutation({
    mutationFn: async (version: string) => (await api.get(`/roi-benchmarks/${encodeURIComponent(version)}`)).data,
    onSuccess: data => { setDraft(JSON.stringify(data, null, 1)); setMessage(null); },
    onError: e => setMessage({ tone: "danger", text: apiError(e) }),
  });
  const save = useMutation({
    mutationFn: async () => {
      let data: unknown;
      try { data = JSON.parse(draft); } catch { throw new Error("json"); }
      return (await api.post("/roi-benchmarks", { data, notes: notes || null })).data as { version: string };
    },
    onSuccess: r => { setMessage({ tone: "success", text: `Saved ${r.version}. It is not used until you make it active.` }); qc.invalidateQueries({ queryKey: ["roi-benchmarks"] }); },
    onError: e => setMessage({ tone: "danger", text: (e as Error).message === "json" ? "That is not valid JSON." : apiError(e) }),
  });
  const activate = useMutation({
    mutationFn: async (version: string) => (await api.post(`/roi-benchmarks/${encodeURIComponent(version)}/activate`)).data,
    onSuccess: () => { setMessage({ tone: "success", text: "Active version changed. New assessments use it; sent reports keep theirs." }); qc.invalidateQueries({ queryKey: ["roi-benchmarks"] }); },
    onError: e => setMessage({ tone: "danger", text: apiError(e) }),
  });

  if (list.isError) return null;          // not HAIP's sales workspace: nothing to manage here
  return (
    <Card>
      <CardHeader title="Assessment benchmarks" description="The figures behind the public property assessment. Every report names the version it used." />
      <CardBody className="space-y-4">
        {list.isPending ? (
          <div className="h-16 animate-pulse rounded-xl bg-[var(--haip-surface)]" aria-busy="true" />
        ) : (
          <ul className="divide-y divide-[var(--haip-border)]">
            {list.data.items.map(v => (
              <li key={v.version} className="flex flex-wrap items-center gap-2 py-2.5">
                <span className="font-semibold text-[var(--haip-fg)] break-all">{v.version}</span>
                {v.is_active && <StatusPill tone="success">Active</StatusPill>}
                {v.sample && <StatusPill tone="warning">Sample values</StatusPill>}
                {v.source === "seed" && <StatusPill>Seed file</StatusPill>}
                <span className="ml-auto flex gap-2">
                  <button type="button" onClick={() => load.mutate(v.version)} className="min-h-[44px] px-2 text-[13.5px] font-semibold text-primary">Load</button>
                  {!v.is_active && (
                    <button type="button" onClick={() => activate.mutate(v.version)} disabled={activate.isPending} className="min-h-[44px] px-2 text-[13.5px] font-semibold text-primary disabled:opacity-50">Make active</button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
        <label className="block">
          <span className="mb-1 block text-[13px] font-semibold text-[var(--haip-fg-muted)]">New version (JSON, change &quot;version&quot; to a new name)</span>
          <textarea value={draft} onChange={e => setDraft(e.target.value)} rows={12} spellCheck={false}
            className="w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-3 font-mono text-[13px] text-[var(--haip-fg)] max-md:text-[16px]" />
        </label>
        <label className="block">
          <span className="mb-1 block text-[13px] font-semibold text-[var(--haip-fg-muted)]">What changed (optional)</span>
          <input value={notes} onChange={e => setNotes(e.target.value)} maxLength={500}
            className="w-full min-h-[44px] rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] sm:text-[14px]" />
        </label>
        {message && <p role="status" className={message.tone === "success" ? "text-[13.5px] text-[var(--haip-status-success-fg)]" : "text-[13.5px] text-[var(--haip-status-danger-fg)]"}>{message.text}</p>}
        <button type="button" onClick={() => save.mutate()} disabled={!draft.trim() || save.isPending}
          className="min-h-[44px] rounded-xl bg-primary px-5 text-[14px] font-semibold text-primary-foreground disabled:opacity-50">
          {save.isPending ? "Saving…" : "Save as a new version"}
        </button>
      </CardBody>
    </Card>
  );
}
