"use client";
// The left column of the quote builder: plan, route, dates and party, caravan, overnight stay, kilometres, kits and discount.
// These only collect choices; the price comes from the server (QuoteCard).
import type { ReactNode } from "react";
import { Plus, X } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import {
  addDays, commissionOptions, dayLabel, entryData, entryName, entryState, kitsFor, kmRateOptions, kmText, money, packageLevels, packageTag,
  routeKm, routeSights, routeStops, tierFor,
} from "@/app/dashboard/quotes/quoteHelpers";
import type { Catalog, CatalogEntry, KmDetail, OptionForm, StayCheck, Vehicle } from "@/app/dashboard/quotes/types";
import { BTN_GHOST, Chip, Field, INPUT, Stepper } from "./ui";

type Set = (patch: Partial<OptionForm>) => void;

function Pending({ e }: { e: CatalogEntry }) {
  const s = entryState(e);
  if (s === "published") return null;
  return <StatusPill tone="warning">{s === "new" ? "New, waiting approval" : `v${(e.live?.version ?? 0) + 1} waiting approval`}</StatusPill>;
}

function PickCard({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
      className={cn("flex min-h-11 flex-col items-start gap-1 rounded-xl border p-3 text-left transition-colors",
        on ? "border-primary bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)] bg-[var(--haip-card)] hover:border-[var(--haip-border-strong)]")}>
      {children}
    </button>
  );
}

export function PlanSection({ catalog, form, set, selectPlan, onOpenPackages }: {
  catalog: Catalog; form: OptionForm; set: Set; selectPlan: (k: string) => void; onOpenPackages: () => void;
}) {
  const current = catalog.packages.find(p => p.key === form.package_key);
  const levels = current ? packageLevels(entryData(current)) : [];
  const tier = tierFor(catalog, form.package_key);
  return (
    <Card>
      <CardHeader title="Plan" />
      <CardBody className="space-y-3">
        {catalog.packages.length === 0 ? (
          <p className="text-[13px] text-[var(--haip-fg-subtle)]">No packages yet. Add one in the Packages tab; it can be priced here once it is saved.</p>
        ) : (
          <div role="group" aria-label="Plan" className="grid gap-2 sm:grid-cols-2">
            {catalog.packages.map(p => {
              const d = entryData(p);
              return (
                <PickCard key={p.key} on={form.package_key === p.key} onClick={() => selectPlan(p.key)}>
                  <b className="text-[14px]">{entryName(p)}</b>
                  <span className="num text-[13px] font-semibold text-primary">{packageTag(d)}</span>
                  {d.summary ? <span className="line-clamp-2 text-[12px] text-[var(--haip-fg-subtle)]">{String(d.summary)}</span> : null}
                  <Pending e={p} />
                </PickCard>
              );
            })}
          </div>
        )}
        {levels.length > 0 && (
          <div role="group" aria-label="Level" className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-[var(--haip-fg-2)]">Level</span>
            {levels.map(l => <Chip key={l} on={form.level === l} onClick={() => set({ level: l })}>{/^\d+$/.test(l) ? `${money(l)} a day` : l}</Chip>)}
          </div>
        )}
        <div role="group" aria-label="Selling to" className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-[var(--haip-fg-2)]">Selling to</span>
          <Chip on={form.channel === "direct"} onClick={() => set({ channel: "direct" })}>Guest directly</Chip>
          <Chip on={form.channel === "reseller"} onClick={() => set({ channel: "reseller", reseller_tier: tier?.name ?? null, commission_percent: tier ? String(Number(tier.commission_percent)) : null })}>Reseller (B2B)</Chip>
          {form.channel === "reseller" && tier && (
            <select aria-label="Commission" value={form.commission_percent ?? ""} onChange={e => set({ commission_percent: e.target.value })} className={cn(INPUT, "w-auto")}>
              {commissionOptions(tier).map(c => <option key={c} value={c}>{c}% commission</option>)}
            </select>
          )}
        </div>
        {form.channel === "reseller" && !tier && <p className="text-xs text-[var(--haip-status-warning-fg)]">No reseller terms are published for this plan.</p>}
        <button type="button" className={BTN_GHOST} onClick={onOpenPackages}>Edit or add packages</button>
      </CardBody>
    </Card>
  );
}

