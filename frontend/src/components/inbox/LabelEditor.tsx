"use client";
// Chat labels on one conversation (PATCH /conversations/{id} {labels}); up to 10, 24 characters each.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "@/lib/icons";
import api from "@/lib/api";

export function LabelEditor({ conversationId, labels }: { conversationId: string; labels: string[] }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: (next: string[]) => api.patch(`/conversations/${conversationId}`, { labels: next }),
    onSuccess: () => { setError(""); qc.invalidateQueries({ queryKey: ["conversations"] }); qc.invalidateQueries({ queryKey: ["conversation", conversationId] }); },
    onError: (e: { response?: { data?: { detail?: string } } }) => setError(e?.response?.data?.detail || "Couldn't save the label."),
  });
  const add = () => {
    const v = draft.trim();
    setDraft(""); setAdding(false);
    if (v && !labels.some(l => l.toLowerCase() === v.toLowerCase())) save.mutate([...labels, v]);
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b border-[var(--haip-border)] px-4 py-1.5">
      {labels.map(l => (
        <span key={l} className="inline-flex items-center gap-1 rounded-full bg-[var(--haip-primary-tint)] py-0.5 pl-2.5 pr-1 text-[12px] font-medium text-primary">
          {l}
          <button type="button" aria-label={`Remove label ${l}`} onClick={() => save.mutate(labels.filter(x => x !== l))}
            className="flex size-6 items-center justify-center rounded-full"><X size={11} /></button>
        </span>
      ))}
      {adding ? (
        <input autoFocus value={draft} maxLength={24} placeholder="VIP, Wedding…" aria-label="New label"
          onChange={e => setDraft(e.target.value)} onBlur={add}
          onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); add(); } if (e.key === "Escape") { setDraft(""); setAdding(false); } }}
          className="min-h-8 w-32 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2 text-[16px] sm:text-[12.5px]" />
      ) : labels.length < 10 && (
        <button type="button" onClick={() => setAdding(true)} className="inline-flex min-h-8 items-center gap-1 text-[12.5px] font-medium text-[var(--haip-fg-muted)]">
          <Plus size={12} /> Label
        </button>
      )}
      {error && <span role="alert" className="text-[12px] text-[var(--haip-status-danger-fg)]">{error}</span>}
    </div>
  );
}
