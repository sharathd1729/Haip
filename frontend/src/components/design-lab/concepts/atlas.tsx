"use client";
// A · Field Atlas: Indian road-atlas cartography. Map-paper ground, forest-ink sidebar, ochre actions, river blue info,
// laterite red for urgency. Contour hairlines instead of boxes; condensed map-label headings. Signature: the work queue
// and each guest's story are drawn as a route with stops; bookings are road segments with milestone dots.
import {
  ArrowDownRight, ArrowLeft, ArrowRight, ArrowUpRight, CalendarDays, Camera, ChartColumn, ChevronLeft, ChevronRight, Globe, House, Inbox, Megaphone, Menu,
  MessageCircle, Paperclip, Phone, Plus, Search, Send, Settings, SlidersHorizontal, Sparkles, SquareKanban,
} from "lucide-react";
import { Fragment, type ComponentType } from "react";
import { cn } from "@/lib/utils";
import {
  AGENTS, AI_DRAFT, ALERTS, CAL_DAYS, CAL_TODAY_INDEX, CHANNEL_LABEL, GUEST, KPIS, LEADS, PERIOD_LABEL, PROPERTIES, QUEUE,
  RESERVATIONS, SOURCES, STAGES, THREAD, TODAY_LABEL, TREND, TREND_DAYS, dayLabel, inr, inrShort, type Channel, type Lead, type ResKind,
} from "../data";
import { barStyle, trendPath, useCalendar, useInbox, useLeads, type ScreenProps } from "../hooks";
import type { Screen } from "../concepts";

type Icon = ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
const SW = 1.5;
const NAV: { id: string; label: string; icon: Icon; count?: number }[] = [
  { id: "home", label: "Today", icon: House },
  { id: "inbox", label: "Inbox", icon: Inbox, count: 4 },
  { id: "leads", label: "Leads", icon: SquareKanban, count: 5 },
  { id: "calendar", label: "Calendar", icon: CalendarDays },
  { id: "calls", label: "Calls", icon: Phone, count: 3 },
  { id: "campaigns", label: "Campaigns", icon: Megaphone },
  { id: "reports", label: "Reports", icon: ChartColumn },
  { id: "settings", label: "Settings", icon: Settings },
];
const SCREEN_IDS = ["home", "inbox", "leads", "calendar"];
const TITLES: Record<Screen, string> = { home: "Today", inbox: "Inbox", leads: "Leads 360", calendar: "Calendar" };

// Map-legend symbols for channels: shape and colour together, so the channel never depends on colour alone.
function ChannelMark({ channel, label = true }: { channel: Channel; label?: boolean }) {
  const glyph = {
    whatsapp: <span className="size-2.5 rounded-[2px] bg-[var(--ok)]" />,
    instagram: <span className="size-2.5 rounded-full bg-[var(--accent)]" />,
    call: <span className="size-0 border-x-[5px] border-b-[9px] border-x-transparent border-b-[var(--info)]" />,
    website: <span className="size-2.5 rotate-45 border-[1.5px] border-[var(--muted)]" />,
  }[channel];
  return <span className="inline-flex items-center gap-1.5 text-[12.5px] text-[var(--muted)]">{glyph}{label && CHANNEL_LABEL[channel]}</span>;
}

function Label({ children, className }: { children: React.ReactNode; className?: string }) {
  return <h2 className={cn("font-[family-name:var(--font-label)] text-[15px] font-semibold uppercase tracking-[0.06em] text-[var(--ink)]", className)}>{children}</h2>;
}

function Btn({ children, kind = "line", className, onClick }: { children: React.ReactNode; kind?: "solid" | "line" | "quiet"; className?: string; onClick?: () => void }) {
  const k = {
    solid: "bg-[var(--accent)] text-[var(--on-accent)] hover:bg-[var(--accent-hover)]",
    line: "border border-[var(--field)] text-[var(--ink)] hover:bg-[var(--raised)]",
    quiet: "text-[var(--accent)] hover:bg-[var(--raised)] underline-offset-4 hover:underline",
  };
  return <button type="button" onClick={onClick} className={cn("press inline-flex h-9 items-center justify-center gap-1.5 rounded-[3px] px-3 text-[13.5px] font-semibold max-sm:h-11", k[kind], className)}>{children}</button>;
}

function Tone({ tone, children }: { tone: "ok" | "warn" | "bad" | "info"; children: React.ReactNode }) {
  const cls = { ok: "bg-[var(--ok-bg)] text-[var(--ok)]", warn: "bg-[var(--warn-bg)] text-[var(--warn)]", bad: "bg-[var(--bad-bg)] text-[var(--bad)]", info: "bg-[var(--info-bg)] text-[var(--info)]" }[tone];
  return <span className={cn("inline-flex items-center gap-1 rounded-[2px] px-1.5 py-px font-[family-name:var(--font-label)] text-[12px] font-semibold uppercase tracking-[0.04em]", cls)}>{children}</span>;
}

