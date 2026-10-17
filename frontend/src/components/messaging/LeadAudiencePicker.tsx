"use client";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, AlertCircle, Users } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

export interface LeadFilter {
  heat?: string[]; stage_ids?: string[]; sources?: string[]; assigned_to?: string[];
  trip_within_days?: number; quiet_days_min?: number; created_within_days?: number; not_messaged_days?: number;
  quoted_open?: boolean; past_guests?: boolean;
}

interface Tally { leads: number; with_phone: number }
interface Options {
  totals: Tally;
  presets: { id: string; label: string; description: string; filter: LeadFilter }[];
  stages: (Tally & { id: string; label: string; category: string | null })[];
  sources: (Tally & { value: string; label: string })[];
  owners: (Tally & { id: string; name: string })[];
}
export interface Preview {
  matched: number; will_receive: number; no_phone: number; invalid_phone: number; opted_out: number;
  recently_messaged: number; truncated: boolean; heat: { hot: number; warm: number; cold: number };
  sample: { name: string | null; phone: string; heat: string | null; why: string[] }[];
}

const HEAT_STYLE: Record<string, string> = {
  hot: "bg-red-50 text-red-700 border-red-200", warm: "bg-amber-50 text-amber-700 border-amber-200", cold: "bg-blue-50 text-blue-700 border-blue-200",
};

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on}
      className={cn("px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-colors text-left",
        on ? "bg-primary text-white border-primary" : "bg-white text-[var(--haip-fg-muted)] border-[var(--haip-border)] hover:border-[color-mix(in_srgb,var(--primary)_25%,transparent)]")}>
      {children}
    </button>
  );
}

const toggle = (list: string[] | undefined, v: string) => {
  const cur = list ?? [];
  const next = cur.includes(v) ? cur.filter(x => x !== v) : [...cur, v];
  return next.length ? next : undefined;
};

function Pick({ label, value, onChange, options }: {
  label: string; value: number | undefined; onChange: (v: number | undefined) => void; options: number[];
}) {
  return (
    <label className="block">
      <span className="text-[11px] font-medium text-[var(--haip-fg-muted)] block mb-1">{label}</span>
      <select value={value ?? ""} onChange={e => onChange(e.target.value ? Number(e.target.value) : undefined)}
        className="w-full px-2.5 py-2 border border-[var(--haip-border)] rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-primary/30">
        <option value="">Any</option>
        {options.map(n => <option key={n} value={n}>{n} days</option>)}
      </select>
    </label>
  );
}

