"use client";
// Lead page, "Evidence": upload what happened outside HAIP so the record is complete and the won/lost reason can be read
// from what was actually said. Two uploads: a WhatsApp "Export chat" file (.txt or .zip) and a call recording (audio).
// Backend: POST /leads/{id}/evidence (multipart, leads.write, audited), GET /leads/{id}/evidence (lead_evidence_service).
// A chat whose guest side HAIP cannot tell asks "Which name is the guest?" (422 pick_guest_sender) and re-sends the pick.
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2, MessageSquare, Mic2, Upload } from "@/lib/icons";
import { Card, CardBody, CardHeader, Drawer, StatusPill } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { istDate } from "./format";

export interface EvidenceItem {
  id: string; kind: "chat_export" | "call_recording"; status: "done" | "processing" | "transcribing" | "analysing" | "failed";
  filename: string | null; created_at: string; uploaded_by_name: string | null; message_count: number; duplicate_count: number;
  media_count: number; duration_seconds: number | null; summary: string | null;
}
type Sender = { name: string; messages: number };
type Kind = EvidenceItem["kind"];

const STATUS: Record<EvidenceItem["status"], { label: string; tone: "success" | "warning" | "danger" | "neutral" }> = {
  done: { label: "Done", tone: "success" }, processing: { label: "Processing", tone: "warning" },
  transcribing: { label: "Transcribing", tone: "warning" }, analysing: { label: "Analysing", tone: "warning" },
  failed: { label: "Failed", tone: "danger" },
};

function detail(e: unknown): { code?: string; message?: string; senders?: Sender[] } {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (d && typeof d === "object") return d as { code?: string; message?: string; senders?: Sender[] };
  return { message: typeof d === "string" ? d : undefined };
}

export function describeEvidence(i: EvidenceItem): string {
  if (i.kind === "chat_export") {
    const parts = [`${i.message_count} message${i.message_count === 1 ? "" : "s"} added`];
    if (i.duplicate_count) parts.push(`${i.duplicate_count} already here`);
    if (i.media_count) parts.push(`${i.media_count} file${i.media_count === 1 ? "" : "s"}`);
    return parts.join(" · ");
  }
  if (i.duration_seconds == null) return "Call recording";
  const m = Math.floor(i.duration_seconds / 60), s = i.duration_seconds % 60;
  return `Call recording · ${m}:${String(s).padStart(2, "0")}`;
}

const btn = "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3.5 text-[14px] font-semibold text-[var(--haip-fg)] disabled:opacity-60";

