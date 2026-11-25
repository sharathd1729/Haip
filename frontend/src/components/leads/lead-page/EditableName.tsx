"use client";
// The guest's name, renamed in place on the lead page (PATCH /inquiries/{id} guest_name): the pencil opens a box,
// Enter or leaving the box saves, Escape cancels. The name lives on the guest, so every lead of theirs shows the change.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Pencil } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";

export function EditableName({ inquiryId, name, canEdit, className }: {
  inquiryId: string; name: string | null | undefined; canEdit: boolean; className?: string;
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const save = useMutation({
    mutationFn: (guest_name: string) => api.patch(`/inquiries/${inquiryId}`, { guest_name }),
    onSuccess: () => {
      toast({ variant: "success", title: "Name saved" });
      qc.invalidateQueries({ queryKey: ["lead", inquiryId] });
      qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] });
      qc.invalidateQueries({ queryKey: ["leads"] });
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Name not saved", description: typeof d === "string" ? d : "Please try again." });
    },
  });

  function commit() {
    setEditing(false);
    const v = draft.trim();
    if (!v) { toast({ variant: "error", title: "The name cannot be empty" }); return; }
    if (v !== (name ?? "")) save.mutate(v);
  }

  if (editing) {
    return (
      <input autoFocus value={draft} maxLength={120} aria-label="Guest name" autoComplete="off"
        onChange={e => setDraft(e.target.value)} onBlur={commit}
        onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); commit(); } if (e.key === "Escape") setEditing(false); }}
        className="min-h-11 w-full min-w-0 rounded-lg border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-2.5 text-[16px] font-semibold text-[var(--haip-fg)]" />
    );
  }
  return (
    <div className="flex min-w-0 items-center gap-1">
      <h1 className={cn("min-w-0", className)}>{name}</h1>
      {canEdit && (
        <button type="button" onClick={() => { setDraft(name ?? ""); setEditing(true); }} aria-label="Edit the guest's name"
          title="Edit name" disabled={save.isPending}
          className="grid size-11 shrink-0 place-items-center rounded-lg text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-surface)] hover:text-[var(--haip-fg)]">
          <Pencil size={15} aria-hidden />
        </button>
      )}
    </div>
  );
}
