"use client";
// E · AI Command Center: a live operations room where the AI shows its working. Low-glare dark surfaces, cool blue for
// actions, violet ONLY for AI (so a person always knows what the machine suggested). Icon rail + live status strip +
// an insight rail on wide screens; on phones the insights open as a bottom sheet. Onest for UI, JetBrains Mono for data.
import {
  Activity, ArrowDownRight, ArrowLeft, ArrowUpRight, Bot, CalendarDays, Camera, ChartColumn, ChevronLeft, ChevronRight,
  Globe, House, Inbox, Megaphone, MessageCircle, Paperclip, Phone, Plus, Search, Send, Settings, Sparkles, SquareKanban, X,
} from "lucide-react";
import { useState, type ComponentType } from "react";
import { cn } from "@/lib/utils";
import {
  AGENTS, AI_DRAFT, CAL_DAYS, CAL_TODAY_INDEX, CHANNEL_LABEL, GUEST, KPIS, LEADS, PROPERTIES, QUEUE, RESERVATIONS, SOURCES,
  STAGES, THREAD, TREND, TREND_DAYS, dayLabel, inr, inrShort, type Channel, type ResKind,
} from "../data";
import { barStyle, trendPath, useCalendar, useInbox, useLeads, type ScreenProps } from "../hooks";
import type { Screen } from "../concepts";

type Icon = ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
const SW = 1.6;
const MONO = "font-[family-name:var(--font-mono)]";
const NAV: { id: string; label: string; icon: Icon; count?: number }[] = [
  { id: "home", label: "Ops", icon: House },
  { id: "inbox", label: "Inbox", icon: Inbox, count: 4 },
  { id: "leads", label: "Leads", icon: SquareKanban, count: 5 },
  { id: "calendar", label: "Calendar", icon: CalendarDays },
  { id: "calls", label: "Calls", icon: Phone, count: 3 },
  { id: "campaigns", label: "Campaigns", icon: Megaphone },
  { id: "reports", label: "Reports", icon: ChartColumn },
  { id: "settings", label: "Settings", icon: Settings },
];
const SCREEN_IDS = ["home", "inbox", "leads", "calendar"];
const TITLES: Record<Screen, string> = { home: "Operations", inbox: "Inbox", leads: "Leads 360", calendar: "Calendar" };

const INSIGHTS = [
  { title: "Call Priya Nair now", why: "Asked twice for a total; quotes sent within 30 min convert 2.4× better here.", conf: 92, action: "Call" },
  { title: "Ratha 2 is free 19–20 Oct", why: "3 open leads asked for those dates. Offer it to Rahul Sharma first (highest intent).", conf: 81, action: "Draft offer" },
  { title: "Add a pet policy", why: "3 enquiries this week asked about pets; the AI had to hand each one to a person.", conf: 74, action: "Open KB" },
];
const SCORE: Record<string, number> = { l1: 86, l2: 64, l3: 41, l4: 58, l5: 52, l6: 91, l7: 33, l8: 100, l9: 100, l10: 0 };

const CH_ICON: Record<Channel, Icon> = { whatsapp: MessageCircle, instagram: Camera, call: Phone, website: Globe };
function Ch({ channel, label = true }: { channel: Channel; label?: boolean }) {
  const I = CH_ICON[channel];
  return <span className="inline-flex items-center gap-1 text-[12px] text-[var(--muted)]"><I size={12} strokeWidth={SW} />{label && CHANNEL_LABEL[channel]}</span>;
}
function Btn({ children, kind = "ghost", className, onClick }: { children: React.ReactNode; kind?: "primary" | "ghost" | "ai"; className?: string; onClick?: () => void }) {
  const k = {
    primary: "bg-[var(--accent)] text-[var(--on-accent)] hover:bg-[var(--accent-hover)]",
    ghost: "border border-[var(--line-strong)] text-[var(--ink)] hover:bg-[var(--raised)]",
    ai: "bg-[var(--ai-bg)] text-[var(--ai)] border border-[var(--ai)]/40 hover:border-[var(--ai)]",
  };
  return <button type="button" onClick={onClick} className={cn("press inline-flex h-8 items-center justify-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-medium max-sm:h-11 max-sm:px-3.5", k[kind], className)}>{children}</button>;
}
function Panel({ title, meta, children, className }: { title: string; meta?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("min-w-0 rounded-lg border border-[var(--line)] bg-[var(--surface)]", className)} aria-label={title}>
      <div className="flex h-10 items-center gap-2 border-b border-[var(--line)] px-3.5"><h2 className="text-[12.5px] font-semibold uppercase tracking-[0.06em] text-[var(--muted)]">{title}</h2><span className="ml-auto text-[12px] text-[var(--muted)]">{meta}</span></div>
      {children}
    </section>
  );
}
function Confidence({ value }: { value: number }) {
  return <span className={cn(MONO, "inline-flex items-center gap-1.5 text-[11px] text-[var(--ai)]")}><span className="h-1 w-10 overflow-hidden rounded-full bg-[var(--ai-bg)]"><span className="block h-full bg-[var(--ai)]" style={{ width: `${value}%` }} /></span>{value}%</span>;
}

