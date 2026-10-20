"use client";
// C · Indigo Atelier: heritage-hotel stationery and Jaipur indigo, made practical. Linen ground, indigo shell, brass for
// small highlights, madder only for urgency. Spectral serif for headings and headline figures, Manrope for everything you
// read and operate. Fine ruled lists instead of boxes. Phone: top bar + drawer. Signature: a booking register with serif dates.
import {
  ArrowLeft, CalendarDays, Camera, ChartColumn, ChevronLeft, ChevronRight, Globe, House, Inbox, Megaphone, Menu,
  MessageCircle, Paperclip, Phone, Plus, Search, Send, Settings, Sparkles, SquareKanban, X,
} from "lucide-react";
import { Fragment, useState, type ComponentType } from "react";
import { cn } from "@/lib/utils";
import {
  AGENTS, AI_DRAFT, ALERTS, CAL_DAYS, CAL_TODAY_INDEX, CHANNEL_LABEL, GUEST, KPIS, LEADS, PROPERTIES, QUEUE, RESERVATIONS,
  SOURCES, STAGES, THREAD, TREND_DAYS, dayLabel, inr, inrShort, type Channel, type Lead, type ResKind,
} from "../data";
import { barStyle, trendPath, useCalendar, useInbox, useLeads, type ScreenProps } from "../hooks";
import type { Screen } from "../concepts";

type Icon = ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
const SW = 1.25;
const SERIF = "font-[family-name:var(--font-serif)]";
const GROUPS: { title: string; items: { id: string; label: string; icon: Icon; count?: number }[] }[] = [
  { title: "Front desk", items: [
    { id: "home", label: "Overview", icon: House },
    { id: "inbox", label: "Conversations", icon: Inbox, count: 4 },
    { id: "leads", label: "Enquiries", icon: SquareKanban, count: 5 },
    { id: "calendar", label: "Register", icon: CalendarDays },
    { id: "calls", label: "Calls", icon: Phone, count: 3 },
  ] },
  { title: "Studio", items: [
    { id: "campaigns", label: "Campaigns", icon: Megaphone },
    { id: "reports", label: "Reports", icon: ChartColumn },
    { id: "settings", label: "Settings", icon: Settings },
  ] },
];
const SCREEN_IDS = ["home", "inbox", "leads", "calendar"];
const TITLES: Record<Screen, string> = { home: "Overview", inbox: "Conversations", leads: "Enquiries", calendar: "Register" };

const CH_ICON: Record<Channel, Icon> = { whatsapp: MessageCircle, instagram: Camera, call: Phone, website: Globe };
function Ch({ channel }: { channel: Channel }) {
  const I = CH_ICON[channel];
  return <span className="inline-flex items-center gap-1 text-[12.5px] text-[var(--muted)]"><I size={13} strokeWidth={1.5} />{CHANNEL_LABEL[channel]}</span>;
}

function Btn({ children, kind = "line", className, onClick }: { children: React.ReactNode; kind?: "solid" | "line" | "text"; className?: string; onClick?: () => void }) {
  const k = {
    solid: "bg-[var(--accent)] text-[var(--on-accent)] hover:bg-[var(--accent-hover)]",
    line: "border border-[var(--field)] text-[var(--ink)] hover:border-[var(--accent)] hover:text-[var(--accent)]",
    text: "text-[var(--accent)] hover:underline underline-offset-4",
  };
  return <button type="button" onClick={onClick} className={cn("press inline-flex h-9 items-center justify-center gap-1.5 rounded-full px-4 text-[13px] font-semibold max-sm:h-11", k[kind], className)}>{children}</button>;
}

function Heading({ children, className, id }: { children: React.ReactNode; className?: string; id?: string }) {
  return <h2 id={id} className={cn(SERIF, "text-[19px] font-medium leading-tight tracking-[-0.01em]", className)}>{children}</h2>;
}

// ── shell ─────────────────────────────────────────────────────────────────────

