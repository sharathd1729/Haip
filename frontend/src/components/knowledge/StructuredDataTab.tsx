"use client";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, History, Loader2, Plus, RotateCcw } from "@/lib/icons";
import api from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, Drawer, EmptyState, StatusPill, Tabs } from "@/components/ui/kit";
import { FieldEditor, type EditorContext } from "./FieldEditor";
import { KIND_SPECS, SPEC_BY_KIND, blankFor, fromPayload, toPayload, type Json } from "./businessDataSpecs";

interface BRecord {
  id: string; kind: string; key: string; version: number; status: string; data: Json;
  effective_from?: string | null; effective_to?: string | null; change_note?: string | null;
  created_by?: string | null; created_at?: string; published_by?: string | null; published_at?: string | null; rejected_reason?: string | null;
}
interface Group { kind: string; key: string; live: BRecord | null; scheduled: BRecord | null; draft: BRecord | null; latest_version: number }
interface Check { errors: string[]; warnings: string[] }
interface Change { path: string; old: unknown; new: unknown }

function apiProblems(e: unknown): { message: string; problems: string[] } {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (d && typeof d === "object" && "message" in d) {
    const o = d as { message: string; problems?: string[] };
    return { message: o.message, problems: o.problems ?? [] };
  }
  return { message: typeof d === "string" ? d : "Something went wrong. Try again.", problems: [] };
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 58);
const show = (v: unknown) => (v == null || v === "" ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));

