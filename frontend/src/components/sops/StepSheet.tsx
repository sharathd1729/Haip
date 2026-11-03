"use client";
// One SOP step: how to do it, the values to paste (Copy), catalogue categories with their "Not confirmed" state, the photo
// order, what to fill in HAIP first, and evidence (screenshot or https link). BottomSheet on phones, Drawer above 768px.
import Link from "next/link";
import { useRef, useState } from "react";
import { BottomSheet, Drawer, StatusPill } from "@/components/ui/kit";
import { btn, btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/bookings";
import { Camera, Copy, ExternalLink } from "@/lib/icons";
import { ruleWords, sopsApi, type Step } from "@/lib/sops";
import { useIsPhone } from "@/lib/useIsPhone";

const VERIFY_WORDS = { auto: "HAIP checks this", evidence: "Needs a screenshot or link", manual: "Tick when done" } as const;

export function StepSheet({ sopId, step, canWork, onClose, onChanged }: {
  sopId: string; step: Step | null; canWork: boolean; onClose: () => void; onChanged: () => void;
}) {
  const phone = useIsPhone();
  const { toast } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  if (!step) return null;

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) toast({ variant: "success", title: ok }); onChanged(); }
    catch (e) { toast({ variant: "error", title: errorMessage(e, "That didn't work") }); }
    finally { setBusy(false); }
  };
  const copy = (t: string) => navigator.clipboard?.writeText(t).then(
    () => toast({ variant: "success", title: "Copied" }), () => toast({ variant: "error", title: "Could not copy" }));
  const openEvidence = () => run(async () => { window.open(await sopsApi.evidence(sopId, step.key), "_blank", "noopener"); });

  const body = (
    <div className="grid gap-4 text-[15px]">
      <p>{step.how}</p>
      {step.link && <Link className={`${btn} justify-self-start`} href={step.link.href}>{step.link.label}</Link>}
      {step.changed && <StatusPill tone="warning">Changed since you did it: check again</StatusPill>}
      {step.needs.length > 0 && (
        <div className="grid gap-1.5 rounded-xl border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] p-3">
          <b className="text-sm">Fill this in HAIP first</b>
          {step.needs.map(n => n.href
            ? <Link key={n.label} href={n.href} className="text-sm font-semibold underline underline-offset-4">{n.label}</Link>
            : <span key={n.label} className="text-sm">{n.label}</span>)}
        </div>)}
      {step.values.map(v => (
        <div key={v.label} className="grid gap-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-semibold text-[var(--haip-fg-muted)]">{v.label}{v.ai ? " · written by AI, read it first" : ""}</span>
            <button className={btn} onClick={() => copy(v.text)} aria-label={`Copy ${v.label}`}><Copy size={15} /> Copy</button>
          </div>
          <p className="whitespace-pre-wrap rounded-xl bg-[var(--haip-surface)] p-3">{v.text}</p>
        </div>))}
      {step.categories && step.categories.length > 0 && (
        <div className="grid gap-2">
          <span className="text-sm font-semibold text-[var(--haip-fg-muted)]">Suggested, best first</span>
          {step.categories.map(c => (
            <div key={c.key} className="grid gap-1 rounded-xl bg-[var(--haip-surface)] p-3">
              <div className="flex flex-wrap items-center gap-2">
                <b>{c.name}</b>
                <StatusPill tone={c.status === "verified" && !c.stale ? "success" : "warning"}>{ruleWords(c)}</StatusPill>
                <button className={btn} onClick={() => copy(c.name)} aria-label={`Copy ${c.name}`}><Copy size={15} /></button>
              </div>
              <span className="text-sm text-[var(--haip-fg-muted)]">{c.source_note} (as of {c.as_of})</span>
            </div>))}
        </div>)}
      {step.photos && step.photos.length > 0 && (
        <ol className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {step.photos.map((p, i) => (
            <li key={p.asset_id} className="grid gap-1">
              {p.url
                // eslint-disable-next-line @next/next/no-img-element -- short-lived private link, not an optimisable asset
                ? <a href={p.url} target="_blank" rel="noopener noreferrer"><img src={p.url} alt={p.alt || `Photo ${i + 1}`} className="aspect-square w-full rounded-lg object-cover" /></a>
                : <span className="aspect-square rounded-lg bg-[var(--haip-surface)]" />}
              <span className="text-xs text-[var(--haip-fg-muted)]">{i + 1}. {p.subject ?? "photo"}</span>
            </li>))}
        </ol>)}
      {step.notes.map(n => <p key={n} className="text-sm text-[var(--haip-fg-muted)]">{n}</p>)}
      {step.rules.filter(r => r.status !== "haip_advice" || r.stale).map(r => (
        <p key={r.key} className="text-sm text-[var(--haip-fg-muted)]">{ruleWords(r)}: {r.source_note} (as of {r.as_of})</p>))}
      {step.check_result && (
        <StatusPill tone={step.check_result.result === "ok" ? "success" : step.check_result.result === "fail" ? "danger" : "neutral"}>
          {step.check_result.detail}</StatusPill>)}
      {canWork && step.verify !== "manual" && (
        <div className="grid gap-2 border-t border-[var(--haip-border)] pt-3">
          <span className="text-sm font-semibold">Screenshot or link</span>
          {step.evidence?.asset_id && <button className={`${btn} justify-self-start`} onClick={openEvidence}><ExternalLink size={15} /> See your screenshot</button>}
          {step.evidence?.url && <a className="break-all text-sm underline" href={step.evidence.url} target="_blank" rel="noopener noreferrer">{step.evidence.url}</a>}
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp,application/pdf" className="sr-only"
            onChange={e => { const f = e.target.files?.[0]; if (f) run(() => sopsApi.upload(sopId, step.key, f), "Screenshot added"); e.target.value = ""; }} />
          <button className={`${btn} justify-self-start`} disabled={busy} onClick={() => fileRef.current?.click()}><Camera size={15} /> Add screenshot</button>
          <div className="flex gap-2">
            <input className={inputCls} inputMode="url" placeholder="https://…" value={link} onChange={e => setLink(e.target.value)} aria-label="Link" />
            <button className={btn} disabled={busy || !link.startsWith("https://")}
              onClick={() => run(() => sopsApi.link(sopId, step.key, link), "Link added").then(() => setLink(""))}>Add</button>
          </div>
        </div>)}
    </div>
  );
  const footer = canWork ? (
    <div className="flex flex-wrap gap-2">
      {step.status === "todo"
        ? <>
          <button className={btnPrimary} disabled={busy} onClick={() => run(() => sopsApi.step(sopId, step.key, "done"), "Marked done")}>Mark done</button>
          <button className={btn} disabled={busy} onClick={() => run(() => sopsApi.step(sopId, step.key, "skip"))}>Not for us</button>
        </>
        : <button className={btn} disabled={busy} onClick={() => run(() => sopsApi.step(sopId, step.key, "undo"))}>Undo</button>}
    </div>) : undefined;
  const props = { open: true, onOpenChange: (o: boolean) => { if (!o) onClose(); }, title: step.title,
    description: VERIFY_WORDS[step.verify], footer };
  return phone ? <BottomSheet {...props}>{body}</BottomSheet> : <Drawer {...props}>{body}</Drawer>;
}
