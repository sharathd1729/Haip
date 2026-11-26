"use client";
// Bar shown while contacts are ticked: tag, list, drip, opt out, export. Every action is confirmed with the count and
// toasts what changed. Backend: /messaging/subscribers/{bulk,enrol,export} (services/wa_contacts.py).
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, List, Play, Tag, UserX, X } from "@/lib/icons";
import api from "@/lib/api";
import { BottomSheet, SheetActions, sheetActionCls } from "@/components/ui/kit";
import {
  bulkTarget, confirmLabel, enrolToast, plural, resultToast,
  type BulkAction, type ContactFilter, type EnrolResult,
} from "./contactsHelpers";
import type { ContactList } from "./ContactListsBar";

interface Flow { id: string; name: string; is_active: boolean }

const ACTIONS: { action: BulkAction; label: string; icon: typeof Tag; hint: string }[] = [
  { action: "add_tag", label: "Add tag", icon: Tag, hint: "A short word to find them later, e.g. vip or wedding." },
  { action: "remove_tag", label: "Remove tag", icon: Tag, hint: "Takes this tag off everyone picked." },
  { action: "add_to_list", label: "Add to list", icon: List, hint: "Puts them on a list you can send a campaign to." },
  { action: "remove_from_list", label: "Remove from list", icon: List, hint: "Takes them off the list. They stay in your contacts." },
  { action: "enrol", label: "Start a drip", icon: Play, hint: "Starts a switched-on flow for each person. Only people who are opted in and already in your guest list get it." },
  { action: "export", label: "Export", icon: Download, hint: "A spreadsheet of numbers, names, tags and lists." },
  { action: "opt_out", label: "Opt out", icon: UserX, hint: "They stop getting campaigns. Only they can opt back in." },
];

const field = "w-full px-3 py-2.5 border border-[var(--haip-border)] rounded-xl text-base sm:text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/30";

function saveBlob(data: Blob, filename: string) {
  const url = URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function BulkActionBar({ selected, allMatching, matchingCount, filter, lists, onSelectAll, onClear, onDone, onToast }: {
  selected: string[];
  allMatching: boolean;
  matchingCount: number | undefined;
  filter: ContactFilter;
  lists: ContactList[];
  onSelectAll: () => void;
  onClear: () => void;
  onDone: () => void;
  onToast: (msg: string, ok?: boolean) => void;
}) {
  const [action, setAction] = useState<BulkAction | null>(null);
  const [value, setValue] = useState("");
  const count = allMatching ? matchingCount ?? 0 : selected.length;
  const target = bulkTarget(selected, allMatching, filter);

  const { data: flows = [] } = useQuery<Flow[]>({
    queryKey: ["wa-flows"],
    queryFn: () => api.get("/messaging/flows").then(r => r.data),
    enabled: action === "enrol",
    staleTime: 60_000,
  });
  const activeFlows = flows.filter(f => f.is_active);

  const needsList = action === "add_to_list" || action === "remove_from_list";
  const valueLabel = needsList ? lists.find(l => l.id === value)?.name
    : action === "enrol" ? activeFlows.find(f => f.id === value)?.name
    : value.trim();
  const ready = action === "opt_out" || action === "export" || !!valueLabel;

  const run = useMutation({
    mutationFn: async () => {
      if (action === "export") {
        const r = await api.post("/messaging/subscribers/export", target, { responseType: "blob" });
        saveBlob(r.data, "whatsapp-contacts.csv");
        return resultToast("export", count, count);
      }
      if (action === "enrol") {
        const r = await api.post<EnrolResult>("/messaging/subscribers/enrol", { ...target, flow_id: value });
        return enrolToast(r.data, valueLabel ?? "the flow");
      }
      const r = await api.post("/messaging/subscribers/bulk", { ...target, action, value: needsList ? value : value.trim() || undefined });
      return resultToast(action!, r.data.changed, r.data.selected, valueLabel);
    },
    onSuccess: msg => { onToast(msg); setAction(null); onDone(); },
    onError: (e: unknown) => onToast((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "That didn't work. Nothing was changed.", false),
  });

  const meta = ACTIONS.find(a => a.action === action);
  const showSelectAll = !allMatching && matchingCount !== undefined && matchingCount > selected.length;

  return (
    <div className="sticky top-0 z-10 bg-[var(--haip-primary-tint)] border-b border-[var(--haip-border)] px-4 sm:px-6 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span className="font-semibold text-[var(--haip-fg)]">{plural(count)} picked</span>
        {showSelectAll && (
          <button type="button" onClick={onSelectAll} className="text-primary font-semibold underline min-h-[32px]">
            Pick all {plural(matchingCount!)} matching
          </button>
        )}
        <button type="button" onClick={onClear} className="inline-flex items-center gap-1 text-[var(--haip-fg-muted)] min-h-[32px]"><X size={12} /> Clear</button>
      </div>
      <div className="flex gap-1.5 overflow-x-auto pb-1 mt-1 -mx-1 px-1">
        {ACTIONS.map(a => (
          <button key={a.action} type="button" onClick={() => { setValue(""); setAction(a.action); }}
            className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-xl border px-3 min-h-[44px] sm:min-h-[36px] text-xs font-medium bg-white hover:bg-[var(--haip-surface)] ${a.action === "opt_out" ? "border-[var(--haip-status-danger-border)] text-[var(--haip-status-danger-fg)]" : "border-[var(--haip-border)] text-[var(--haip-fg-2)]"}`}>
            <a.icon size={13} /> {a.label}
          </button>
        ))}
      </div>

      <BottomSheet
        open={!!action}
        onOpenChange={o => { if (!o) setAction(null); }}
        title={meta ? `${meta.label}: ${plural(count)}` : ""}
        description={meta?.hint}
        footer={(
          <SheetActions>
            <button type="button" className={sheetActionCls()} onClick={() => setAction(null)}>Cancel</button>
            <button type="button" className={sheetActionCls(true)} disabled={!ready || run.isPending || count === 0} onClick={() => run.mutate()}>
              {run.isPending ? "Working…" : meta?.label}
            </button>
          </SheetActions>
        )}
      >
        <div className="space-y-3">
          {(action === "add_tag" || action === "remove_tag") && (
            <input autoFocus value={value} maxLength={40} onChange={e => setValue(e.target.value)} placeholder="vip" aria-label="Tag" className={field} />
          )}
          {needsList && (lists.length === 0
            ? <p className="text-sm text-[var(--haip-fg-subtle)]">You have no lists yet. Create one with &quot;New list&quot; above the contacts.</p>
            : (
              <select value={value} onChange={e => setValue(e.target.value)} aria-label="List" className={field}>
                <option value="">Choose a list</option>
                {lists.map(l => <option key={l.id} value={l.id}>{l.name} ({l.count.toLocaleString("en-IN")})</option>)}
              </select>
            ))}
          {action === "enrol" && (activeFlows.length === 0
            ? <p className="text-sm text-[var(--haip-fg-subtle)]">No flow is switched on. Turn one on in Flows and drips first.</p>
            : (
              <select value={value} onChange={e => setValue(e.target.value)} aria-label="Flow" className={field}>
                <option value="">Choose a flow</option>
                {activeFlows.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            ))}
          {action && ready && <p className="text-sm font-medium text-[var(--haip-fg)]">{confirmLabel(action, count, valueLabel)}</p>}
        </div>
      </BottomSheet>
    </div>
  );
}