export function WhereSection({ catalog, form, selectDest, onNewRoute, editor }: {
  catalog: Catalog; form: OptionForm; selectDest: (k: string) => void; onNewRoute: () => void; editor: ReactNode;
}) {
  return (
    <Card>
      <CardHeader title="Where" />
      <CardBody className="space-y-3">
        <div role="group" aria-label="Route" className="grid gap-2 sm:grid-cols-2">
          {catalog.destinations.map(d => {
            const data = entryData(d);
            const km = routeKm(data);
            const nights = data.usual_nights;
            return (
              <PickCard key={d.key} on={form.destination_key === d.key} onClick={() => selectDest(d.key)}>
                <b className="text-[14px]">{entryName(d)}</b>
                {data.description ? <span className="line-clamp-2 text-[12px] text-[var(--haip-fg-subtle)]">{String(data.description)}</span> : null}
                <span className="num text-[12px] font-semibold text-[var(--haip-fg-2)]">
                  {typeof nights === "number" ? `${nights} night${nights === 1 ? "" : "s"} · ` : ""}{km === null ? "km not set" : kmText(km)}
                </span>
                <Pending e={d} />
              </PickCard>
            );
          })}
          {catalog.permissions.can_draft && (
            <button type="button" onClick={onNewRoute}
              className="flex min-h-11 flex-col items-start gap-1 rounded-xl border border-dashed border-[var(--haip-border-strong)] p-3 text-left hover:bg-[var(--haip-surface)]">
              <b className="flex items-center gap-1 text-[14px]"><Plus size={14} /> New route</b>
              <span className="text-[12px] text-[var(--haip-fg-subtle)]">Guest wants somewhere else? Build it here. It is saved for every agent.</span>
            </button>
          )}
        </div>
        {catalog.destinations.length === 0 && !catalog.permissions.can_draft && <p className="text-[13px] text-[var(--haip-fg-subtle)]">No routes yet.</p>}
        {editor}
      </CardBody>
    </Card>
  );
}

const STAY: { value: StayCheck; label: string }[] = [{ value: "not_checked", label: "Not checked" }, { value: "checking", label: "Checking" }, { value: "confirmed", label: "Confirmed" }];

export function WhenSection({ catalog, form, set, days, vehicles, stayCheck, onStayCheck, stayName, onStayName }: {
  catalog: Catalog; form: OptionForm; set: Set; days: number | null; vehicles: Vehicle[];
  stayCheck: StayCheck; onStayCheck: (v: StayCheck) => void; stayName: string; onStayName: (v: string) => void;
}) {
  const end = addDays(form.start_date, form.nights);
  const list: Vehicle[] = vehicles.length ? vehicles : catalog.vehicles.map(v => ({ property_id: v.id, property_name: v.name, status: "available" as const }));
  const checked = vehicles.length > 0;
  return (
    <Card>
      <CardHeader title="When, who and which caravan" />
      <CardBody className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Field label="Start" htmlFor="q-start" className="col-span-2 sm:col-span-1">
            <input id="q-start" type="date" min={catalog.today} value={form.start_date} onChange={e => e.target.value && set({ start_date: e.target.value })} className={INPUT} />
          </Field>
          <Stepper id="q-nights" label="Nights" value={form.nights} min={0} max={30} onChange={v => set({ nights: v })} />
          <Stepper id="q-adults" label="Adults" value={form.adults} min={1} max={20} onChange={v => set({ adults: v })} />
          <Stepper id="q-kids" label="Children" value={form.children} min={0} max={20} onChange={v => set({ children: v })} />
          <Stepper id="q-hours" label="Return late (hours)" value={form.extra_hours} min={0} max={12} onChange={v => set({ extra_hours: v })} />
        </div>
        <p className="text-xs text-[var(--haip-fg-subtle)]">
          {dayLabel(form.start_date)} to {dayLabel(end)}{form.extra_hours ? ` + ${form.extra_hours} h` : ""}
          {days ? ` · ${days} day${days === 1 ? "" : "s"} billed` : ""} · {form.adults + form.children} guests
        </p>
        <div className="space-y-2">
          <span className="text-xs font-semibold text-[var(--haip-fg-2)]">Caravan</span>
          <div className="grid gap-2 sm:grid-cols-2">
            {list.map(v => {
              const free = v.status === "available";
              const on = form.vehicle_property_id === v.property_id;
              return (
                <button key={v.property_id} type="button" aria-pressed={on} disabled={checked && !free} onClick={() => set({ vehicle_property_id: v.property_id })}
                  className={cn("flex min-h-11 flex-col items-start rounded-xl border p-3 text-left disabled:cursor-not-allowed disabled:opacity-60",
                    on ? "border-primary bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)] bg-[var(--haip-card)] hover:border-[var(--haip-border-strong)]")}>
                  <b className="text-[14px]">{v.property_name}</b>
                  <span className="text-[12px] text-[var(--haip-fg-subtle)]">
                    {!checked ? "Not checked yet" : v.status === "available" ? (on ? "Free · chosen" : "Free") : v.status === "over_capacity" ? "Too small for this group" : "Booked or blocked on these dates"}
                  </span>
                </button>
              );
            })}
          </div>
          {form.vehicle_property_id && <button type="button" className={BTN_GHOST} onClick={() => set({ vehicle_property_id: null })}>Pick the first free one for me</button>}
        </div>
        <div className="space-y-2">
          <span className="text-xs font-semibold text-[var(--haip-fg-2)]">Overnight stay</span>
          <div className="flex flex-wrap items-center gap-2">
            <div role="group" aria-label="Overnight stay checked" className="flex flex-wrap gap-2">
              {STAY.map(s => <Chip key={s.value} on={stayCheck === s.value} onClick={() => onStayCheck(s.value)}>{s.label}</Chip>)}
            </div>
            <input aria-label="Overnight stay name" value={stayName} maxLength={120} onChange={e => onStayName(e.target.value)} placeholder="Where (e.g. partner stay)" className={cn(INPUT, "sm:w-56")} />
          </div>
          <p className="text-xs text-[var(--haip-fg-subtle)]">Sending the price needs the stay confirmed. It is saved with the quote.</p>
        </div>
      </CardBody>
    </Card>
  );
}

