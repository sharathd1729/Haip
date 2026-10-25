"use client";
// The trip file's forms, each in a bottom sheet: Accept (route + km included), crew, odometer (Dispatch / Return), expense,
// extra, and one checklist item. Inputs are 16px+ (no zoom on phones), buttons 48px+. The server checks every rule again.
import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { BottomSheet } from "@/components/ui/kit";
import { EXPENSE_LABELS, type ChecklistItem, type OpsFileFull } from "@/lib/ops";

export type SheetKind = "accept" | "crew" | "dispatch" | "return" | "expense" | "extra" | "item" | null;
type Submit = (path: string, body?: object, method?: "post" | "put") => Promise<boolean>;

const input = "min-h-12 w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] focus:outline-2 focus:outline-[var(--ring)]";
const label = "flex flex-col gap-1.5 text-[14px] font-semibold text-[var(--haip-fg)]";

function Shell({ open, onClose, title, description, busy, submitLabel, onSubmit, children }: {
  open: boolean; onClose: () => void; title: string; description?: string; busy: boolean; submitLabel: string;
  onSubmit: () => void; children: ReactNode;
}) {
  return (
    <BottomSheet open={open} onOpenChange={o => !o && onClose()} title={title} description={description}
      className="sm:mx-auto sm:max-w-lg"
      footer={
        <div className="flex gap-2">
          <button type="button" className="haip-btn-secondary min-h-12 flex-1 text-[15px]" onClick={onClose}>Cancel</button>
          <button type="submit" form="ops-sheet-form" disabled={busy} className="haip-btn-primary min-h-12 flex-[2] text-[15px]">
            {busy ? "Saving…" : submitLabel}
          </button>
        </div>
      }>
      <form id="ops-sheet-form" className="flex flex-col gap-4 pb-2" onSubmit={e => { e.preventDefault(); onSubmit(); }}>
        {children}
      </form>
    </BottomSheet>
  );
}

const num = (v: string) => (v.trim() === "" ? undefined : Number(v));