function InsightList({ compact }: { compact?: boolean }) {
  return (
    <ul className="divide-y divide-[var(--line)]">
      {INSIGHTS.map(i => (
        <li key={i.title} className={cn(compact ? "p-3" : "p-3.5")}>
          <p className="flex items-center gap-1.5 text-[13.5px] font-semibold"><Sparkles size={13} strokeWidth={SW} className="shrink-0 text-[var(--ai)]" />{i.title}</p>
          <p className="mt-1 text-[12.5px] leading-snug text-[var(--muted)]"><span className="text-[var(--ai)]">Why: </span>{i.why}</p>
          <div className="mt-2 flex items-center justify-between"><Confidence value={i.conf} /><Btn kind="ai">{i.action}</Btn></div>
        </li>
      ))}
    </ul>
  );
}

// ── shell ─────────────────────────────────────────────────────────────────────

function Shell({ screen, go, children, actions, rail = true, fab = rail }: ScreenProps & { children: React.ReactNode; actions?: React.ReactNode; rail?: boolean; fab?: boolean }) {
  const [sheet, setSheet] = useState(false);
  return (
    <div className="lab-root lab-command flex">
      <aside className="sticky top-0 hidden h-dvh w-[68px] shrink-0 flex-col items-center gap-1 border-r border-[var(--line)] bg-[var(--chrome)] py-3 md:flex">
        <span className="mb-3 flex size-9 items-center justify-center rounded-lg bg-[var(--accent)] text-[13px] font-bold text-[var(--on-accent)]">R</span>
        {NAV.map(item => {
          const active = item.id === screen;
          return (
            <button key={item.id} type="button" aria-current={active ? "page" : undefined} onClick={() => SCREEN_IDS.includes(item.id) && go(item.id as Screen)}
              className={cn("relative flex w-[56px] flex-col items-center gap-0.5 rounded-lg py-2 text-[10.5px]", active ? "bg-[var(--chrome-active)] text-[var(--ink)]" : "text-[var(--chrome-muted)] hover:text-[var(--ink)]")}>
              <item.icon size={19} strokeWidth={SW} />{item.label}
              {item.count ? <span className={cn(MONO, "absolute right-1.5 top-1 rounded bg-[var(--bad)] px-1 text-[9.5px] leading-[14px] text-[var(--on-accent)]")}>{item.count}</span> : null}
            </button>
          );
        })}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-[var(--line)] bg-[var(--bg)]">
          <div className="flex h-12 items-center gap-3 px-3 md:px-5">
            <h1 className="text-[15px] font-semibold md:text-[16px]">{TITLES[screen]}</h1>
            <label className="hidden h-8 w-[260px] items-center gap-2 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2.5 text-[var(--muted)] lg:flex"><Search size={14} strokeWidth={SW} /><input placeholder="Ask or search…" className="w-full bg-transparent text-[13px] text-[var(--ink)] outline-none" /><kbd className={cn(MONO, "text-[10.5px]")}>/</kbd></label>
            <div className="ml-auto flex items-center gap-2">{actions}</div>
          </div>
          {/* Live status strip: what is happening right now, not a period total. */}
          <div className={cn(MONO, "scroll flex h-8 items-center gap-5 overflow-x-auto border-t border-[var(--line)] px-3 text-[11.5px] text-[var(--muted)] md:px-5")}>
            <span className="flex shrink-0 items-center gap-1.5 text-[var(--ok)]"><span className="relative flex size-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--ok)] opacity-60 motion-reduce:hidden" /><span className="relative inline-flex size-2 rounded-full bg-[var(--ok)]" /></span>LIVE</span>
            <span className="shrink-0">2 agents online</span>
            <span className="shrink-0"><span className="text-[var(--ink)]">1</span> call in progress</span>
            <span className="shrink-0"><span className="text-[var(--bad)]">8</span> past target</span>
            <span className="shrink-0 text-[var(--ai)]">AI answered 18 today · 3 handed over</span>
          </div>
        </header>
        <div className="flex min-h-0 flex-1">
          <main className="min-w-0 flex-1 pb-24 md:pb-6">{children}</main>
          {rail && (
            <aside aria-label="AI insights" className="sticky top-[81px] hidden h-[calc(100dvh-81px)] w-[300px] shrink-0 overflow-y-auto border-l border-[var(--line)] bg-[var(--chrome)] 2xl:block">
              <div className="flex h-10 items-center gap-2 border-b border-[var(--line)] px-3.5 text-[12.5px] font-semibold uppercase tracking-[0.06em] text-[var(--ai)]"><Bot size={15} strokeWidth={SW} />Copilot</div>
              <InsightList />
            </aside>
          )}
        </div>
      </div>

      {fab && <button type="button" onClick={() => setSheet(true)} aria-label="Open AI insights" className="press fixed bottom-20 right-4 z-30 flex h-12 items-center gap-2 rounded-full border border-[var(--ai)]/50 bg-[var(--ai-bg)] px-4 text-[13.5px] font-semibold text-[var(--ai)] shadow-[0_8px_24px_-8px_rgba(0,0,0,0.6)] md:bottom-6 2xl:hidden"><Sparkles size={16} strokeWidth={SW} />3 insights</button>}
      {sheet && (
        <div className="fixed inset-0 z-50 2xl:hidden" role="dialog" aria-modal="true" aria-label="AI insights">
          <button type="button" aria-label="Close" onClick={() => setSheet(false)} className="absolute inset-0 bg-[var(--bg)]/70" />
          <div className="absolute inset-x-0 bottom-0 max-h-[80dvh] overflow-y-auto rounded-t-2xl border-t border-[var(--line-strong)] bg-[var(--surface)] pb-[env(safe-area-inset-bottom)] md:inset-x-auto md:right-6 md:bottom-6 md:w-[380px] md:rounded-2xl md:border">
            <div className="flex h-12 items-center gap-2 border-b border-[var(--line)] px-4 text-[13px] font-semibold uppercase tracking-[0.06em] text-[var(--ai)]"><Bot size={16} strokeWidth={SW} />Copilot<button type="button" aria-label="Close" onClick={() => setSheet(false)} className="ml-auto flex size-10 items-center justify-center text-[var(--muted)]"><X size={18} /></button></div>
            <InsightList compact />
          </div>
        </div>
      )}

      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 flex h-16 border-t border-[var(--line)] bg-[var(--chrome)] pb-[env(safe-area-inset-bottom)] md:hidden">
        {NAV.slice(0, 5).map(item => {
          const active = item.id === screen;
          return (
            <button key={item.id} type="button" onClick={() => SCREEN_IDS.includes(item.id) && go(item.id as Screen)} className={cn("relative flex flex-1 flex-col items-center justify-center gap-1 text-[11px]", active ? "text-[var(--accent)]" : "text-[var(--chrome-muted)]")}>
              <item.icon size={20} strokeWidth={SW} />{item.label}
              {item.count ? <span className={cn(MONO, "absolute right-[calc(50%-20px)] top-2 rounded bg-[var(--bad)] px-1 text-[10px] leading-[15px] text-[var(--on-accent)]")}>{item.count}</span> : null}
            </button>
          );
        })}
      </nav>
    </div>
  );
}