export function RouteSection({ dest, form, set, km, onEditRoute }: {
  dest: CatalogEntry | undefined; form: OptionForm; set: Set; km: KmDetail | null; onEditRoute: () => void;
}) {
  if (!dest) return null;
  const data = entryData(dest);
  const stops = routeStops(data);
  const sights = routeSights(data);
  const planned = Number(km?.planned_km ?? 0), included = km?.included_km != null ? Number(km.included_km) : null;
  const scale = Math.max(planned, included ?? 0, 1) * 1.08;
  const rates = kmRateOptions(km);
  const lastNight = stops.map(s => !!s.overnight).lastIndexOf(true);
  const left = sights.filter(s => !form.sights.includes(s.name));
  return (
    <Card>
      <CardHeader title="Route" description="Distances are the route's own estimates." />
      <CardBody className="space-y-3">
        {km && included === null ? (
          <p className="text-[13px] text-[var(--haip-fg-subtle)]">This plan has no distance charge. {km.planned_km ? `${kmText(km.planned_km)} planned.` : ""}</p>
        ) : km ? (
          <div className="space-y-1.5">
            <div className="flex flex-wrap justify-between gap-2 text-[13px]">
              <b className="num">{kmText(km.planned_km)} planned</b>
              <span className="num text-[var(--haip-fg-subtle)]">{kmText(included)} included{Number(km.extra_km) > 0 ? ` · ${kmText(km.extra_km)} extra` : ""}</span>
            </div>
            <svg viewBox="0 0 100 6" preserveAspectRatio="none" className="h-2 w-full overflow-hidden rounded-full" role="img" aria-label={`${kmText(planned)} of ${kmText(included)} included`}>
              <rect x="0" y="0" width="100" height="6" className="fill-[var(--haip-status-neutral-bg)]" />
              <rect x="0" y="0" width={(planned / scale) * 100} height="6" className="fill-[var(--haip-accent)]" />
              <rect x="0" y="0" width={(Math.min(planned, included ?? 0) / scale) * 100} height="6" className="fill-[var(--primary)]" />
            </svg>
          </div>
        ) : null}
        {rates.length > 0 && Number(km?.extra_km) > 0 && (
          <Field label="Rate for extra km (your call within the published range)" htmlFor="q-kmr" hint="The applied rate is written into the quote.">
            <select id="q-kmr" value={String(Number(form.km_rate ?? km?.applied_rate ?? km?.suggested_rate ?? 0))} onChange={e => set({ km_rate: e.target.value })} className={cn(INPUT, "sm:w-60")}>
              {rates.map(r => <option key={r} value={r}>{money(r)} per km{Number(r) === Number(km?.suggested_rate) ? " (suggested)" : ""}</option>)}
            </select>
          </Field>
        )}
        {km?.rate_mode === "fixed" && Number(km.extra_km) > 0 && <p className="text-xs text-[var(--haip-fg-subtle)]">This plan charges a fixed {money(km.applied_rate)} per extra km.</p>}
        <ol className="space-y-1 border-l-2 border-[var(--haip-border)] pl-3">
          {stops.map((s, i) => (
            <li key={`${s.name}-${i}`} className="space-y-1">
              <div className="flex items-center justify-between gap-2 text-[13px]">
                <span className={cn(s.overnight && "font-semibold")}>{s.name}{s.overnight ? <span className="font-normal text-[var(--haip-fg-subtle)]"> · overnight</span> : null}</span>
                <span className="num shrink-0 text-xs text-[var(--haip-fg-subtle)]">{s.distance_km_from_previous == null ? "km not set" : `+${kmText(s.distance_km_from_previous)}`}</span>
              </div>
              {i === Math.max(lastNight, 0) && form.sights.map(name => {
                const sight = sights.find(x => x.name === name);
                return (
                  <div key={name} className="flex items-center justify-between gap-2 text-[13px]">
                    <span className="min-w-0 truncate">{name} <StatusPill tone="highlight">Added</StatusPill></span>
                    <span className="flex shrink-0 items-center gap-1">
                      <span className="num text-xs text-[var(--haip-fg-subtle)]">+{kmText(sight?.km_round_trip ?? 0)}</span>
                      <button type="button" aria-label={`Remove ${name}`} onClick={() => set({ sights: form.sights.filter(x => x !== name) })}
                        className="flex h-11 w-11 items-center justify-center rounded-lg text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-surface)] sm:h-7 sm:w-7"><X size={13} /></button>
                    </span>
                  </div>
                );
              })}
            </li>
          ))}
        </ol>
        {left.length > 0 && (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Add a sight">
            {left.map(s => <Chip key={s.name} on={false} onClick={() => set({ sights: [...form.sights, s.name] })}>+ {s.name} <span className="num text-[var(--haip-fg-subtle)]">{kmText(s.km_round_trip)}</span></Chip>)}
          </div>
        )}
        <button type="button" className={BTN_GHOST} onClick={onEditRoute}>Change this route</button>
      </CardBody>
    </Card>
  );
}

