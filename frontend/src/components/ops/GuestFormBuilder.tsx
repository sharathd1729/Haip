"use client";
// Settings › Business › Guest details form (workspace redesign Phase 4, mockup B): what guests fill before they arrive.
// Always-asked fields (the law) are shown locked; four standard questions are Off / Ask / Required; the owner adds up to 8
// questions of their own (short answer, yes or no, pick one, date), a welcome line and a house-rules link; a live phone
// preview sits beside it. GET / PUT /ops/guest-form/config (services/guest_form_config; PUT needs ops.manage, audited).
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { ArrowDown, Lock, Trash2 } from "@/lib/icons";
import { Card, CardBody, CardHeader, EmptyState, PageHeader } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";

type Mode = "off" | "ask" | "req";
type Kind = "text" | "yesno" | "choice" | "date";
interface Question { id: string; label: string; kind: Kind; options: string[]; required: boolean }
interface Cfg { age: Mode; emergency: Mode; food: Mode; requests: Mode; questions: Question[]; welcome: string; rules_url: string }
interface Resp { config: Cfg; always: string[] }

const STANDARD: { key: "age" | "emergency" | "food" | "requests"; label: string }[] = [
  { key: "age", label: "Age of each guest" },
  { key: "emergency", label: "Emergency contact" },
  { key: "food", label: "Food: allergies or preferences" },
  { key: "requests", label: "Anything we should arrange" },
];
const KINDS: { kind: Kind; label: string }[] = [
  { kind: "text", label: "Short answer" }, { kind: "yesno", label: "Yes or no" }, { kind: "choice", label: "Pick one" }, { kind: "date", label: "Date" },
];
const MODES: { m: Mode; label: string }[] = [{ m: "off", label: "Off" }, { m: "ask", label: "Ask" }, { m: "req", label: "Required" }];
const input = "min-h-11 w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)]";
const newId = () => Array.from(crypto.getRandomValues(new Uint8Array(8)), b => "abcdefghijklmnopqrstuvwxyz0123456789"[b % 36]).join("");
const errorText = (e: unknown) => {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map(x => String((x as { msg?: string }).msg ?? "").replace(/^Value error, /, "")).join("; ");
  return "Couldn't save. Try again.";
};

