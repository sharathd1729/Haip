"use client";
// Self check-in on one property (Ops 2, gap 7): nobody meets the guest, so the property holds the steps, lock code and key box.
// Only whole-unit segments offer it (segment profile ops.selfCheckIn). The backend keeps the values encrypted and shows them
// only to owner/manager (ops.manage); other ops roles see whether each is set. The pre-arrival message (card Ops 2d) sends them.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { Drawer } from "@/components/ui/kit";
import { OPS_READ_ROLES, canManageOps } from "@/lib/ops";
import { useSegment } from "@/lib/segments";

interface View {
  enabled: boolean; revealed: boolean; offered: boolean;
  set: { steps: boolean; lock_code: boolean; key_box: boolean };
  steps: string | null; lock_code: string | null; key_box: string | null;
}
type Draft = { steps: string; lock_code: string; key_box: string };

export function SelfCheckInButton({ propertyId, name }: { propertyId: string; name: string }) {
  const seg = useSegment();
  const role = useSession().data?.user?.role;
  const [open, setOpen] = useState(false);
  if (!seg.ops.selfCheckIn || !OPS_READ_ROLES.includes(role ?? "")) return null;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}
        className="min-h-11 w-full rounded-xl border border-[var(--haip-border)] px-3 text-left text-sm font-semibold text-primary hover:border-primary">
        Self check-in
      </button>
      {open && <SelfCheckInSheet propertyId={propertyId} name={name} manage={canManageOps(role)} onClose={() => setOpen(false)} />}
    </>
  );
}

function SelfCheckInSheet({ propertyId, name, manage, onClose }: { propertyId: string; name: string; manage: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const key = ["ops-self-check-in", propertyId];
  const q = useQuery<View>({ queryKey: key, queryFn: () => api.get(`/ops/properties/${propertyId}/self-check-in`).then(r => r.data), gcTime: 0 });
  const [draft, setDraft] = useState<Draft | null>(null);
  const v = q.data;
  const d: Draft = draft ?? { steps: v?.steps ?? "", lock_code: v?.lock_code ?? "", key_box: v?.key_box ?? "" };
  const save = useMutation({
    mutationFn: (body: Partial<Draft> & { enabled?: boolean }) => api.put(`/ops/properties/${propertyId}/self-check-in`, body).then(r => r.data as View),
    onSuccess: data => { qc.setQueryData(key, data); setDraft(null); },
  });
  const err = (save.error as { response?: { data?: { detail?: unknown } } } | null)?.response?.data?.detail;

  return (
    <Drawer open onOpenChange={o => { if (!o) onClose(); }} title={`Self check-in: ${name}`}
      description="Nobody meets the guest here. The pre-arrival message carries these steps.">
      {q.isPending ? <p className="text-sm text-[var(--haip-fg-subtle)]">Loading…</p>
        : q.isError || !v ? <p role="alert" className="text-sm text-[var(--haip-status-danger-fg)]">Couldn&apos;t load self check-in. Close and try again.</p>
        : (
          <div className="space-y-4">
            <label className="flex min-h-11 items-center justify-between gap-3 rounded-xl border border-[var(--haip-border)] px-3">
              <span className="text-[15px] font-semibold">Guests check themselves in</span>
              <input type="checkbox" className="h-5 w-5" checked={v.enabled} disabled={!manage || save.isPending}
                onChange={e => save.mutate({ ...(draft ?? {}), enabled: e.target.checked })} />
            </label>
            {!manage ? (
              <ul className="space-y-1 text-sm text-[var(--haip-fg-2)]">
                <li>Check-in steps: {v.set.steps ? "set" : "not set"}</li>
                <li>Lock code: {v.set.lock_code ? "set" : "not set"}</li>
                <li>Key box: {v.set.key_box ? "set" : "not set"}</li>
                <li className="text-[var(--haip-fg-subtle)]">Only the owner or a manager can see and change these.</li>
              </ul>
            ) : (
              <>
                <Text label="Check-in steps" value={d.steps} multiline onChange={s => setDraft({ ...d, steps: s })}
                  hint="Where to park, which gate, which floor, how to open the door." />
                <Text label="Lock code" value={d.lock_code} onChange={s => setDraft({ ...d, lock_code: s })} />
                <Text label="Key box" value={d.key_box} onChange={s => setDraft({ ...d, key_box: s })} hint="Where it is and its code." />
                {typeof err === "string" && <p role="alert" className="text-sm text-[var(--haip-status-danger-fg)]">{err}</p>}
                <button type="button" className="haip-btn-primary min-h-11 px-5 disabled:opacity-50" disabled={!draft || save.isPending}
                  onClick={() => save.mutate(d)}>
                  {save.isPending ? "Saving…" : "Save"}
                </button>
              </>
            )}
          </div>
        )}
    </Drawer>
  );
}

function Text({ label, value, onChange, hint, multiline }: { label: string; value: string; onChange: (v: string) => void; hint?: string; multiline?: boolean }) {
  const cls = "w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2.5 text-base";
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium text-[var(--haip-fg-2)]">{label}</span>
      {multiline
        ? <textarea rows={4} maxLength={1500} className={cls} value={value} onChange={e => onChange(e.target.value)} autoComplete="off" />
        : <input className={cls} value={value} maxLength={label === "Lock code" ? 40 : 200} onChange={e => onChange(e.target.value)} autoComplete="off" spellCheck={false} />}
      {hint && <span className="block text-xs text-[var(--haip-fg-subtle)]">{hint}</span>}
    </label>
  );
}
