"use client";
// Everything waiting for a person: drafted posts and AI images. A post is reviewed in its drawer, where the images are
// shown exactly as they will be posted and "Ask for changes" needs a note (the AI uses it for the next version).
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Card, DataTable, StatusPill, type Column } from "@/components/ui/kit";
import { ContentDrawer } from "./ContentDrawer";
import { KIND_LABEL, STUDIO, btn, btnPrimary, day, studioError, when, type Kind } from "./types";

interface Pending {
  type: "content" | "ai_image"; id: string; title: string; kind: string; version_id: string | null; planned_for: string | null;
  waiting_since: string; created_by: string | null; review?: { high: number; medium: number; reviewed: boolean };
}

export function ApprovalsTab() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canReview = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();
  const [open, setOpen] = useState<string | null>(null);
  const q = useQuery<{ count: number; items: Pending[] }>({ queryKey: ["studio-approvals"], queryFn: () => api.get(`${STUDIO}/approvals`).then(r => r.data) });
  const act = useMutation({
    mutationFn: ({ p, approve }: { p: Pending; approve: boolean }) =>
      api.post(`${STUDIO}/approvals/${p.type}/${p.id}/${approve ? "approve" : "reject"}`, { version_id: p.version_id }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["studio-approvals"] }); qc.invalidateQueries({ queryKey: ["studio-content"] }); qc.invalidateQueries({ queryKey: ["studio-media"] }); },
    onError: e => toast({ variant: "error", title: "Not done", description: studioError(e, "Try again.") }),
  });

  const columns: Column<Pending>[] = [
    { key: "title", header: "Waiting for approval", cell: p => (
      <div className="min-w-0">
        <p className="truncate font-semibold">{p.title}</p>
        <p className="text-xs text-[var(--haip-fg-subtle)]">
          {p.type === "ai_image" ? "AI image" : KIND_LABEL[p.kind as Kind] ?? p.kind}{p.planned_for ? ` · planned ${day(p.planned_for)}` : ""}
          {p.created_by === "agency" && <StatusPill tone="info" className="ml-2">By the agency</StatusPill>}
          {p.review && (p.review.high > 0 ? <StatusPill tone="danger" className="ml-2">{p.review.high} must fix</StatusPill>
            : p.review.medium > 0 ? <StatusPill tone="warning" className="ml-2">{p.review.medium} to check</StatusPill>
            : p.review.reviewed ? <StatusPill tone="success" className="ml-2">Checks passed</StatusPill> : null)}
        </p>
      </div>) },
    { key: "since", header: "Waiting since", hideBelow: "md", cell: p => when(p.waiting_since) },
    { key: "act", header: "", align: "right", cell: p => p.type === "content" ? (
      <span className="flex justify-end" onClick={e => e.stopPropagation()}>
        <button type="button" className={canReview ? btnPrimary : btn} onClick={() => setOpen(p.id)}>{canReview ? "Review" : "Open"}</button>
      </span>) : canReview ? (
      <span className="flex justify-end gap-2" onClick={e => e.stopPropagation()}>
        <button type="button" className={btnPrimary} disabled={act.isPending} onClick={() => act.mutate({ p, approve: true })}>Approve</button>
        <button type="button" className={btn} disabled={act.isPending} onClick={() => act.mutate({ p, approve: false })}>Reject</button>
      </span>) : null },
  ];

  return (
    <Card className="p-0">
      <DataTable columns={columns} rows={q.data?.items ?? []} rowKey={p => `${p.type}:${p.id}`} loading={q.isLoading}
        error={q.isError ? studioError(q.error, "Could not load approvals.") : null} onRetry={() => q.refetch()}
        onRowClick={p => p.type === "content" && setOpen(p.id)}
        empty={{ title: "Nothing waiting", hint: "Drafts from the weekly run and AI images that need a decision show up here." }} />
      <ContentDrawer id={open} onClose={() => { setOpen(null); qc.invalidateQueries({ queryKey: ["studio-approvals"] }); }} />
    </Card>
  );
}
