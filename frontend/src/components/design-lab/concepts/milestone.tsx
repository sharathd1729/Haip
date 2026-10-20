"use client";
// B · Milestone: Indian highway signage. White stone, road-black chrome, signage blue for actions, milestone yellow only
// for what needs you now. Archivo with condensed tabular numerals; compact, high-contrast rows. Top navigation (no sidebar)
// on desktop, black bottom bar on phones. Signature: queue counts set as milestone stones with a yellow cap.
import {
  ArrowDownRight, ArrowLeft, ArrowUpRight, Bell, CalendarDays, Camera, ChevronLeft, ChevronRight, CircleAlert, Clock, Globe,
  House, Inbox, Info, LayoutGrid, List, MessageCircle, Paperclip, Phone, Plus, Search, Send, Sparkles, SquareKanban,
  TriangleAlert,
} from "lucide-react";
import { Fragment, type ComponentType } from "react";
import { cn } from "@/lib/utils";
import {
  AGENTS, AI_DRAFT, ALERTS, CAL_DAYS, CAL_TODAY_INDEX, CHANNEL_LABEL, GUEST, KPIS, LEADS, PERIOD_LABEL, PROPERTIES, QUEUE,
  RESERVATIONS, SOURCES, STAGES, THREAD, TREND, TREND_DAYS, dayLabel, inr, inrShort, type Channel, type ResKind,
} from "../data";
import { barStyle, useCalendar, useInbox, useLeads, type ScreenProps } from "../hooks";
import type { Screen } from "../concepts";

type Icon = ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
const SW = 2.25;
const NAV: { id: Screen | string; label: string; icon: Icon; count?: number }[] = [
  { id: "home", label: "Home", icon: House },
  { id: "inbox", label: "Inbox", icon: Inbox, count: 4 },
  { id: "leads", label: "Leads", icon: SquareKanban, count: 5 },
  { id: "calendar", label: "Calendar", icon: CalendarDays },
  { id: "calls", label: "Calls", icon: Phone, count: 3 },
];
const MORE = ["Campaigns", "Reports", "Settings"];
const SCREEN_IDS = ["home", "inbox", "leads", "calendar"];
const TITLES: Record<Screen, string> = { home: "Home", inbox: "Inbox", leads: "Leads 360", calendar: "Calendar" };
const COND = "[font-stretch:72%]";

const CH_ICON: Record<Channel, Icon> = { whatsapp: MessageCircle, instagram: Camera, call: Phone, website: Globe };
function Ch({ channel }: { channel: Channel }) {
  const I = CH_ICON[channel];
  return <span className="inline-flex items-center gap-1 text-[12.5px] font-medium text-[var(--muted)]"><I size={13} strokeWidth={SW} />{CHANNEL_LABEL[channel]}</span>;
}

function B({ children, kind = "outline", className, onClick }: { children: React.ReactNode; kind?: "blue" | "outline" | "black"; className?: string; onClick?: () => void }) {
  const k = {
    blue: "bg-[var(--accent)] text-[var(--on-accent)] hover:bg-[var(--accent-hover)]",
    black: "bg-[var(--ink)] text-[var(--surface)] hover:opacity-90",
    outline: "border-2 border-[var(--ink)] text-[var(--ink)] hover:bg-[var(--raised)]",
  };
  return <button type="button" onClick={onClick} className={cn("press inline-flex h-9 items-center justify-center gap-1.5 rounded-md px-3 text-[13.5px] font-bold max-sm:h-11", k[kind], className)}>{children}</button>;
}

/** The milestone stone: yellow cap, white body, condensed numeral. Used only for things waiting on the team. */
function Stone({ value, label, sub, urgent }: { value: number; label: string; sub: string; urgent?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col items-center text-center">
      <div className="w-[88px] overflow-hidden rounded-t-[44px] rounded-b-md border-2 border-[var(--ink)] bg-[var(--surface)] shadow-[0_2px_0_rgba(0,0,0,0.08)]">
        <div className={cn("flex h-9 items-end justify-center pb-1 text-[11px] font-bold uppercase tracking-[0.08em]", urgent ? "bg-[var(--cap)] text-[var(--on-cap)]" : "bg-[var(--raised)] text-[var(--muted)]")}>{urgent ? "Now" : "Today"}</div>
        <div className={cn("num py-1.5 text-[40px] font-extrabold leading-none", COND)}>{value}</div>
      </div>
      <p className="mt-2 text-[13px] font-bold leading-tight">{label}</p>
      <p className="text-[12px] text-[var(--muted)]">{sub}</p>
    </div>
  );
}

// ── shell ─────────────────────────────────────────────────────────────────────

