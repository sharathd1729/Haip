"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Card, DataTable, StatusPill, Tabs, type Column } from "@/components/ui/kit";
import { NewslettersPanel } from "./OutreachPanels";
import { ContentDrawer } from "./ContentDrawer";
import { KIND_LABEL, STATUS, STUDIO, btnPrimary, day, inputCls, studioError, when, type ContentItem, type Kind } from "./types";

const FILTERS = [
  { value: "", label: "Active" }, { value: "in_review", label: "Waiting for approval" },
  { value: "approved", label: "Approved" }, { value: "draft", label: "Drafts" },
];

export function ContentTab() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind>("post");
  const [title, setTitle] = useState("");

  const list = useQuery<ContentItem[]>({
    queryKey: ["studio-content", status], placeholderData: p => p,
    queryFn: () => api.get(`${STUDIO}/content`, { params: status ? { status } : {} }).then(r => r.data),
  });
  const create = useMutation({
    mutationFn: () => api.post(`${STUDIO}/content`, { kind, title }).then(r => r.data as ContentItem),
    onSuccess: it => { setTitle(""); qc.invalidateQueries({ queryKey: ["studio-content"] }); setOpen(it.id); },
    onError: e => toast({ variant: "error", title: "Not created", description: studioError(e, "Try again.") }),
  });

  const columns: Column<ContentItem>[] = [
    { key: "title", header: "Content", cell: c => (
      <div className="min-w-0">
        <p className="truncate font-semibold text-[var(--haip-fg)]">{c.title}</p>
        <p className="mt-0.5 text-xs text-[var(--haip-fg-subtle)]">{KIND_LABEL[c.kind]}{c.planned_for ? ` · planned ${day(c.planned_for)}` : ""}</p>
      </div>) },
    { key: "status", header: "Status", cell: c => (
      <span className="flex flex-wrap gap-1.5">
        <StatusPill tone={STATUS[c.status].tone}>{STATUS[c.status].label}</StatusPill>
        {c.generation_status === "pending" && <StatusPill tone="info">AI writing</StatusPill>}
        {c.generation_status === "failed" && <StatusPill tone="danger">AI failed</StatusPill>}
      </span>) },
    { key: "updated", header: "Updated", align: "right", hideBelow: "md", cell: c => when(c.updated_at) },
  ];

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <form className="flex flex-col gap-2 sm:flex-row sm:items-end" onSubmit={e => { e.preventDefault(); if (title.trim()) create.mutate(); }}>
          <label className="space-y-1 sm:w-40">
            <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Type</span>
            <select className={inputCls} value={kind} onChange={e => setKind(e.target.value as Kind)}>
              {(Object.keys(KIND_LABEL) as Kind[]).map(k => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
            </select>
          </label>
          <label className="flex-1 space-y-1">
            <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">What is it about?</span>
            <input className={inputCls} maxLength={160} placeholder="e.g. Monsoon weekend in Coorg" value={title} onChange={e => setTitle(e.target.value)} />
          </label>
          <button type="submit" className={btnPrimary} disabled={!title.trim() || create.isPending}>New content</button>
        </form>
      </Card>

      <Tabs label="Filter content" value={status} onChange={setStatus} items={FILTERS} />
      <DataTable columns={columns} rows={list.data ?? []} rowKey={c => c.id} loading={list.isLoading}
        error={list.isError ? studioError(list.error, "Could not load content.") : null} onRetry={() => list.refetch()}
        onRowClick={c => setOpen(c.id)}
        empty={{ title: "No content here yet", hint: "Create a piece above, or turn a plan's calendar into drafts on the Plan tab." }} />
      <ContentDrawer id={open} onClose={() => setOpen(null)} />
      <NewslettersPanel />
    </div>
  );
}