// Faint contour lines for the shell's header only: a quiet map texture, never behind data.
function Contours({ className }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 240 80" className={className} preserveAspectRatio="none">
      {[0, 1, 2, 3, 4].map(i => <path key={i} d={`M-10 ${62 - i * 11} C 40 ${44 - i * 11}, 90 ${80 - i * 11}, 140 ${54 - i * 11} S 230 ${40 - i * 9}, 260 ${56 - i * 11}`} fill="none" stroke="currentColor" strokeWidth="0.8" />)}
    </svg>
  );
}

// ── shell ─────────────────────────────────────────────────────────────────────

function Shell({ screen, go, children, actions }: ScreenProps & { children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="lab-root lab-atlas flex">
      <aside className="sticky top-0 hidden h-dvh w-[72px] shrink-0 flex-col bg-[var(--chrome)] text-[var(--chrome-ink)] md:flex lg:w-[244px]">
        <div className="relative h-[88px] overflow-hidden px-4 pt-5">
          <Contours className="absolute inset-0 h-full w-full text-[var(--chrome-muted)] opacity-25" />
          <p className="relative font-[family-name:var(--font-label)] text-[22px] font-bold uppercase tracking-[0.08em] max-lg:text-center max-lg:text-[18px]">R<span className="max-lg:hidden">atha</span></p>
          <p className="relative text-[12px] text-[var(--chrome-muted)] max-lg:hidden">Caravan journeys · Bengaluru</p>
        </div>
        <nav aria-label="Main" className="scroll flex-1 overflow-y-auto py-2">
          {NAV.map(item => {
            const active = item.id === screen;
            return (
              <button key={item.id} type="button" title={item.label} aria-current={active ? "page" : undefined}
                onClick={() => SCREEN_IDS.includes(item.id) && go(item.id as Screen)}
                className={cn("relative flex h-11 w-full items-center gap-3 px-6 text-[14.5px] max-lg:justify-center max-lg:px-0", active ? "bg-[var(--chrome-active)] font-semibold" : "text-[var(--chrome-muted)] hover:text-[var(--chrome-ink)]")}>
                {active && <span aria-hidden className="absolute inset-y-1 left-0 w-[3px] bg-[var(--route)]" />}
                <item.icon size={19} strokeWidth={SW} />
                <span className="flex-1 text-left max-lg:hidden">{item.label}</span>
                {item.count != null && <span className="num font-[family-name:var(--font-label)] text-[13px] font-semibold text-[var(--chrome-ink)] max-lg:hidden">{item.count}</span>}
              </button>
            );
          })}
        </nav>
        <div className="flex items-center gap-3 border-t border-[var(--chrome-active)] px-4 py-3 max-lg:justify-center">
          <span className="flex size-8 items-center justify-center rounded-full border border-[var(--chrome-muted)] text-[12px] font-semibold">SD</span>
          <span className="text-[13px] max-lg:hidden">Sharath D<span className="block text-[11.5px] text-[var(--chrome-muted)]">Owner</span></span>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-[var(--line)] bg-[var(--bg)]">
          <div className="flex h-12 items-center gap-3 px-4 md:h-16 md:px-8">
            <button type="button" aria-label="Menu" className="-ml-2 flex size-10 items-center justify-center md:hidden"><Menu size={20} strokeWidth={SW} /></button>
            <div className="min-w-0">
              <h1 className="truncate font-[family-name:var(--font-label)] text-[19px] font-bold uppercase leading-none tracking-[0.05em] md:text-[24px]">{TITLES[screen]}</h1>
              <p className="mt-1 hidden text-[12.5px] text-[var(--muted)] md:block">{TODAY_LABEL} · {PERIOD_LABEL}</p>
            </div>
            <div className="ml-auto flex items-center gap-2">{actions}</div>
          </div>
        </header>
        <main className="min-w-0 flex-1 pb-20 md:pb-10">{children}</main>
      </div>

      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 flex h-16 border-t border-[var(--line-strong)] bg-[var(--surface)] pb-[env(safe-area-inset-bottom)] md:hidden">
        {NAV.slice(0, 4).map(item => {
          const active = item.id === screen;
          return (
            <button key={item.id} type="button" onClick={() => go(item.id as Screen)} className={cn("relative flex flex-1 flex-col items-center justify-center gap-1 text-[12px]", active ? "font-semibold text-[var(--ink)]" : "text-[var(--muted)]")}>
              {active && <span aria-hidden className="absolute top-0 h-[3px] w-10 bg-[var(--route)]" />}
              <item.icon size={21} strokeWidth={active ? 2 : SW} />{item.label}
              {item.count ? <span className="num absolute right-[calc(50%-22px)] top-2 min-w-4 rounded-full bg-[var(--bad)] px-1 text-[10px] font-bold leading-4 text-[var(--on-accent)]">{item.count}</span> : null}
            </button>
          );
        })}
        <button type="button" className="flex flex-1 flex-col items-center justify-center gap-1 text-[12px] text-[var(--muted)]"><Menu size={21} strokeWidth={SW} />More</button>
      </nav>
    </div>
  );
}

