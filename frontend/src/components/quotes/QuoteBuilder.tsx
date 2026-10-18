"use client";
// New quote (layout B): the choices on the left, the quote on the right (below on phones), priced by POST /quotes/preview on every
// change (debounced). "Save to lead" re-prices from published records and stores the options (POST /quotes). "Send quote +
// payment link" saves first when needed, then POST /quotes/{id}/send (a Razorpay link per option + the WhatsApp quote).
import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { addDays, entryData, fallbackOption, kitsFor, money, packageLevels, toOptionPayload } from "@/app/dashboard/quotes/quoteHelpers";
import { sendGate } from "@/app/dashboard/quotes/sendHelpers";
import type { Catalog, CatalogEntry, IssueResult, LeadHit, OptionForm, Preview, SendResult, StayCheck } from "@/app/dashboard/quotes/types";
import { useDebounced } from "./LeadPicker";
import { QuoteCard, type SentState } from "./QuoteCard";
import { KitsSection, PlanSection, RouteSection, WhenSection, WhereSection } from "./QuoteSections";
import { RouteEditor } from "./RouteEditor";
import { apiProblems } from "./ui";

const SAVE_FAILED = "quote-save-failed";
const locked = (p: CatalogEntry | undefined) => ((p ? entryData(p).destination_keys : []) as string[] | undefined) ?? [];
const usualNights = (d: CatalogEntry | undefined) => { const n = d ? entryData(d).usual_nights : null; return typeof n === "number" ? n : null; };

function firstForm(c: Catalog): OptionForm {
  const pkg = c.packages.find(p => p.live) ?? c.packages[0];
  const keys = locked(pkg);
  const dest = c.destinations.find(d => (keys.length ? keys.includes(d.key) : !!d.live)) ?? null;
  const levels = pkg ? packageLevels(entryData(pkg)) : [];
  return {
    package_key: pkg?.key ?? "", start_date: addDays(c.today, 7), nights: usualNights(dest ?? undefined) ?? 1, adults: 2, children: 0,
    level: levels[0] ?? null, destination_key: dest?.key ?? null, sights: [], km_rate: null, extra_hours: 0, kits: [], discount_percent: null,
    vehicle_property_id: null, channel: "direct", reseller_tier: null, commission_percent: null,
  };
}