function NavList({ screen, go, onPick }: ScreenProps & { onPick?: () => void }) {
  return (
    <>
      {GROUPS.map(g => (
        <div key={g.title} className="mb-5">
          <p className={cn(SERIF, "mb-1.5 px-5 text-[13px] italic text-[var(--chrome-muted)]")}>{g.title}</p>
          {g.items.map(item => {
            const active = item.id === screen;
            return (
              <button key={item.id} type="button" aria-current={active ? "page" : undefined}
                onClick={() => { if (SCREEN_IDS.includes(item.id)) { go(item.id as Screen); onPick?.(); } }}
                className={cn("mx-2 flex h-10 w-[calc(100%-16px)] items-center gap-3 rounded-md px-3 text-[14px]", active ? "bg-[var(--chrome-active)] font-semibold text-[var(--chrome-ink)]" : "text-[var(--chrome-muted)] hover:text-[var(--chrome-ink)]")}>
                <item.icon size={18} strokeWidth={1.5} />
                <span className="flex-1 text-left">{item.label}</span>
                {item.count != null && <span className={cn("num text-[12.5px]", active ? "text-[var(--brass)]" : "")}>{item.count}</span>}
                {active && <span aria-hidden className="size-1.5 rounded-full bg-[var(--brass-light)]" />}
              </button>
            );
          })}
        </div>
      ))}
    </>
  );
}

function Shell(props: ScreenProps & { children: React.ReactNode; actions?: React.ReactNode }) {
  const { screen, children, actions } = props;
  const [drawer, setDrawer] = useState(false);
  return (
    <div className="lab-root lab-atelier flex">
      <aside className="sticky top-0 hidden h-dvh w-[252px] shrink-0 flex-col bg-[var(--chrome)] lg:flex">
        <div className="px-5 pb-6 pt-7"><p className={cn(SERIF, "text-[26px] italic leading-none text-[var(--chrome-ink)]")}>Ratha</p><p className="mt-1.5 text-[12px] tracking-[0.02em] text-[var(--chrome-muted)]">Caravan journeys, Bengaluru</p></div>
        <nav aria-label="Main" className="scroll flex-1 overflow-y-auto"><NavList {...props} /></nav>
        <div className="mx-5 flex items-center gap-3 border-t border-[var(--chrome-active)] py-4"><span className={cn(SERIF, "flex size-9 items-center justify-center rounded-full bg-[var(--chrome-active)] text-[14px] text-[var(--chrome-ink)]")}>S</span><span className="text-[13px] text-[var(--chrome-ink)]">Sharath D<span className="block text-[12px] text-[var(--chrome-muted)]">Owner</span></span></div>
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button type="button" aria-label="Close menu" onClick={() => setDrawer(false)} className="absolute inset-0 bg-[var(--scrim)]" />
          <div className="absolute inset-y-0 left-0 flex w-[284px] max-w-[85vw] flex-col bg-[var(--chrome)] shadow-[8px_0_32px_rgba(11,13,32,0.35)]">
            <div className="flex items-center justify-between px-5 pb-5 pt-5"><p className={cn(SERIF, "text-[24px] italic text-[var(--chrome-ink)]")}>Ratha</p><button type="button" aria-label="Close menu" onClick={() => setDrawer(false)} className="flex size-11 items-center justify-center text-[var(--chrome-ink)]"><X size={20} /></button></div>
            <nav aria-label="Main" className="scroll flex-1 overflow-y-auto"><NavList {...props} onPick={() => setDrawer(false)} /></nav>
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 bg-[var(--bg)]">
          <div className="flex h-14 items-center gap-2 px-3 md:h-[76px] md:px-10">
            <button type="button" aria-label="Open menu" onClick={() => setDrawer(true)} className="flex size-11 items-center justify-center lg:hidden"><Menu size={21} strokeWidth={1.5} /></button>
            <div className="min-w-0">
              <h1 className={cn(SERIF, "truncate text-[22px] font-medium leading-none tracking-[-0.015em] md:text-[32px]")}>{TITLES[screen]}</h1>
              <p className="mt-1.5 hidden text-[12.5px] text-[var(--muted)] md:block">Saturday, 17 October · last 7 days</p>
            </div>
            <div className="ml-auto flex items-center gap-2">{actions}</div>
          </div>
          <div className="mx-3 border-b border-[var(--line-strong)] md:mx-10" />
          <div className="mx-3 mt-[3px] border-b border-[var(--line)] md:mx-10" />
        </header>
        <main className="min-w-0 flex-1 pb-12">{children}</main>
      </div>
    </div>
  );
}

// ── home ──────────────────────────────────────────────────────────────────────