export function TripSheets({ file, kind, item, onClose, submit, busy }: {
  file: OpsFileFull; kind: SheetKind; item: ChecklistItem | null; onClose: () => void; submit: Submit; busy: boolean;
}) {
  const d = file.details;
  const base = `/ops/files/${file.id}`;
  const [f, setF] = useState<Record<string, string>>({});
  const set = (k: string) => (e: { target: { value: string } }) => setF(p => ({ ...p, [k]: e.target.value }));

  // Fresh values each time a sheet opens (prefilled from the file).
  useEffect(() => {
    if (kind === "accept") setF({ route: d.route ?? "", allowance_km: d.allowance_km ?? "", extra_km_rate: d.extra_km_rate ?? "" });
    else if (kind === "crew") setF({ driver: d.driver_staff_id ?? "", helper: d.helper_staff_id ?? "" });
    else if (kind === "dispatch") setF({ km: d.start_odometer_photo_km ? String(d.start_odometer_photo_km) : "" });
    else if (kind === "return") setF({ km: "" });
    else if (kind === "expense") setF({ category: "fuel", amount: "", vendor: "" });
    else if (kind === "extra") setF({ kind: "upsell", label: "", amount: "" });
    else if (kind === "item") setF({ note: item?.note ?? "" });
    // Only when a sheet opens: a background refetch of the file must not wipe what the person is typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, item?.key, file.id]);

  const staff = useQuery<{ id: string; name: string; active: boolean }[]>({
    queryKey: ["ops-staff"], queryFn: () => api.get("/ops/staff").then(r => r.data), enabled: kind === "crew", staleTime: 60_000,
  });
  const done = async (ok: Promise<boolean>) => { if (await ok) onClose(); };

  return (
    <>
      <Shell open={kind === "accept"} onClose={onClose} title="Accept the trip" busy={busy} submitLabel="Accept"
        description="Check the route is possible: height, parking, permits, partner site."
        onSubmit={() => done(submit(`${base}/accept`, {
          route: f.route, allowance_km: num(f.allowance_km ?? ""), extra_km_rate: num(f.extra_km_rate ?? ""),
        }))}>
        <label className={label}>Route<input className={input} required value={f.route ?? ""} onChange={set("route")} placeholder="Bangalore → Coorg → Bangalore" /></label>
        <label className={label}>Km included
          <input className={input} inputMode="numeric" value={f.allowance_km ?? ""} onChange={set("allowance_km")} placeholder="From the quote" />
        </label>
        <label className={label}>Extra km rate (₹ per km{d.rate_includes_gst ? ", GST included" : ", before GST"})
          <input className={input} inputMode="decimal" value={f.extra_km_rate ?? ""} onChange={set("extra_km_rate")} />
        </label>
        {d.rate_source && <p className="text-[13px] text-[var(--haip-fg-subtle)]">Filled from the booking&apos;s quote. Change it only if the guest agreed something else.</p>}
      </Shell>

      <Shell open={kind === "crew"} onClose={onClose} title="Driver and helper" busy={busy} submitLabel="Save crew"
        description="Nobody can be on two trips at the same time."
        onSubmit={() => done(submit(`${base}/crew`, { driver_staff_id: f.driver, helper_staff_id: f.helper }))}>
        {(["driver", "helper"] as const).map(role => (
          <label key={role} className={label}>{role === "driver" ? "Driver" : "Helper"}
            <select className={input} required value={f[role] ?? ""} onChange={set(role)}>
              <option value="">Pick a person</option>
              {(staff.data ?? []).filter(s => s.active).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
        ))}
        {staff.data?.length === 0 && <p className="text-[13.5px] text-[var(--haip-fg-subtle)]">Add your drivers and helpers in Ops settings first.</p>}
      </Shell>

      <Shell open={kind === "dispatch" || kind === "return"} onClose={onClose} busy={busy}
        title={kind === "dispatch" ? "Dispatch the trip" : "Vehicle is back"}
        description={kind === "dispatch" ? "This tap starts the trip. Check the odometer number." : "Enter the end odometer. Extra km is added to the bill."}
        submitLabel={kind === "dispatch" ? "Dispatch now" : "Save return"}
        onSubmit={() => done(submit(`${base}/${kind}`, { reading_km: num(f.km ?? "") }))}>
        <label className={label}>Odometer (km)
          <input className={input} required inputMode="numeric" pattern="[0-9]*" value={f.km ?? ""} onChange={set("km")} />
        </label>
        {kind === "dispatch" && d.start_odometer_photo_km && (
          <p className="text-[13px] text-[var(--haip-fg-subtle)]">Read from the driver&apos;s photo. Change it if the photo was wrong.</p>
        )}
      </Shell>

      <Shell open={kind === "expense"} onClose={onClose} title="Add an expense" busy={busy} submitLabel="Add"
        description="Drivers can also send the bill photo on WhatsApp."
        onSubmit={() => done(submit(`${base}/expenses`, { category: f.category, amount: num(f.amount ?? ""), vendor: f.vendor || undefined }))}>
        <label className={label}>What for
          <select className={input} value={f.category ?? "fuel"} onChange={set("category")}>
            {Object.entries(EXPENSE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className={label}>Amount (₹, GST included)<input className={input} required inputMode="decimal" value={f.amount ?? ""} onChange={set("amount")} /></label>
        <label className={label}>Shop or vendor (optional)<input className={input} value={f.vendor ?? ""} onChange={set("vendor")} /></label>
      </Shell>

      <Shell open={kind === "extra"} onClose={onClose} title="Something the guest asked for" busy={busy} submitLabel="Add for approval"
        description="It is billed only after a manager approves it."
        onSubmit={() => done(submit(`${base}/extras`, { kind: f.kind, label: f.label, amount: num(f.amount ?? "") }))}>
        <label className={label}>What<input className={input} required value={f.label ?? ""} onChange={set("label")} placeholder="Bonfire kit" /></label>
        <label className={label}>Type
          <select className={input} value={f.kind ?? "upsell"} onChange={set("kind")}>
            <option value="upsell">Add-on</option><option value="extra_hours">Extra hours</option><option value="extra_route">Extra stop or route</option>
            <option value="extra_guest">Extra guest</option><option value="damage">Damage</option><option value="other">Other</option>
          </select>
        </label>
        <label className={label}>Price (₹, GST included)<input className={input} required inputMode="decimal" value={f.amount ?? ""} onChange={set("amount")} /></label>
      </Shell>

      <BottomSheet open={kind === "item" && !!item} onOpenChange={o => !o && onClose()} title={item?.label ?? ""}
        className="sm:mx-auto sm:max-w-lg"
        description={item ? (item.source === "staff" ? "Usually ticked by the helper's WhatsApp photo." : item.source === "system" ? "Ticked by HAIP from the booking." : "Your check.") : undefined}>
        {item && (
          <div className="flex flex-col gap-3 pb-2">
            {item.ai_verdict && (
              <p className="rounded-xl bg-[var(--haip-surface)] px-3 py-2 text-[14px]">
                Photo check: {item.ai_verdict.ok ? "looks fine" : item.ai_verdict.problems.join("; ") || "does not look right"}
              </p>
            )}
            <label className={label}>Note (optional)<input className={input} value={f.note ?? ""} onChange={set("note")} /></label>
            <button type="button" disabled={busy} className="haip-btn-primary min-h-12 text-[15px]"
              onClick={() => done(submit(`${base}/checklist/${item.key}`, { status: "green", note: f.note || undefined }, "put"))}>It&apos;s fine</button>
            <button type="button" disabled={busy} className="haip-btn-secondary min-h-12 text-[15px]"
              onClick={() => done(submit(`${base}/checklist/${item.key}`, { status: "red", note: f.note || undefined }, "put"))}>There is a problem</button>
            {item.status !== "pending" && (
              <button type="button" disabled={busy} className="min-h-12 text-[15px] font-semibold text-[var(--haip-fg-muted)]"
                onClick={() => done(submit(`${base}/checklist/${item.key}`, { status: "pending" }, "put"))}>Not checked yet</button>
            )}
          </div>
        )}
      </BottomSheet>
    </>
  );
}
