"use client";
// "Form C data" for one guest from abroad (ops_form_c): the Bureau of Immigration portal's fields in its order, each one
// copyable, so a person can file Form C by hand. HAIP never files it. Passport / visa numbers are masked; a role with guest
// PII rights can show them (and the photos) with an audited reveal, kept in this component only (never in the query
// cache). A manager ticks "Submitted on the portal", which closes the Form C ops item.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Drawer, StatusPill } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { countryName, type FormCSheet as Sheet } from "@/lib/ops";

const when = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Check your connection and try again.";
}

export function FormCSheet({ fileId, guest, open, onOpenChange, manage, onChanged }: {
  fileId: string; guest: number; open: boolean; onOpenChange: (o: boolean) => void; manage: boolean; onChanged: () => void;
}) {
  const { toast } = useToast();
  const base = `/ops/files/${fileId}/guest-form/guests/${guest}/form-c`;
  const q = useQuery<Sheet>({ queryKey: ["ops-form-c", fileId, guest], queryFn: () => api.get(base).then(r => r.data), enabled: open, staleTime: 0 });
  const [full, setFull] = useState<Sheet | null>(null);
  const [busy, setBusy] = useState<"reveal" | "tick" | null>(null);
  const [note, setNote] = useState("");
  const close = (o: boolean) => { if (!o) { setFull(null); setNote(""); } onOpenChange(o); };
  const s = full ?? q.data;

  const reveal = async () => {
    setBusy("reveal");
    try { setFull((await api.post(`${base}/reveal`)).data); }
    catch (e) { toast({ title: "Couldn't show the numbers", description: errorText(e), variant: "error" }); }
    finally { setBusy(null); }
  };
  const tick = async () => {
    setBusy("tick");
    try {
      await api.post(`${base}/submitted`, { note: note.trim() || null });
      toast({ title: "Form C marked as submitted", variant: "success" });
      setFull(null); await q.refetch(); onChanged();
    } catch (e) { toast({ title: "Not saved", description: errorText(e), variant: "error" }); }
    finally { setBusy(null); }
  };
  const copy = async (label: string, value: string) => {
    try { await navigator.clipboard.writeText(value); toast({ title: `${label} copied`, variant: "success" }); }
    catch { toast({ title: "Couldn't copy", description: "Select the text and copy it yourself.", variant: "error" }); }
  };

  return (
    <Drawer open={open} onOpenChange={close} title={`Form C data: guest ${guest}`}
      description="Copy each field into the Bureau of Immigration portal. HAIP never files it for you."
      footer={s && !s.submitted_at && manage ? (
        <div className="flex w-full flex-col gap-2">
          <label className="flex flex-col gap-1.5 text-[14px] font-semibold">Portal acknowledgement number (optional)
            <input className="min-h-12 w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px]"
              value={note} onChange={e => setNote(e.target.value)} maxLength={300} />
          </label>
          <button type="button" className="haip-btn-primary min-h-12 w-full text-[16px]" disabled={busy !== null} onClick={tick}>
            {busy === "tick" ? "Saving…" : "Submitted on the portal"}</button>
        </div>
      ) : undefined}>
      {q.isPending && open && <p className="text-[15px] text-[var(--haip-fg-subtle)]">Loading…</p>}
      {q.isError && (
        <div className="flex flex-col gap-2">
          <p className="text-[15px]">Couldn&rsquo;t load the Form C data. {errorText(q.error)}</p>
          <button type="button" className="haip-btn-secondary min-h-12" onClick={() => q.refetch()}>Try again</button>
        </div>
      )}
      {s && (
        <div className="flex flex-col gap-3">
          <p className="rounded-xl bg-[var(--haip-status-warning-bg)] px-3 py-2 text-[14px] text-[var(--haip-status-warning-fg)]">{s.note}</p>
          <div className="flex flex-wrap items-center gap-2">
            {s.submitted_at ? <StatusPill tone="success">Submitted {when(s.submitted_at)}</StatusPill>
              : s.due_at ? <StatusPill tone={new Date(s.due_at) < new Date() ? "danger" : "warning"}>Due by {when(s.due_at)}</StatusPill>
              : <StatusPill tone="neutral">Due 24 hours after arrival</StatusPill>}
            {s.submitted_note && <span className="text-[13.5px] text-[var(--haip-fg-muted)]">Ack: {s.submitted_note}</span>}
          </div>
          {!s.revealed && s.can_reveal && (
            <button type="button" className="haip-btn-secondary min-h-12" disabled={busy !== null} onClick={reveal}>
              {busy === "reveal" ? "Opening…" : "Show passport and visa numbers and photos"}</button>
          )}
          {!s.revealed && !s.can_reveal && (
            <p className="text-[13.5px] text-[var(--haip-fg-subtle)]">Passport and visa numbers are hidden for your role. A manager can see them.</p>
          )}
          {s.revealed && <p className="text-[13.5px] text-[var(--haip-fg-subtle)]">Shown to you and recorded in the audit log.</p>}
          <dl className="flex flex-col">
            {s.fields.map(r => {
              const value = r.value && r.format === "country" ? countryName(r.value) : r.value;
              return (
                <div key={r.key} className="flex min-h-[52px] items-center gap-3 border-t border-[var(--haip-border)] py-2 first:border-t-0">
                  <div className="min-w-0 flex-1">
                    <dt className="text-[13px] text-[var(--haip-fg-subtle)]">{r.label}</dt>
                    <dd className="break-words text-[15px] font-semibold">{value ?? <span className="font-normal text-[var(--haip-fg-muted)]">{r.hint ?? "—"}</span>}</dd>
                    {value && r.hint && <dd className="text-[12.5px] text-[var(--haip-fg-subtle)]">{r.hint}</dd>}
                  </div>
                  {value && !r.masked && (
                    <button type="button" className="haip-btn-secondary min-h-11 shrink-0 px-3 text-[14px]" onClick={() => copy(r.label, value)}>Copy</button>
                  )}
                </div>
              );
            })}
          </dl>
          {s.photos.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {s.photos.filter(p => p.url).map(p => (
                <a key={p.kind} href={p.url!} target="_blank" rel="noreferrer noopener" className="haip-btn-secondary min-h-12 flex-1 text-[15px]">
                  Open {p.kind} {p.pdf ? "PDF" : "photo"}</a>
              ))}
              <p className="w-full text-[12.5px] text-[var(--haip-fg-subtle)]">Links work for 10 minutes.</p>
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
}
