"use client";
// Website page: languages + the launch report (website phase 6). "Add Hindi" asks HAIP to translate the words you wrote
// into a NEW DRAFT; you check it in the preview (/hi) and publish it like any change. Backend: endpoints/website_growth.py.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCheck2, Languages } from "lucide-react";
import { Card, CardBody, StatusPill } from "@/components/ui/kit";
import { btn } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { webError } from "@/lib/website";
import { growthApi } from "@/lib/websiteGrowth";

export function LaunchPanel({ canApprove, isNew, onDraft }: { canApprove: boolean; isNew: boolean; onDraft: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const langs = useQuery({ queryKey: ["web-langs"], queryFn: growthApi.languages });
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useQuery({ queryKey: ["web-translate", jobId], queryFn: () => growthApi.translateJob(jobId!), enabled: !!jobId,
    refetchInterval: q => (["pending", "running"].includes(q.state.data?.status || "pending") ? 3000 : false) });
  const start = useMutation({ mutationFn: (code: string) => growthApi.translate(code), onSuccess: j => setJobId(j.id),
    onError: e => toast({ variant: "error", title: "Couldn't start", description: webError(e, "Try again.") }) });
  const st = job.data?.status;
  const loaded = useRef<string | null>(null);      // reload the draft once per finished job (onDraft is a new function each render)
  useEffect(() => {
    if (st !== "ready" || !jobId || loaded.current === jobId) return;
    loaded.current = jobId;
    onDraft();
    qc.invalidateQueries({ queryKey: ["web-langs"] });
  }, [st, jobId, onDraft, qc]);
  return (
    <Card><CardBody className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Languages size={20} aria-hidden="true" className="text-[var(--primary)]" />
        <p className="mr-auto font-semibold">Languages and launch</p>
        <Link className={btn} href="/dashboard/marketing/website/launch"><FileCheck2 size={16} aria-hidden="true" />Launch report</Link>
      </div>
      {langs.isError ? <p className="text-sm">Couldn&apos;t load languages. <button className="underline" onClick={() => langs.refetch()}>Try again</button></p>
        : <ul className="grid gap-2">{(langs.data || []).map(l => (
          <li key={l.code} className="flex flex-wrap items-center gap-2 text-[15px]">
            <b className="font-semibold">{l.name}</b>
            {l.live ? <StatusPill tone="success">On your website</StatusPill> : <StatusPill tone="neutral">Not added</StatusPill>}
            {canApprove && isNew && <button className={btn} disabled={start.isPending || st === "pending" || st === "running"} onClick={() => start.mutate(l.code)}>
              {st === "pending" || st === "running" ? "Translating…" : l.live ? "Translate again" : `Add ${l.name}`}</button>}
          </li>))}</ul>}
      {st === "ready" && <p className="text-sm">Done: a new draft has the {job.data?.language === "hi" ? "Hindi" : ""} words. Open the preview, add /hi to the address to read them, then publish.
        {job.data?.result?.left_in_english.length ? ` ${job.data.result.left_in_english.length} text(s) stayed in English.` : ""}</p>}
      {st === "failed" && <p className="text-sm">{job.data?.error}</p>}
      <p className="text-xs text-[var(--haip-fg-muted)]">Only the words you wrote are translated. Stays, trips, reviews and prices come from HAIP and stay as they are.</p>
    </CardBody></Card>
  );
}