export function QuoteBuilder({ catalog, startRoute, onRouteUsed, onOpenPackages }: {
  catalog: Catalog; startRoute: string | null; onRouteUsed: () => void; onOpenPackages: () => void;
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [form, setForm] = useState<OptionForm>(() => firstForm(catalog));
  const [fallbackKey, setFallbackKey] = useState("");
  const [stayCheck, setStayCheck] = useState<StayCheck>("not_checked");
  const [stayName, setStayName] = useState("");
  const [lead, setLead] = useState<LeadHit | null>(null);
  const [nextAt, setNextAt] = useState("");
  const [editing, setEditing] = useState<null | { entry: CatalogEntry | null }>(null);
  const [saved, setSaved] = useState<IssueResult | null>(null);
  const [sent, setSent] = useState<SentState | null>(null);

  const set = (patch: Partial<OptionForm>) => { setForm(f => ({ ...f, ...patch })); setSaved(null); };

  const selectDest = (key: string) => {
    setForm(f => {
      const dest = catalog.destinations.find(d => d.key === key);
      const pkg = catalog.packages.find(p => p.key === f.package_key);
      const keys = locked(pkg);
      const pkgKey = keys.length && !keys.includes(key) ? (catalog.packages.find(p => !locked(p).length)?.key ?? f.package_key) : f.package_key;
      return { ...f, destination_key: key, sights: [], km_rate: null, nights: usualNights(dest) ?? f.nights, package_key: pkgKey };
    });
    if (fallbackKey === key) setFallbackKey("");
    setSaved(null);
  };

  const selectPlan = (key: string) => {
    setForm(f => {
      const pkg = catalog.packages.find(p => p.key === key);
      const d = pkg ? entryData(pkg) : {};
      const keys = locked(pkg);
      const levels = packageLevels(d);
      const offered = new Set(kitsFor(catalog, key).map(k => k.name));
      let nights = f.nights;
      if (typeof d.duration_hours === "number" && d.duration_hours % 24 === 0) nights = d.duration_hours / 24;
      if (typeof d.min_days === "number") nights = Math.max(nights, d.day_count === "noon_to_noon" ? d.min_days : d.min_days - 1);
      const destKey = keys.length && (!f.destination_key || !keys.includes(f.destination_key)) ? keys[0] : f.destination_key;
      return {
        ...f, package_key: key, km_rate: null, level: levels.length ? (f.level && levels.includes(f.level) ? f.level : levels[0]) : null,
        destination_key: destKey, sights: destKey === f.destination_key ? f.sights : [],
        kits: f.kits.filter(k => offered.has(k)), extra_hours: d.extra_hour_charge ? f.extra_hours : 0, nights,
      };
    });
    setSaved(null);
  };

  // "Quote it" from the Routes tab.
  useEffect(() => {
    if (startRoute) { selectDest(startRoute); onRouteUsed(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startRoute]);

  const fallback = useMemo(() => (fallbackKey ? fallbackOption(form, fallbackKey, catalog) : null), [form, fallbackKey, catalog]);
  const body = useMemo(() => JSON.stringify({
    primary: toOptionPayload(form), fallback: fallback ? toOptionPayload(fallback) : null, stay_check: stayCheck, stay_name: stayName.trim() || null,
  }), [form, fallback, stayCheck, stayName]);
  const debounced = useDebounced(body, 300);
  const preview = useQuery<Preview>({
    queryKey: ["quote-preview", debounced], queryFn: () => api.post("/quotes/preview", JSON.parse(debounced)).then(r => r.data),
    enabled: !!form.package_key && catalog.permissions.can_quote, placeholderData: keepPreviousData, retry: 0, staleTime: 15_000,
  });

  const save = useMutation({
    mutationFn: () => api.post("/quotes", {
      ...JSON.parse(body), inquiry_id: lead!.inquiry_id, next_step_at: nextAt ? new Date(nextAt).toISOString() : null,
    }).then(r => r.data as IssueResult),
    onSuccess: res => {
      setSaved(res);
      qc.invalidateQueries({ queryKey: ["quotes", lead?.inquiry_id] });
      toast({ variant: "success", title: "Quote saved", description: `${money(res.quotes[0]?.amount)} saved to ${lead?.guest_name}. Prices are locked in the quote.` });
    },
    onError: e => toast({ variant: "error", title: "Couldn't save the quote", description: apiProblems(e).message }),
  });

  const send = useMutation({
    mutationFn: async () => {
      // Save first when the quote changed since it was saved (that failure already has its own message).
      const issued = saved ?? await save.mutateAsync().catch(() => { throw new Error(SAVE_FAILED); });
      return api.post(`/quotes/${issued.quotes[0].id}/send`).then(r => r.data as SendResult);
    },
    onSuccess: res => {
      setSent({ quoteId: res.quote_id, journey: res.journey, notice: res.message.status === "queued" ? null : res.message.message });
      qc.invalidateQueries({ queryKey: ["quotes", lead?.inquiry_id] });
      if (res.message.status === "queued") toast({ variant: "success", title: "Quote sent", description: "Sending on WhatsApp with the payment link." });
    },
    onError: e => {
      if (e instanceof Error && e.message === SAVE_FAILED) return;
      toast({ variant: "error", title: "Couldn't send the quote", description: apiProblems(e).message });
    },
  });
  const newQuote = () => {
    setSent(null); setSaved(null); setLead(null); setNextAt(""); setFallbackKey(""); setStayCheck("not_checked"); setStayName("");
    setForm(firstForm(catalog));
  };
  const gate = sendGate({ canQuote: catalog.permissions.can_quote, preview: preview.data, lead, nextAt, saved: !!saved, setup: catalog.send_setup });

  const dest = catalog.destinations.find(d => d.key === form.destination_key);
  const q = preview.data?.primary;
  const editor = editing ? (
    <RouteEditor catalog={catalog} entry={editing.entry} onCancel={() => setEditing(null)}
      onSaved={key => { setEditing(null); selectDest(key); }} />
  ) : null;

  if (!catalog.permissions.can_quote) {
    return <p className="text-[13px] text-[var(--haip-fg-subtle)]">Your role can edit routes and packages but not price quotes. Use the Routes and Packages tabs.</p>;
  }
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_400px]">
      <div className="min-w-0 space-y-4">
        <PlanSection catalog={catalog} form={form} set={set} selectPlan={selectPlan} onOpenPackages={onOpenPackages} />
        <WhereSection catalog={catalog} form={form} selectDest={selectDest} onNewRoute={() => setEditing({ entry: null })}
          editor={editing && !editing.entry ? editor : null} />
        <WhenSection catalog={catalog} form={form} set={set} days={q?.days ?? null} vehicles={q?.availability ?? []}
          stayCheck={stayCheck} onStayCheck={v => { setStayCheck(v); setSaved(null); }} stayName={stayName} onStayName={setStayName} />
        <RouteSection dest={dest} form={form} set={set} km={q?.km ?? null} onEditRoute={() => setEditing({ entry: dest ?? null })} />
        {editing?.entry ? editor : null}
        <KitsSection catalog={catalog} form={form} set={set} />
      </div>
      <div className="min-w-0 lg:sticky lg:top-4 lg:max-h-[calc(100vh-6rem)] lg:self-start lg:overflow-y-auto">
        <QuoteCard catalog={catalog} form={form} preview={preview.data} loading={preview.isFetching} failed={preview.isError}
          onFix={set} fallbackKey={fallbackKey} onFallback={k => { setFallbackKey(k); setSaved(null); }}
          lead={lead} onLead={l => { setLead(l); setSaved(null); }} nextAt={nextAt} onNextAt={setNextAt}
          onSave={() => save.mutate()} saving={save.isPending} saved={saved}
          gate={gate} onSend={() => send.mutate()} sending={send.isPending} sent={sent} onNewQuote={newQuote} />
      </div>
    </div>
  );
}
