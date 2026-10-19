"use client";
// New booking, layout "A · One page": seven numbered sections (each number becomes a tick, or "!" after Create finds a problem
// there); desktop (>= 1024px) keeps a sticky side card with the summary, the clickable "Still needed" list and Create; a phone
// keeps a bottom bar (total + the first missing thing + Review) that opens a review sheet. Create with problems scrolls to the
// first bad section. The server prices, checks the caravans and decides what is missing (POST /bookings/compose/preview);
// Create (POST /bookings/compose) answers with a receipt of what HAIP did.
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { ArrowLeft } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/kit";
import { BTN } from "@/components/quotes/ui";
import { useDebounced } from "@/components/quotes/calc/useDebounced";
import { GuestSection } from "./GuestSection";
import { TripSection } from "./TripSection";
import { VehicleSection } from "./VehicleSection";
import { AddonsSection, PriceSection } from "./PriceSections";
import { ConfirmSection, PaymentSection } from "./PaySections";
import { BottomBar, Receipt, ReviewSheet, SummaryAside } from "./Summary";
import { allProblems, applyQuote, applyTrip, defaultForm, firstProblemSection, money, pickGuest, SECTIONS, sectionMark, shownProblems, span, toPayload } from "./helpers";
import type { BookingForm, ComposeContext, ComposeReceipt, ComposeSetup, GuestCard, Preview, Problem, QuoteCard, Section, SourceKey } from "./types";
import { Messages, SectionCard } from "./ui";

export interface FlowParams { inquiry?: string | null; guest?: string | null; quote?: string | null; property?: string | null; from?: string | null; to?: string | null }

const errDetail = (e: unknown) => (e as { response?: { status?: number; data?: { detail?: { message?: string; problems?: Problem[] } | string } } })?.response;