// ── home ──────────────────────────────────────────────────────────────────────

function Home(props: ScreenProps) {
  const t = trendPath(600, 120, 4);
  const total = SOURCES.reduce((s, x) => s + x.value, 0);
  const figures = [
    { k: KPIS.newLeads.label, v: String(KPIS.newLeads.value), d: KPIS.newLeads.change },
    { k: KPIS.bookings.label, v: String(KPIS.bookings.value), d: KPIS.bookings.change },
    { k: KPIS.bookedValue.label, v: inr(KPIS.bookedValue.value), d: KPIS.bookedValue.change },
    { k: KPIS.cash.label, v: inr(KPIS.cash.value), d: KPIS.cash.change },
    { k: KPIS.occupancy.label, v: `${KPIS.occupancy.value}%`, d: KPIS.occupancy.change },
    { k: KPIS.response.label, v: `${KPIS.response.value} min`, d: KPIS.response.change },
  ];
  return (
    <Shell {...props} actions={<><div className="hidden border border-[var(--field)] sm:flex">{["Today", "7 days", "Month"].map((p, i) => <button key={p} type="button" className={cn("h-9 px-3 font-[family-name:var(--font-label)] text-[13.5px] font-semibold uppercase tracking-[0.04em]", i === 1 ? "bg-[var(--ink)] text-[var(--surface)]" : "text-[var(--muted)]")}>{p}</button>)}</div><Btn kind="line"><SlidersHorizontal size={15} strokeWidth={SW} /><span className="max-sm:hidden">Filters</span></Btn></>}>
      <div className="mx-auto grid max-w-[1200px] gap-x-12 gap-y-8 px-4 py-6 md:px-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        {/* Signature: the queue as today's route. Each stop is something someone is waiting for. */}
        <section aria-labelledby="atlas-route">
          <Label className="mb-1">Today&apos;s route</Label>
          <p className="mb-4 text-[13px] text-[var(--muted)]">14 people waiting · 8 past their target time</p>
          <ol className="relative">
            <span aria-hidden className="absolute bottom-6 left-[11px] top-3 w-[2px] bg-[repeating-linear-gradient(to_bottom,var(--route)_0_8px,transparent_8px_13px)]" />
            {QUEUE.map(q => (
              <li key={q.kind} className="relative flex gap-4 pb-5 last:pb-0">
                <span className={cn("relative z-10 mt-1 flex size-6 shrink-0 items-center justify-center rounded-full border-2 bg-[var(--bg)]", q.urgency === "now" ? "border-[var(--bad)]" : q.urgency === "soon" ? "border-[var(--accent)]" : "border-[var(--ok)]")}>
                  <span className={cn("size-2 rounded-full", q.urgency === "now" ? "bg-[var(--bad)]" : q.urgency === "soon" ? "bg-[var(--accent)]" : "bg-[var(--ok)]")} />
                </span>
                <div className="min-w-0 flex-1 border-b border-[var(--line)] pb-4">
                  <div className="flex items-baseline gap-3">
                    <span className={cn("num font-[family-name:var(--font-label)] text-[30px] font-bold leading-none", q.urgency === "now" && "text-[var(--bad)]")}>{q.count}</span>
                    <span className="text-[14px] font-semibold leading-snug">{q.label}</span>
                  </div>
                  <div className="mt-1.5 flex items-center justify-between gap-2 text-[12.5px] text-[var(--muted)]">
                    <span>Oldest {q.oldest}</span>
                    <Btn kind="quiet" className="h-8 px-2">Go there</Btn>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <div className="min-w-0 space-y-8">
          <section aria-labelledby="atlas-legend">
            <div className="mb-3 flex items-baseline justify-between"><Label>Key figures</Label><span className="text-[12.5px] text-[var(--muted)]">{PERIOD_LABEL} vs the 7 before</span></div>
            <dl className="grid grid-cols-2 border-t border-[var(--ink)] sm:grid-cols-3">
              {figures.map((f, i) => (
                <div key={f.k} className={cn("border-b border-[var(--line)] py-3 pr-3", i % 2 === 1 && "max-sm:border-l max-sm:pl-3", i % 3 !== 0 && "sm:border-l sm:pl-4")}>
                  <dt className="text-[12.5px] text-[var(--muted)]">{f.k}</dt>
                  <dd className="num mt-0.5 font-[family-name:var(--font-label)] text-[24px] font-semibold leading-tight">{f.v}</dd>
                  <dd className={cn("flex items-center gap-0.5 text-[12px] font-semibold", f.d >= 0 ? "text-[var(--ok)]" : "text-[var(--bad)]")}>{f.d >= 0 ? <ArrowUpRight size={13} strokeWidth={2} /> : <ArrowDownRight size={13} strokeWidth={2} />}{Math.abs(f.d)}%</dd>
                </div>
              ))}
            </dl>
          </section>

          <section aria-labelledby="atlas-elev">
            <div className="mb-2 flex items-baseline justify-between"><Label>Booked value, 14 days</Label><span className="num text-[12.5px] text-[var(--muted)]">peak {inrShort(Math.max(...TREND))}</span></div>
            <svg viewBox="0 0 600 120" className="h-[120px] w-full" role="img" aria-label="Booked value per day, last 14 days">
              {[30, 60, 90].map(y => <line key={y} x1="0" x2="600" y1={y} y2={y} stroke="var(--line)" />)}
              <path d={t.area} fill="var(--accent)" opacity="0.12" />
              <path d={t.line} fill="none" stroke="var(--accent)" strokeWidth="1.75" />
              {t.points.map(([x, y], i) => i === t.points.length - 1 && <circle key={i} cx={x} cy={y} r="4.5" fill="var(--bg)" stroke="var(--accent)" strokeWidth="2" />)}
            </svg>
            <div className="flex justify-between font-[family-name:var(--font-label)] text-[12px] uppercase tracking-[0.04em] text-[var(--muted)]">{TREND_DAYS.filter((_, i) => i % 2 === 0).map(d => <span key={d}>{d}</span>)}</div>
          </section>

          <div className="grid gap-8 sm:grid-cols-2">
            <section aria-labelledby="atlas-src">
              <Label className="mb-3">Where leads came from</Label>
              <div className="flex h-3 overflow-hidden">{SOURCES.map((s, i) => <span key={s.label} className={["bg-[var(--accent)]", "bg-[var(--ok)]", "bg-[var(--info)]", "bg-[var(--muted)]"][i]} style={{ width: `${(s.value / total) * 100}%` }} />)}</div>
              <ul className="mt-3 space-y-1.5">{SOURCES.map(s => <li key={s.label} className="flex items-center justify-between text-[13.5px]"><ChannelMark channel={s.channel} /><span className="num font-semibold">{s.value}</span></li>)}</ul>
            </section>
            <section aria-labelledby="atlas-notes">
              <Label className="mb-3">Notes on the way</Label>
              <ul className="space-y-3">{ALERTS.map(a => <li key={a.text} className="text-[13.5px] leading-snug"><Tone tone={a.tone === "danger" ? "bad" : a.tone === "warning" ? "warn" : "info"}>{a.tone === "danger" ? "Urgent" : a.tone === "warning" ? "Due" : "AI"}</Tone><p className="mt-1">{a.text}</p><Btn kind="quiet" className="mt-0.5 h-8 px-0">{a.action}</Btn></li>)}</ul>
            </section>
          </div>
        </div>
      </div>
    </Shell>
  );
}

// ── inbox ─────────────────────────────────────────────────────────────────────

function Journey() {
  return (
    <ol className="relative mt-2">
      <span aria-hidden className="absolute bottom-3 left-[7px] top-2 w-[2px] bg-[var(--line-strong)]" />
      {GUEST.journey.map((j, i) => {
        const current = !j.done && (i === 0 || GUEST.journey[i - 1].done);
        return (
          <li key={j.label} className="relative flex gap-3 pb-3 last:pb-0">
            <span className={cn("relative z-10 mt-0.5 size-4 shrink-0 rounded-full border-2", j.done ? "border-[var(--ok)] bg-[var(--ok)]" : current ? "border-[var(--route)] bg-[var(--bg)]" : "border-[var(--line-strong)] bg-[var(--bg)]")} />
            <span className="text-[13px] leading-snug"><span className={cn(j.done ? "" : current ? "font-semibold text-[var(--accent)]" : "text-[var(--muted)]")}>{j.label}</span>{j.when && <span className="block text-[12px] text-[var(--muted)]">{j.when}</span>}</span>
          </li>
        );
      })}
    </ol>
  );
}

function InboxScreen(props: ScreenProps) {
  const ib = useInbox();
  const c = ib.conversation;
  return (
    <Shell {...props} actions={<Btn kind="solid"><Plus size={16} strokeWidth={2} /><span className="max-sm:hidden">New message</span></Btn>}>
      <div className="grid grid-cols-1 h-[calc(100dvh-48px-64px)] md:h-[calc(100dvh-64px)] md:grid-cols-[340px_1fr] xl:grid-cols-[340px_1fr_300px]">
        <section aria-label="Conversations" className={cn("flex min-h-0 min-w-0 flex-col border-r border-[var(--line)]", ib.open && "max-md:hidden")}>
          <div className="space-y-3 px-4 py-3">
            <label className="flex h-10 items-center gap-2 border-b-2 border-[var(--field)] max-sm:h-11"><Search size={16} strokeWidth={SW} className="text-[var(--muted)]" /><input placeholder="Search guests and messages" className="w-full bg-transparent text-[16px] outline-none sm:text-[14px]" /></label>
            <div className="flex gap-4 font-[family-name:var(--font-label)] text-[14px] font-semibold uppercase tracking-[0.04em]">{(["all", "waiting", "mine"] as const).map(f => <button key={f} type="button" onClick={() => ib.setFilter(f)} className={cn("h-9 border-b-2", ib.filter === f ? "border-[var(--route)] text-[var(--ink)]" : "border-transparent text-[var(--muted)]")}>{f === "waiting" ? "Needs reply" : f === "mine" ? "Mine" : "All"}</button>)}</div>
          </div>
          <ul className="scroll min-h-0 flex-1 overflow-y-auto">
            {ib.list.map(conv => (
              <li key={conv.id}>
                <button type="button" onClick={() => ib.pick(conv.id)} className={cn("w-full border-t border-[var(--line)] px-4 py-3 text-left", conv.id === ib.selected ? "bg-[var(--surface)]" : "hover:bg-[var(--raised)]")}>
                  <span className="flex items-center gap-2"><span className={cn("truncate text-[14.5px]", conv.unread ? "font-bold" : "font-semibold")}>{conv.name}</span>{conv.unread > 0 && <span className="num rounded-full bg-[var(--accent)] px-1.5 text-[11px] font-bold leading-[18px] text-[var(--on-accent)]">{conv.unread}</span>}<span className="ml-auto text-[12px] text-[var(--muted)]">{conv.time}</span></span>
                  <span className="mt-1 block truncate text-[13px] text-[var(--muted)]">{conv.preview}</span>
                  <span className="mt-2 flex items-center gap-3"><ChannelMark channel={conv.channel} />{conv.waiting && <Tone tone={conv.hot ? "bad" : "warn"}>Waiting {conv.waiting}</Tone>}<span className="ml-auto text-[12px] text-[var(--muted)]">{conv.agent?.split(" ")[0] ?? "Unassigned"}</span></span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section aria-label="Conversation" className={cn("flex min-h-0 min-w-0 flex-col bg-[var(--surface)]", !ib.open && "max-md:hidden")}>
          <div className="flex h-16 items-center gap-3 border-b border-[var(--line)] px-3 md:px-6">
            <button type="button" onClick={ib.back} aria-label="Back to conversations" className="flex size-10 items-center justify-center md:hidden"><ArrowLeft size={19} /></button>
            <div className="min-w-0 flex-1"><p className="truncate font-[family-name:var(--font-label)] text-[18px] font-bold uppercase tracking-[0.04em]">{c.name}</p><p className="flex items-center gap-2 text-[12.5px] text-[var(--muted)]"><ChannelMark channel={c.channel} /> · {c.agent ?? "Unassigned"}</p></div>
            <Btn kind="line" className="max-sm:hidden"><Phone size={15} strokeWidth={SW} />Call</Btn>
            <select aria-label="Assign to" data-assign defaultValue={c.agent ?? ""} className="h-9 rounded-[3px] border border-[var(--field)] bg-[var(--surface)] px-2 text-[13.5px] max-lg:hidden"><option value="">Unassigned</option>{AGENTS.map(a => <option key={a.id}>{a.name}</option>)}</select>
          </div>
          <div className="scroll min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-5 md:px-8">
            {THREAD.map(m => m.from === "note" ? (
              <p key={m.id} className="mx-auto max-w-[520px] border-y border-dashed border-[var(--field)] py-2 text-center text-[13px] text-[var(--warn)]"><span className="font-semibold">{m.author}:</span> {m.text}</p>
            ) : (
              <div key={m.id} className={cn("flex", m.from === "guest" ? "justify-start" : "justify-end")}>
                <div className={cn("max-w-[80%] px-3.5 py-2.5 text-[14px] leading-relaxed", m.from === "guest" ? "rounded-[2px_12px_12px_12px] bg-[var(--raised)]" : "rounded-[12px_2px_12px_12px] bg-[var(--chrome)] text-[var(--chrome-ink)]")}>
                  <p>{m.text}</p><p className={cn("mt-1 text-[11.5px]", m.from === "guest" ? "text-[var(--muted)]" : "text-[var(--chrome-muted)]")}>{m.time}{m.author ? ` · ${m.author}` : ""}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="border-t border-[var(--line)] px-3 py-3 md:px-6">
            {ib.draft !== "sent" && (
              <div className="mb-3 border-l-2 border-[var(--route)] bg-[var(--bg)] px-3 py-2.5">
                <p className="flex items-center gap-1.5 font-[family-name:var(--font-label)] text-[13px] font-semibold uppercase tracking-[0.04em] text-[var(--accent)]"><Sparkles size={14} strokeWidth={SW} />Suggested reply</p>
                <p className="mt-1 text-[14px] leading-relaxed">{AI_DRAFT}</p>
                <div className="mt-2 flex gap-2"><Btn kind="solid" onClick={() => ib.setDraft("sent")}>Send as is</Btn><Btn kind="line" onClick={() => ib.setDraft("edited")}>Edit first</Btn></div>
              </div>
            )}
            <div className="flex items-end gap-2">
              <button type="button" aria-label="Attach" className="flex size-11 items-center justify-center text-[var(--muted)]"><Paperclip size={18} strokeWidth={SW} /></button>
              <textarea rows={1} placeholder="Write a reply…" className="min-h-11 flex-1 resize-none border-b-2 border-[var(--field)] bg-transparent px-1 py-2.5 text-[16px] outline-none focus:border-[var(--accent)] sm:text-[14px]" />
              <Btn kind="solid" className="h-11 w-11 px-0"><Send size={17} strokeWidth={SW} /></Btn>
            </div>
          </div>
        </section>

        <aside aria-label="Guest" className="scroll hidden min-h-0 overflow-y-auto border-l border-[var(--line)] px-5 py-5 xl:block">
          <p className="font-[family-name:var(--font-label)] text-[20px] font-bold uppercase tracking-[0.04em]">{GUEST.name}</p>
          <p className="num text-[13px] text-[var(--muted)]">{GUEST.phone} · {GUEST.city}</p>
          <dl className="mt-4 grid grid-cols-[84px_1fr] gap-y-2 border-t border-[var(--ink)] pt-3 text-[13px]">
            {[["Stage", GUEST.stage], ["Owner", GUEST.owner], ["Dates", GUEST.trip.dates], ["Party", GUEST.trip.party], ["Route", GUEST.trip.route], ["Estimate", GUEST.value]].map(([k, v]) => <Fragment key={k}><dt className="text-[var(--muted)]">{k}</dt><dd className="font-semibold">{v}</dd></Fragment>)}
          </dl>
          <Label className="mb-1 mt-6 text-[14px]">The journey so far</Label>
          <Journey />
        </aside>
      </div>
    </Shell>
  );
}

// ── leads ─────────────────────────────────────────────────────────────────────

const PRI = { hot: { t: "bad", l: "Hot" }, warm: { t: "warn", l: "Warm" }, cold: { t: "info", l: "Cold" } } as const;

function LeadCard({ l }: { l: Lead }) {
  return (
    <article className="border border-[var(--line)] bg-[var(--surface)] p-3 hover:border-[var(--field)]">
      <div className="flex items-start gap-2">
        <h3 className="min-w-0 flex-1 truncate text-[14.5px] font-semibold">{l.name}</h3>
        <Tone tone={PRI[l.priority].t}>{PRI[l.priority].l}</Tone>
      </div>
      <p className="mt-1 text-[13px] text-[var(--muted)]">{[l.dates, l.party].filter(Boolean).join(" · ") || "No dates yet"}</p>
      <div className="mt-2 flex items-center justify-between"><ChannelMark channel={l.channel} />{l.value ? <span className="num font-[family-name:var(--font-label)] text-[16px] font-semibold">{inrShort(l.value)}</span> : null}</div>
      <p className={cn("mt-2 flex items-center gap-1.5 border-t border-dashed border-[var(--line-strong)] pt-2 text-[13px]", l.due === "now" ? "font-semibold text-[var(--bad)]" : "")}><ArrowRight size={13} strokeWidth={2} className="shrink-0" /><span className="min-w-0 flex-1 truncate">{l.next}</span><span className="shrink-0 font-normal text-[var(--muted)]">{l.owner?.split(" ")[0] ?? "No owner"}</span></p>
    </article>
  );
}

function LeadsScreen(props: ScreenProps) {
  const ld = useLeads();
  return (
    <Shell {...props} actions={<><div className="hidden border border-[var(--field)] md:flex">{(["board", "list"] as const).map(v => <button key={v} type="button" onClick={() => ld.setView(v)} className={cn("h-9 px-3 font-[family-name:var(--font-label)] text-[13.5px] font-semibold uppercase tracking-[0.04em]", ld.view === v ? "bg-[var(--ink)] text-[var(--surface)]" : "text-[var(--muted)]")}>{v}</button>)}</div><Btn kind="solid"><Plus size={16} /><span className="max-sm:hidden">Add lead</span></Btn></>}>
      <div className="px-4 py-5 md:px-8">
        {/* Stage legend doubles as the filter. */}
        <div className="scroll -mx-4 mb-5 flex gap-0 overflow-x-auto border-b border-[var(--line)] px-4 md:mx-0 md:px-0">
          {[{ key: "all", label: "All", count: 55 }, ...STAGES].map(s => (
            <button key={s.key} type="button" onClick={() => ld.setStage(s.key)} className={cn("h-11 shrink-0 border-b-2 px-3 font-[family-name:var(--font-label)] text-[14px] font-semibold uppercase tracking-[0.04em]", ld.stage === s.key ? "border-[var(--route)] text-[var(--ink)]" : "border-transparent text-[var(--muted)]")}>{s.label} <span className="num ml-1 font-normal">{s.count}</span></button>
          ))}
        </div>
        {ld.view === "board" ? (
          <>
            <div className="hidden gap-5 md:grid md:grid-cols-3 xl:grid-cols-5">
              {STAGES.map(s => (
                <section key={s.key} aria-label={s.label} className="min-w-0">
                  <div className="mb-3 border-t-2 border-[var(--ink)] pt-2"><Label className="text-[14px]">{s.label}</Label><p className="num text-[12.5px] text-[var(--muted)]">{s.count} leads{s.value && ` · ${s.value}`}</p></div>
                  <div className="space-y-2">{LEADS.filter(l => l.stage === s.key).map(l => <LeadCard key={l.id} l={l} />)}</div>
                </section>
              ))}
            </div>
            <div className="space-y-2 md:hidden">{ld.list.map(l => <LeadCard key={l.id} l={l} />)}</div>
          </>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-t-2 border-[var(--ink)] text-[13.5px]">
              <thead><tr className="text-left font-[family-name:var(--font-label)] text-[13px] uppercase tracking-[0.05em] text-[var(--muted)]">{["Guest", "Stage", "Dates", "Value", "Owner", "Next stop"].map(h => <th key={h} className="border-b border-[var(--line-strong)] py-2.5 pr-4 font-semibold">{h}</th>)}</tr></thead>
              <tbody>{ld.list.map(l => (
                <tr key={l.id} className="border-b border-[var(--line)] hover:bg-[var(--surface)]"><td className="py-3 pr-4 font-semibold">{l.name}</td><td className="pr-4">{STAGES.find(s => s.key === l.stage)?.label}</td><td className="pr-4 text-[var(--muted)]">{l.dates ?? "—"}</td><td className="num pr-4">{l.value ? inr(l.value) : "—"}</td><td className="pr-4">{l.owner ?? <span className="text-[var(--warn)]">No owner</span>}</td><td className={cn("pr-4", l.due === "now" && "font-semibold text-[var(--bad)]")}>{l.next}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </Shell>
  );
}

// ── calendar ──────────────────────────────────────────────────────────────────

const ROAD: Record<ResKind, { line: string; dot: string; label: string }> = {
  direct: { line: "bg-[var(--ok)]", dot: "border-[var(--ok)]", label: "Direct" },
  ota: { line: "bg-[var(--info)]", dot: "border-[var(--info)]", label: "Airbnb" },
  hold: { line: "bg-[repeating-linear-gradient(90deg,var(--route)_0_10px,transparent_10px_16px)]", dot: "border-[var(--route)]", label: "On hold" },
  blocked: { line: "bg-[repeating-linear-gradient(45deg,var(--line-strong)_0_4px,transparent_4px_8px)]", dot: "border-[var(--line-strong)]", label: "Blocked" },
  maintenance: { line: "bg-[var(--bad)]", dot: "border-[var(--bad)]", label: "Maintenance" },
};

function CalendarScreen(props: ScreenProps) {
  const cal = useCalendar();
  const days = Array.from({ length: CAL_DAYS }, (_, i) => i);
  return (
    <Shell {...props} actions={<><Btn kind="line" className="w-9 px-0 max-sm:w-11"><ChevronLeft size={16} /></Btn><span className="font-[family-name:var(--font-label)] text-[14px] font-semibold uppercase tracking-[0.04em]">12 Oct – 1 Nov</span><Btn kind="line" className="w-9 px-0 max-sm:w-11"><ChevronRight size={16} /></Btn></>}>
      <div className="px-4 py-5 md:px-8">
        <ul className="mb-4 flex flex-wrap gap-x-5 gap-y-1.5 text-[12.5px] text-[var(--muted)]">{(Object.keys(ROAD) as ResKind[]).map(k => <li key={k} className="flex items-center gap-2"><span className={cn("h-[5px] w-6", ROAD[k].line)} />{ROAD[k].label}</li>)}</ul>

        <div className="hidden gap-6 md:flex">
          <div className="min-w-0 flex-1 overflow-x-auto">
            <div className="min-w-[820px]">
              <div className="grid grid-cols-[110px_1fr]">
                <div />
                <div className="grid border-b border-[var(--ink)]" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>
                  {days.map(i => { const d = dayLabel(i); return <div key={i} className="pb-1.5 text-center"><p className="font-[family-name:var(--font-label)] text-[11.5px] uppercase text-[var(--muted)]">{d.dow.slice(0, 2)}</p><p className={cn("num font-[family-name:var(--font-label)] text-[15px] font-semibold", i === CAL_TODAY_INDEX && "text-[var(--accent)]")}>{d.day}</p></div>; })}
                </div>
              </div>
              {PROPERTIES.map(p => (
                <div key={p.id} className="grid grid-cols-[110px_1fr] border-b border-[var(--line)]">
                  <div className="py-4"><p className="font-[family-name:var(--font-label)] text-[16px] font-bold uppercase tracking-[0.04em]">{p.name}</p><p className="text-[12px] text-[var(--muted)]">{p.note}</p></div>
                  <div className="relative h-[84px]">
                    <div className="absolute inset-0 grid" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>{days.map(i => <div key={i} className={cn("border-l border-dotted border-[var(--line)]", i === CAL_TODAY_INDEX && "bg-[var(--accent)]/10")} />)}</div>
                    {RESERVATIONS.filter(r => r.property === p.id).map(r => (
                      <button key={r.id} type="button" onClick={() => cal.setSelected(r.id)} style={barStyle(r)} className={cn("press group absolute top-4 h-14 text-left", cal.selected === r.id && "z-10")}>
                        <span className={cn("block truncate px-1 text-[12.5px] font-semibold", cal.selected === r.id ? "text-[var(--accent)]" : "")}>{r.guest}</span>
                        <span className="relative mt-1.5 block h-[5px]">
                          <span className={cn("absolute inset-x-0 top-0 h-[5px]", ROAD[r.kind].line)} />
                          <span className={cn("absolute -left-1 -top-[4px] size-[13px] rounded-full border-[3px] bg-[var(--bg)]", ROAD[r.kind].dot)} />
                          <span className={cn("absolute -right-1 -top-[4px] size-[13px] rounded-full border-[3px] bg-[var(--bg)]", ROAD[r.kind].dot)} />
                        </span>
                        <span className="mt-1.5 block truncate px-1 text-[11.5px] text-[var(--muted)]">{r.route ?? r.status}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
          {cal.res && (
            <aside aria-label="Reservation" className="w-[272px] shrink-0 border-t-2 border-[var(--ink)] pt-3 max-lg:hidden">
              <p className="font-[family-name:var(--font-label)] text-[13px] font-semibold uppercase tracking-[0.05em] text-[var(--muted)]">{ROAD[cal.res.kind].label} · {cal.res.status}</p>
              <p className="mt-1 font-[family-name:var(--font-label)] text-[24px] font-bold uppercase leading-tight tracking-[0.03em]">{cal.res.guest}</p>
              <p className="text-[13px] text-[var(--muted)]">{PROPERTIES.find(p => p.id === cal.res!.property)?.name} · {dayLabel(cal.res.start).day}–{dayLabel(cal.res.end).day} {dayLabel(cal.res.end).month} · {cal.res.end - cal.res.start} nights</p>
              {cal.res.amount != null && (
                <dl className="mt-4 grid grid-cols-2 gap-y-2 text-[13.5px]">
                  {[["Party", cal.res.party], ["Route", cal.res.route], ["Source", cal.res.source], ["Total", inr(cal.res.amount)], ["Paid", inr(cal.res.paid ?? 0)], ["Balance", inr(cal.res.amount - (cal.res.paid ?? 0))]].map(([k, v]) => <div key={k}><dt className="text-[12px] text-[var(--muted)]">{k}</dt><dd className="num font-semibold">{v}</dd></div>)}
                </dl>
              )}
              <Btn kind="solid" className="mt-5 w-full">Open booking</Btn>
            </aside>
          )}
        </div>

        <div className="md:hidden">
          <div className="grid grid-cols-7 border-t-2 border-[var(--ink)]">
            {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <div key={i} className="py-1.5 text-center font-[family-name:var(--font-label)] text-[12px] uppercase text-[var(--muted)]">{d}</div>)}
            {days.map(i => {
              const stays = cal.onDay(i);
              return (
                <button key={i} type="button" onClick={() => cal.setDay(i)} aria-pressed={cal.day === i} className={cn("flex h-[60px] flex-col items-center border-t border-[var(--line)] pt-1.5", cal.day === i && "bg-[var(--surface)]")}>
                  <span className={cn("num font-[family-name:var(--font-label)] text-[16px] font-semibold", i === CAL_TODAY_INDEX && "text-[var(--accent)] underline decoration-2 underline-offset-4")}>{dayLabel(i).day}</span>
                  <span className="mt-auto mb-1.5 flex w-full flex-col gap-0.5 px-0.5">{stays.map(r => <span key={r.id} className={cn("h-[4px] w-full", ROAD[r.kind].line)} />)}</span>
                </button>
              );
            })}
          </div>
          <Label className="mb-2 mt-5 text-[14px]">{dayLabel(cal.day).dow} {dayLabel(cal.day).day} {dayLabel(cal.day).month}</Label>
          <ul className="border-t border-[var(--ink)]">
            {cal.onDay(cal.day).length === 0 && <li className="py-4 text-[13.5px] text-[var(--muted)]">Both caravans are free.</li>}
            {cal.onDay(cal.day).map(r => (
              <li key={r.id} className="flex items-center gap-3 border-b border-[var(--line)] py-3">
                <span className={cn("h-[5px] w-6 shrink-0", ROAD[r.kind].line)} />
                <div className="min-w-0 flex-1"><p className="truncate text-[14px] font-semibold">{r.guest}</p><p className="text-[12.5px] text-[var(--muted)]">{PROPERTIES.find(p => p.id === r.property)?.name} · {dayLabel(r.start).day}–{dayLabel(r.end).day} {dayLabel(r.end).month} · {ROAD[r.kind].label}</p></div>
                {r.amount != null && <span className="num font-[family-name:var(--font-label)] text-[15px] font-semibold">{inrShort(r.amount)}</span>}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Shell>
  );
}

export default function Atlas(props: ScreenProps) {
  if (props.screen === "inbox") return <InboxScreen {...props} />;
  if (props.screen === "leads") return <LeadsScreen {...props} />;
  if (props.screen === "calendar") return <CalendarScreen {...props} />;
  return <Home {...props} />;
}