function Home(props: ScreenProps) {
  const t = trendPath(560, 120, 4);
  const figs = [
    [KPIS.newLeads.label, String(KPIS.newLeads.value), KPIS.newLeads.change],
    [KPIS.bookings.label, String(KPIS.bookings.value), KPIS.bookings.change],
    [KPIS.bookedValue.label, inr(KPIS.bookedValue.value), KPIS.bookedValue.change],
    [KPIS.cash.label, inr(KPIS.cash.value), KPIS.cash.change],
    [KPIS.occupancy.label, `${KPIS.occupancy.value}%`, KPIS.occupancy.change],
    [KPIS.response.label, `${KPIS.response.value} min`, KPIS.response.change],
  ] as const;
  return (
    <Shell {...props} actions={<><select aria-label="Period" className="h-9 rounded-full border border-[var(--field)] bg-transparent px-3 text-[13px] max-sm:hidden"><option>Last 7 days</option><option>This month</option></select><Btn kind="solid"><Plus size={15} strokeWidth={2} /><span className="max-sm:hidden">New enquiry</span></Btn></>}>
      <div className="mx-auto grid max-w-[1180px] gap-x-14 gap-y-10 px-4 py-8 md:px-10 lg:grid-cols-[1fr_1.25fr]">
        <section aria-labelledby="at-await">
          <Heading id="at-await">Awaiting you</Heading>
          <p className="mt-1 text-[13px] text-[var(--muted)]">Fourteen guests, eight past their reply time.</p>
          <ul className="mt-4 border-t border-[var(--line-strong)]">
            {QUEUE.map(q => (
              <li key={q.kind} className="flex items-baseline gap-4 border-b border-[var(--line)] py-3.5">
                <span className={cn(SERIF, "num w-10 text-[34px] leading-none", q.urgency === "now" ? "text-[var(--bad)]" : "text-[var(--accent)]")}>{q.count}</span>
                <span className="min-w-0 flex-1"><span className="block text-[14.5px] font-semibold">{q.label}</span><span className="text-[12.5px] text-[var(--muted)]">Longest wait {q.oldest}</span></span>
                <Btn kind="text" className="h-9 px-1">Attend</Btn>
              </li>
            ))}
          </ul>
          <Heading className="mt-10">Notes</Heading>
          <ul className="mt-3 space-y-4">{ALERTS.map(a => <li key={a.text} className="text-[14px] leading-relaxed"><span className={cn(SERIF, "mr-1.5 italic", a.tone === "danger" ? "text-[var(--bad)]" : a.tone === "warning" ? "text-[var(--brass)]" : "text-[var(--accent)]")}>{a.tone === "danger" ? "Urgent." : a.tone === "warning" ? "Payment." : "Suggestion."}</span>{a.text} <Btn kind="text" className="h-auto px-0">{a.action}</Btn></li>)}</ul>
        </section>

        <div className="min-w-0 space-y-10">
          <section aria-labelledby="at-figs">
            <div className="flex items-baseline justify-between"><Heading id="at-figs">The week in figures</Heading><span className="text-[12.5px] text-[var(--muted)]">compared with the week before</span></div>
            <dl className="mt-4 grid grid-cols-2 border-t border-[var(--line-strong)] sm:grid-cols-3">
              {figs.map(([k, v, d]) => (
                <div key={k} className="border-b border-[var(--line)] py-4 pr-4">
                  <dt className="text-[12.5px] text-[var(--muted)]">{k}</dt>
                  <dd className={cn(SERIF, "num mt-1 text-[27px] leading-none")}>{v}</dd>
                  <dd className={cn("mt-1 text-[12px] font-semibold", d >= 0 ? "text-[var(--ok)]" : "text-[var(--bad)]")}>{d >= 0 ? "Up" : "Down"} {Math.abs(d)}%</dd>
                </div>
              ))}
            </dl>
          </section>
          <section aria-labelledby="at-trend">
            <div className="flex items-baseline justify-between"><Heading id="at-trend">Booked value</Heading><span className="text-[12.5px] text-[var(--muted)]">per day, fourteen days</span></div>
            <svg viewBox="0 0 560 120" className="mt-4 h-[120px] w-full" role="img" aria-label="Booked value per day, last 14 days">
              <line x1="0" x2="560" y1="118" y2="118" stroke="var(--line-strong)" />
              <path d={t.line} fill="none" stroke="var(--accent)" strokeWidth="1.5" />
              {t.points.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={i === t.points.length - 1 ? 4.5 : 2} fill={i === t.points.length - 1 ? "var(--brass)" : "var(--accent)"} />)}
            </svg>
            <div className={cn(SERIF, "flex justify-between text-[12.5px] italic text-[var(--muted)]")}>{TREND_DAYS.filter((_, i) => i % 3 === 0).map(d => <span key={d}>{d} Oct</span>)}</div>
          </section>
          <section aria-labelledby="at-src">
            <Heading id="at-src">Where enquiries began</Heading>
            <ul className="mt-3 border-t border-[var(--line-strong)]">{SOURCES.map(s => <li key={s.label} className="flex items-center justify-between border-b border-[var(--line)] py-2.5 text-[14px]"><Ch channel={s.channel} /><span className="flex items-center gap-3"><span className="h-1 rounded-full bg-[var(--accent)]" style={{ width: s.value * 14 }} /><span className={cn(SERIF, "num w-5 text-right text-[17px]")}>{s.value}</span></span></li>)}</ul>
          </section>
        </div>
      </div>
    </Shell>
  );
}