export function NewBookingFlow({ params }: { params: FlowParams }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const setupQ = useQuery<ComposeSetup>({ queryKey: ["new-booking-setup"], queryFn: () => api.get("/bookings/compose/setup").then(r => r.data) });
  const [form, setForm] = useState<BookingForm | null>(null);
  const [ctx, setCtx] = useState<ComposeContext | undefined>();
  const [showErr, setShowErr] = useState(false);
  const [review, setReview] = useState(false);
  const [done, setDone] = useState<ComposeReceipt | null>(null);
  const [serverProblems, setServerProblems] = useState<Problem[] | null>(null);
  const started = useRef(false);
  const setup = setupQ.data;

  const set = useCallback((patch: Partial<BookingForm>) => { setForm(f => (f ? { ...f, ...patch } : f)); setServerProblems(null); }, []);
  const loadCtx = useCallback((p: Record<string, string>) =>
    qc.fetchQuery<ComposeContext>({ queryKey: ["new-booking-context", p], queryFn: () => api.get("/bookings/compose/context", { params: p }).then(r => r.data) }), [qc]);

  // Start: an empty form, then whatever the page was opened with (a lead, a guest, a quote, a calendar slot).
  useEffect(() => {
    if (!setup || started.current) return;
    started.current = true;
    let f = defaultForm(setup);
    if (params.property && setup.vehicles.some(v => v.id === params.property)) f.vehicle = params.property;
    if (params.from && params.from >= setup.today) f = { ...f, checkIn: params.from, checkOut: params.to && params.to >= params.from ? params.to : params.from };
    setForm(f);
    const p: Record<string, string> = {};
    if (params.quote) p.quote_id = params.quote;
    else if (params.inquiry) p.inquiry_id = params.inquiry;
    else if (params.guest) p.guest_id = params.guest;
    if (!Object.keys(p).length) return;
    loadCtx(p).then(c => {
      setCtx(c);
      if (!c.guest) return;
      setForm(cur => {
        if (!cur) return cur;
        let next = pickGuest(cur, c.guest!, c);
        next.fromLead = !!params.inquiry;
        const q = c.quote_id ? c.quotes.find(x => x.quote_id === c.quote_id) : null;
        if (q) next = applyQuote(next, q.quote_id, q.prefill, setup);
        return next;
      });
    }).catch(() => toast({ variant: "error", title: "Couldn't load that lead or guest", description: "Search for the guest below." }));
  }, [setup, params, loadCtx, toast]);

  const onPick = useCallback((g: GuestCard) => {
    set({ guest: g, newGuest: null, adding: false, guestQ: "" });
    loadCtx({ guest_id: g.guest_id }).then(c => { setCtx(c); setForm(cur => (cur ? pickGuest(cur, c.guest ?? g, c) : cur)); })
      .catch(() => setForm(cur => (cur ? { ...cur, start: "scratch" } : cur)));
  }, [set, loadCtx]);
  const onAddNew = useCallback((ng: { phone: string; name: string; source: SourceKey }) => {
    setCtx(undefined);
    set({ newGuest: ng, guest: null, adding: false, start: "scratch", inquiryId: null });
  }, [set]);
  const onUseQuote = useCallback((q: QuoteCard) => {
    if (!setup) return;
    setForm(cur => (cur ? applyQuote(cur, q.quote_id, q.prefill, setup) : cur));
    setServerProblems(null);
    toast({ variant: "success", title: `Filled from ${q.number}`, description: `Package, dates, ${q.guests ?? ""} guests, add-ons and ${money(q.total)}` });
  }, [setup, toast]);
  const onScratch = useCallback(() => setForm(cur => (cur ? applyTrip({ ...cur, start: "scratch" }, ctx?.trip) : cur)), [ctx]);

  const payload = useMemo(() => (form ? toPayload(form) : null), [form]);
  const debounced = useDebounced(payload, 300);
  const previewQ = useQuery<Preview>({
    queryKey: ["new-booking-preview", debounced],
    queryFn: () => api.post("/bookings/compose/preview", debounced).then(r => r.data),
    enabled: !!debounced && !done,
    placeholderData: prev => prev,
  });
  const preview = previewQ.data;

  const problems = useMemo(() => (form ? serverProblems ?? allProblems(form, preview) : []), [form, preview, serverProblems]);
  const ordered = useMemo(() => [...problems].sort((a, b) => SECTIONS.findIndex(s => s.key === a.section) - SECTIONS.findIndex(s => s.key === b.section)), [problems]);

  const jump = useCallback((s: Section) => {
    setReview(false);
    requestAnimationFrame(() => document.getElementById(`sec-${s}`)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, []);

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<ComposeReceipt>("/bookings/compose", body).then(r => r.data),
    onSuccess: r => { setDone(r); setReview(false); qc.invalidateQueries({ queryKey: ["bookings"] }); window.scrollTo({ top: 0 }); },
    onError: e => {
      const res = errDetail(e);
      const d = res?.data?.detail;
      const list = typeof d === "object" && d?.problems?.length ? d.problems : null;
      if (list) {
        setServerProblems(list);
        setShowErr(true);
        const first = firstProblemSection(list);
        if (first) jump(first);
      }
      toast({ variant: "error", title: res?.status === 409 ? "That caravan is not free" : "Couldn't create the booking",
              description: typeof d === "string" ? d : d?.message ?? "Something went wrong. Try again." });
    },
  });

  const onCreate = () => {
    if (!form || !payload) return;
    if (!preview && !serverProblems) {
      toast({ variant: "info", title: "Still checking the price and caravans. Try again in a moment." });
      return;
    }
    if (problems.length) {
      setShowErr(true);
      const first = firstProblemSection(problems);
      toast({ variant: "error", title: problems.length === 1 ? problems[0].message : `${problems.length} things to fix before creating. ${ordered[0].message}` });
      if (first) jump(first);
      return;
    }
    create.mutate(payload);
  };

  const again = () => { if (!setup) return; setForm(defaultForm(setup)); setCtx(undefined); setDone(null); setShowErr(false); setServerProblems(null); window.scrollTo({ top: 0 }); };

  const back = params.inquiry ? { href: `/dashboard/leads/${params.inquiry}`, label: "Back to the lead" }
    : params.property || params.from ? { href: "/dashboard/portfolio/calendar", label: "Back to the calendar" } : { href: "/dashboard/bookings", label: "Back to Bookings" };
  const subtitle = form?.fromLead && form.guest ? `From ${form.guest.name || "the guest"}'s lead${ctx?.lead?.trip ? ` · ${ctx.lead.trip}` : ""}`
    : params.property || params.from ? "From the calendar" : "From Bookings";
  const head = (
    <div className="flex items-center gap-2">
      <Link href={back.href} aria-label={back.label} className="grid size-11 shrink-0 place-items-center rounded-xl text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]"><ArrowLeft size={18} /></Link>
      <div className="grid min-w-0 flex-1">
        <h1 className="haip-page-title font-[family-name:var(--font-display)] text-[24px] font-semibold leading-tight">New booking</h1>
        <span className="truncate text-[13px] text-[var(--haip-fg-subtle)]">{subtitle}</span>
      </div>
    </div>
  );

  if (setupQ.isError) return (
    <div className="mx-auto max-w-[1240px] px-4 py-6">{head}
      <EmptyState title="Couldn't load the booking form." hint="Check your connection and try again." action={<button type="button" className={BTN} onClick={() => setupQ.refetch()}>Try again</button>} />
    </div>
  );
  if (!setup || !form) return (
    <div className="mx-auto grid max-w-[1240px] gap-3.5 px-4 py-4" aria-busy>{head}{[0, 1, 2].map(i => <Skeleton key={i} className="h-40 w-full rounded-2xl" />)}</div>
  );
  if (done) return <div className="mx-auto grid max-w-[1240px] gap-3.5 px-4 pb-14 pt-3.5">{head}<Receipt r={done} onAgain={again} /></div>;

  const shown = shownProblems(form, serverProblems ? { ...(preview as Preview), problems: serverProblems } : preview, showErr);
  const hasGuest = !!(form.guest || form.newGuest);
  const mark = (s: Section) => (preview || serverProblems ? sectionMark(s, problems, showErr, hasGuest) : "todo");
  const errs = (s: Section) => shown.filter(p => p.section === s);
  const warns = (s: Section) => (preview?.warnings ?? []).filter(w => w.section === s);
  const on = form.addons.filter(a => a.on).length;
  const sum = { form, setup, preview };

  return (
    <div className="mx-auto grid max-w-[1240px] gap-3.5 px-4 pb-[110px] pt-3.5 lg:pb-14">
      {head}
      <div className="grid items-start gap-3.5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid min-w-0 gap-3.5">
          <SectionCard id="sec-guest" n={1} title="Guest" mark={mark("guest")} summary={form.guest?.name || form.newGuest?.name}>
            <GuestSection form={form} set={set} setup={setup} ctx={ctx} onPick={onPick} onAddNew={onAddNew} onUseQuote={onUseQuote} onScratch={onScratch} showErr={showErr} />
            <Messages tone="bad" items={errs("guest")} />
          </SectionCard>
          <SectionCard id="sec-trip" n={2} title="Trip" mark={mark("trip")} summary={form.checkIn && form.checkOut ? span(form.checkIn, form.checkOut) : undefined}>
            <TripSection form={form} set={set} setup={setup} />
            <Messages tone="bad" items={errs("trip")} />
            <Messages tone="warn" items={warns("trip")} />
          </SectionCard>
          <SectionCard id="sec-veh" n={3} title="Caravan and interior" mark={mark("veh")} summary={preview?.vehicle?.name}>
            <VehicleSection form={form} set={set} setup={setup} preview={preview} />
            <Messages tone="bad" items={errs("veh").filter(p => !p.live)} />
          </SectionCard>
          <SectionCard id="sec-addons" n={4} title="Add-ons" mark={mark("addons")} summary={on ? `${on} added` : "optional"}>
            <AddonsSection form={form} set={set} preview={preview} />
          </SectionCard>
          <SectionCard id="sec-price" n={5} title="Price" mark={mark("price")} summary={preview?.price ? money(preview.price.total) : undefined}>
            <PriceSection form={form} set={set} setup={setup} preview={preview} />
            <Messages tone="bad" items={errs("price")} />
          </SectionCard>
          <SectionCard id="sec-pay" n={6} title="Payment" mark={mark("pay")}>
            <PaymentSection form={form} set={set} setup={setup} preview={preview} />
            <Messages tone="bad" items={errs("pay")} />
          </SectionCard>
          <SectionCard id="sec-confirm" n={7} title="Confirmation" mark={mark("confirm")} summary={form.confirm === "now" ? "WhatsApp now" : "later"}>
            <ConfirmSection form={form} set={set} preview={preview} />
            <Messages tone="warn" items={warns("confirm")} />
          </SectionCard>
          {previewQ.isError && <p role="alert" className="text-[13px] text-[var(--haip-status-danger-fg)]">Couldn&apos;t update the price and checks. They refresh when you change something, or <button type="button" className="underline" onClick={() => previewQ.refetch()}>try again</button>.</p>}
        </div>
        <aside className="sticky top-3.5 hidden max-h-[calc(100vh-28px)] gap-3 overflow-auto lg:grid">
          <SummaryAside {...sum} problems={ordered} showErr={showErr} onJump={jump} onCreate={onCreate} creating={create.isPending} />
        </aside>
      </div>
      <BottomBar problems={ordered} showErr={showErr} preview={preview} form={form} onReview={() => setReview(true)} />
      {review && <ReviewSheet {...sum} problems={ordered} onJump={jump} onClose={() => setReview(false)} onCreate={onCreate} creating={create.isPending} />}
    </div>
  );
}
