"use client";
// Named contact lists ("Wedding enquiries 2026"): pick one to filter the page, create, rename, delete.
// Data: /messaging/contact-lists (services/wa_contacts.py).
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { List, Pencil, Plus, Trash2, Users } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { BottomSheet, SheetActions, sheetActionCls } from "@/components/ui/kit";
import { plural } from "./contactsHelpers";

export interface ContactList { id: string; name: string; count: number }

const chip = "inline-flex min-h-[44px] sm:min-h-[36px] items-center gap-1.5 px-3 rounded-full text-xs font-medium whitespace-nowrap transition-colors";
const inputCls = "w-full px-3 py-2.5 border border-[var(--haip-border)] rounded-xl text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-primary/30";

function errText(e: unknown, fallback: string): string {
  return (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}

export function ContactListsBar({ lists, loading, active, onPick, onToast }: {
  lists: ContactList[];
  loading: boolean;
  active: string | null;
  onPick: (id: string | null) => void;
  onToast: (msg: string, ok?: boolean) => void;
}) {
  const qc = useQueryClient();
  const [sheet, setSheet] = useState<null | { mode: "new" } | { mode: "rename"; list: ContactList } | { mode: "delete"; list: ContactList }>(null);
  const [name, setName] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["wa-contact-lists"] });

  const save = useMutation({
    mutationFn: () => sheet?.mode === "rename"
      ? api.patch(`/messaging/contact-lists/${sheet.list.id}`, { name })
      : api.post("/messaging/contact-lists", { name }),
    onSuccess: r => {
      refresh();
      onToast(sheet?.mode === "rename" ? `Renamed to "${r.data.name}"` : `Created "${r.data.name}". Tick contacts below and choose Add to list.`);
      if (sheet?.mode === "new") onPick(r.data.id);
      setSheet(null);
    },
    onError: e => onToast(errText(e, "Couldn't save the list."), false),
  });
  const remove = useMutation({
    mutationFn: (l: ContactList) => api.delete(`/messaging/contact-lists/${l.id}`),
    onSuccess: (_r, l) => {
      refresh();
      qc.invalidateQueries({ queryKey: ["wa-subscribers"] });
      if (active === l.id) onPick(null);
      onToast(`Deleted "${l.name}". The contacts are still here.`);
      setSheet(null);
    },
    onError: e => onToast(errText(e, "Couldn't delete the list."), false),
  });

  const open = (s: NonNullable<typeof sheet>) => { setName(s.mode === "rename" ? s.list.name : ""); setSheet(s); };
  const current = lists.find(l => l.id === active);

  return (
    <div className="mb-3">
      <div className="flex items-center gap-2 mb-1.5">
        <p className="text-xs font-semibold text-[var(--haip-fg-2)]">Lists</p>
        <p className="text-[11.5px] text-[var(--haip-fg-subtle)] truncate">Group contacts to message them together, e.g. &quot;Corporate HR contacts&quot;.</p>
      </div>
      {!loading && lists.length === 0 ? (
        <button type="button" onClick={() => open({ mode: "new" })}
          className="w-full flex items-center gap-3 rounded-xl border border-dashed border-[var(--haip-border)] px-4 py-3 text-left hover:bg-[var(--haip-surface)] min-h-[44px]">
          <List size={16} className="text-primary flex-shrink-0" />
          <span className="text-sm text-[var(--haip-fg-2)]">Group contacts to message them together. <span className="font-semibold text-primary">Create your first list</span></span>
        </button>
      ) : (
        <div className="flex gap-1.5 overflow-x-auto -mx-1 px-1 pb-1">
          <button type="button" onClick={() => onPick(null)} aria-pressed={!active}
            className={cn(chip, !active ? "bg-[var(--haip-tab-active-bg)] text-[var(--haip-tab-active-fg)]" : "border border-[var(--haip-border)] text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]")}>
            <Users size={12} /> Everyone
          </button>
          {lists.map(l => (
            <button key={l.id} type="button" onClick={() => onPick(l.id)} aria-pressed={active === l.id}
              className={cn(chip, active === l.id ? "bg-[var(--haip-tab-active-bg)] text-[var(--haip-tab-active-fg)]" : "border border-[var(--haip-border)] text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]")}>
              {l.name} <span className="tabular-nums opacity-70">{l.count.toLocaleString("en-IN")}</span>
            </button>
          ))}
          <button type="button" onClick={() => open({ mode: "new" })} className={cn(chip, "border border-dashed border-[var(--haip-border)] text-primary hover:bg-[var(--haip-surface)]")}>
            <Plus size={12} /> New list
          </button>
        </div>
      )}
      {current && (
        <div className="flex items-center gap-3 mt-1 text-[11.5px] text-[var(--haip-fg-subtle)]">
          <span>Showing {plural(current.count)} on &quot;{current.name}&quot;.</span>
          <button type="button" onClick={() => open({ mode: "rename", list: current })} className="inline-flex items-center gap-1 text-primary font-semibold min-h-[32px]"><Pencil size={11} /> Rename</button>
          <button type="button" onClick={() => open({ mode: "delete", list: current })} className="inline-flex items-center gap-1 text-[var(--haip-status-danger-fg)] font-semibold min-h-[32px]"><Trash2 size={11} /> Delete</button>
        </div>
      )}

      <BottomSheet
        open={!!sheet}
        onOpenChange={o => { if (!o) setSheet(null); }}
        title={sheet?.mode === "delete" ? `Delete "${sheet.list.name}"?` : sheet?.mode === "rename" ? "Rename list" : "New list"}
        description={sheet?.mode === "delete" ? `The ${plural(sheet.list.count)} on it stay in your contacts; only the list goes.` : "A name your team will recognise, e.g. \"Wedding enquiries 2026\"."}
        footer={sheet?.mode === "delete" ? (
          <SheetActions>
            <button type="button" className={sheetActionCls()} onClick={() => setSheet(null)}>Cancel</button>
            <button type="button" className={sheetActionCls(true)} disabled={remove.isPending} onClick={() => remove.mutate(sheet.list)}>Delete list</button>
          </SheetActions>
        ) : (
          <SheetActions>
            <button type="button" className={sheetActionCls()} onClick={() => setSheet(null)}>Cancel</button>
            <button type="button" className={sheetActionCls(true)} disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>
              {sheet?.mode === "rename" ? "Save" : "Create list"}
            </button>
          </SheetActions>
        )}
      >
        {sheet && sheet.mode !== "delete" && (
          <input autoFocus value={name} maxLength={80} onChange={e => setName(e.target.value)} aria-label="List name"
            onKeyDown={e => { if (e.key === "Enter" && name.trim()) save.mutate(); }}
            placeholder="Wedding enquiries 2026" className={inputCls} />
        )}
      </BottomSheet>
    </div>
  );
}