export function LeadAudiencePicker({ filter, onChange, consent, onConsent, onPreview }: {
  filter: LeadFilter; onChange: (f: LeadFilter) => void;
  consent: boolean; onConsent: (v: boolean) => void; onPreview?: (p: Preview | undefined) => void;
}) {
  const set = (patch: Partial<LeadFilter>) => onChange({ ...filter, ...patch });

  const { data: opts } = useQuery<Options>({
    queryKey: ["wa-audience-options"],
    queryFn: () => api.get("/messaging/campaigns/audience-options").then(r => r.data),
    staleTime: 60_000,
  });

  // Recount a moment after the last click, not on every one.
  const [settled, setSettled] = useState(filter);
  useEffect(() => { const t = setTimeout(() => setSettled(filter), 350); return () => clearTimeout(t); }, [filter]);
  const { data: preview, isFetching, isError } = useQuery<Preview>({
    queryKey: ["wa-audience-preview", settled],
    queryFn: () => api.post("/messaging/campaigns/audience-preview", { audience_filter: settled }).then(r => r.data),
    staleTime: 0,
    placeholderData: (prev) => prev,
  });
  useEffect(() => { onPreview?.(preview); }, [preview, onPreview]);

  const left = preview ? preview.no_phone + preview.invalid_phone + preview.opted_out + preview.recently_messaged : 0;

  return (
    <div className="space-y-4">
      {opts && (
        <p className="text-xs text-[var(--haip-fg-subtle)] flex items-center gap-1.5">
          <Users size={13} className="text-[var(--haip-fg-subtle)]" />
          <span><strong className="text-[var(--haip-fg)]">{opts.totals.leads.toLocaleString()}</strong> leads in your CRM ·{" "}
            <strong className="text-[var(--haip-fg)]">{opts.totals.with_phone.toLocaleString()}</strong> have a phone number</span>
        </p>
      )}

      {/* Ready-made segments */}
      <div>
        <p className="text-[11px] font-semibold text-[var(--haip-fg-2)] mb-1.5">Start from a segment</p>
        <div className="flex flex-wrap gap-1.5">
          <Chip on={Object.keys(filter).filter(k => k !== "not_messaged_days").length === 0} onClick={() => onChange({ not_messaged_days: filter.not_messaged_days })}>
            Everyone with a phone
          </Chip>
          {(opts?.presets ?? []).map(p => (
            <Chip key={p.id} on={JSON.stringify(p.filter) === JSON.stringify({ ...filter, not_messaged_days: undefined })}
              onClick={() => onChange({ ...p.filter, not_messaged_days: filter.not_messaged_days })}>
              <span title={p.description}>{p.label}</span>
            </Chip>
          ))}
        </div>
      </div>

      {/* Filters */}
      <details className="group border border-[var(--haip-border)] rounded-xl" open>
        <summary className="cursor-pointer select-none px-3 py-2 text-xs font-semibold text-[var(--haip-fg-2)]">Narrow it down</summary>
        <div className="px-3 pb-3 space-y-3">
          <div>
            <p className="text-[11px] font-medium text-[var(--haip-fg-muted)] mb-1">How warm the lead is</p>
            <div className="flex gap-1.5">
              {["hot", "warm", "cold"].map(h => (
                <Chip key={h} on={!!filter.heat?.includes(h)} onClick={() => set({ heat: toggle(filter.heat, h) })}><span className="capitalize">{h}</span></Chip>
              ))}
            </div>
            <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">From mood, urgency, trip dates, group size, quote and how much they've chatted.</p>
          </div>

          {opts && opts.stages.length > 0 && (
            <div>
              <p className="text-[11px] font-medium text-[var(--haip-fg-muted)] mb-1">Stage</p>
              <div className="flex flex-wrap gap-1.5">
                {opts.stages.filter(s => s.leads > 0).map(s => (
                  <Chip key={s.id} on={!!filter.stage_ids?.includes(s.id)} onClick={() => set({ stage_ids: toggle(filter.stage_ids, s.id) })}>
                    {s.label} <span className="opacity-70">{s.with_phone.toLocaleString()}</span>
                  </Chip>
                ))}
              </div>
            </div>
          )}

          {opts && opts.sources.length > 0 && (
            <div>
              <p className="text-[11px] font-medium text-[var(--haip-fg-muted)] mb-1">Where they came from</p>
              <div className="flex flex-wrap gap-1.5">
                {opts.sources.map(s => (
                  <Chip key={s.value} on={!!filter.sources?.includes(s.value)} onClick={() => set({ sources: toggle(filter.sources, s.value) })}>
                    <span className="capitalize">{s.label}</span> <span className="opacity-70">{s.with_phone.toLocaleString()}</span>
                  </Chip>
                ))}
              </div>
            </div>
          )}

          {opts && opts.owners.length > 1 && (
            <div>
              <p className="text-[11px] font-medium text-[var(--haip-fg-muted)] mb-1">Owner</p>
              <div className="flex flex-wrap gap-1.5">
                {opts.owners.map(o => (
                  <Chip key={o.id} on={!!filter.assigned_to?.includes(o.id)} onClick={() => set({ assigned_to: toggle(filter.assigned_to, o.id) })}>
                    {o.name} <span className="opacity-70">{o.with_phone.toLocaleString()}</span>
                  </Chip>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Pick label="Trip in the next" value={filter.trip_within_days} onChange={v => set({ trip_within_days: v })} options={[14, 30, 45, 60, 90, 180]} />
            <Pick label="Enquired in the last" value={filter.created_within_days} onChange={v => set({ created_within_days: v })} options={[7, 14, 30, 90, 180]} />
            <Pick label="Quiet for at least" value={filter.quiet_days_min} onChange={v => set({ quiet_days_min: v })} options={[7, 14, 30, 60, 90]} />
            <Pick label="Skip if messaged in the last" value={filter.not_messaged_days} onChange={v => set({ not_messaged_days: v })} options={[7, 14, 30, 60]} />
          </div>

          <div className="flex flex-wrap gap-4 text-xs text-[var(--haip-fg-2)]">
            <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-primary" checked={!!filter.quoted_open} onChange={e => set({ quoted_open: e.target.checked || undefined })} /> Has a quote, not booked</label>
            <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-primary" checked={!!filter.past_guests} onChange={e => set({ past_guests: e.target.checked || undefined })} /> Stayed before</label>
          </div>
        </div>
      </details>

      {/* Result */}
      <div className="rounded-xl border border-[var(--haip-border)] p-3" aria-live="polite">
        {isError ? (
          <p className="text-xs text-red-600 flex items-center gap-1.5"><AlertCircle size={13} /> Couldn't count the audience. Try again.</p>
        ) : !preview ? (
          <p className="text-xs text-[var(--haip-fg-subtle)] flex items-center gap-1.5"><Loader2 size={13} className="animate-spin" /> Counting…</p>
        ) : (
          <>
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-2xl font-bold text-[var(--haip-fg)] tabular-nums">{preview.will_receive.toLocaleString()}</span>
              <span className="text-sm text-[var(--haip-fg-muted)]">will receive this</span>
              {isFetching && <Loader2 size={12} className="animate-spin text-[var(--haip-fg-subtle)]/70" />}
              {preview.will_receive > 0 && (
                <span className="ml-auto flex gap-1">
                  {(["hot", "warm", "cold"] as const).map(h => preview.heat[h] > 0 && (
                    <span key={h} className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full border capitalize", HEAT_STYLE[h])}>{preview.heat[h].toLocaleString()} {h}</span>
                  ))}
                </span>
              )}
            </div>
            {left > 0 && (
              <p className="text-[11px] text-[var(--haip-fg-subtle)] mt-1">
                {preview.matched.toLocaleString()} matched, {left.toLocaleString()} left out:{" "}
                {[
                  preview.no_phone && `${preview.no_phone.toLocaleString()} have no phone number`,
                  preview.invalid_phone && `${preview.invalid_phone.toLocaleString()} have an invalid number`,
                  preview.opted_out && `${preview.opted_out.toLocaleString()} opted out`,
                  preview.recently_messaged && `${preview.recently_messaged.toLocaleString()} messaged recently`,
                ].filter(Boolean).join(" · ")}
              </p>
            )}
            {preview.truncated && <p className="text-[11px] text-amber-700 mt-1">Very large audience: only the first 50,000 leads were considered.</p>}
            {preview.sample.length > 0 && (
              <ul className="mt-3 divide-y divide-[var(--haip-border)] border border-[var(--haip-border)] rounded-lg">
                {preview.sample.map((m, i) => (
                  <li key={i} className="px-3 py-1.5 flex items-center gap-2 text-xs">
                    <span className="font-medium text-[var(--haip-fg)] truncate w-32 flex-shrink-0">{m.name || "—"}</span>
                    <span className="font-mono text-[10px] text-[var(--haip-fg-subtle)] flex-shrink-0">{m.phone}</span>
                    {m.heat && <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded-full border capitalize flex-shrink-0", HEAT_STYLE[m.heat])}>{m.heat}</span>}
                    <span className="text-[10px] text-[var(--haip-fg-subtle)] truncate">{m.why.join(" · ")}</span>
                  </li>
                ))}
                {preview.will_receive > preview.sample.length && (
                  <li className="px-3 py-1.5 text-[10px] text-[var(--haip-fg-subtle)]">…and {(preview.will_receive - preview.sample.length).toLocaleString()} more, hottest first</li>
                )}
              </ul>
            )}
          </>
        )}
      </div>

      <label className={cn("flex items-start gap-2.5 p-3 rounded-xl border cursor-pointer text-xs", consent ? "border-[color-mix(in_srgb,var(--primary)_25%,transparent)] bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)]")}>
        <input type="checkbox" checked={consent} onChange={e => onConsent(e.target.checked)} className="mt-0.5 accent-primary" />
        <span className="text-[var(--haip-fg-2)] leading-snug">
          These leads contacted us or gave us their number, and none have asked us to stop.
          <span className="block text-[10px] text-[var(--haip-fg-subtle)] mt-0.5">Anyone who replied STOP is already left out. This confirmation is saved with the campaign.</span>
        </span>
      </label>
    </div>
  );
}
