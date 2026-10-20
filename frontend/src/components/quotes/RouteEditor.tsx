"use client";
// Route editor (inside a quote and in the Routes tab). Saves a DRAFT destination record; an owner's save also publishes it.
// Anyone else's draft waits for approval by an owner or manager -- a quote can be previewed on it meanwhile, not saved.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, X } from "@/lib/icons";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { emptyRoute, kmToFirstNight, routeFromData, routeToData, slug, validateRoute } from "@/app/dashboard/quotes/quoteHelpers";
import type { Catalog, CatalogEntry, RouteForm } from "@/app/dashboard/quotes/types";
import { BTN, BTN_GHOST, BTN_PRIMARY, Callout, Field, INPUT, apiProblems } from "./ui";

export function RouteEditor({ catalog, entry, onSaved, onCancel }: {
  catalog: Catalog; entry: CatalogEntry | null; onSaved: (key: string) => void; onCancel: () => void;
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const source = entry ? (entry.draft ?? entry.live) : null;
  const [form, setForm] = useState<RouteForm>(() => (entry && source ? routeFromData(entry.key, source.data) : emptyRoute()));
  const [errors, setErrors] = useState<string[]>([]);
  const [savedDraft, setSavedDraft] = useState<{ id: string; key: string } | null>(null);
  const owner = catalog.permissions.is_owner;
  const set = (patch: Partial<RouteForm>) => setForm(f => ({ ...f, ...patch }));
  const total = form.places.reduce((s, p) => s + (Number(p.km) || 0), 0);
  const nightsAt = form.places.filter(p => p.overnight).length;

  const save = useMutation({
    mutationFn: async () => {
      const data = routeToData(form, (source?.data ?? {}) as Record<string, unknown>);
      let key = form.key;
      let recordId: string;
      const draftId = savedDraft?.id ?? entry?.draft?.record_id;
      if (draftId) {
        recordId = (await api.patch(`/business-data/records/${draftId}`, { data })).data.id;
        key = savedDraft?.key ?? entry!.key;
      } else {
        if (!key) {
          const base = slug(form.name) || "route";
          const taken = new Set(catalog.destinations.map(d => d.key));
          key = base;
          for (let i = 2; taken.has(key); i++) key = `${base}-${i}`;
        }
        recordId = (await api.post("/business-data/records", { kind: "destination", key, data, note: entry ? "Changed in the quote builder" : "New route from the quote builder" })).data.id;
      }
      setSavedDraft({ id: recordId, key: key! });                      // a failed publish must not create a second draft on retry
      if (owner) await api.post(`/business-data/records/${recordId}/publish`, {});
      return key!;
    },
    onSuccess: key => {
      qc.invalidateQueries({ queryKey: ["quote-catalog"] });
      toast({ variant: "success", title: owner ? "Route published" : "Route sent for approval",
        description: owner ? "Every agent can quote it now." : "You can price it in a quote now; saving the quote waits for approval." });
      onSaved(key);
    },
    onError: e => { const p = apiProblems(e); setErrors([p.message, ...p.problems]); },
  });

  const submit = () => {
    const problems = validateRoute(form);
    setErrors(problems);
    if (!problems.length) save.mutate();
  };

  const placeRow = (i: number) => {
    const p = form.places[i];
    const update = (patch: Partial<typeof p>) => set({ places: form.places.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
    return (
      <li key={i} className="grid grid-cols-[1.25rem_minmax(0,1fr)_4.5rem_auto_auto] items-center gap-2">
        <span className="num text-xs text-[var(--haip-fg-subtle)]">{i + 1}</span>
        <input aria-label={`Place ${i + 1}`} value={p.name} onChange={e => update({ name: e.target.value })} placeholder="Place" className={INPUT} />
        <input aria-label={`Km to place ${i + 1}`} value={p.km} inputMode="numeric" placeholder="km" onChange={e => update({ km: e.target.value.replace(/[^0-9.]/g, "") })} className={INPUT} />
        <label className="flex min-h-11 items-center gap-1.5 text-xs font-medium text-[var(--haip-fg-2)] sm:min-h-0">
          <input type="checkbox" checked={p.overnight} onChange={e => update({ overnight: e.target.checked })} className="h-5 w-5 accent-[var(--primary)] sm:h-4 sm:w-4" /> Night
        </label>
        <button type="button" aria-label={`Remove place ${i + 1}`} disabled={form.places.length <= 1} onClick={() => set({ places: form.places.filter((_, j) => j !== i) })}
          className="flex h-11 w-11 items-center justify-center rounded-lg text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-surface)] disabled:opacity-30 sm:h-8 sm:w-8"><X size={14} /></button>
      </li>
    );
  };

  return (
    <Card>
      <CardHeader title={entry ? `Change ${String(source?.data.name ?? entry.key)}` : "New route"}
        description={entry ? `Saves as a new version. Quotes already saved keep the version they were priced on.` : "Saved for every agent once approved."} />
      <CardBody className="space-y-4">
        {errors.length > 0 && <Callout tone="danger"><ul className="list-disc space-y-0.5 pl-4">{errors.map(e => <li key={e}>{e}</li>)}</ul></Callout>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Route name" htmlFor="re-name"><input id="re-name" value={form.name} maxLength={120} onChange={e => set({ name: e.target.value })} placeholder="e.g. Chikmagalur coffee trail" className={INPUT} /></Field>
          <Field label="Usual nights" htmlFor="re-nights"><input id="re-nights" inputMode="numeric" value={form.usual_nights} onChange={e => set({ usual_nights: e.target.value.replace(/\D/g, "").slice(0, 2) })} className={INPUT} /></Field>
          <Field label="Short description" htmlFor="re-desc" className="sm:col-span-2"><input id="re-desc" value={form.description} maxLength={2000} onChange={e => set({ description: e.target.value })} placeholder="What the guest gets" className={INPUT} /></Field>
          <Field label="Km from base to the first night" htmlFor="re-kmb" hint={`Leave empty to use ${kmToFirstNight(form)} km from the places below.`}>
            <input id="re-kmb" inputMode="numeric" value={form.km_from_base} onChange={e => set({ km_from_base: e.target.value.replace(/[^0-9.]/g, "") })} className={INPUT} />
          </Field>
          <Field label="Driving hours from base" htmlFor="re-hrs"><input id="re-hrs" inputMode="decimal" value={form.hours_from_base} onChange={e => set({ hours_from_base: e.target.value.replace(/[^0-9.]/g, "") })} className={INPUT} /></Field>
        </div>
        <div className="space-y-2">
          <p className="text-xs font-semibold text-[var(--haip-fg-2)]">Places in order, with km from the previous one (end with the return to base)</p>
          <ol className="space-y-2">{form.places.map((_, i) => placeRow(i))}</ol>
          <button type="button" className={BTN_GHOST} onClick={() => set({ places: [...form.places, { name: "", km: "", overnight: false }] })}><Plus size={13} /> Add a place</button>
        </div>
        <div className="space-y-2">
          <p className="text-xs font-semibold text-[var(--haip-fg-2)]">Optional sights guests can add (km there and back)</p>
          {form.sights.length === 0 && <p className="text-xs text-[var(--haip-fg-subtle)]">None yet.</p>}
          <ul className="space-y-2">
            {form.sights.map((s, i) => (
              <li key={i} className="grid grid-cols-[minmax(0,1fr)_4.5rem_auto] items-center gap-2">
                <input aria-label={`Sight ${i + 1}`} value={s.name} placeholder="Sight" onChange={e => set({ sights: form.sights.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} className={INPUT} />
                <input aria-label={`Km for sight ${i + 1}`} value={s.km} inputMode="numeric" placeholder="km" onChange={e => set({ sights: form.sights.map((x, j) => (j === i ? { ...x, km: e.target.value.replace(/[^0-9.]/g, "") } : x)) })} className={INPUT} />
                <button type="button" aria-label={`Remove sight ${i + 1}`} onClick={() => set({ sights: form.sights.filter((_, j) => j !== i) })}
                  className="flex h-11 w-11 items-center justify-center rounded-lg text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-surface)] sm:h-8 sm:w-8"><X size={14} /></button>
              </li>
            ))}
          </ul>
          <button type="button" className={BTN_GHOST} onClick={() => set({ sights: [...form.sights, { name: "", km: "" }] })}><Plus size={13} /> Add a sight</button>
        </div>
        <p className="num text-[13px]"><b>{total.toLocaleString("en-IN")} km</b> <span className="text-[var(--haip-fg-subtle)]">· {nightsAt} overnight stop{nightsAt === 1 ? "" : "s"} · distances are your estimate</span></p>
        <p className="text-xs text-[var(--haip-fg-subtle)]">{owner ? "You are the owner, so this publishes straight away." : "Goes to an owner or manager for approval. You can price it in a quote now; saving the quote waits for approval."}</p>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={submit} disabled={save.isPending} className={BTN_PRIMARY}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : owner ? "Publish route" : "Save and send for approval"}
          </button>
          <button type="button" onClick={onCancel} className={BTN}>Cancel</button>
        </div>
      </CardBody>
    </Card>
  );
}