const DISCOUNTS = ["0", "2.5", "5", "7.5", "10"];

export function KitsSection({ catalog, form, set }: { catalog: Catalog; form: OptionForm; set: Set }) {
  const pkg = catalog.packages.find(p => p.key === form.package_key);
  const included = !!(pkg && entryData(pkg).kits_included);
  const kits = kitsFor(catalog, form.package_key);
  return (
    <Card>
      <CardHeader title="Kits and discount" />
      <CardBody className="space-y-3">
        {kits.length === 0 ? <p className="text-[13px] text-[var(--haip-fg-subtle)]">This plan has no experience kits.</p> : (
          <div className="space-y-1">
            {kits.map(k => (
              <label key={k.name} className="flex min-h-11 cursor-pointer items-center gap-3">
                <input type="checkbox" checked={form.kits.includes(k.name)} className="h-5 w-5 accent-[var(--primary)]"
                  onChange={e => set({ kits: e.target.checked ? [...form.kits, k.name] : form.kits.filter(x => x !== k.name) })} />
                <span className="flex-1 text-[13.5px] font-medium">{k.name}</span>
                <span className="num text-[13px] text-[var(--haip-fg-subtle)]">{included ? "Included" : `${money(k.amount)}${k.unit === "per_day" ? " a day" : ""}`}</span>
              </label>
            ))}
            <p className="text-xs text-[var(--haip-fg-subtle)]">Suggest only the one kit that fits the trip.</p>
          </div>
        )}
        <Field label="Closing discount" htmlFor="q-disc" hint="Checked against the published discount limits; shown as its own line.">
          <select id="q-disc" value={form.discount_percent ?? "0"} onChange={e => set({ discount_percent: e.target.value === "0" ? null : e.target.value })} className={cn(INPUT, "sm:w-40")}>
            {DISCOUNTS.map(d => <option key={d} value={d}>{d === "0" ? "None" : `${d}%`}</option>)}
          </select>
        </Field>
      </CardBody>
    </Card>
  );
}
