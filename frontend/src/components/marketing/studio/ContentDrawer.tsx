"use client";
// One content item: edit (each save is a new version), ask the AI for a version, send for approval, approve or ask
// for changes. Approval is bound to the exact version shown; the server refuses if it changed meanwhile. The preview
// is the saved version drawn exactly as it will be posted (photo, text and look), so it is what the approver signs off.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Drawer, StatusPill, Timeline, type TimelineEntry } from "@/components/ui/kit";
import { PayloadForm, emptyPayload } from "./PayloadForm";
import { PublishPanel } from "./PublishPanel";
import { RenderedPreview } from "./RenderedPreview";
import { BrandReviewPanel } from "./BrandReviewPanel";
import { KIND_LABEL, STATUS, STUDIO, btn, btnPrimary, inputCls, studioError, when, type ContentItem } from "./types";

const LOOKS = [
  { value: "overlay", label: "Text on photo", hint: "Dark fade with white text" },
  { value: "panel", label: "Brand panel", hint: "Text on a band in your brand colour" },
  { value: "photo", label: "Photo only", hint: "No text on the image" },
] as const;

const DECISION_LABEL = { submitted: "Sent for approval", approved: "Approved", rejected: "Changes asked", withdrawn: "Approval voided by an edit" };

export function ContentDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const me = session?.user?.id;
  const canApprove = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();

  const q = useQuery<ContentItem>({
    queryKey: ["studio-item", id], enabled: !!id,
    queryFn: () => api.get(`${STUDIO}/content/${id}`).then(r => r.data),
    refetchInterval: d => (d.state.data?.generation_status === "pending" ? 3000 : false),
  });
  const item = q.data;
  const current = item?.current ?? null;
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [brief, setBrief] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => { setDraft(current?.payload ?? {}); }, [current?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const done = (r: { data: ContentItem }) => {
    qc.setQueryData(["studio-item", id], r.data);
    qc.invalidateQueries({ queryKey: ["studio-content"] });
  };
  const fail = (title: string) => (e: unknown) => toast({ variant: "error", title, description: studioError(e, "Try again.") });
  const save = useMutation({ mutationFn: () => api.post(`${STUDIO}/content/${id}/versions`, { payload: draft }), onSuccess: done, onError: fail("Not saved") });
  const gen = useMutation({ mutationFn: () => api.post(`${STUDIO}/content/${id}/generate`, { brief: brief || null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["studio-item", id] }), onError: fail("Could not start the AI") });
  const pick = useMutation({
    mutationFn: () => api.post(`${STUDIO}/content/${id}/pick-photos`),
    onSuccess: r => {
      qc.invalidateQueries({ queryKey: ["studio-item", id] });
      toast({ variant: "success", title: r.data.filled ? `${r.data.filled} photo${r.data.filled === 1 ? "" : "s"} chosen` : "Nothing to fill",
        description: r.data.filled ? "Saved as a new version. Swap any photo below." : "Every slot already has a photo." });
    },
    onError: fail("Photos not chosen"),
  });
  const act = useMutation({
    mutationFn: (a: "submit" | "approve" | "reject") => api.post(`${STUDIO}/content/${id}/${a}`, { version_id: current?.id, note: note || null }),
    onSuccess: r => { done(r); setNote(""); }, onError: fail("Not done"),
  });

  const dirty = JSON.stringify(draft) !== JSON.stringify(current?.payload ?? {});
  const locked = ["in_review", "approved", "archived", "scheduled", "published"].includes(item?.status ?? "");
  const ownVersion = !!current && current.created_by === me && role !== "owner";
  const busy = save.isPending || act.isPending || pick.isPending || item?.generation_status === "pending";
  const look = ((draft.design as { style?: string } | undefined)?.style) ?? (item?.kind === "post" && !draft.overlay_text ? "photo" : "overlay");
  const setLook = (style: string) => setDraft({ ...draft, design: { ...((draft.design as object) ?? {}), style } });

  const timeline: TimelineEntry[] = [
    ...(item?.versions ?? []).map(v => ({ id: v.id, at: v.created_at, title: `Version ${v.version} · ${v.origin === "ai" ? "written by AI" : "edited by a person"}`,
      detail: v.note ?? undefined })),
    ...(item?.decisions ?? []).map(d => ({ id: d.id, at: d.created_at, title: DECISION_LABEL[d.decision], detail: d.note ?? undefined })),
  ].sort((a, b) => (a.at < b.at ? 1 : -1)).map(({ at, ...e }) => ({ ...e, time: when(at) }));

  return (
    <Drawer open={!!id} onOpenChange={o => !o && onClose()} wide
      title={item?.title ?? "Content"}
      description={item && <span className="flex flex-wrap items-center gap-2"><StatusPill tone={STATUS[item.status].tone}>{STATUS[item.status].label}</StatusPill>{KIND_LABEL[item.kind]}{current && ` · version ${current.version}`}</span>}
      footer={item && current && (
        <div className="flex flex-wrap items-center gap-2">
          {!locked && <button type="button" className={btn} disabled={!dirty || busy} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save as new version"}</button>}
          {(item.status === "draft" || item.status === "rejected") && (
            <button type="button" className={btnPrimary} disabled={dirty || busy} onClick={() => act.mutate("submit")}>Send for approval</button>
          )}
          {item.status === "in_review" && canApprove && (
            <>
              <button type="button" className={btnPrimary} disabled={busy || ownVersion} onClick={() => act.mutate("approve")}
                title={ownVersion ? "You wrote or generated this version, so someone else must approve it." : undefined}>Approve this version</button>
              <button type="button" className={btn} disabled={busy || !note.trim()} onClick={() => act.mutate("reject")}
                title={!note.trim() ? "Write what should change first; the AI uses it for the next version." : undefined}>Ask for changes</button>
            </>
          )}
          {dirty && !locked && <span className="text-xs text-[var(--haip-fg-subtle)]">Save your edits before sending for approval.</span>}
        </div>
      )}>
      {q.isLoading ? <Skeleton className="h-64 w-full" /> : q.isError ? (
        <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not load this content.")}</p>
      ) : item && (
        <div className="space-y-5">
          {item.generation_status === "pending" && <p className="rounded-lg bg-[var(--haip-status-info-bg)] p-3 text-sm text-[var(--haip-status-info-fg)]">The AI is writing a version…</p>}
          {item.generation_status === "failed" && item.generation_error && (
            <p className="rounded-lg bg-[var(--haip-status-danger-bg)] p-3 text-sm text-[var(--haip-status-danger-fg)]">AI could not write this: {item.generation_error}</p>
          )}
          {item.status === "approved" && <p className="rounded-lg bg-[var(--haip-status-success-bg)] p-3 text-sm text-[var(--haip-status-success-fg)]">Approved. Schedule it below to post to Instagram. Any edit creates a new version that needs approval again.</p>}

          {!locked && (
            <div className="flex flex-col gap-2 rounded-xl border border-[var(--haip-border)] p-3 sm:flex-row sm:items-end">
              <label className="flex-1 space-y-1">
                <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Ask the AI for a version</span>
                <input className={inputCls} placeholder="e.g. monsoon weekend, couples, warm tone" maxLength={1000} value={brief} onChange={e => setBrief(e.target.value)} />
              </label>
              <button type="button" className={btn} disabled={busy} onClick={() => gen.mutate()}>{current ? "Write a new version" : "Write it"}</button>
            </div>
          )}

          {current ? (
            <>
              {current.origin === "ai" && <StatusPill tone="info">Written by AI · check facts before approving</StatusPill>}
              <RenderedPreview itemId={item.id} versionId={current.id} kind={item.kind}
                note={dirty ? "Showing the saved version; save to see your edits" : undefined} />
              {!locked && (
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div role="radiogroup" aria-label="Look" className="flex flex-wrap gap-1.5">
                    {LOOKS.map(l => (
                      <button key={l.value} type="button" role="radio" aria-checked={look === l.value} title={l.hint} disabled={busy}
                        onClick={() => setLook(l.value)}
                        className={`min-h-11 rounded-full border px-3 text-[13px] font-semibold sm:min-h-9 ${look === l.value
                          ? "border-primary bg-primary text-primary-foreground" : "border-[var(--haip-border)] text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]"}`}>
                        {l.label}
                      </button>
                    ))}
                  </div>
                  <button type="button" className={btn} disabled={busy || dirty} onClick={() => pick.mutate()}
                    title={dirty ? "Save your edits first." : "Fill every empty photo slot from your library"}>
                    {pick.isPending ? "Choosing…" : "Pick photos from the library"}
                  </button>
                </div>
              )}
              <BrandReviewPanel itemId={item.id} versionId={current.id} canAsk={role !== "viewer" && item.status !== "archived"} />
              <PayloadForm key={current.id} kind={item.kind} value={draft} onChange={setDraft} disabled={locked || busy} />
            </>
          ) : (
            <p className="text-sm text-[var(--haip-fg-subtle)]">No version yet. Ask the AI above, or start writing:
              <button type="button" className="ml-2 font-semibold text-primary" onClick={() => setDraft(emptyPayload(item.kind))}>write it myself</button>
            </p>
          )}
          {!current && Object.keys(draft).length > 0 && (
            <>
              <PayloadForm key="new" kind={item.kind} value={draft} onChange={setDraft} />
              <button type="button" className={btnPrimary} disabled={save.isPending} onClick={() => save.mutate()}>Save first version</button>
            </>
          )}

          {item.status === "in_review" && canApprove && (
            <label className="block space-y-1">
              <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">What should change?</span>
              <input className={inputCls} maxLength={500} value={note} onChange={e => setNote(e.target.value)}
                placeholder="Needed to ask for changes; optional when approving" />
            </label>
          )}

          {["approved", "scheduled", "published"].includes(item.status) && <PublishPanel itemId={item.id} canSchedule={canApprove} />}

          <section className="space-y-2">
            <h3 className="text-[13px] font-bold text-[var(--haip-fg)]">History</h3>
            <Timeline entries={timeline} />
          </section>
        </div>
      )}
    </Drawer>
  );
}
