"use client";
// Caption checks for the version on screen (Instagram toolkit phase 1): exactly what the feed shows before "... more",
// the checks (visible line, one ask, hashtags N/5, search words, price policy), the "sounds human" score and what the
// humanizer fixed. Undo puts the AI's original wording back as a new version (it needs approval again, like any edit).
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, type ContentItem, type TextChecks } from "./types";

const STATUS_TONE: Record<"ok" | "warn" | "bad", Tone> = { ok: "success", warn: "warning", bad: "danger" };
const VERDICT = {
  pass: { label: "Sounds human", cls: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]" },
  review: { label: "Mostly human; check the wording", cls: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]" },
  flagged: { label: "Reads like a machine wrote it", cls: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]" },
} as const;

export function CaptionChecks({ itemId, versionId, checks, canUndo, onChanged }: {
  itemId: string; versionId: string; checks: TextChecks; canUndo: boolean; onChanged: (item: ContentItem) => void;
}) {
  const { toast } = useToast();
  const undo = useMutation({
    mutationFn: () => api.post(`${STUDIO}/content/${itemId}/undo-humanize`, { version_id: versionId }).then(r => r.data as ContentItem),
    onSuccess: d => { onChanged(d); toast({ variant: "success", title: "Original wording restored", description: "Saved as a new version." }); },
    onError: e => toast({ variant: "error", title: "Not undone", description: studioError(e, "Try again.") }),
  });
  const { caption, human, fixed } = checks;
  const verdict = VERDICT[human.verdict];
  const weakest = human.checks.filter(c => c.score !== null).sort((a, b) => (a.score ?? 0) - (b.score ?? 0))[0];

  return (
    <section className="space-y-3" aria-label="Caption checks">
      <h3 className="text-[13px] font-bold text-[var(--haip-fg)]">Caption checks</h3>

      {caption.visible !== null && (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-[var(--haip-fg-subtle)]">How it shows in the feed</p>
          <p className="whitespace-pre-line break-words rounded-xl bg-[var(--haip-surface)] p-3 text-sm text-[var(--haip-fg)]">
            {caption.visible || <span className="text-[var(--haip-fg-subtle)]">No caption yet.</span>}
            {caption.truncated && <span className="text-[var(--haip-fg-subtle)]">… more</span>}
          </p>
        </div>
      )}

      {human.score !== null && (
        <div className={`flex flex-wrap items-center gap-3 rounded-xl p-3 ${verdict.cls}`}>
          <span className="font-[family-name:var(--font-display)] text-3xl font-extrabold tabular-nums leading-none" aria-label={`Score ${human.score} out of 100`}>{human.score}</span>
          <span className="min-w-0 flex-1 text-sm">
            <span className="font-semibold">{verdict.label}.</span>{" "}
            {fixed ? `${fixed.summary}.` : human.verdict !== "pass" && weakest ? `Weakest: ${weakest.label.toLowerCase()} (${weakest.detail}).` : ""}
          </span>
          {fixed && canUndo && (
            <button type="button" className={btn} disabled={undo.isPending} onClick={() => undo.mutate()}
              title="Put back the wording the AI wrote, as a new version">
              {undo.isPending ? "Undoing…" : "Undo fixes"}
            </button>
          )}
        </div>
      )}
      {fixed && fixed.changes.some(c => c.kind === "word") && (
        <p className="text-xs text-[var(--haip-fg-subtle)]">
          Swapped: {fixed.changes.filter(c => c.kind === "word").map(c => `“${c.from}” → ${c.to ? `“${c.to}”` : "removed"}`).join(", ")}.
          Keep a word as written from Studio settings.
        </p>
      )}

      <ul className="divide-y divide-[var(--haip-border)]">
        {caption.checks.map(c => (
          <li key={c.key} className="flex items-start justify-between gap-3 py-2">
            <span className="min-w-0 text-sm text-[var(--haip-fg)]">
              {c.label}
              {c.status !== "ok" && <span className="block text-xs text-[var(--haip-fg-subtle)]">{c.detail}</span>}
            </span>
            <StatusPill tone={STATUS_TONE[c.status]} className="max-w-[45%] shrink-0 truncate">{c.value}</StatusPill>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Owner setting: brand words the humanizer keeps as written (e.g. "curated", "unwind"). Others see the list. */
export function KeepWordsCard() {
  const { data: session } = useSession();
  const isOwner = session?.user?.role === "owner";
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<{ keep_words?: string[] }>({ queryKey: ["studio-settings"], queryFn: () => api.get(`${STUDIO}/settings`).then(r => r.data) });
  const [text, setText] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api.put(`${STUDIO}/settings`, { keep_words: (text ?? "").split(/[\n,]/).map(s => s.trim()).filter(Boolean) }),
    onSuccess: r => { qc.setQueryData(["studio-settings"], r.data); setText(null); toast({ variant: "success", title: "Words saved" }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: studioError(e, "Try again.") }),
  });
  const words = q.data?.keep_words ?? [];
  return (
    <Card>
      <CardHeader title="Words to keep" description="HAIP swaps stock AI words (elevate, unlock, curated) in drafts. Words listed here stay as written." />
      <CardBody>
        {q.isLoading ? <Skeleton className="h-16 w-full" /> : q.isError ? (
          <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not load the list.")}</p>
        ) : isOwner ? (
          <form className="space-y-2" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
            <textarea className={inputCls} rows={2} aria-label="Words to keep, one per line" placeholder="e.g. curated, unwind"
              value={text ?? words.join("\n")} onChange={e => setText(e.target.value)} />
            <button type="submit" className={btnPrimary} disabled={save.isPending || text === null}>{save.isPending ? "Saving…" : "Save words"}</button>
          </form>
        ) : words.length ? (
          <p className="text-sm text-[var(--haip-fg)]">{words.join(", ")}</p>
        ) : (
          <p className="text-sm text-[var(--haip-fg-subtle)]">None yet. The owner can add words here.</p>
        )}
      </CardBody>
    </Card>
  );
}