function Segmented({ value, onChange, label, disabled }: { value: Mode; onChange: (m: Mode) => void; label: string; disabled: boolean }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex gap-0.5 rounded-full border border-[var(--haip-border)] p-0.5">
      {MODES.map(o => (
        <button key={o.m} type="button" role="radio" aria-checked={value === o.m} disabled={disabled} onClick={() => onChange(o.m)}
          className={`min-h-10 rounded-full px-3.5 text-[14px] ${value === o.m ? "bg-primary font-semibold text-primary-foreground" : "text-[var(--haip-fg-muted)]"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function GuestFormBuilder({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const { data, isPending, isError, refetch } = useQuery<Resp>({
    queryKey: ["guest-form-config"], queryFn: () => api.get("/ops/guest-form/config").then(r => r.data),
  });
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (data && !cfg) setCfg(data.config); }, [data, cfg]);
  const dirty = useMemo(() => !!cfg && !!data && JSON.stringify(cfg) !== JSON.stringify(data.config), [cfg, data]);
  const save = useMutation({
    mutationFn: (c: Cfg) => api.put("/ops/guest-form/config", c).then(r => r.data as Resp),
    onSuccess: r => { qc.setQueryData(["guest-form-config"], r); setCfg(r.config); setSaved(true); },
  });

  if (isPending || (!cfg && !isError)) return <div className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-64" /></div>;
  if (isError || !cfg || !data) {
    return <Card><EmptyState title="The guest form didn't load" hint="Check your connection and try again."
      action={<button type="button" onClick={() => refetch()} className="haip-btn-primary min-h-11 px-4">Try again</button>} /></Card>;
  }
  const edit = (patch: Partial<Cfg>) => { setCfg({ ...cfg, ...patch }); setSaved(false); };
  const editQ = (i: number, patch: Partial<Question>) => edit({ questions: cfg.questions.map((q, n) => (n === i ? { ...q, ...patch } : q)) });
  const move = (i: number) => { const q = [...cfg.questions]; [q[i], q[i + 1]] = [q[i + 1], q[i]]; edit({ questions: q }); };
  const preview = [
    "Guests and IDs",
    ...STANDARD.filter(s => cfg[s.key] !== "off").map(s => `${s.label}${cfg[s.key] === "ask" ? " (optional)" : ""}`),
    ...cfg.questions.filter(q => q.label.trim()).map(q => `${q.label}${q.required ? "" : " (optional)"}`),
    "Check and sign",
  ];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Guest details form" subtitle="What guests fill before they arrive. The link goes out with each booking's ops file." />
      <div className="flex flex-wrap items-start gap-6">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-4">
          <Card>
            <CardHeader title="Always asked" description="Needed by law for every stay. These can't be switched off." />
            <CardBody>
              <ul className="divide-y divide-[var(--haip-border)]">
                {data.always.map(a => (
                  <li key={a} className="flex min-h-11 items-center gap-3 py-2 text-[15px]"><Lock size={16} aria-hidden className="shrink-0 text-[var(--haip-fg-subtle)]" />{a}</li>
                ))}
              </ul>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Standard questions" description="Required means the guest can't send the form without it." />
            <CardBody>
              <ul className="divide-y divide-[var(--haip-border)]">
                {STANDARD.map(s => (
                  <li key={s.key} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                    <span className="text-[15px]">{s.label}</span>
                    <Segmented value={cfg[s.key]} label={s.label} disabled={!canEdit} onChange={m => edit({ [s.key]: m } as Partial<Cfg>)} />
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Your questions" description={`Up to 8. Answers show on the ops file. ${cfg.questions.length} of 8 used.`} />
            <CardBody className="flex flex-col gap-3">
              {cfg.questions.length === 0 && <p className="text-[14px] text-[var(--haip-fg-subtle)]">None yet. Add one below, for example &ldquo;What time will you reach?&rdquo;</p>}
              {cfg.questions.map((q, i) => (
                <div key={q.id} className="flex flex-col gap-3 rounded-xl border border-[var(--haip-border)] p-3">
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-[var(--haip-surface)] px-2.5 py-1 text-[12px] font-semibold text-[var(--haip-fg-muted)]">{KINDS.find(k => k.kind === q.kind)?.label}</span>
                    <span className="flex-1" />
                    {i < cfg.questions.length - 1 && (
                      <button type="button" aria-label="Move down" disabled={!canEdit} onClick={() => move(i)} className="flex size-11 items-center justify-center rounded-full text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]"><ArrowDown size={18} aria-hidden /></button>
                    )}
                    <button type="button" aria-label={`Remove ${q.label || "question"}`} disabled={!canEdit} onClick={() => edit({ questions: cfg.questions.filter((_, n) => n !== i) })}
                      className="flex size-11 items-center justify-center rounded-full text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]"><Trash2 size={18} aria-hidden /></button>
                  </div>
                  <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-[var(--haip-fg-muted)]">Question
                    <input className={input} value={q.label} maxLength={120} disabled={!canEdit} onChange={e => editQ(i, { label: e.target.value })} placeholder="What time will you reach?" />
                  </label>
                  {q.kind === "choice" && (
                    <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-[var(--haip-fg-muted)]">Choices, one per line
                      <textarea className={`${input} min-h-24 py-2`} disabled={!canEdit} value={q.options.join("\n")}
                        onChange={e => editQ(i, { options: e.target.value.split("\n").slice(0, 8) })} placeholder={"Before 2 pm\n2 to 6 pm\nAfter 6 pm"} />
                    </label>
                  )}
                  <label className="flex min-h-11 items-center gap-3 text-[15px]">
                    <input type="checkbox" className="size-5 accent-[var(--primary)]" checked={q.required} disabled={!canEdit} onChange={e => editQ(i, { required: e.target.checked })} />
                    Required
                  </label>
                </div>
              ))}
              {canEdit && cfg.questions.length < 8 && (
                <div className="flex flex-wrap gap-2">
                  {KINDS.map(k => (
                    <button key={k.kind} type="button" className="min-h-11 rounded-full border border-dashed border-[var(--haip-border-strong)] px-4 text-[14px]"
                      onClick={() => edit({ questions: [...cfg.questions, { id: newId(), label: "", kind: k.kind, options: k.kind === "choice" ? ["", ""] : [], required: false }] })}>
                      + {k.label}
                    </button>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Welcome line and house rules" />
            <CardBody className="flex flex-col gap-3">
              <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-[var(--haip-fg-muted)]">Shown at the top of the form
                <input className={input} value={cfg.welcome} maxLength={200} disabled={!canEdit} onChange={e => edit({ welcome: e.target.value })}
                  placeholder="Help us get your stay ready. Takes about 3 minutes." />
              </label>
              <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-[var(--haip-fg-muted)]">House rules link (guests agree before signing)
                <input className={input} value={cfg.rules_url} maxLength={300} inputMode="url" disabled={!canEdit} onChange={e => edit({ rules_url: e.target.value })}
                  placeholder="https://" />
              </label>
            </CardBody>
          </Card>
        </div>

        <aside className="flex w-full flex-[1_1_320px] flex-col items-center gap-2 lg:sticky lg:top-24 lg:max-w-[360px]">
          <span className="self-start text-[13px] font-semibold text-[var(--haip-fg-subtle)]">Live preview</span>
          <div className="w-[300px] overflow-hidden rounded-[36px] border-[10px] border-[var(--haip-fg)] bg-[var(--haip-canvas)]">
            <div className="flex flex-col gap-1 bg-primary px-4 py-4 text-primary-foreground">
              <span className="font-[family-name:var(--font-display)] text-[19px] font-semibold">Before you arrive</span>
              <span className="text-[12px] opacity-90">{cfg.welcome || "Please fill this in for everyone staying. About 3 minutes."}</span>
            </div>
            <ol className="flex flex-col gap-2 p-3">
              {preview.map((p, n) => (
                <li key={`${p}-${n}`} className="rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2.5 text-[13px]">{p}</li>
              ))}
            </ol>
          </div>
          <span className="max-w-[300px] text-center text-[13px] text-[var(--haip-fg-subtle)]">New links use it at once. Forms already filled keep their answers.</span>
        </aside>
      </div>

      {canEdit && (dirty || saved || save.isError) && (
        <div className="sticky bottom-[calc(68px+env(safe-area-inset-bottom))] z-30 rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-4 py-3 shadow-sm md:bottom-4">
          <div className="flex flex-wrap items-center justify-end gap-3">
            {save.isError && <span role="alert" className="flex-1 text-[14px] text-[var(--haip-status-danger-fg)]">{errorText(save.error)}</span>}
            {saved && !dirty && !save.isError && <span className="flex-1 text-[14px] text-[var(--haip-fg-subtle)]">Saved. New guest links use this form.</span>}
            <button type="button" className="haip-btn-secondary min-h-11 px-4" disabled={!dirty || save.isPending} onClick={() => { setCfg(data.config); save.reset(); }}>Undo changes</button>
            <button type="button" className="haip-btn-primary min-h-11 px-5" disabled={!dirty || save.isPending}
              onClick={() => save.mutate({ ...cfg, questions: cfg.questions.map(q => ({ ...q, options: q.options.map(o => o.trim()).filter(Boolean) })) })}>
              {save.isPending ? "Saving…" : "Save form"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