function Shell({ screen, go, children, actions }: ScreenProps & { children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="lab-root lab-milestone">
      <header className="sticky top-0 z-30 bg-[var(--chrome)] text-[var(--chrome-ink)]">
        <div className="mx-auto flex h-[52px] max-w-[1400px] items-center gap-6 px-4 md:h-14 md:px-6">
          <span className={cn("text-[20px] font-black uppercase tracking-[0.04em]", COND)}>Ratha</span>
          <nav aria-label="Main" className="hidden h-full items-stretch md:flex">
            {NAV.map(item => {
              const active = item.id === screen;
              return (
                <button key={item.label} type="button" aria-current={active ? "page" : undefined} onClick={() => SCREEN_IDS.includes(item.id) && go(item.id as Screen)}
                  className={cn("relative flex items-center gap-2 px-3 text-[14px] font-bold", active ? "text-[var(--chrome-ink)]" : "text-[var(--chrome-muted)] hover:text-[var(--chrome-ink)]")}>
                  {item.label}
                  {item.count ? <span className="num rounded-[3px] bg-[var(--cap)] px-1.5 text-[12px] font-extrabold leading-5 text-[var(--on-cap)]">{item.count}</span> : null}
                  {active && <span aria-hidden className="absolute inset-x-3 bottom-0 h-[3px] bg-[var(--cap)]" />}
                </button>
              );
            })}
            {MORE.map(m => <button key={m} type="button" className="hidden px-3 text-[14px] font-bold text-[var(--chrome-muted)] hover:text-[var(--chrome-ink)] xl:block">{m}</button>)}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <label className="hidden h-9 w-[220px] items-center gap-2 rounded-md bg-[var(--chrome-active)] px-3 text-[var(--chrome-muted)] lg:flex"><Search size={15} strokeWidth={SW} /><input placeholder="Search guests, numbers" className="w-full bg-transparent text-[13.5px] text-[var(--chrome-ink)] outline-none placeholder:text-[var(--chrome-muted)]" /></label>
            <button type="button" aria-label="Notifications" className="flex size-10 items-center justify-center rounded-md hover:bg-[var(--chrome-active)]"><Bell size={19} strokeWidth={SW} /></button>
            <span className="flex size-8 items-center justify-center rounded-md bg-[var(--surface)] text-[12px] font-extrabold text-[var(--ink)]">SD</span>
          </div>
        </div>
      </header>
      <div className="border-b-2 border-[var(--ink)] bg-[var(--surface)]">
        <div className="mx-auto flex max-w-[1400px] items-center gap-3 px-4 py-3 md:px-6 md:py-4">
          <h1 className={cn("text-[24px] font-extrabold uppercase leading-none tracking-[0.01em] md:text-[34px]", COND)}>{TITLES[screen]}</h1>
          <span className="hidden text-[13px] font-semibold text-[var(--muted)] sm:inline">{PERIOD_LABEL}</span>
          <div className="ml-auto flex items-center gap-2">{actions}</div>
        </div>
      </div>
      <main className="mx-auto max-w-[1400px] pb-24 md:pb-10">{children}</main>
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 flex h-16 bg-[var(--chrome)] pb-[env(safe-area-inset-bottom)] md:hidden">
        {NAV.map(item => {
          const active = item.id === screen;
          return (
            <button key={item.label} type="button" onClick={() => SCREEN_IDS.includes(item.id) && go(item.id as Screen)} className={cn("relative flex flex-1 flex-col items-center justify-center gap-1 text-[11.5px] font-bold", active ? "text-[var(--chrome-ink)]" : "text-[var(--chrome-muted)]")}>
              {active && <span aria-hidden className="absolute top-0 h-[3px] w-full bg-[var(--cap)]" />}
              <item.icon size={21} strokeWidth={SW} />{item.label}
              {item.count ? <span className="num absolute right-[calc(50%-24px)] top-2 rounded-[3px] bg-[var(--cap)] px-1 text-[10.5px] font-extrabold leading-4 text-[var(--on-cap)]">{item.count}</span> : null}
            </button>
          );
        })}
      </nav>
    </div>
  );
}

// ── home ──────────────────────────────────────────────────────────────────────

