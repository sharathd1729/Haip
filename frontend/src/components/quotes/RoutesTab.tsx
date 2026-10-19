"use client";
// Routes: every destination agents can quote (published and waiting approval), with edit, approve and "quote it".
// Routes are versioned business records: a change is a new version; quotes already saved keep the version they were priced on.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "@/lib/icons";
import { timeAgo } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { DataTable, StatusPill, type Column } from "@/components/ui/kit";
import { canApprove, entryData, entryName, entryState, kmText, routeKm, routeSights } from "@/app/dashboard/quotes/quoteHelpers";
import type { Catalog, CatalogEntry } from "@/app/dashboard/quotes/types";
import api from "@/lib/api";
import { RouteEditor } from "./RouteEditor";
import { BTN, BTN_PRIMARY, apiProblems } from "./ui";

export function StatusFor({ e }: { e: CatalogEntry }) {
  const s = entryState(e);
  if (s === "new") return <StatusPill tone="warning">New, waiting approval</StatusPill>;
  if (s === "change") return <StatusPill tone="warning">v{(e.live?.version ?? 0) + 1} waiting approval</StatusPill>;
  return <StatusPill tone="success">Published v{e.live?.version}</StatusPill>;
}

export function lastChange(e: CatalogEntry): string {
  const r = e.draft ?? e.live;
  if (!r) return "—";
  const who = r.created_by_name ?? "Someone";
  return `${who} · ${timeAgo(e.draft ? r.created_at : r.published_at ?? r.created_at)}`;
}

/** Approve (publish) or reject a waiting draft. The server refuses an approver's own draft unless they are the owner. */
export function useReview(kindLabel: string) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const done = () => qc.invalidateQueries({ queryKey: ["quote-catalog"] });
  const approve = useMutation({
    mutationFn: (recordId: string) => api.post(`/business-data/records/${recordId}/publish`, {}),
    onSuccess: () => { done(); toast({ variant: "success", title: `${kindLabel} approved`, description: "Published for every agent. New quotes use it from now." }); },
    onError: e => { const p = apiProblems(e); toast({ variant: "error", title: "Couldn't approve", description: [p.message, ...p.problems].join(" ") }); },
  });
  const reject = useMutation({
    mutationFn: (recordId: string) => api.post(`/business-data/records/${recordId}/reject`, { reason: "Not approved in the quote builder" }),
    onSuccess: () => { done(); toast({ variant: "success", title: "Change turned down", description: "The published version is unchanged." }); },
    onError: e => toast({ variant: "error", title: "Couldn't turn it down", description: apiProblems(e).message }),
  });
  return { approve, reject };
}

export function RoutesTab({ catalog, onQuote }: { catalog: Catalog; onQuote?: (key: string) => void }) {
  const [editing, setEditing] = useState<null | { entry: CatalogEntry | null }>(null);
  const { approve, reject } = useReview("Route");
  const perms = catalog.permissions;
  const busy = approve.isPending || reject.isPending;

  const columns: Column<CatalogEntry>[] = [
    { key: "name", header: "Route", cell: e => (
      <div className="min-w-0">
        <p className="font-semibold">{entryName(e)}</p>
        {entryData(e).description ? <p className="line-clamp-1 text-xs text-[var(--haip-fg-subtle)]">{String(entryData(e).description)}</p> : null}
      </div>
    ) },
    { key: "nights", header: "Nights", hideBelow: "md", cell: e => <span className="num">{String(entryData(e).usual_nights ?? "—")}</span> },
    { key: "km", header: "Km", align: "right", cell: e => <span className="num">{kmText(routeKm(entryData(e)))}</span> },
    { key: "sights", header: "Sights", hideBelow: "md", cell: e => <span className="num">{routeSights(entryData(e)).length}</span> },
    { key: "status", header: "Status", cell: e => <StatusFor e={e} /> },
    { key: "change", header: "Last change", hideBelow: "lg", cell: e => <span className="text-xs text-[var(--haip-fg-subtle)]">{lastChange(e)}</span> },
    { key: "act", header: <span className="sr-only">Actions</span>, cell: e => (
      <div className="flex flex-wrap justify-end gap-1.5">
        {e.draft && canApprove(e.draft, perms) && (
          <>
            <button type="button" className={BTN_PRIMARY} disabled={busy} onClick={() => approve.mutate(e.draft!.record_id)}>
              {approve.isPending && approve.variables === e.draft.record_id ? <Loader2 size={13} className="animate-spin" /> : "Approve"}
            </button>
            <button type="button" className={BTN} disabled={busy} onClick={() => reject.mutate(e.draft!.record_id)}>Turn down</button>
          </>
        )}
        {perms.can_draft && <button type="button" className={BTN} onClick={() => setEditing({ entry: e })}>Edit</button>}
        {perms.can_quote && onQuote && <button type="button" className={BTN} onClick={() => onQuote(e.key)}>Quote it</button>}
      </div>
    ) },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-2xl text-[13px] text-[var(--haip-fg-subtle)]">
          Every route agents can quote. Add new ones as guests ask for them. A change made by anyone but the owner waits for an owner or manager to approve it.
        </p>
        {perms.can_draft && <button type="button" className={BTN_PRIMARY} onClick={() => setEditing({ entry: null })}><Plus size={14} /> New route</button>}
      </div>
      {editing && <RouteEditor key={editing.entry?.key ?? "new"} catalog={catalog} entry={editing.entry} onCancel={() => setEditing(null)} onSaved={() => setEditing(null)} />}
      <DataTable columns={columns} rows={catalog.destinations} rowKey={e => e.key}
        empty={{ title: "No routes yet", hint: perms.can_draft ? "Add the first route: places in order with km, and the sights guests can add." : "Ask a manager to add routes." }} />
      {!perms.can_publish && perms.can_draft && <p className="text-xs text-[var(--haip-fg-subtle)]">Your changes go to an owner or manager for approval.</p>}
    </div>
  );
}