export function EvidenceCard({ inquiryId, canEdit }: { inquiryId: string; canEdit: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const key = ["lead-evidence", inquiryId];
  const q = useQuery<{ items: EvidenceItem[] }>({
    queryKey: key, queryFn: () => api.get(`/leads/${inquiryId}/evidence`).then(r => r.data), staleTime: 30_000,
    refetchInterval: d => ((d.state.data?.items ?? []).some(i => ["processing", "transcribing", "analysing"].includes(i.status)) ? 15_000 : false),
  });
  const [open, setOpen] = useState<Kind | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [direction, setDirection] = useState<"outbound" | "inbound">("outbound");
  const [senders, setSenders] = useState<Sender[] | null>(null);
  const [pick, setPick] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const reset = () => { setOpen(null); setFile(null); setSenders(null); setPick(""); setDirection("outbound"); };

  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("kind", open!);
      form.append("file", file!);
      if (open === "chat_export" && pick) form.append("guest_sender", pick);
      if (open === "call_recording") form.append("direction", direction);
      return api.post(`/leads/${inquiryId}/evidence`, form).then(r => r.data as EvidenceItem);
    },
    onSuccess: item => {
      toast({ variant: "success", title: item.kind === "chat_export" ? "Chat imported" : "Recording uploaded",
        description: item.kind === "chat_export" ? describeEvidence(item) : "The transcript and summary are being written." });
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] });
      reset();
    },
    onError: e => {
      const d = detail(e);
      if (d.code === "pick_guest_sender" && d.senders?.length) { setSenders(d.senders); return; }
      toast({ variant: "error", title: "Not uploaded", description: d.message ?? "Please try again." });
    },
  });

  const items = q.data?.items ?? [];
  const accept = open === "chat_export" ? ".txt,.zip,text/plain,application/zip" : ".mp3,.m4a,.aac,.wav,.ogg,.opus,.amr,audio/*";
  return (
    <Card>
      <CardHeader title="Evidence" description="Chats and calls from staff phones, so the record is complete." />
      <CardBody className="grid gap-3">
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            <button type="button" className={btn} onClick={() => setOpen("chat_export")}><MessageSquare size={15} aria-hidden /> Chat export</button>
            <button type="button" className={btn} onClick={() => setOpen("call_recording")}><Mic2 size={15} aria-hidden /> Call recording</button>
          </div>
        )}
        {q.isPending ? (
          <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" aria-hidden /> Loading…</p>
        ) : q.isError ? (
          <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load uploads. <button type="button" className="font-semibold text-primary" onClick={() => q.refetch()}>Try again</button></p>
        ) : items.length === 0 ? (
          <p className="text-sm text-[var(--haip-fg-muted)]">Nothing uploaded yet. Add the WhatsApp chat or a call recording from your phone.</p>
        ) : (
          <ul className="grid gap-2">
            {items.map(i => (
              <li key={i.id} className="grid gap-0.5 rounded-xl border border-[var(--haip-border)] px-3 py-2">
                <span className="flex flex-wrap items-center justify-between gap-2">
                  <strong className="text-[14px] text-[var(--haip-fg)]">{i.kind === "chat_export" ? "WhatsApp chat" : "Call recording"}</strong>
                  <StatusPill tone={STATUS[i.status]?.tone ?? "neutral"}>{STATUS[i.status]?.label ?? i.status}</StatusPill>
                </span>
                <span className="text-[13px] text-[var(--haip-fg-2)]">{describeEvidence(i)}</span>
                <span className="text-[12.5px] text-[var(--haip-fg-subtle)] [overflow-wrap:anywhere]">
                  {istDate(i.created_at)}{i.uploaded_by_name ? ` · ${i.uploaded_by_name}` : ""}{i.filename ? ` · ${i.filename}` : ""}
                </span>
                {i.summary && <span className="text-[13px] text-[var(--haip-fg-2)]">{i.summary}</span>}
              </li>
            ))}
          </ul>
        )}
      </CardBody>
      <Drawer open={open !== null} onOpenChange={o => { if (!o) reset(); }}
        title={open === "chat_export" ? "Upload a WhatsApp chat" : "Upload a call recording"}
        description={open === "chat_export"
          ? "On the phone: open the chat > More > Export chat (with or without media). Upload the .txt or .zip here."
          : "An audio file of the call (mp3, m4a, aac, wav, ogg, opus or amr, up to 50 MB). HAIP writes the transcript and summary."}>
        <div className="grid gap-3">
          <input ref={input} type="file" accept={accept} className="sr-only" onChange={e => { setFile(e.target.files?.[0] ?? null); setSenders(null); setPick(""); }} />
          <button type="button" className={btn} onClick={() => input.current?.click()}>
            <Upload size={15} aria-hidden /> {file ? "Choose another file" : "Choose file"}
          </button>
          {file && <p className="text-[13.5px] text-[var(--haip-fg-2)] [overflow-wrap:anywhere]">{file.name} · {(file.size / 1_048_576).toFixed(1)} MB</p>}
          {open === "call_recording" && (
            <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Who called">
              {(["outbound", "inbound"] as const).map(d => (
                <button key={d} type="button" role="radio" aria-checked={direction === d} onClick={() => setDirection(d)}
                  className={cn("min-h-11 rounded-xl border px-3 text-[14px]", direction === d ? "border-primary ring-1 ring-primary" : "border-[var(--haip-border)]")}>
                  {d === "outbound" ? "We called them" : "They called us"}
                </button>
              ))}
            </div>
          )}
          {senders && (
            <div className="grid gap-1.5" role="radiogroup" aria-label="Which name is the guest?">
              <p className="text-[13.5px] font-semibold text-[var(--haip-fg)]">Which name in the chat is the guest?</p>
              {senders.map(s => (
                <button key={s.name} type="button" role="radio" aria-checked={pick === s.name} onClick={() => setPick(s.name)}
                  className={cn("flex min-h-11 items-center justify-between rounded-xl border px-3 text-left text-[14px] [overflow-wrap:anywhere]",
                    pick === s.name ? "border-primary ring-1 ring-primary" : "border-[var(--haip-border)]")}>
                  <span>{s.name}</span><span className="text-[12.5px] text-[var(--haip-fg-subtle)]">{s.messages} messages</span>
                </button>
              ))}
            </div>
          )}
          <button type="button" disabled={!file || upload.isPending || (!!senders && !pick)} onClick={() => upload.mutate()}
            className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground disabled:opacity-60">
            {upload.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />} Upload
          </button>
        </div>
      </Drawer>
    </Card>
  );
}