function Home(props: ScreenProps) {
  const max = Math.max(...TREND);
  const rows = [
    { k: KPIS.newLeads.label, v: String(KPIS.newLeads.value), d: KPIS.newLeads.change },
    { k: KPIS.bookings.label, v: String(KPIS.bookings.value), d: KPIS.bookings.change },
    { k: KPIS.bookedValue.label, v: inrShort(KPIS.bookedValue.value), d: KPIS.bookedValue.change, full: inr(KPIS.bookedValue.value) },
    { k: KPIS.cash.label, v: inrShort(KPIS.cash.value), d: KPIS.cash.change, full: inr(KPIS.cash.value) },
    { k: KPIS.occupancy.label, v: `${KPIS.occupancy.value}%`, d: KPIS.occupancy.change },
    { k: KPIS.response.label, v: `${KPIS.response.value}m`, d: KPIS.response.change },
  ];
  return (
    <Shell {...props} actions={<><select aria-label="Period" className="h-9 rounded-md border-2 border-[var(--ink)] bg-[var(--surface)] px-2 text-[13.5px] font-bold max-sm:h-11"><option>Last 7 days</option><option>Today</option><option>This month</option></select><select aria-label="Caravan" className="hidden h-9 rounded-md border-2 border-[var(--ink)] bg-[var(--surface)] px-2 text-[13.5px] font-bold sm:block"><option>Both caravans</option></select></>}>
      <div className="space-y-8 px-4 py-6 md:px-6">
        <section aria-labelledby="ms-now">
          <div className="mb-4 flex items-baseline justify-between"><h2 id="ms-now" className="text-[17px] font-extrabold">Needs you now</h2><span className="text-[13px] font-semibold text-[var(--muted)]">14 people · 8 past target</span></div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-6 sm:grid-cols-4">
            {QUEUE.map(q => <Stone key={q.kind} value={q.count} label={q.label} sub={`oldest ${q.oldest}`} urgent={q.urgency === "now"} />)}
          </div>
        </section>

        <section aria-labelledby="ms-kpi">
          <h2 id="ms-kpi" className="sr-only">Key numbers</h2>
          <dl className="grid grid-cols-2 border-y-2 border-[var(--ink)] bg-[var(--surface)] sm:grid-cols-3 xl:grid-cols-6">
            {rows.map((r, i) => (
              <div key={r.k} className={cn("border-[var(--line)] px-4 py-3", i % 2 === 1 && "border-l", "sm:border-l sm:[&:nth-child(3n+1)]:border-l-0 xl:[&:nth-child(3n+1)]:border-l xl:first:border-l-0", i >= 2 && "max-sm:border-t", i >= 3 && "sm:max-xl:border-t")}>
                <dt className="text-[12.5px] font-bold uppercase tracking-[0.04em] text-[var(--muted)]">{r.k}</dt>
                <dd className={cn("num text-[34px] font-extrabold leading-tight", COND)} title={r.full}>{r.v}</dd>
                <dd className={cn("flex items-center gap-0.5 text-[12.5px] font-bold", r.d >= 0 ? "text-[var(--ok)]" : "text-[var(--bad)]")}>{r.d >= 0 ? <ArrowUpRight size={14} strokeWidth={SW} /> : <ArrowDownRight size={14} strokeWidth={SW} />}{Math.abs(r.d)}% vs last week</dd>
              </div>
            ))}
          </dl>
        </section>

        <div className="grid gap-8 lg:grid-cols-[1.6fr_1fr]">
          <section aria-labelledby="ms-trend" className="rounded-md border border-[var(--line)] bg-[var(--surface)] p-4">
            <div className="flex items-baseline justify-between"><h2 id="ms-trend" className="text-[15px] font-extrabold">Booked value per day</h2><span className="text-[12.5px] font-semibold text-[var(--muted)]">14 days</span></div>
            <div className="mt-4 flex h-[150px] items-end gap-1.5" role="img" aria-label="Booked value per day, last 14 days">
              {TREND.map((v, i) => (
                <div key={i} className="flex h-full flex-1 flex-col justify-end">
                  <div className={cn("w-full rounded-t-[2px]", i === TREND.length - 1 ? "bg-[var(--accent)]" : i >= 7 ? "bg-[var(--ink)]" : "bg-[var(--line-strong)]")} style={{ height: `${Math.max(2, (v / max) * 100)}%` }} />
                </div>
              ))}
            </div>
            <div className="mt-1.5 flex gap-1.5">{TREND_DAYS.map((d, i) => <span key={d} className={cn("num flex-1 text-center text-[11px] font-bold", i === TREND.length - 1 ? "text-[var(--accent)]" : "text-[var(--muted)]")}>{d}</span>)}</div>
            <p className="mt-2 text-[12.5px] font-semibold text-[var(--muted)]">Grey: previous 7 days · black: last 7 · blue: today {inr(TREND[TREND.length - 1])}</p>
          </section>
          <section aria-labelledby="ms-src" className="rounded-md border border-[var(--line)] bg-[var(--surface)] p-4">
            <h2 id="ms-src" className="text-[15px] font-extrabold">Leads by source</h2>
            <ul className="mt-3 space-y-3">{SOURCES.map(s => <li key={s.label}><div className="flex items-center justify-between"><Ch channel={s.channel} /><span className={cn("num text-[22px] font-extrabold leading-none", COND)}>{s.value}</span></div><div className="mt-1 h-2 bg-[var(--raised)]"><div className="h-full bg-[var(--ink)]" style={{ width: `${(s.value / 6) * 100}%` }} /></div></li>)}</ul>
          </section>
        </div>

        <section aria-labelledby="ms-alerts">
          <h2 id="ms-alerts" className="mb-3 text-[15px] font-extrabold">Signals</h2>
          <ul className="divide-y divide-[var(--line)] rounded-md border border-[var(--line)] bg-[var(--surface)]">
            {ALERTS.map(a => {
              const I = a.tone === "danger" ? CircleAlert : a.tone === "warning" ? TriangleAlert : Info;
              return (
                <li key={a.text} className="flex items-center gap-3 px-4 py-3">
                  <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-md", a.tone === "danger" ? "bg-[var(--bad)] text-[var(--on-accent)]" : a.tone === "warning" ? "bg-[var(--cap)] text-[var(--on-cap)]" : "bg-[var(--info-bg)] text-[var(--info)]")}><I size={17} strokeWidth={SW} /></span>
                  <span className="min-w-0 flex-1 text-[14px] font-semibold">{a.text}</span>
                  <B kind="outline" className="shrink-0">{a.action}</B>
                </li>
              );
            })}
          </ul>
        </section>
      </div>
    </Shell>
  );
}

