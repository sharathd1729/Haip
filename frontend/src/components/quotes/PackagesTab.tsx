"use client";
// Packages: the plans agents quote from, edited with the same typed editor as the Knowledge Base (businessDataSpecs.ts).
// A save is a draft; the owner's save publishes it, anyone else's waits for an owner or manager to approve.
import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, Drawer, EmptyState } from "@/components/ui/kit";
import { FieldEditor, type EditorContext } from "@/components/knowledge/FieldEditor";
import { SPEC_BY_KIND, blankFor, fromPayload, toPayload, type Json } from "@/components/knowledge/businessDataSpecs";
import { canApprove, entryData, entryName, packageTag, slug } from "@/app/dashboard/quotes/quoteHelpers";
import type { Catalog, CatalogEntry } from "@/app/dashboard/quotes/types";
import api from "@/lib/api";
import { StatusFor, lastChange, useReview } from "./RoutesTab";
import { BTN, BTN_PRIMARY, Callout, INPUT, apiProblems } from "./ui";

const SPEC = SPEC_BY_KIND.package;

export function PackagesTab({ catalog }: { catalog: Catalog }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const perms = catalog.permissions;
  const { approve, reject } = useReview("Package");
  const [editing, setEditing] = useState<null | { entry: CatalogEntry | null; key: string; value: Json; note: string; recordId?: string }>(null);
  const [problems, setProblems] = useState<string[]>([]);

  const ctx: EditorContext = useMemo(() => ({
    destinations: catalog.destinations.filter(d => d.live).map(d => ({ value: d.key, label: entryName(d) })),
    packages: catalog.packages.filter(p => p.live).map(p => ({ value: p.key, label: entryName(p) })),
    vehicles: catalog.vehicles.map(v => ({ value: v.id, label: v.name })),
  }), [catalog]);

  const open = (entry: CatalogEntry | null) => {
    setProblems([]);
    const base = entry ? (entry.draft ?? entry.live) : null;
    setEditing({ entry, key: entry?.key ?? "", note: "", value: base ? fromPayload(SPEC.fields, base.data) : blankFor(SPEC.fields) });
  };

  const save = useMutation({
    mutationFn: async () => {
      const e = editing!;
      const data = toPayload(SPEC.fields, e.value);
      const note = e.note || null;
      const draftId = e.recordId ?? e.entry?.draft?.record_id;
      const rec = draftId
        ? (await api.patch(`/business-data/records/${draftId}`, { data, note })).data
        : (await api.post("/business-data/records", { kind: "package", key: e.key, data, note })).data;
      setEditing(cur => cur && { ...cur, recordId: rec.id });         // a failed publish must not create a second draft on retry
      if (perms.is_owner) await api.post(`/business-data/records/${rec.id}/publish`, {});
      return rec;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["quote-catalog"] });
      setEditing(null);
      toast({ variant: "success", title: perms.is_owner ? "Package published" : "Sent for approval",
        description: perms.is_owner ? "New quotes use it from now. Quotes already saved keep their prices." : "Quotes keep using the published version until it is approved." });
    },
    onError: e => { const p = apiProblems(e); setProblems([p.message, ...p.problems]); qc.invalidateQueries({ queryKey: ["quote-catalog"] }); },
  });

  const busy = approve.isPending || reject.isPending;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-2xl text-[13px] text-[var(--haip-fg-subtle)]">The plans agents quote from. Edit a price or add a package; quotes already saved keep the version they used.</p>
        {perms.can_draft && <button type="button" className={BTN_PRIMARY} onClick={() => open(null)}><Plus size={14} /> New package</button>}
      </div>
      {catalog.packages.length === 0 ? (
        <Card><EmptyState title="No packages yet" hint="Add the day rate first: price a day, guests and km included, extra guest and km charges." /></Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {catalog.packages.map(p => (
            <Card key={p.key}>
              <CardBody className="space-y-2">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-semibold">{entryName(p)}</p>
                    <p className="num text-[13px] font-semibold text-primary">{packageTag(entryData(p))}</p>
                  </div>
                  <StatusFor e={p} />
                </div>
                {entryData(p).summary ? <p className="line-clamp-2 text-xs text-[var(--haip-fg-subtle)]">{String(entryData(p).summary)}</p> : null}
                <p className="text-xs text-[var(--haip-fg-subtle)]">{lastChange(p)}</p>
                <div className="flex flex-wrap gap-2">
                  {perms.can_draft && <button type="button" className={BTN} onClick={() => open(p)}>{p.draft ? "Edit the waiting change" : "Edit"}</button>}
                  {p.draft && canApprove(p.draft, perms) && (
                    <>
                      <button type="button" className={BTN_PRIMARY} disabled={busy} onClick={() => approve.mutate(p.draft!.record_id)}>
                        {approve.isPending && approve.variables === p.draft.record_id ? <Loader2 size={13} className="animate-spin" /> : "Approve"}
                      </button>
                      <button type="button" className={BTN} disabled={busy} onClick={() => reject.mutate(p.draft!.record_id)}>Turn down</button>
                    </>
                  )}
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      <Drawer wide open={!!editing} onOpenChange={o => { if (!o) setEditing(null); }}
        title={editing?.entry ? `Edit ${entryName(editing.entry)}` : "New package"}
        description={perms.is_owner ? "Publishing makes this the price for new quotes from today." : "Saved as a draft for an owner or manager to approve. Until then, quotes use the current version."}
        footer={editing && (
          <div className="flex w-full flex-wrap justify-end gap-2">
            <button type="button" className={BTN} onClick={() => setEditing(null)}>Cancel</button>
            <button type="button" className={BTN_PRIMARY} disabled={save.isPending || !editing.key} onClick={() => save.mutate()}>
              {save.isPending ? <Loader2 size={14} className="animate-spin" /> : perms.is_owner ? "Publish" : "Send for approval"}
            </button>
          </div>
        )}>
        {editing && (
          <div className="space-y-5">
            {problems.length > 0 && <Callout tone="danger"><ul className="list-disc space-y-0.5 pl-4">{problems.map(x => <li key={x}>{x}</li>)}</ul></Callout>}
            {!editing.entry && (
              <div className="space-y-1">
                <label htmlFor="pk-key" className="block text-xs font-semibold text-[var(--haip-fg-2)]">Short name used in links</label>
                <input id="pk-key" value={editing.key} onChange={e => setEditing({ ...editing, key: slug(e.target.value) })} placeholder="e.g. day-rate" className={INPUT} />
                <p className="text-[11px] text-[var(--haip-fg-subtle)]">Lowercase letters, numbers and dashes. It cannot be changed later.</p>
              </div>
            )}
            <FieldEditor fields={SPEC.fields} value={editing.value} ctx={ctx}
              onChange={v => setEditing(cur => cur && ({ ...cur, value: v, key: !cur.entry && !cur.key && v.name ? slug(String(v.name)) : cur.key }))} />
            <div className="space-y-1">
              <label htmlFor="pk-note" className="block text-xs font-semibold text-[var(--haip-fg-2)]">What changed and why (kept in the history)</label>
              <input id="pk-note" value={editing.note} maxLength={500} onChange={e => setEditing({ ...editing, note: e.target.value })} className={INPUT} />
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