// ── home ──────────────────────────────────────────────────────────────────────

function Tile({ label, value, change, spark }: { label: string; value: string; change: number; spark?: boolean }) {
  const t = trendPath(120, 30, 2);
  return (
    <div className="flex min-w-0 flex-col gap-1 bg-[var(--surface)] p-3.5">
      <p className="text-[12px] text-[var(--muted)]">{label}</p>
      <p className={cn(MONO, "num text-[21px] font-medium tracking-tight")}>{value}</p>
      {spark && <svg viewBox="0 0 120 30" preserveAspectRatio="none" className="h-[22px] w-full" aria-hidden><path d={t.line} fill="none" stroke="var(--accent)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" /></svg>}
      <p className={cn(MONO, "flex items-center gap-1 text-[11.5px]", change >= 0 ? "text-[var(--ok)]" : "text-[var(--bad)]")}>{change >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}{change >= 0 ? "+" : ""}{change}% <span className="text-[var(--muted)]">7d</span></p>
    </div>
  );
}

function Home(props: ScreenProps) {
  const t = trendPath(640, 150, 4);
  return (
    <Shell {...props} fab={false} actions={<><div className={cn(MONO, "hidden rounded-md border border-[var(--line)] p-0.5 text-[11.5px] sm:flex")}>{["1D", "7D", "30D"].map((p, i) => <button key={p} type="button" className={cn("h-7 rounded px-2", i === 1 ? "bg-[var(--raised)] text-[var(--ink)]" : "text-[var(--muted)]")}>{p}</button>)}</div><Btn kind="primary"><Plus size={14} />New</Btn></>}>
      <div className="grid gap-3 p-3 md:p-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <Panel title="Queue · live" meta={<span className={MONO}>14 people</span>}>
          <table className="w-full text-[13px]">
            <tbody className="divide-y divide-[var(--line)]">
              {QUEUE.map(q => (
                <tr key={q.kind}>
                  <td className="py-3 pl-3.5"><span className={cn(MONO, "num text-[18px]", q.urgency === "now" ? "text-[var(--bad)]" : "text-[var(--ink)]")}>{q.count}</span></td>
                  <td className="px-3"><p className="font-medium">{q.label}</p><p className={cn(MONO, "text-[11.5px] text-[var(--muted)]")}>oldest {q.oldest}</p></td>
                  <td className="pr-3.5 text-right">{q.urgency === "now" ? <span className={cn(MONO, "rounded bg-[var(--bad-bg)] px-1.5 py-0.5 text-[11px] text-[var(--bad)]")}>OVER SLA</span> : <span className={cn(MONO, "text-[11px] text-[var(--muted)]")}>ON TRACK</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Key metrics" meta={<span className={MONO}>last 7d</span>}>
          <div className="grid grid-cols-2 gap-px bg-[var(--line)] sm:grid-cols-3">
            <Tile label={KPIS.newLeads.label} value={String(KPIS.newLeads.value)} change={KPIS.newLeads.change} />
            <Tile label={KPIS.bookings.label} value={String(KPIS.bookings.value)} change={KPIS.bookings.change} />
            <Tile label={KPIS.bookedValue.label} value={inrShort(KPIS.bookedValue.value)} change={KPIS.bookedValue.change} spark />
            <Tile label={KPIS.cash.label} value={inrShort(KPIS.cash.value)} change={KPIS.cash.change} />
            <Tile label={KPIS.occupancy.label} value={`${KPIS.occupancy.value}%`} change={KPIS.occupancy.change} />
            <Tile label={KPIS.response.label} value={`${KPIS.response.value}m`} change={KPIS.response.change} />
          </div>
        </Panel>
        <Panel title="Booked value · 14d" meta={<span className={cn(MONO, "text-[var(--ink)]")}>today {inr(TREND[TREND.length - 1])}</span>}>
          <div className="p-3.5">
            <svg viewBox="0 0 640 150" className="h-[150px] w-full" role="img" aria-label="Booked value per day, last 14 days">
              <defs><linearGradient id="cmd-area" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="var(--accent)" stopOpacity="0.28" /><stop offset="1" stopColor="var(--accent)" stopOpacity="0" /></linearGradient></defs>
              {[30, 60, 90, 120].map(y => <line key={y} x1="0" x2="640" y1={y} y2={y} stroke="var(--line)" />)}
              <line x1={t.points[7][0]} x2={t.points[7][0]} y1="0" y2="150" stroke="var(--line-strong)" strokeDasharray="2 4" />
              <path d={t.area} fill="url(#cmd-area)" />
              <path d={t.line} fill="none" stroke="var(--accent)" strokeWidth="2" />
            </svg>
            <div className={cn(MONO, "mt-1 flex justify-between text-[10.5px] text-[var(--muted)]")}>{TREND_DAYS.filter((_, i) => i % 2 === 0).map(d => <span key={d}>{d}/10</span>)}</div>
          </div>
        </Panel>
        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
          <Panel title="Sources" meta={<span className={MONO}>14 leads</span>}>
            <ul className="space-y-2.5 p-3.5">{SOURCES.map(s => <li key={s.label}><div className="flex justify-between"><Ch channel={s.channel} /><span className={cn(MONO, "text-[12.5px]")}>{s.value}</span></div><div className="mt-1 h-1 rounded-full bg-[var(--raised)]"><div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${(s.value / 6) * 100}%` }} /></div></li>)}</ul>
          </Panel>
          <Panel title="AI" meta={<span className="text-[var(--ai)]">3 suggestions</span>} className="2xl:hidden"><InsightList compact /></Panel>
          <Panel title="Activity" meta={<Activity size={13} />} className="hidden 2xl:block">
            <ol className={cn(MONO, "space-y-2 p-3.5 text-[11.5px] text-[var(--muted)]")}>{["10:41 Priya Nair wrote on WhatsApp", "10:38 AI drafted a reply (held: price)", "10:22 Meera Reddy paid ₹26,400", "09:57 Missed call · Kabir Shah", "09:40 Bala logged a call · 4 min"].map(e => <li key={e}><span className="text-[var(--ink)]">{e.slice(0, 5)}</span>{e.slice(5)}</li>)}</ol>
          </Panel>
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
    <Shell {...props} rail={false} actions={<Btn kind="primary"><Plus size={14} /><span className="max-sm:hidden">New</span></Btn>}>
      <div className="grid grid-cols-1 h-[calc(100dvh-81px-64px)] md:h-[calc(100dvh-81px)] md:grid-cols-[320px_1fr] xl:grid-cols-[320px_1fr_310px]">
        <section aria-label="Conversations" className={cn("flex min-h-0 min-w-0 flex-col border-r border-[var(--line)] bg-[var(--chrome)]", ib.open && "max-md:hidden")}>
          <div className="flex gap-1 border-b border-[var(--line)] p-2">{(["all", "waiting", "mine"] as const).map(f => <button key={f} type="button" onClick={() => ib.setFilter(f)} className={cn("h-8 flex-1 rounded-md text-[12.5px] max-sm:h-10", ib.filter === f ? "bg-[var(--raised)] font-medium text-[var(--ink)]" : "text-[var(--muted)]")}>{f === "waiting" ? "Needs reply" : f === "mine" ? "Mine" : "All"}</button>)}</div>
          <ul className="scroll min-h-0 flex-1 overflow-y-auto">
            {ib.list.map(conv => (
              <li key={conv.id}>
                <button type="button" onClick={() => ib.pick(conv.id)} className={cn("relative w-full border-b border-[var(--line)] px-3 py-2.5 text-left", conv.id === ib.selected ? "bg-[var(--raised)]" : "hover:bg-[var(--surface)]")}>
                  {conv.id === ib.selected && <span aria-hidden className="absolute inset-y-0 left-0 w-[2px] bg-[var(--accent)]" />}
                  <span className="flex items-center gap-2"><span className={cn("truncate text-[13.5px]", conv.unread ? "font-semibold" : "")}>{conv.name}</span><Ch channel={conv.channel} label={false} /><span className={cn(MONO, "ml-auto text-[11px] text-[var(--muted)]")}>{conv.time}</span></span>
                  <span className="mt-0.5 block truncate text-[12.5px] text-[var(--muted)]">{conv.preview}</span>
                  <span className="mt-1.5 flex items-center gap-2">{conv.waiting && <span className={cn(MONO, "rounded px-1.5 text-[10.5px] leading-[18px]", conv.hot ? "bg-[var(--bad-bg)] text-[var(--bad)]" : "bg-[var(--warn-bg)] text-[var(--warn)]")}>WAIT {conv.waiting}</span>}{conv.aiDraft && <span className="inline-flex items-center gap-1 text-[11px] text-[var(--ai)]"><Sparkles size={11} />draft</span>}<span className="ml-auto text-[11.5px] text-[var(--muted)]">{conv.agent?.split(" ")[0] ?? "—"}</span></span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section aria-label="Conversation" className={cn("flex min-h-0 min-w-0 flex-col", !ib.open && "max-md:hidden")}>
          <div className="flex h-12 items-center gap-2 border-b border-[var(--line)] px-3">
            <button type="button" onClick={ib.back} aria-label="Back to conversations" className="flex size-10 items-center justify-center md:hidden"><ArrowLeft size={18} /></button>
            <p className="min-w-0 flex-1 truncate text-[14px] font-semibold">{c.name} <span className="font-normal text-[var(--muted)]">· {CHANNEL_LABEL[c.channel]}</span></p>
            <Btn className="max-sm:hidden"><Phone size={13} />Call</Btn>
            <select aria-label="Assign to" data-assign defaultValue={c.agent ?? ""} className="h-8 rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-2 text-[12.5px] max-lg:hidden"><option value="">Unassigned</option>{AGENTS.map(a => <option key={a.id}>{a.name}</option>)}</select>
          </div>
          <div className="scroll min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-4 md:px-6">
            {THREAD.map(m => m.from === "note" ? (
              <p key={m.id} className={cn(MONO, "mx-auto max-w-[520px] rounded-md border border-dashed border-[var(--warn)]/50 px-3 py-1.5 text-center text-[11.5px] text-[var(--warn)]")}>NOTE · {m.author}: {m.text}</p>
            ) : (
              <div key={m.id} className={cn("flex", m.from === "guest" ? "justify-start" : "justify-end")}>
                <div className={cn("max-w-[78%] rounded-xl px-3 py-2 text-[13.5px] leading-relaxed", m.from === "guest" ? "bg-[var(--surface)]" : m.from === "ai" ? "border border-[var(--ai)]/40 bg-[var(--ai-bg)]" : "bg-[var(--accent)] text-[var(--on-accent)]")}>
                  {m.text}<span className={cn(MONO, "mt-1 flex items-center gap-1 text-[10.5px]", m.from === "ai" ? "text-[var(--ai)]" : "text-[var(--muted)]")}>{m.from === "ai" && <Bot size={11} />}{m.time}{m.author ? ` · ${m.author}` : ""}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="border-t border-[var(--line)] p-3">
            {ib.draft !== "sent" && (
              <div className="mb-2 rounded-lg border border-[var(--ai)]/40 bg-[var(--ai-bg)] p-3">
                <div className="flex items-center gap-2"><p className="flex items-center gap-1.5 text-[12.5px] font-semibold text-[var(--ai)]"><Sparkles size={13} />Draft · held for you</p><span className="ml-auto"><Confidence value={88} /></span></div>
                <p className="mt-1.5 text-[13.5px] leading-relaxed">{AI_DRAFT}</p>
                <p className="mt-1.5 text-[11.5px] text-[var(--muted)]"><span className="text-[var(--ai)]">Why held:</span> mentions a total; your policy sends prices only from a person.</p>
                <div className="mt-2 flex gap-2"><Btn kind="primary" onClick={() => ib.setDraft("sent")}>Approve &amp; send</Btn><Btn onClick={() => ib.setDraft("edited")}>Edit</Btn></div>
              </div>
            )}
            <div className="flex items-end gap-2">
              <button type="button" aria-label="Attach" className="flex size-10 items-center justify-center text-[var(--muted)]"><Paperclip size={17} /></button>
              <textarea rows={1} placeholder="Reply, or type / for actions" className="min-h-10 flex-1 resize-none rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-3 py-2 text-[16px] outline-none focus:border-[var(--accent)] sm:text-[13.5px]" />
              <Btn kind="primary" className="h-10 w-10 px-0"><Send size={15} /></Btn>
            </div>
          </div>
        </section>

        <aside aria-label="AI brief" className="scroll hidden min-h-0 overflow-y-auto border-l border-[var(--line)] bg-[var(--chrome)] xl:block">
          <div className="flex h-10 items-center gap-2 border-b border-[var(--line)] px-3.5 text-[12.5px] font-semibold uppercase tracking-[0.06em] text-[var(--ai)]"><Bot size={15} />Brief</div>
          <div className="space-y-4 p-3.5 text-[13px]">
            <p className="leading-relaxed">Family of 4 (kids 6 and 9) wants Ratha 1 on <span className="font-semibold">24–26 Oct</span> for Coorg. Asked for the total twice. Phone shared, one call so far.</p>
            <div className="grid grid-cols-2 gap-2">{[["Intent", "High"], ["Win chance", "86%"], ["Est. value", "₹45.5k"], ["Owner", "Asha"]].map(([k, v]) => <div key={k} className="rounded-md bg-[var(--surface)] p-2"><p className="text-[11px] text-[var(--muted)]">{k}</p><p className={cn(MONO, "text-[14px]")}>{v}</p></div>)}</div>
            <div><p className="mb-1.5 text-[11.5px] uppercase tracking-[0.06em] text-[var(--muted)]">Next best action</p><Btn kind="ai" className="w-full justify-start"><Phone size={13} />Call with the quote in 5 min</Btn></div>
            <div><p className="mb-1.5 text-[11.5px] uppercase tracking-[0.06em] text-[var(--muted)]">Timeline</p><ol className={cn(MONO, "space-y-1.5 text-[11.5px]")}>{GUEST.journey.filter(j => j.when).map(j => <li key={j.label} className={j.done ? "" : "text-[var(--warn)]"}><span className="text-[var(--muted)]">{j.when}</span> · {j.label}</li>)}</ol></div>
          </div>
        </aside>
      </div>
    </Shell>
  );
}

// ── leads ─────────────────────────────────────────────────────────────────────

function LeadsScreen(props: ScreenProps) {
  const ld = useLeads();
  return (
    <Shell {...props} actions={<><div className="hidden rounded-md border border-[var(--line)] p-0.5 text-[12px] md:flex">{(["list", "board"] as const).map(v => <button key={v} type="button" onClick={() => ld.setView(v === "list" ? "board" : "list")} className={cn("h-7 rounded px-2.5 capitalize", (v === "list") === (ld.view === "board") ? "bg-[var(--raised)] text-[var(--ink)]" : "text-[var(--muted)]")}>{v}</button>)}</div><Btn kind="primary"><Plus size={14} /><span className="max-sm:hidden">Lead</span></Btn></>}>
      <div className="p-3 md:p-5">
        <div className={cn(MONO, "scroll mb-3 flex gap-2 overflow-x-auto text-[12px]")}>
          {[{ key: "all", label: "all", count: 55 }, ...STAGES].map(s => <button key={s.key} type="button" onClick={() => ld.setStage(s.key)} className={cn("h-8 shrink-0 rounded-md border px-2.5 lowercase max-sm:h-10", ld.stage === s.key ? "border-[var(--accent)] bg-[var(--info-bg)] text-[var(--accent)]" : "border-[var(--line)] text-[var(--muted)]")}>{s.label} {s.count}</button>)}
        </div>
        {ld.view === "board" ? (
          <div className="hidden overflow-x-auto rounded-lg border border-[var(--line)] bg-[var(--surface)] md:block">
            <table className="w-full min-w-[860px] text-[13px]">
              <thead className="border-b border-[var(--line)] text-left text-[11.5px] uppercase tracking-[0.06em] text-[var(--muted)]"><tr>{["Lead", "Stage", "Dates", "Value", "Win chance", "Owner", "Next best action"].map(h => <th key={h} className="px-3.5 py-2.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-[var(--line)]">{ld.list.map(l => (
                <tr key={l.id} className="hover:bg-[var(--raised)]">
                  <td className="px-3.5 py-2.5"><p className="font-medium">{l.name}</p><Ch channel={l.channel} /></td>
                  <td className="px-3.5 text-[var(--muted)]">{STAGES.find(s => s.key === l.stage)?.label}</td>
                  <td className={cn(MONO, "px-3.5 text-[12px] text-[var(--muted)]")}>{l.dates ?? "—"}</td>
                  <td className={cn(MONO, "px-3.5")}>{l.value ? inrShort(l.value) : "—"}</td>
                  <td className="px-3.5"><Confidence value={SCORE[l.id]} /></td>
                  <td className="px-3.5">{l.owner?.split(" ")[0] ?? <span className="text-[var(--warn)]">none</span>}</td>
                  <td className="px-3.5"><span className={cn("inline-flex items-center gap-1.5", l.due === "now" ? "text-[var(--bad)]" : "")}>{l.due === "now" && <span className="size-1.5 rounded-full bg-[var(--bad)]" />}{l.next}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : (
          <div className="hidden gap-3 md:grid md:grid-cols-3 xl:grid-cols-5">
            {STAGES.map(s => (
              <Panel key={s.key} title={s.label} meta={<span className={MONO}>{s.count}</span>}>
                <div className="space-y-2 p-2">{LEADS.filter(l => l.stage === s.key).map(l => <div key={l.id} className="rounded-md border border-[var(--line)] bg-[var(--bg)] p-2.5"><p className="truncate text-[13px] font-medium">{l.name}</p><div className="mt-1 flex items-center justify-between"><Confidence value={SCORE[l.id]} /><span className={cn(MONO, "text-[12px]")}>{l.value ? inrShort(l.value) : ""}</span></div><p className={cn("mt-1 truncate text-[12px]", l.due === "now" ? "text-[var(--bad)]" : "text-[var(--muted)]")}>{l.next}</p></div>)}</div>
              </Panel>
            ))}
          </div>
        )}
        <ul className="space-y-2 md:hidden">{ld.list.map(l => (
          <li key={l.id} className="rounded-lg border border-[var(--line)] bg-[var(--surface)] p-3">
            <div className="flex items-center gap-2"><p className="truncate text-[14px] font-semibold">{l.name}</p><Ch channel={l.channel} label={false} /><span className={cn(MONO, "ml-auto text-[13px]")}>{l.value ? inrShort(l.value) : ""}</span></div>
            <div className="mt-1.5 flex items-center justify-between"><span className="text-[12px] text-[var(--muted)]">{STAGES.find(s => s.key === l.stage)?.label} · {l.dates ?? "no dates"}</span><Confidence value={SCORE[l.id]} /></div>
            <p className={cn("mt-1.5 flex items-center gap-1.5 text-[12.5px]", l.due === "now" ? "text-[var(--bad)]" : "text-[var(--ai)]")}><Sparkles size={12} />{l.next}</p>
          </li>
        ))}</ul>
      </div>
    </Shell>
  );
}

// ── calendar ──────────────────────────────────────────────────────────────────

const BAR: Record<ResKind, string> = {
  direct: "bg-[var(--accent)] text-[var(--on-accent)]",
  ota: "bg-[var(--info-bg)] text-[var(--accent)] border border-[var(--accent)]/60",
  hold: "border border-dashed border-[var(--ai)] bg-[var(--ai-bg)] text-[var(--ai)]",
  blocked: "bg-[var(--raised)] text-[var(--muted)] border border-[var(--line-strong)]",
  maintenance: "bg-[var(--bad-bg)] text-[var(--bad)] border border-[var(--bad)]/60",
};
const BAR_LABEL: Record<ResKind, string> = { direct: "Direct", ota: "Airbnb", hold: "AI hold", blocked: "Blocked", maintenance: "Maintenance" };

function CalendarScreen(props: ScreenProps) {
  const cal = useCalendar();
  const days = Array.from({ length: CAL_DAYS }, (_, i) => i);
  const occ = days.map(i => cal.onDay(i).filter(r => r.kind !== "blocked" && r.kind !== "maintenance").length / 2);
  return (
    <Shell {...props} actions={<><Btn className="w-8 px-0 max-sm:w-10"><ChevronLeft size={15} /></Btn><span className={cn(MONO, "text-[12px] max-sm:hidden")}>12/10 – 01/11</span><Btn className="w-8 px-0 max-sm:w-10"><ChevronRight size={15} /></Btn></>}>
      <div className="space-y-3 p-3 md:p-5">
        <p className="flex items-start gap-2 rounded-lg border border-[var(--ai)]/40 bg-[var(--ai-bg)] px-3 py-2 text-[13px]"><Sparkles size={14} className="mt-0.5 shrink-0 text-[var(--ai)]" /><span><span className="font-semibold">Ratha 2 is free 19–20 Oct.</span> <span className="text-[var(--muted)]">3 open leads asked for those dates.</span></span></p>
        <div className="hidden overflow-x-auto rounded-lg border border-[var(--line)] bg-[var(--surface)] md:block">
          <div className="min-w-[880px]">
            <div className="grid grid-cols-[110px_1fr] border-b border-[var(--line)]">
              <div className="px-3 py-2 text-[11px] uppercase tracking-[0.06em] text-[var(--muted)]">Occupancy</div>
              <div className="grid" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>{days.map(i => { const d = dayLabel(i); return <div key={i} className={cn("border-l border-[var(--line)] py-1 text-center", i === CAL_TODAY_INDEX && "bg-[var(--info-bg)]")}><p className={cn(MONO, "text-[10px] text-[var(--muted)]")}>{d.dow.slice(0, 2)}</p><p className={cn(MONO, "text-[12.5px]", i === CAL_TODAY_INDEX && "text-[var(--accent)]")}>{d.day}</p><span className="mx-auto mt-1 block h-1 w-4/5 rounded-full bg-[var(--raised)]"><span className="block h-full rounded-full bg-[var(--ok)]" style={{ width: `${occ[i] * 100}%` }} /></span></div>; })}</div>
            </div>
            {PROPERTIES.map(p => (
              <div key={p.id} className="grid grid-cols-[110px_1fr] border-b border-[var(--line)] last:border-b-0">
                <div className="px-3 py-3"><p className="text-[13.5px] font-semibold">{p.name}</p><p className="text-[11.5px] text-[var(--muted)]">{p.note}</p></div>
                <div className="relative h-[60px]">
                  <div className="absolute inset-0 grid" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>{days.map(i => <div key={i} className={cn("border-l border-[var(--line)]", i === CAL_TODAY_INDEX && "bg-[var(--info-bg)]/60")} />)}</div>
                  {RESERVATIONS.filter(r => r.property === p.id).map(r => <button key={r.id} type="button" onClick={() => cal.setSelected(r.id)} style={barStyle(r)} className={cn("press absolute top-2.5 flex h-10 items-center overflow-hidden rounded-md px-2 text-left text-[12px] font-medium", BAR[r.kind], cal.selected === r.id && "ring-2 ring-[var(--ink)]")}><span className="truncate">{r.guest}</span></button>)}
                </div>
              </div>
            ))}
          </div>
        </div>
        {cal.res && (
          <div className="hidden flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-[var(--line)] bg-[var(--surface)] px-4 py-3 md:flex">
            <span className={cn("rounded px-1.5 py-0.5 text-[11.5px]", BAR[cal.res.kind])}>{BAR_LABEL[cal.res.kind]}</span>
            <p className="text-[15px] font-semibold">{cal.res.guest}</p>
            <p className={cn(MONO, "text-[12px] text-[var(--muted)]")}>{PROPERTIES.find(p => p.id === cal.res!.property)?.name} · {dayLabel(cal.res.start).day}–{dayLabel(cal.res.end).day}/{dayLabel(cal.res.end).month} · {cal.res.end - cal.res.start}n</p>
            {cal.res.amount != null && <p className={cn(MONO, "text-[12.5px]")}>{inr(cal.res.amount)} · due <span className="text-[var(--warn)]">{inr(cal.res.amount - (cal.res.paid ?? 0))}</span></p>}
            <Btn kind="primary" className="ml-auto">Open</Btn>
          </div>
        )}
        <div className="md:hidden">
          <div className="grid grid-cols-7 gap-1">
            {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <div key={i} className={cn(MONO, "text-center text-[10.5px] text-[var(--muted)]")}>{d}</div>)}
            {days.map(i => (
              <button key={i} type="button" onClick={() => cal.setDay(i)} aria-pressed={cal.day === i} className={cn("flex h-14 flex-col items-center justify-between rounded-md border py-1.5", cal.day === i ? "border-[var(--accent)] bg-[var(--info-bg)]" : "border-[var(--line)] bg-[var(--surface)]")}>
                <span className={cn(MONO, "text-[13px]", i === CAL_TODAY_INDEX && "text-[var(--accent)]")}>{dayLabel(i).day}</span>
                <span className="h-1 w-3/4 rounded-full bg-[var(--raised)]"><span className={cn("block h-full rounded-full", cal.onDay(i).some(r => r.kind === "maintenance") ? "bg-[var(--bad)]" : "bg-[var(--ok)]")} style={{ width: `${Math.max(cal.onDay(i).some(r => r.kind === "maintenance") ? 50 : 0, occ[i] * 100)}%` }} /></span>
              </button>
            ))}
          </div>
          <p className={cn(MONO, "mb-2 mt-4 text-[12px] uppercase text-[var(--muted)]")}>{dayLabel(cal.day).dow} {dayLabel(cal.day).day}/{dayLabel(cal.day).month}</p>
          <ul className="space-y-2">
            {cal.onDay(cal.day).length === 0 && <li className="rounded-lg border border-dashed border-[var(--line-strong)] p-4 text-center text-[13px] text-[var(--ok)]">Both caravans free</li>}
            {cal.onDay(cal.day).map(r => <li key={r.id} className="flex items-center gap-3 rounded-lg border border-[var(--line)] bg-[var(--surface)] p-3"><span className={cn("rounded px-1.5 py-0.5 text-[10.5px]", BAR[r.kind])}>{BAR_LABEL[r.kind]}</span><div className="min-w-0 flex-1"><p className="truncate text-[13.5px] font-medium">{r.guest}</p><p className={cn(MONO, "text-[11px] text-[var(--muted)]")}>{PROPERTIES.find(p => p.id === r.property)?.name} · {dayLabel(r.start).day}–{dayLabel(r.end).day}</p></div>{r.amount != null && <span className={cn(MONO, "text-[12.5px]")}>{inrShort(r.amount)}</span>}</li>)}
          </ul>
        </div>
      </div>
    </Shell>
  );
}

export default function Command(props: ScreenProps) {
  if (props.screen === "inbox") return <InboxScreen {...props} />;
  if (props.screen === "leads") return <LeadsScreen {...props} />;
  if (props.screen === "calendar") return <CalendarScreen {...props} />;
  return <Home {...props} />;
}