// ── inbox ─────────────────────────────────────────────────────────────────────

function InboxScreen(props: ScreenProps) {
  const ib = useInbox();
  const c = ib.conversation;
  return (
    <Shell {...props} actions={<B kind="blue"><Plus size={16} strokeWidth={SW} /><span className="max-sm:hidden">New message</span></B>}>
      <div className="grid grid-cols-1 h-[calc(100dvh-52px-57px-64px)] md:h-[calc(100dvh-56px-75px)] md:grid-cols-[330px_1fr] xl:grid-cols-[330px_1fr_290px]">
        <section aria-label="Conversations" className={cn("flex min-h-0 min-w-0 flex-col border-r-2 border-[var(--ink)] bg-[var(--surface)]", ib.open && "max-md:hidden")}>
          <div className="flex gap-1 border-b border-[var(--line)] p-2">{(["all", "waiting", "mine"] as const).map(f => <button key={f} type="button" onClick={() => ib.setFilter(f)} className={cn("h-9 flex-1 rounded-md text-[13px] font-bold max-sm:h-11", ib.filter === f ? "bg-[var(--ink)] text-[var(--surface)]" : "text-[var(--muted)] hover:bg-[var(--raised)]")}>{f === "waiting" ? "Needs reply" : f === "mine" ? "Mine" : "All"}</button>)}</div>
          <ul className="scroll min-h-0 flex-1 overflow-y-auto">
            {ib.list.map(conv => (
              <li key={conv.id}>
                <button type="button" onClick={() => ib.pick(conv.id)} className={cn("flex w-full items-start gap-3 border-b border-[var(--line)] px-3 py-2.5 text-left", conv.id === ib.selected ? "bg-[var(--info-bg)]" : "hover:bg-[var(--raised)]")}>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2"><span className={cn("truncate text-[14px]", conv.unread ? "font-extrabold" : "font-semibold")}>{conv.name}</span><span className="ml-auto shrink-0 text-[12px] font-semibold text-[var(--muted)]">{conv.time}</span></span>
                    <span className="block truncate text-[13px] text-[var(--muted)]">{conv.preview}</span>
                    <span className="mt-1 flex items-center gap-2"><Ch channel={conv.channel} />{conv.waiting && <span className={cn("inline-flex items-center gap-1 rounded-[3px] px-1.5 text-[11.5px] font-extrabold leading-5", conv.hot ? "bg-[var(--bad)] text-[var(--on-accent)]" : "bg-[var(--cap)] text-[var(--on-cap)]")}><Clock size={11} strokeWidth={SW} />{conv.waiting}</span>}</span>
                  </span>
                  {conv.unread > 0 && <span className="num mt-0.5 rounded-[3px] bg-[var(--accent)] px-1.5 text-[11.5px] font-extrabold leading-5 text-[var(--on-accent)]">{conv.unread}</span>}
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section aria-label="Conversation" className={cn("flex min-h-0 min-w-0 flex-col", !ib.open && "max-md:hidden")}>
          <div className="flex h-14 items-center gap-2 border-b border-[var(--line)] bg-[var(--surface)] px-3 md:px-4">
            <button type="button" onClick={ib.back} aria-label="Back to conversations" className="flex size-10 items-center justify-center md:hidden"><ArrowLeft size={20} strokeWidth={SW} /></button>
            <div className="min-w-0 flex-1"><p className="truncate text-[16px] font-extrabold">{c.name}</p><p className="text-[12.5px] font-semibold text-[var(--muted)]">{CHANNEL_LABEL[c.channel]} · {c.agent ?? "Unassigned"}</p></div>
            <B kind="black" className="max-sm:hidden"><Phone size={15} strokeWidth={SW} />Call</B>
            <select aria-label="Assign to" data-assign defaultValue={c.agent ?? ""} className="h-9 rounded-md border-2 border-[var(--ink)] bg-[var(--surface)] px-2 text-[13px] font-bold max-lg:hidden"><option value="">Unassigned</option>{AGENTS.map(a => <option key={a.id}>{a.name}</option>)}</select>
          </div>
          <div className="scroll min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3 py-4 md:px-6">
            {THREAD.map(m => m.from === "note" ? (
              <p key={m.id} className="mx-auto max-w-[520px] rounded-md bg-[var(--cap)]/30 px-3 py-2 text-[13px] font-semibold"><span className="font-extrabold">{m.author}:</span> {m.text}</p>
            ) : (
              <div key={m.id} className={cn("flex", m.from === "guest" ? "justify-start" : "justify-end")}>
                <div className={cn("max-w-[80%] rounded-md px-3 py-2 text-[14px] font-medium leading-snug", m.from === "guest" ? "border border-[var(--line)] bg-[var(--surface)]" : "bg-[var(--accent)] text-[var(--on-accent)]")}>
                  {m.text}<span className={cn("mt-0.5 block text-[11.5px] font-semibold", m.from === "guest" ? "text-[var(--muted)]" : "opacity-85")}>{m.time}{m.author ? ` · ${m.author}` : ""}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="border-t-2 border-[var(--ink)] bg-[var(--surface)] p-3">
            {ib.draft !== "sent" && (
              <div className="mb-2 rounded-md border-2 border-[var(--accent)] p-2.5">
                <p className="flex items-center gap-1.5 text-[12.5px] font-extrabold uppercase tracking-[0.04em] text-[var(--accent)]"><Sparkles size={14} strokeWidth={SW} />AI reply ready</p>
                <p className="mt-1 text-[14px] font-medium">{AI_DRAFT}</p>
                <div className="mt-2 flex gap-2"><B kind="blue" onClick={() => ib.setDraft("sent")}>Send</B><B kind="outline" onClick={() => ib.setDraft("edited")}>Edit</B></div>
              </div>
            )}
            <div className="flex items-end gap-2">
              <button type="button" aria-label="Attach" className="flex size-11 items-center justify-center rounded-md hover:bg-[var(--raised)]"><Paperclip size={19} strokeWidth={SW} /></button>
              <textarea rows={1} placeholder="Type a reply" className="min-h-11 flex-1 resize-none rounded-md border-2 border-[var(--field)] bg-[var(--surface)] px-3 py-2.5 text-[16px] font-medium outline-none focus:border-[var(--accent)] sm:text-[14px]" />
              <B kind="blue" className="h-11 w-11 px-0"><Send size={18} strokeWidth={SW} /></B>
            </div>
          </div>
        </section>

        <aside aria-label="Guest" className="scroll hidden min-h-0 overflow-y-auto border-l border-[var(--line)] bg-[var(--surface)] p-4 xl:block">
          <p className="text-[18px] font-extrabold">{GUEST.name}</p>
          <p className="num text-[13px] font-semibold text-[var(--muted)]">{GUEST.phone}</p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <div className="rounded-md bg-[var(--raised)] p-2"><p className="text-[11.5px] font-bold uppercase text-[var(--muted)]">Dates</p><p className="text-[14px] font-extrabold">{GUEST.trip.dates}</p></div>
            <div className="rounded-md bg-[var(--raised)] p-2"><p className="text-[11.5px] font-bold uppercase text-[var(--muted)]">Party</p><p className="text-[14px] font-extrabold">4 people</p></div>
          </div>
          <dl className="mt-3 grid grid-cols-[80px_1fr] gap-y-1.5 text-[13.5px]">
            {[["Stage", GUEST.stage], ["Owner", GUEST.owner], ["Route", GUEST.trip.route], ["Estimate", GUEST.value], ["Source", GUEST.firstTouch]].map(([k, v]) => <Fragment key={k}><dt className="font-semibold text-[var(--muted)]">{k}</dt><dd className="font-bold">{v}</dd></Fragment>)}
          </dl>
          <h3 className="mt-5 text-[13px] font-extrabold uppercase tracking-[0.04em]">History</h3>
          <ol className="mt-2 space-y-2 text-[13px]">{GUEST.journey.map(j => <li key={j.label} className="flex items-baseline gap-2"><span className={cn("size-2 shrink-0 rounded-full", j.done ? "bg-[var(--ink)]" : "bg-[var(--cap)]")} /><span className={cn("font-semibold", !j.done && "text-[var(--muted)]")}>{j.label}<span className="block text-[12px] font-normal text-[var(--muted)]">{j.when}</span></span></li>)}</ol>
        </aside>
      </div>
    </Shell>
  );
}

// ── leads ─────────────────────────────────────────────────────────────────────

const PRI = { hot: "bg-[var(--bad)] text-[var(--on-accent)]", warm: "bg-[var(--cap)] text-[var(--on-cap)]", cold: "bg-[var(--raised)] text-[var(--muted)]" };

function LeadsScreen(props: ScreenProps) {
  const ld = useLeads();
  const view = ld.view === "board" ? "list" : "board"; // Milestone opens on the fast table; the toggle flips to the board.
  return (
    <Shell {...props} actions={<><div className="hidden overflow-hidden rounded-md border-2 border-[var(--ink)] md:flex"><button type="button" onClick={() => ld.setView("board")} className={cn("flex h-8 items-center gap-1 px-2.5 text-[13px] font-bold", view === "list" ? "bg-[var(--ink)] text-[var(--surface)]" : "")}><List size={15} strokeWidth={SW} />Table</button><button type="button" onClick={() => ld.setView("list")} className={cn("flex h-8 items-center gap-1 px-2.5 text-[13px] font-bold", view === "board" ? "bg-[var(--ink)] text-[var(--surface)]" : "")}><LayoutGrid size={15} strokeWidth={SW} />Board</button></div><B kind="blue"><Plus size={16} strokeWidth={SW} /><span className="max-sm:hidden">Add lead</span></B></>}>
      <div className="px-4 py-5 md:px-6">
        <div className="mb-4 grid grid-cols-3 gap-2 sm:grid-cols-6">
          {[{ key: "all", label: "All", count: 55 }, ...STAGES].map(s => (
            <button key={s.key} type="button" onClick={() => ld.setStage(s.key)} className={cn("press rounded-md border-2 px-2 py-1.5 text-left", ld.stage === s.key ? "border-[var(--ink)] bg-[var(--ink)] text-[var(--surface)]" : "border-[var(--line)] bg-[var(--surface)] hover:border-[var(--ink)]")}>
              <span className={cn("num block text-[24px] font-extrabold leading-none", COND)}>{s.count}</span><span className="text-[12px] font-bold">{s.label}</span>
            </button>
          ))}
        </div>

        {view === "list" ? (
          <>
            <div className="hidden overflow-x-auto rounded-md border-2 border-[var(--ink)] bg-[var(--surface)] md:block">
              <table className="w-full min-w-[820px] text-[13.5px]">
                <thead className="bg-[var(--ink)] text-left text-[12px] uppercase tracking-[0.04em] text-[var(--surface)]"><tr>{["", "Guest", "Stage", "Dates", "Value", "Owner", "Next step", "Due"].map(h => <th key={h} className="px-3 py-2 font-extrabold">{h}</th>)}</tr></thead>
                <tbody>{ld.list.map(l => (
                  <tr key={l.id} className="border-t border-[var(--line)] hover:bg-[var(--raised)]">
                    <td className="py-2 pl-3"><span className={cn("rounded-[3px] px-1.5 py-0.5 text-[11px] font-extrabold uppercase", PRI[l.priority])}>{l.priority}</span></td>
                    <td className="px-3 py-2 font-bold">{l.name}<span className="block"><Ch channel={l.channel} /></span></td>
                    <td className="px-3 font-semibold">{STAGES.find(s => s.key === l.stage)?.label}</td>
                    <td className="px-3 text-[var(--muted)]">{l.dates ?? "—"}</td>
                    <td className={cn("num px-3 text-[17px] font-extrabold", COND)}>{l.value ? inr(l.value) : "—"}</td>
                    <td className="px-3 font-semibold">{l.owner ?? <span className="rounded-[3px] bg-[var(--cap)] px-1 text-[12px] font-extrabold text-[var(--on-cap)]">Nobody</span>}</td>
                    <td className="px-3 font-semibold">{l.next}</td>
                    <td className={cn("px-3 font-extrabold", l.due === "now" && "text-[var(--bad)]")}>{l.due ?? "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="hidden gap-3 md:grid md:grid-cols-3 xl:grid-cols-5">
            {STAGES.map(s => (
              <section key={s.key} aria-label={s.label} className="min-w-0 rounded-md bg-[var(--raised)] p-2">
                <h2 className="mb-2 flex items-baseline justify-between px-1 text-[13.5px] font-extrabold">{s.label}<span className="num text-[12px] font-bold text-[var(--muted)]">{s.count}</span></h2>
                <div className="space-y-2">{LEADS.filter(l => l.stage === s.key).map(l => (
                  <div key={l.id} className="rounded-md border border-[var(--line)] bg-[var(--surface)] p-2.5"><div className="flex items-center gap-2"><span className="truncate text-[13.5px] font-extrabold">{l.name}</span><span className={cn("ml-auto rounded-[3px] px-1 text-[10.5px] font-extrabold uppercase", PRI[l.priority])}>{l.priority}</span></div><p className="text-[12.5px] text-[var(--muted)]">{l.dates ?? "No dates"}</p><p className={cn("mt-1 text-[12.5px] font-bold", l.due === "now" && "text-[var(--bad)]")}>{l.next}</p></div>
                ))}</div>
              </section>
            ))}
          </div>
        )}
        <ul className="space-y-2 md:hidden">{ld.list.map(l => (
          <li key={l.id} className="rounded-md border border-[var(--line)] bg-[var(--surface)] p-3">
            <div className="flex items-center gap-2"><span className={cn("rounded-[3px] px-1.5 text-[11px] font-extrabold uppercase leading-5", PRI[l.priority])}>{l.priority}</span><span className="truncate text-[15px] font-extrabold">{l.name}</span>{l.value ? <span className={cn("num ml-auto text-[18px] font-extrabold", COND)}>{inrShort(l.value)}</span> : null}</div>
            <p className="mt-1 text-[13px] font-semibold text-[var(--muted)]">{STAGES.find(s => s.key === l.stage)?.label} · {l.dates ?? "No dates"} · {l.owner?.split(" ")[0] ?? "No owner"}</p>
            <div className="mt-2 flex items-center gap-2"><span className={cn("min-w-0 flex-1 truncate text-[13.5px] font-bold", l.due === "now" && "text-[var(--bad)]")}>{l.next}</span><B kind="black" className="h-10 shrink-0"><Phone size={15} strokeWidth={SW} /></B></div>
          </li>
        ))}</ul>
      </div>
    </Shell>
  );
}

// ── calendar ──────────────────────────────────────────────────────────────────

const BLOCK: Record<ResKind, string> = {
  direct: "bg-[var(--accent)] text-[var(--on-accent)]",
  ota: "bg-[var(--surface)] text-[var(--ink)] border-2 border-[var(--ink)]",
  hold: "bg-[var(--cap)] text-[var(--on-cap)]",
  blocked: "bg-[repeating-linear-gradient(135deg,var(--raised)_0_6px,var(--line)_6px_12px)] text-[var(--muted)]",
  maintenance: "bg-[var(--bad)] text-[var(--on-accent)]",
};
const BLOCK_LABEL: Record<ResKind, string> = { direct: "Direct", ota: "Airbnb", hold: "On hold", blocked: "Blocked", maintenance: "Maintenance" };

function CalendarScreen(props: ScreenProps) {
  const cal = useCalendar();
  const days = Array.from({ length: CAL_DAYS }, (_, i) => i);
  return (
    <Shell {...props} actions={<><B kind="outline" className="w-9 px-0 max-sm:w-11"><ChevronLeft size={17} strokeWidth={SW} /></B><span className="text-[14px] font-extrabold max-sm:hidden">12 Oct – 1 Nov</span><B kind="outline" className="w-9 px-0 max-sm:w-11"><ChevronRight size={17} strokeWidth={SW} /></B><B kind="blue" className="max-sm:hidden"><Plus size={16} strokeWidth={SW} />Booking</B></>}>
      <div className="px-4 py-5 md:px-6">
        <ul className="mb-4 flex flex-wrap gap-2">{(Object.keys(BLOCK) as ResKind[]).map(k => <li key={k} className={cn("rounded-[3px] px-2 py-0.5 text-[12px] font-extrabold", BLOCK[k])}>{BLOCK_LABEL[k]}</li>)}</ul>
        <div className="hidden overflow-x-auto rounded-md border-2 border-[var(--ink)] bg-[var(--surface)] md:block">
          <div className="min-w-[900px]">
            <div className="grid grid-cols-[120px_1fr] bg-[var(--ink)] text-[var(--surface)]">
              <div className="px-3 py-2 text-[12px] font-extrabold uppercase">Caravan</div>
              <div className="grid" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>{days.map(i => { const d = dayLabel(i); return <div key={i} className={cn("py-1 text-center", i === CAL_TODAY_INDEX && "bg-[var(--cap)] text-[var(--on-cap)]")}><p className="text-[10.5px] font-bold uppercase">{d.dow.slice(0, 2)}</p><p className={cn("num text-[16px] font-extrabold leading-none", COND)}>{d.day}</p></div>; })}</div>
            </div>
            {PROPERTIES.map(p => (
              <div key={p.id} className="grid grid-cols-[120px_1fr] border-t border-[var(--line)]">
                <div className="px-3 py-3"><p className="text-[15px] font-extrabold">{p.name}</p><p className="text-[12px] font-semibold text-[var(--muted)]">{p.note}</p></div>
                <div className="relative h-[60px]">
                  <div className="absolute inset-0 grid" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>{days.map(i => <div key={i} className={cn("border-l border-[var(--line)]", i === CAL_TODAY_INDEX && "bg-[var(--cap)]/15")} />)}</div>
                  {RESERVATIONS.filter(r => r.property === p.id).map(r => (
                    <button key={r.id} type="button" onClick={() => cal.setSelected(r.id)} style={barStyle(r)} className={cn("press absolute top-2.5 flex h-10 items-center overflow-hidden rounded-[4px] px-2 text-left text-[12.5px] font-extrabold", BLOCK[r.kind], cal.selected === r.id && "outline outline-[3px] outline-offset-1 outline-[var(--ink)]")}><span className="truncate">{r.guest}</span></button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
        {cal.res && (
          <section aria-label="Reservation" className="mt-4 hidden flex-wrap items-center gap-x-8 gap-y-2 rounded-md border-2 border-[var(--ink)] bg-[var(--surface)] p-4 md:flex">
            <div><p className="text-[12px] font-extrabold uppercase text-[var(--muted)]">{BLOCK_LABEL[cal.res.kind]} · {cal.res.status}</p><p className="text-[20px] font-extrabold">{cal.res.guest}</p></div>
            {[["Caravan", PROPERTIES.find(p => p.id === cal.res!.property)?.name], ["Dates", `${dayLabel(cal.res.start).day}–${dayLabel(cal.res.end).day} ${dayLabel(cal.res.end).month}`], ["Nights", String(cal.res.end - cal.res.start)], ...(cal.res.amount != null ? [["Total", inr(cal.res.amount)], ["Balance", inr(cal.res.amount - (cal.res.paid ?? 0))]] : [])].map(([k, v]) => <div key={k}><p className="text-[12px] font-bold uppercase text-[var(--muted)]">{k}</p><p className={cn("num text-[22px] font-extrabold leading-tight", COND)}>{v}</p></div>)}
            <B kind="blue" className="ml-auto">Open booking</B>
          </section>
        )}
        <div className="md:hidden">
          <div className="grid grid-cols-7 overflow-hidden rounded-md border-2 border-[var(--ink)] bg-[var(--surface)]">
            {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <div key={i} className="bg-[var(--ink)] py-1 text-center text-[11.5px] font-extrabold text-[var(--surface)]">{d}</div>)}
            {days.map(i => {
              const n = cal.onDay(i).filter(r => r.kind !== "blocked" && r.kind !== "maintenance").length;
              const out = cal.onDay(i).some(r => r.kind === "maintenance");
              return (
                <button key={i} type="button" onClick={() => cal.setDay(i)} aria-pressed={cal.day === i} className={cn("flex h-14 flex-col items-center justify-center gap-0.5 border-t border-l border-[var(--line)] [&:nth-child(7n+8)]:border-l-0", cal.day === i && "bg-[var(--info-bg)]")}>
                  <span className={cn("num text-[18px] font-extrabold leading-none", COND, i === CAL_TODAY_INDEX && "rounded-[3px] bg-[var(--cap)] px-1")}>{dayLabel(i).day}</span>
                  <span className="text-[10.5px] font-extrabold">{out ? <span className="text-[var(--bad)]">Svc</span> : n === 2 ? "Full" : n === 1 ? "1 out" : <span className="text-[var(--ok)]">Free</span>}</span>
                </button>
              );
            })}
          </div>
          <h2 className="mb-2 mt-4 text-[15px] font-extrabold">{dayLabel(cal.day).dow} {dayLabel(cal.day).day} {dayLabel(cal.day).month}</h2>
          <ul className="space-y-2">
            {cal.onDay(cal.day).length === 0 && <li className="rounded-md border-2 border-dashed border-[var(--line-strong)] p-4 text-center text-[14px] font-bold text-[var(--ok)]">Both caravans free</li>}
            {cal.onDay(cal.day).map(r => <li key={r.id} className={cn("flex items-center gap-3 rounded-md p-3", BLOCK[r.kind])}><div className="min-w-0 flex-1"><p className="truncate text-[15px] font-extrabold">{r.guest}</p><p className="text-[12.5px] font-bold opacity-90">{PROPERTIES.find(p => p.id === r.property)?.name} · {dayLabel(r.start).day}–{dayLabel(r.end).day} {dayLabel(r.end).month}</p></div>{r.amount != null && <span className={cn("num text-[20px] font-extrabold", COND)}>{inrShort(r.amount)}</span>}</li>)}
          </ul>
        </div>
      </div>
    </Shell>
  );
}

export default function Milestone(props: ScreenProps) {
  if (props.screen === "inbox") return <InboxScreen {...props} />;
  if (props.screen === "leads") return <LeadsScreen {...props} />;
  if (props.screen === "calendar") return <CalendarScreen {...props} />;
  return <Home {...props} />;
}