// ── inbox ─────────────────────────────────────────────────────────────────────

function InboxScreen(props: ScreenProps) {
  const ib = useInbox();
  const c = ib.conversation;
  return (
    <Shell {...props} actions={<label className="hidden h-9 w-[240px] items-center gap-2 rounded-full border border-[var(--field)] px-3 md:flex"><Search size={15} strokeWidth={1.5} className="text-[var(--muted)]" /><input placeholder="Search conversations" className="w-full bg-transparent text-[13px] outline-none" /></label>}>
      <div className="grid grid-cols-1 h-[calc(100dvh-60px)] md:h-[calc(100dvh-82px)] md:grid-cols-[320px_1fr] xl:grid-cols-[320px_1fr_300px]">
        <section aria-label="Conversations" className={cn("flex min-h-0 min-w-0 flex-col border-r border-[var(--line)]", ib.open && "max-md:hidden")}>
          <div className="flex gap-5 px-5 pt-3 text-[13.5px]">{(["all", "waiting", "mine"] as const).map(f => <button key={f} type="button" onClick={() => ib.setFilter(f)} className={cn("h-10 border-b", ib.filter === f ? "border-[var(--accent)] font-semibold text-[var(--accent)]" : "border-transparent text-[var(--muted)]")}>{f === "waiting" ? "Awaiting reply" : f === "mine" ? "Mine" : "All"}</button>)}</div>
          <ul className="scroll min-h-0 flex-1 overflow-y-auto">
            {ib.list.map(conv => (
              <li key={conv.id}>
                <button type="button" onClick={() => ib.pick(conv.id)} className={cn("w-full border-b border-[var(--line)] px-5 py-3.5 text-left", conv.id === ib.selected ? "bg-[var(--surface)]" : "hover:bg-[var(--raised)]")}>
                  <span className="flex items-baseline gap-2"><span className={cn(SERIF, "truncate text-[17px]", conv.unread ? "font-semibold" : "")}>{conv.name}</span><span className="ml-auto shrink-0 text-[12px] text-[var(--muted)]">{conv.time}</span></span>
                  <span className="mt-0.5 block truncate text-[13px] text-[var(--muted)]">{conv.preview}</span>
                  <span className="mt-1.5 flex items-center gap-3"><Ch channel={conv.channel} />{conv.waiting && <span className={cn("text-[12px] font-semibold", conv.hot ? "text-[var(--bad)]" : "text-[var(--brass)]")}>Waiting {conv.waiting}</span>}{conv.unread > 0 && <span className="num ml-auto flex size-5 items-center justify-center rounded-full bg-[var(--accent)] text-[11px] font-semibold text-[var(--on-accent)]">{conv.unread}</span>}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section aria-label="Conversation" className={cn("flex min-h-0 min-w-0 flex-col", !ib.open && "max-md:hidden")}>
          <div className="flex h-16 items-center gap-3 border-b border-[var(--line)] px-3 md:px-8">
            <button type="button" onClick={ib.back} aria-label="Back to conversations" className="flex size-11 items-center justify-center md:hidden"><ArrowLeft size={19} strokeWidth={1.5} /></button>
            <div className="min-w-0 flex-1"><p className={cn(SERIF, "truncate text-[20px]")}>{c.name}</p><p className="text-[12.5px] text-[var(--muted)]">{CHANNEL_LABEL[c.channel]} · attended by {c.agent ?? "no one yet"}</p></div>
            <Btn kind="line" className="max-sm:hidden"><Phone size={14} strokeWidth={1.5} />Call</Btn>
            <select aria-label="Assign to" data-assign defaultValue={c.agent ?? ""} className="h-9 rounded-full border border-[var(--field)] bg-transparent px-3 text-[13px] max-lg:hidden"><option value="">Unassigned</option>{AGENTS.map(a => <option key={a.id}>{a.name}</option>)}</select>
          </div>
          <div className="scroll min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-6 md:px-12">
            {THREAD.map(m => m.from === "note" ? (
              <p key={m.id} className={cn(SERIF, "mx-auto max-w-[480px] text-center text-[14px] italic text-[var(--brass)]")}>{m.author}: “{m.text}”</p>
            ) : (
              <div key={m.id} className={cn("flex", m.from === "guest" ? "justify-start" : "justify-end")}>
                <div className={cn("max-w-[76%] px-4 py-3 text-[14px] leading-relaxed", m.from === "guest" ? "rounded-2xl rounded-tl-sm bg-[var(--surface)] shadow-[0_1px_2px_rgba(24,27,52,0.06)]" : "rounded-2xl rounded-tr-sm bg-[var(--accent)] text-[var(--on-accent)]")}>
                  {m.text}<span className={cn("mt-1 block text-[11.5px]", m.from === "guest" ? "text-[var(--muted)]" : "opacity-80")}>{m.time}{m.author ? ` · ${m.author}` : ""}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="border-t border-[var(--line)] px-3 py-4 md:px-8">
            {ib.draft !== "sent" && (
              <div className="mb-3 rounded-xl border border-[var(--brass)]/50 bg-[var(--surface)] p-3.5">
                <p className={cn(SERIF, "flex items-center gap-1.5 text-[14px] italic text-[var(--brass)]")}><Sparkles size={14} strokeWidth={1.5} />A suggested reply</p>
                <p className="mt-1 text-[14px] leading-relaxed">{AI_DRAFT}</p>
                <div className="mt-2.5 flex gap-2"><Btn kind="solid" onClick={() => ib.setDraft("sent")}>Send</Btn><Btn kind="line" onClick={() => ib.setDraft("edited")}>Refine</Btn></div>
              </div>
            )}
            <div className="flex items-end gap-2 rounded-2xl border border-[var(--field)] bg-[var(--surface)] p-1.5 pl-3">
              <textarea rows={1} placeholder="Write to Priya…" className="min-h-10 flex-1 resize-none bg-transparent py-2 text-[16px] outline-none sm:text-[14px]" />
              <button type="button" aria-label="Attach" className="flex size-10 items-center justify-center text-[var(--muted)]"><Paperclip size={18} strokeWidth={1.5} /></button>
              <Btn kind="solid" className="h-10 w-10 px-0"><Send size={16} strokeWidth={1.75} /></Btn>
            </div>
          </div>
        </section>

        <aside aria-label="Guest folio" className="scroll hidden min-h-0 overflow-y-auto border-l border-[var(--line)] px-6 py-6 xl:block">
          <p className={cn(SERIF, "text-[13px] italic text-[var(--muted)]")}>Guest folio</p>
          <p className={cn(SERIF, "text-[24px] leading-tight")}>{GUEST.name}</p>
          <p className="num mt-0.5 text-[13px] text-[var(--muted)]">{GUEST.phone} · {GUEST.city}</p>
          <dl className="mt-5 border-t border-[var(--line-strong)] text-[13.5px]">
            {[["Stage", GUEST.stage], ["Attended by", GUEST.owner], ["Dates", GUEST.trip.dates], ["Party", GUEST.trip.party], ["Route", GUEST.trip.route], ["Occasion", GUEST.trip.occasion], ["Estimate", GUEST.value]].map(([k, v]) => <div key={k} className="flex justify-between gap-3 border-b border-[var(--line)] py-2"><dt className="text-[var(--muted)]">{k}</dt><dd className="text-right font-semibold">{v}</dd></div>)}
          </dl>
          <p className={cn(SERIF, "mt-6 text-[16px]")}>Story so far</p>
          <ol className="mt-2 space-y-2.5">{GUEST.journey.map(j => <li key={j.label} className="grid grid-cols-[14px_1fr] gap-2 text-[13px]"><span className={cn("mt-1.5 size-2 rounded-full", j.done ? "bg-[var(--accent)]" : "border border-[var(--brass)]")} /><span className={j.done ? "" : "text-[var(--muted)]"}>{j.label}{j.when && <span className={cn(SERIF, "block text-[12.5px] italic text-[var(--muted)]")}>{j.when}</span>}</span></li>)}</ol>
        </aside>
      </div>
    </Shell>
  );
}

// ── leads ─────────────────────────────────────────────────────────────────────

const PRI_LABEL = { hot: "Warm welcome needed", warm: "In conversation", cold: "Quiet" };
const PRI_DOT = { hot: "bg-[var(--bad)]", warm: "bg-[var(--brass)]", cold: "bg-[var(--line-strong)]" };

function Card({ l }: { l: Lead }) {
  return (
    <article className="rounded-lg bg-[var(--surface)] p-3.5 shadow-[0_1px_2px_rgba(24,27,52,0.06),0_0_0_1px_var(--line)]">
      <p className={cn(SERIF, "text-[17px] leading-tight")}>{l.name}</p>
      <p className="mt-1 text-[12.5px] text-[var(--muted)]">{[l.dates, l.party].filter(Boolean).join(" · ") || "Dates not yet shared"}</p>
      <div className="mt-2.5 flex items-center justify-between"><Ch channel={l.channel} />{l.value ? <span className={cn(SERIF, "num text-[17px]")}>{inrShort(l.value)}</span> : null}</div>
      <div className="mt-2.5 flex items-center gap-2 border-t border-[var(--line)] pt-2.5 text-[12.5px]"><span className={cn("size-2 shrink-0 rounded-full", PRI_DOT[l.priority])} aria-hidden /><span className={cn("min-w-0 flex-1 truncate", l.due === "now" && "font-semibold text-[var(--bad)]")}>{l.next}</span><span className="text-[var(--muted)]">{l.owner?.split(" ")[0] ?? "Unattended"}</span></div>
    </article>
  );
}

function LeadsScreen(props: ScreenProps) {
  const ld = useLeads();
  return (
    <Shell {...props} actions={<><div className="hidden rounded-full border border-[var(--field)] p-0.5 md:flex">{(["board", "list"] as const).map(v => <button key={v} type="button" onClick={() => ld.setView(v)} className={cn("h-8 rounded-full px-3.5 text-[13px]", ld.view === v ? "bg-[var(--accent)] font-semibold text-[var(--on-accent)]" : "text-[var(--muted)]")}>{v === "board" ? "By stage" : "Register"}</button>)}</div><Btn kind="solid"><Plus size={15} strokeWidth={2} /><span className="max-sm:hidden">New enquiry</span></Btn></>}>
      <div className="px-4 py-6 md:px-10">
        <div className="scroll -mx-4 mb-6 flex gap-6 overflow-x-auto px-4 md:mx-0 md:px-0">
          {[{ key: "all", label: "All enquiries", count: 55 }, ...STAGES].map(s => <button key={s.key} type="button" onClick={() => ld.setStage(s.key)} className={cn("min-h-11 shrink-0 border-b pb-1.5 text-[14px] sm:min-h-0", ld.stage === s.key ? "border-[var(--accent)] font-semibold text-[var(--accent)]" : "border-transparent text-[var(--muted)]")}>{s.label} <span className={cn(SERIF, "num italic")}>{s.count}</span></button>)}
        </div>
        {ld.view === "board" ? (
          <>
            <div className="hidden gap-6 md:grid md:grid-cols-3 xl:grid-cols-5">
              {STAGES.map(s => (
                <section key={s.key} aria-label={s.label} className="min-w-0">
                  <div className="mb-3 border-b border-[var(--line-strong)] pb-2"><Heading className="text-[17px]">{s.label}</Heading><p className="num text-[12.5px] text-[var(--muted)]">{s.count} enquiries{s.value && ` · ${s.value}`}</p></div>
                  <div className="space-y-2.5">{LEADS.filter(l => l.stage === s.key).map(l => <Card key={l.id} l={l} />)}</div>
                </section>
              ))}
            </div>
            <div className="space-y-2.5 md:hidden">{ld.list.map(l => <Card key={l.id} l={l} />)}</div>
          </>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-[13.5px]">
              <thead><tr className="border-b border-[var(--line-strong)] text-left">{["Guest", "Stage", "Dates", "Estimate", "Attended by", "Next"].map(h => <th key={h} className={cn(SERIF, "py-2.5 pr-4 text-[14px] font-normal italic text-[var(--muted)]")}>{h}</th>)}</tr></thead>
              <tbody>{ld.list.map(l => <tr key={l.id} className="border-b border-[var(--line)]"><td className={cn(SERIF, "py-3 pr-4 text-[16px]")}>{l.name}</td><td className="pr-4">{STAGES.find(s => s.key === l.stage)?.label}</td><td className="pr-4 text-[var(--muted)]">{l.dates ?? "—"}</td><td className="num pr-4">{l.value ? inr(l.value) : "—"}</td><td className="pr-4">{l.owner ?? <span className="text-[var(--brass)]">Unattended</span>}</td><td className={cn("pr-4", l.due === "now" && "font-semibold text-[var(--bad)]")}>{l.next}</td></tr>)}</tbody>
            </table>
          </div>
        )}
        <p className="mt-6 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-[var(--muted)]">{(Object.keys(PRI_LABEL) as (keyof typeof PRI_LABEL)[]).map(k => <span key={k} className="inline-flex items-center gap-1.5"><span className={cn("size-2 rounded-full", PRI_DOT[k])} />{PRI_LABEL[k]}</span>)}</p>
      </div>
    </Shell>
  );
}

// ── calendar ──────────────────────────────────────────────────────────────────

const ENTRY: Record<ResKind, string> = {
  direct: "bg-[var(--accent)] text-[var(--on-accent)]",
  ota: "bg-[var(--info-bg)] text-[var(--accent)] shadow-[inset_0_0_0_1px_var(--accent)]",
  hold: "bg-[var(--surface)] text-[var(--brass)] shadow-[inset_0_0_0_1.5px_var(--brass)]",
  blocked: "bg-[repeating-linear-gradient(135deg,var(--raised)_0_5px,var(--surface)_5px_10px)] text-[var(--muted)] shadow-[inset_0_0_0_1px_var(--line-strong)]",
  maintenance: "bg-[var(--bad-bg)] text-[var(--bad)] shadow-[inset_0_0_0_1px_var(--bad)]",
};
const FULL_DAY: Record<string, string> = { Mon: "Monday", Tue: "Tuesday", Wed: "Wednesday", Thu: "Thursday", Fri: "Friday", Sat: "Saturday", Sun: "Sunday" };
const ENTRY_LABEL: Record<ResKind, string> = { direct: "Direct", ota: "Airbnb", hold: "On hold", blocked: "Blocked", maintenance: "Maintenance" };

function CalendarScreen(props: ScreenProps) {
  const cal = useCalendar();
  const days = Array.from({ length: CAL_DAYS }, (_, i) => i);
  return (
    <Shell {...props} actions={<><Btn kind="line" className="w-9 px-0 max-sm:w-11"><ChevronLeft size={16} strokeWidth={1.5} /></Btn><span className={cn(SERIF, "text-[16px] italic max-sm:hidden")}>October</span><Btn kind="line" className="w-9 px-0 max-sm:w-11"><ChevronRight size={16} strokeWidth={1.5} /></Btn></>}>
      <div className="px-4 py-6 md:px-10">
        <ul className="mb-5 flex flex-wrap gap-x-5 gap-y-2 text-[12.5px] text-[var(--muted)]">{(Object.keys(ENTRY) as ResKind[]).map(k => <li key={k} className="flex items-center gap-2"><span className={cn("h-3 w-5 rounded-[3px]", ENTRY[k])} />{ENTRY_LABEL[k]}</li>)}</ul>
        <div className="hidden gap-8 md:flex">
          <div className="min-w-0 flex-1 overflow-x-auto">
            <div className="min-w-[860px]">
              <div className="grid grid-cols-[120px_1fr] border-b border-[var(--line-strong)]">
                <div />
                <div className="grid" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>{days.map(i => { const d = dayLabel(i); return <div key={i} className="pb-2 text-center"><p className="text-[10.5px] uppercase tracking-[0.06em] text-[var(--muted)]">{d.dow.slice(0, 1)}</p><p className={cn(SERIF, "num text-[19px] leading-tight", i === CAL_TODAY_INDEX && "text-[var(--brass)] underline decoration-1 underline-offset-[5px]")}>{d.day}</p></div>; })}</div>
              </div>
              {PROPERTIES.map(p => (
                <div key={p.id} className="grid grid-cols-[120px_1fr] border-b border-[var(--line)]">
                  <div className="py-4"><p className={cn(SERIF, "text-[18px]")}>{p.name}</p><p className="text-[12px] text-[var(--muted)]">{p.note}</p></div>
                  <div className="relative h-[76px]">
                    <div className="absolute inset-0 grid" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>{days.map(i => <div key={i} className={cn("border-l border-[var(--line)]/70", i === CAL_TODAY_INDEX && "bg-[var(--brass)]/10")} />)}</div>
                    {RESERVATIONS.filter(r => r.property === p.id).map(r => (
                      <button key={r.id} type="button" onClick={() => cal.setSelected(r.id)} style={barStyle(r)} className={cn("press absolute top-4 h-11 overflow-hidden rounded-md px-2.5 py-1 text-left", ENTRY[r.kind], cal.selected === r.id && "ring-2 ring-[var(--brass)] ring-offset-2 ring-offset-[var(--bg)]")}>
                        <span className={cn(SERIF, "block truncate text-[14px] leading-tight")}>{r.guest}</span><span className="block truncate text-[11px] opacity-80">{r.route ?? r.status}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
          {cal.res && (
            <aside aria-label="Reservation" className="w-[270px] shrink-0 max-lg:hidden">
              <p className={cn(SERIF, "text-[13px] italic text-[var(--muted)]")}>{ENTRY_LABEL[cal.res.kind]} · {cal.res.status}</p>
              <p className={cn(SERIF, "text-[26px] leading-tight")}>{cal.res.guest}</p>
              <p className="mt-1 text-[13px] text-[var(--muted)]">{PROPERTIES.find(p => p.id === cal.res!.property)?.name}, {dayLabel(cal.res.start).day} to {dayLabel(cal.res.end).day} {dayLabel(cal.res.end).month}, {cal.res.end - cal.res.start} nights</p>
              {cal.res.amount != null && <dl className="mt-4 border-t border-[var(--line-strong)] text-[13.5px]">{[["Party", cal.res.party], ["Route", cal.res.route], ["Source", cal.res.source], ["Total", inr(cal.res.amount)], ["Received", inr(cal.res.paid ?? 0)], ["Balance", inr(cal.res.amount - (cal.res.paid ?? 0))]].map(([k, v]) => <Fragment key={k}><div className="flex justify-between border-b border-[var(--line)] py-2"><dt className="text-[var(--muted)]">{k}</dt><dd className="num font-semibold">{v}</dd></div></Fragment>)}</dl>}
              <Btn kind="solid" className="mt-5 w-full">Open the booking</Btn>
            </aside>
          )}
        </div>
        <div className="md:hidden">
          <p className={cn(SERIF, "mb-2 text-[20px]")}>October</p>
          <div className="grid grid-cols-7 border-t border-[var(--line-strong)]">
            {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <div key={i} className="py-1.5 text-center text-[11px] uppercase tracking-[0.06em] text-[var(--muted)]">{d}</div>)}
            {days.map(i => (
              <button key={i} type="button" onClick={() => cal.setDay(i)} aria-pressed={cal.day === i} className={cn("flex h-14 flex-col items-center border-t border-[var(--line)] pt-1.5", cal.day === i && "bg-[var(--surface)]")}>
                <span className={cn(SERIF, "num text-[18px] leading-none", i === CAL_TODAY_INDEX && "text-[var(--brass)]")}>{dayLabel(i).day}</span>
                <span className="mt-auto mb-1.5 flex w-[70%] flex-col gap-[3px]">{cal.onDay(i).map(r => <span key={r.id} className={cn("h-[3px] rounded-full", r.kind === "maintenance" ? "bg-[var(--bad)]" : r.kind === "blocked" ? "bg-[var(--line-strong)]" : r.kind === "hold" ? "bg-[var(--brass)]" : "bg-[var(--accent)]")} />)}</span>
              </button>
            ))}
          </div>
          <p className={cn(SERIF, "mb-2 mt-6 text-[18px]")}>{FULL_DAY[dayLabel(cal.day).dow]}, {dayLabel(cal.day).day} {dayLabel(cal.day).month === "Oct" ? "October" : "November"}</p>
          <ul className="border-t border-[var(--line-strong)]">
            {cal.onDay(cal.day).length === 0 && <li className={cn(SERIF, "py-4 italic text-[var(--muted)]")}>Both caravans are free.</li>}
            {cal.onDay(cal.day).map(r => <li key={r.id} className="flex items-center gap-3 border-b border-[var(--line)] py-3"><span className={cn("h-8 w-1.5 shrink-0 rounded-full", ENTRY[r.kind])} /><div className="min-w-0 flex-1"><p className={cn(SERIF, "truncate text-[17px]")}>{r.guest}</p><p className="text-[12.5px] text-[var(--muted)]">{PROPERTIES.find(p => p.id === r.property)?.name} · {ENTRY_LABEL[r.kind]}</p></div>{r.amount != null && <span className={cn(SERIF, "num text-[16px]")}>{inrShort(r.amount)}</span>}</li>)}
          </ul>
        </div>
      </div>
    </Shell>
  );
}

export default function Atelier(props: ScreenProps) {
  if (props.screen === "inbox") return <InboxScreen {...props} />;
  if (props.screen === "leads") return <LeadsScreen {...props} />;
  if (props.screen === "calendar") return <CalendarScreen {...props} />;
  return <Home {...props} />;
}
