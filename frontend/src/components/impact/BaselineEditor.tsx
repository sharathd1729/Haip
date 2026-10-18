"use client";
// The owner types the "before HAIP" figures here: value, the period it describes and where it comes from. Each save or removal
// is audited on the server. Managers see the figures read-only; money rows need revenue access.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Drawer } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { formatValue, type BaselineRow, type Unit } from "./types";

const field = "mt-1 w-full min-h-11 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base text-[var(--haip-fg)] focus:outline-none focus:ring-2 focus:ring-primary sm:min-h-10 sm:text-sm";
const UNIT_HINT: Record<Unit, string> = { minutes: "minutes", "%": "percent (0-100)", count: "number", inr: "rupees" };

function apiError(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0] && typeof d[0].msg === "string") return String(d[0].msg).replace(/^Value error, /, "");
  return "Could not save. Check the fields and try again.";
}

function Row({ row, canEdit, onSaved }: { row: BaselineRow; canEdit: boolean; onSaved: () => void }) {
  const { toast } = useToast();
  const b = row.baseline;
  const [value, setValue] = useState(b ? String(b.value) : "");
  const [period, setPeriod] = useState(b?.period_label ?? "");
  const [note, setNote] = useState(b?.source_note ?? "");
  const save = useMutation({
    mutationFn: () => api.put(`/dashboard/impact/baselines/${row.metric}`, { value: Number(value), period_label: period, source_note: note || null }),
    onSuccess: () => { toast({ variant: "success", title: `${row.label} saved` }); onSaved(); },
    onError: e => toast({ variant: "error", title: apiError(e) }),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/dashboard/impact/baselines/${row.metric}`),
    onSuccess: () => { setValue(""); setPeriod(""); setNote(""); toast({ variant: "success", title: `${row.label} removed` }); onSaved(); },
    onError: e => toast({ variant: "error", title: apiError(e) }),
  });

  if (row.restricted) {
    return <li className="py-3"><p className="text-sm font-semibold text-[var(--haip-fg)]">{row.label}</p><p className="text-[13px] text-[var(--haip-fg-subtle)]">Needs revenue access.</p></li>;
  }
  const valid = value.trim() !== "" && Number.isFinite(Number(value)) && Number(value) >= 0 && (row.unit !== "%" || Number(value) <= 100) && period.trim() !== "";
  if (!canEdit) {
    return (
      <li className="py-3">
        <p className="text-sm font-semibold text-[var(--haip-fg)]">{row.label}</p>
        <p className="text-[13px] text-[var(--haip-fg-subtle)]">{b ? `${formatValue(b.value, row.unit)} · ${b.period_label}${b.source_note ? ` · ${b.source_note}` : ""}` : "Not entered"}</p>
      </li>
    );
  }
  return (
    <li className="py-4">
      <p className="text-sm font-semibold text-[var(--haip-fg)]">{row.label}</p>
      <p className="mt-0.5 text-[12.5px] leading-relaxed text-[var(--haip-fg-subtle)]">{row.definition}</p>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="block text-xs font-medium text-[var(--haip-fg-subtle)]">Value ({UNIT_HINT[row.unit]})
          <input className={field} inputMode="decimal" value={value} onChange={e => setValue(e.target.value)} placeholder="e.g. 240" />
        </label>
        <label className="block text-xs font-medium text-[var(--haip-fg-subtle)]">Period it describes
          <input className={field} maxLength={80} value={period} onChange={e => setPeriod(e.target.value)} placeholder="Jan–Mar 2026, a typical month" />
        </label>
        <label className="block text-xs font-medium text-[var(--haip-fg-subtle)] sm:col-span-2">Where it comes from (optional, not published)
          <input className={field} maxLength={500} value={note} onChange={e => setNote(e.target.value)} placeholder="WhatsApp export, my estimate…" />
        </label>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" disabled={!valid || save.isPending} onClick={() => save.mutate()}
          className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          {save.isPending ? "Saving…" : "Save"}
        </button>
        {b && <button type="button" disabled={remove.isPending} onClick={() => remove.mutate()}
          className="min-h-11 rounded-lg border border-[var(--haip-border)] px-4 text-sm font-semibold text-[var(--haip-fg-muted)] disabled:opacity-50">Remove</button>}
      </div>
    </li>
  );
}

export function BaselineEditor({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const queryClient = useQueryClient();
  const { data, isPending, isError, refetch } = useQuery<{ metrics: BaselineRow[]; can_edit: boolean }>({
    queryKey: ["impact-baselines"], queryFn: () => api.get("/dashboard/impact/baselines").then(r => r.data), enabled: open,
  });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["impact-baselines"] });
    queryClient.invalidateQueries({ queryKey: ["impact"] });
  };
  return (
    <Drawer open={open} onOpenChange={onOpenChange} wide title="Before-HAIP figures"
      description="What things looked like before HAIP, in your own numbers. Shown as owner-entered next to what HAIP measures.">
      {isPending ? (
        <div className="space-y-3">{[0, 1, 2].map(i => <Skeleton key={i} className="h-24 rounded-xl" />)}</div>
      ) : isError || !data ? (
        <div role="alert" className="py-10 text-center">
          <p className="text-sm font-semibold text-[var(--haip-fg)]">Couldn&apos;t load the figures</p>
          <button type="button" onClick={() => refetch()} className="mt-3 min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground">Try again</button>
        </div>
      ) : (
        <>
          {!data.can_edit && <p className="mb-2 text-[13px] text-[var(--haip-fg-subtle)]">Only the owner can change these.</p>}
          <ul className="divide-y divide-[var(--haip-border)]">
            {data.metrics.map(row => <Row key={`${row.metric}-${row.baseline?.updated_at ?? "new"}`} row={row} canEdit={data.can_edit} onSaved={refresh} />)}
          </ul>
        </>
      )}
    </Drawer>
  );
}