export function StructuredDataTab() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [kind, setKind] = useState(KIND_SPECS[0].kind);
  const [editing, setEditing] = useState<null | { kind: string; key: string; isNew: boolean; recordId?: string; value: Json; note: string; effective: string }>(null);
  const [review, setReview] = useState<null | { check: Check; changes: Change[] }>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [historyOf, setHistoryOf] = useState<null | { kind: string; key: string }>(null);

  const { data: groups, isLoading, isError, refetch } = useQuery<Group[]>({
    queryKey: ["business-data"], queryFn: () => api.get("/business-data/records").then(r => r.data), retry: 1,
  });
  const { data: props = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["properties-lite"], queryFn: () => api.get("/properties").then(r => r.data), staleTime: 5 * 60_000,
  });
  const spec = SPEC_BY_KIND[kind];
  const label = (g: Group) => String(g.live?.data?.name ?? g.draft?.data?.name ?? g.scheduled?.data?.name ?? g.key);
  const ctx: EditorContext = useMemo(() => {
    const pick = (k: string) => (groups ?? []).filter(g => g.kind === k && g.live).map(g => ({ value: g.key, label: label(g) }));
    return { destinations: pick("destination"), packages: pick("package"), vehicles: props.map(p => ({ value: p.id, label: p.name })) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups, props]);
  const counts = (k: string) => (groups ?? []).filter(g => g.kind === k && (g.live || g.scheduled)).length;
  const rows = (groups ?? []).filter(g => g.kind === kind);

  const refresh = () => qc.invalidateQueries({ queryKey: ["business-data"] });
  const fail = (title: string) => (e: unknown) => {
    const p = apiProblems(e);
    setProblems(p.problems);
    toast({ variant: "error", title, description: p.message });
  };

  const open = (g: Group | null) => {
    setReview(null); setProblems([]);
    if (g === null) {
      setEditing({ kind, key: spec.singleton ? "default" : "", isNew: true, value: blankFor(spec.fields), note: "", effective: "" });
      return;
    }
    const base = g.draft ?? g.live ?? g.scheduled;
    setEditing({
      kind: g.kind, key: g.key, isNew: false, recordId: g.draft?.id, note: g.draft?.change_note ?? "",
      value: base ? fromPayload(SPEC_BY_KIND[g.kind].fields, base.data) : blankFor(SPEC_BY_KIND[g.kind].fields), effective: "",
    });
  };

  // Saves the draft (creating it on first save) and returns its id.
  const save = useMutation({
    mutationFn: async () => {
      const e = editing!;
      const data = toPayload(SPEC_BY_KIND[e.kind].fields, e.value);
      const r = e.recordId
        ? await api.patch(`/business-data/records/${e.recordId}`, { data, note: e.note || null })
        : await api.post("/business-data/records", { kind: e.kind, key: e.key, data, note: e.note || null });
      return r.data as BRecord;
    },
    onSuccess: rec => { setEditing(e => (e ? { ...e, recordId: rec.id, key: rec.key, isNew: false } : e)); setProblems([]); refresh(); },
    onError: fail("Couldn't save the draft"),
  });

  const startReview = useMutation({
    mutationFn: async () => {
      const rec = await save.mutateAsync();
      const [check, diff] = await Promise.all([
        api.post(`/business-data/records/${rec.id}/validate`).then(r => r.data as Check),
        api.get(`/business-data/records/${rec.id}/diff`).then(r => r.data as { changes: Change[] }),
      ]);
      return { check, changes: diff.changes };
    },
    onSuccess: setReview,
  });

  const publish = useMutation({
    mutationFn: () => api.post(`/business-data/records/${editing!.recordId}/publish`, editing!.effective ? { effective_from: editing!.effective } : {}).then(r => r.data as BRecord),
    onSuccess: rec => {
      refresh(); setEditing(null); setReview(null);
      toast({ variant: "success", title: "Published", description: `Version ${rec.version} is live from ${rec.effective_from}. The AI uses it immediately; nothing needs re-indexing.` });
    },
    onError: fail("Couldn't publish"),
  });

  const discard = useMutation({
    mutationFn: () => api.post(`/business-data/records/${editing!.recordId}/reject`, {}),
    onSuccess: () => { refresh(); setEditing(null); setReview(null); toast({ variant: "success", title: "Draft discarded", description: "The live version is unchanged." }); },
    onError: fail("Couldn't discard"),
  });

  const deactivate = useMutation({
    mutationFn: (g: { kind: string; key: string }) => api.post(`/business-data/records/${g.kind}/${g.key}/deactivate`, {}),
    onSuccess: () => { refresh(); toast({ variant: "success", title: "Switched off", description: "The AI no longer uses it. Earlier quotes keep their original terms." }); },
    onError: fail("Couldn't switch it off"),
  });

  const draftBusy = save.isPending || startReview.isPending;
  const set = (patch: Partial<NonNullable<typeof editing>>) => { setEditing(e => (e ? { ...e, ...patch } : e)); setReview(null); };

  return (
    <div className="flex-1 overflow-y-auto p-4 sm:p-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <p className="text-[13px] leading-snug text-[var(--haip-fg-subtle)]">
          Exact prices, rules and routes the AI is allowed to state. Changes stay as drafts — the AI never sees a draft — until you publish them.
          Published changes apply to new answers and quotes straight away; quotes already sent keep the terms they were issued with.
        </p>
        <Tabs label="Kind of data" value={kind} onChange={setKind} items={KIND_SPECS.map(k => ({ value: k.kind, label: k.plural, count: counts(k.kind) || undefined }))} />
        <p className="text-xs text-[var(--haip-fg-subtle)]">{spec.blurb}</p>

        {isLoading ? (
          <div className="space-y-2">{[1, 2].map(i => <Skeleton key={i} className="h-20 rounded-2xl" />)}</div>
        ) : isError ? (
          <div role="alert" className="flex items-start gap-3 rounded-xl border border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] px-4 py-3 text-sm text-[var(--haip-status-danger-fg)]">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <span className="flex-1">Couldn&apos;t load your business data.</span>
            <button onClick={() => refetch()} className="min-h-9 rounded-lg border border-current px-3 text-xs font-semibold">Retry</button>
          </div>
        ) : (
          <>
            {rows.length === 0 && (
              <Card><EmptyState title={`No ${spec.plural.toLowerCase()} yet`} hint="Until something is published, the AI says the team will confirm instead of answering from here."
                action={<button onClick={() => open(null)} className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground">Add {spec.label.toLowerCase()}</button>} /></Card>
            )}
            {rows.map(g => {
              const shown = g.live ?? g.scheduled;
              return (
                <Card key={g.key}>
                  <CardBody className="flex flex-wrap items-start gap-3">
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="truncate text-sm font-semibold text-[var(--haip-fg)]">{label(g)}</p>
                      {!spec.singleton && <p className="text-[11px] text-[var(--haip-fg-subtle)]">{g.key}</p>}
                      {shown && <p className="text-xs text-[var(--haip-fg-subtle)]">{spec.summary(shown.data)}</p>}
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {g.live && <StatusPill tone="success">Live · v{g.live.version}</StatusPill>}
                        {g.scheduled && <StatusPill tone="info">v{g.scheduled.version} from {g.scheduled.effective_from}</StatusPill>}
                        {g.draft && <StatusPill tone="warning">Draft · not used by the AI</StatusPill>}
                        {!g.live && !g.scheduled && !g.draft && <StatusPill>Switched off</StatusPill>}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button onClick={() => open(g)} className="min-h-11 rounded-lg border border-[var(--haip-border)] px-3 text-xs font-semibold hover:bg-[var(--haip-surface)] sm:min-h-9">
                        {g.draft ? "Continue draft" : "Edit"}
                      </button>
                      <button onClick={() => setHistoryOf({ kind: g.kind, key: g.key })} className="flex min-h-11 items-center gap-1 rounded-lg border border-[var(--haip-border)] px-3 text-xs font-semibold hover:bg-[var(--haip-surface)] sm:min-h-9">
                        <History size={13} /> History
                      </button>
                    </div>
                  </CardBody>
                </Card>
              );
            })}
            {rows.length > 0 && !spec.singleton && (
              <button onClick={() => open(null)} className="flex min-h-11 items-center gap-1.5 rounded-lg border border-dashed border-[var(--haip-border-strong)] px-4 text-sm font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]">
                <Plus size={14} /> Add {spec.label.toLowerCase()}
              </button>
            )}
          </>
        )}
      </div>

      <Drawer
        wide open={!!editing} onOpenChange={o => { if (!o) { setEditing(null); setReview(null); setProblems([]); } }}
        title={editing ? `${editing.isNew ? "New" : "Edit"} ${SPEC_BY_KIND[editing.kind].label.toLowerCase()}` : ""}
        description="Saved as a draft. The AI keeps using the live version until you publish."
        footer={editing && (
          <div className="flex w-full flex-wrap items-center justify-between gap-2">
            <div className="flex gap-2">
              {editing.recordId && (
                <button onClick={() => discard.mutate()} disabled={discard.isPending} className="min-h-11 rounded-lg border border-[var(--haip-border)] px-3 text-xs font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] sm:min-h-9">
                  Discard draft
                </button>
              )}
              {!editing.isNew && groups?.find(g => g.kind === editing.kind && g.key === editing.key)?.live && (
                <button onClick={() => { if (window.confirm("Switch this off? The AI stops using it. Records that refer to it must be changed first.")) { deactivate.mutate(editing); setEditing(null); } }}
                  className="min-h-11 rounded-lg px-3 text-xs font-semibold text-[var(--haip-red)] hover:bg-[var(--haip-surface)] sm:min-h-9">
                  Switch off
                </button>
              )}
            </div>
            <div className="flex gap-2">
              <button onClick={() => save.mutate(undefined, { onSuccess: () => toast({ variant: "success", title: "Draft saved", description: "The AI is not using it yet." }) })} disabled={draftBusy || !editing.key}
                className="min-h-11 rounded-lg border border-[var(--haip-border)] px-4 text-sm font-semibold hover:bg-[var(--haip-surface)] disabled:opacity-50 sm:min-h-9">
                {save.isPending && !startReview.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save draft"}
              </button>
              {!review ? (
                <button onClick={() => startReview.mutate()} disabled={draftBusy || !editing.key}
                  className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50 sm:min-h-9">
                  {startReview.isPending ? <Loader2 size={14} className="animate-spin" /> : "Review changes"}
                </button>
              ) : (
                <button onClick={() => publish.mutate()} disabled={publish.isPending || review.check.errors.length > 0}
                  className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50 sm:min-h-9">
                  {publish.isPending ? <Loader2 size={14} className="animate-spin" /> : "Publish"}
                </button>
              )}
            </div>
          </div>
        )}
      >
        {editing && (
          <div className="space-y-5">
            {problems.length > 0 && (
              <ul role="alert" className="list-disc space-y-1 rounded-xl border border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] py-3 pl-8 pr-4 text-xs text-[var(--haip-status-danger-fg)]">
                {problems.map(p => <li key={p}>{p}</li>)}
              </ul>
            )}
            {review && <ReviewPanel review={review} effective={editing.effective} onEffective={v => setEditing(e => (e ? { ...e, effective: v } : e))} />}
            {editing.isNew && !SPEC_BY_KIND[editing.kind].singleton && (
              <div className="space-y-1">
                <label className="block text-xs font-semibold text-[var(--haip-fg-2)]">Short name used in links <span className="text-[var(--haip-red)]">*</span></label>
                <input value={editing.key} onChange={e => set({ key: slug(e.target.value) })} placeholder={slug(String(editing.value.name ?? "")) || "e.g. coorg-weekend"}
                  className="min-h-11 w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base sm:min-h-9 sm:text-[13px]" />
                <p className="text-[11px] text-[var(--haip-fg-subtle)]">Lowercase letters, numbers and dashes. It cannot be changed later.</p>
              </div>
            )}
            <FieldEditor fields={SPEC_BY_KIND[editing.kind].fields} value={editing.value} ctx={ctx}
              onChange={v => { set({ value: v, key: editing.isNew && !editing.key && !SPEC_BY_KIND[editing.kind].singleton && v.name ? slug(String(v.name)) : editing.key }); }} />
            <div className="space-y-1">
              <label className="block text-xs font-semibold text-[var(--haip-fg-2)]">What changed and why (kept in the history)</label>
              <input value={editing.note} maxLength={500} onChange={e => set({ note: e.target.value })}
                className="min-h-11 w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base sm:min-h-9 sm:text-[13px]" />
            </div>
          </div>
        )}
      </Drawer>

      <HistoryDrawer target={historyOf} onClose={() => setHistoryOf(null)} onChanged={refresh} />
    </div>
  );
}

function ReviewPanel({ review, effective, onEffective }: { review: { check: Check; changes: Change[] }; effective: string; onEffective: (v: string) => void }) {
  const { check, changes } = review;
  return (
    <div className="space-y-3 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-surface)] p-4">
      <p className="text-sm font-bold text-[var(--haip-fg)]">Review before publishing</p>
      {check.errors.length > 0 && (
        <div role="alert" className="space-y-1">
          <p className="text-xs font-semibold text-[var(--haip-status-danger-fg)]">Fix these first — publishing is blocked:</p>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-[var(--haip-status-danger-fg)]">{check.errors.map(e => <li key={e}>{e}</li>)}</ul>
        </div>
      )}
      {check.warnings.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-[var(--haip-status-warning-fg)]">Worth a look:</p>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-[var(--haip-status-warning-fg)]">{check.warnings.map(e => <li key={e}>{e}</li>)}</ul>
        </div>
      )}
      <div className="space-y-1">
        <p className="text-xs font-semibold text-[var(--haip-fg-2)]">{changes.length ? `${changes.length} change${changes.length === 1 ? "" : "s"} compared with the live version` : "No difference from the live version"}</p>
        <ul className="space-y-1 text-xs">
          {changes.map(c => (
            <li key={c.path} className="break-words rounded-lg bg-[var(--haip-card)] px-3 py-1.5">
              <span className="font-semibold">{c.path}</span>: <span className="text-[var(--haip-fg-subtle)] line-through">{show(c.old)}</span> → <span>{show(c.new)}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="space-y-1">
        <label className="block text-xs font-semibold text-[var(--haip-fg-2)]">Start using it from (leave empty for today)</label>
        <input type="date" value={effective} onChange={e => onEffective(e.target.value)} className="min-h-11 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base sm:min-h-9 sm:text-[13px]" />
        <p className="text-[11px] text-[var(--haip-fg-subtle)]">A future date schedules the change; until then the current version stays in force.</p>
      </div>
    </div>
  );
}

function HistoryDrawer({ target, onClose, onChanged }: { target: { kind: string; key: string } | null; onClose: () => void; onChanged: () => void }) {
  const { toast } = useToast();
  const { data = [], isLoading } = useQuery<BRecord[]>({
    queryKey: ["business-data-history", target?.kind, target?.key], enabled: !!target,
    queryFn: () => api.get(`/business-data/records/${target!.kind}/${target!.key}`).then(r => r.data),
  });
  const restore = useMutation({
    mutationFn: (v: { version: number; publish: boolean }) =>
      api.post(`/business-data/records/${target!.kind}/${target!.key}/rollback`, { to_version: v.version, publish: v.publish, note: `Restored version ${v.version}` }),
    onSuccess: (_d, v) => {
      onChanged();
      toast({ variant: "success", title: v.publish ? "Restored and published" : "Restored as a draft", description: v.publish ? "A new version now carries the old content." : "Review it, then publish." });
      onClose();
    },
    onError: e => toast({ variant: "error", title: "Couldn't restore", description: apiProblems(e).message }),
  });
  const tone = (s: string) => (s === "published" ? "success" : s === "draft" ? "warning" : s === "rejected" || s === "inactive" ? "danger" : "neutral") as "success" | "warning" | "danger" | "neutral";
  return (
    <Drawer open={!!target} onOpenChange={o => { if (!o) onClose(); }} title="Version history" description="Every version is kept. Restoring creates a new version; nothing is overwritten.">
      {isLoading ? <Skeleton className="h-24 rounded-xl" /> : data.length === 0 ? <p className="text-sm text-[var(--haip-fg-subtle)]">No history yet.</p> : (
        <ol className="space-y-3">
          {data.map(r => (
            <li key={r.id} className="space-y-2 rounded-xl border border-[var(--haip-border)] p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-bold">Version {r.version}</span>
                <StatusPill tone={tone(r.status)}>{r.status}</StatusPill>
                {r.effective_from && <span className="text-[11px] text-[var(--haip-fg-subtle)]">from {r.effective_from}{r.effective_to ? ` to ${r.effective_to}` : ""}</span>}
              </div>
              <p className="text-[11px] text-[var(--haip-fg-subtle)]">
                {r.published_at ? `Published ${timeAgo(r.published_at)}` : r.created_at ? `Drafted ${timeAgo(r.created_at)}` : ""}
                {r.change_note ? ` — ${r.change_note}` : ""}{r.rejected_reason ? ` — ${r.rejected_reason}` : ""}
              </p>
              {(r.status === "superseded" || r.status === "published") && (
                <div className="flex flex-wrap gap-2">
                  <button disabled={restore.isPending} onClick={() => restore.mutate({ version: r.version, publish: false })}
                    className="flex min-h-11 items-center gap-1 rounded-lg border border-[var(--haip-border)] px-3 text-xs font-semibold hover:bg-[var(--haip-surface)] sm:min-h-9">
                    <RotateCcw size={12} /> Restore as draft
                  </button>
                  {r.status === "superseded" && (
                    <button disabled={restore.isPending}
                      onClick={() => { if (window.confirm(`Publish the content of version ${r.version} as a new version now?`)) restore.mutate({ version: r.version, publish: true }); }}
                      className="min-h-11 rounded-lg px-3 text-xs font-semibold text-primary hover:bg-[var(--haip-surface)] sm:min-h-9">
                      Restore and publish
                    </button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </Drawer>
  );
}
