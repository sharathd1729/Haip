"use client";
// D · Calm SaaS: the category standard played straight. Zinc neutrals, one teal accent, hairline borders, dense rows,
// a command bar, Geist with mono figures. Phone: top bar + bottom tabs; tablet: icon sidebar; desktop: full sidebar.
import {
  ArrowLeft, ArrowUpRight, ArrowDownRight, CalendarDays, Camera, ChartColumn, ChevronLeft, ChevronRight, Command, Globe,
  House, Inbox, LayoutGrid, List, Megaphone, MessageCircle, MoreHorizontal, Paperclip, Phone, Plus, Search, Send, Settings,
  SlidersHorizontal, Sparkles, SquareKanban, StickyNote,
} from "lucide-react";
import type { ComponentType } from "react";
import { cn } from "@/lib/utils";
import {
  AGENTS, AI_DRAFT, ALERTS, CAL_DAYS, CAL_TODAY_INDEX, CHANNEL_LABEL, GUEST, KPIS, LEADS, PERIOD_LABEL, PROPERTIES, QUEUE,
  RESERVATIONS, SOURCES, STAGES, THREAD, TREND, TREND_DAYS, dayLabel, inr, inrShort, type Channel, type Lead, type ResKind,
} from "../data";
import { barStyle, trendPath, useCalendar, useInbox, useLeads, type ScreenProps } from "../hooks";
import type { Screen } from "../concepts";

const NAV: { id: Screen | "calls" | "campaigns" | "reports" | "settings"; label: string; icon: ComponentType<{ size?: number; strokeWidth?: number }>; count?: number }[] = [
  { id: "home", label: "Home", icon: House },
  { id: "inbox", label: "Inbox", icon: Inbox, count: 4 },
  { id: "leads", label: "Leads", icon: SquareKanban, count: 5 },
  { id: "calendar", label: "Calendar", icon: CalendarDays },
  { id: "calls", label: "Calls", icon: Phone, count: 3 },
  { id: "campaigns", label: "Campaigns", icon: Megaphone },
  { id: "reports", label: "Reports", icon: ChartColumn },
  { id: "settings", label: "Settings", icon: Settings },
];
const TITLES: Record<Screen, string> = { home: "Home", inbox: "Inbox", leads: "Leads", calendar: "Calendar" };
const SW = 1.75;

const CHANNEL_ICON: Record<Channel, ComponentType<{ size?: number; strokeWidth?: number; className?: string }>> = {
  whatsapp: MessageCircle, instagram: Camera, call: Phone, website: Globe,
};

function ChannelTag({ channel }: { channel: Channel }) {
  const Icon = CHANNEL_ICON[channel];
  return (
    <span className="inline-flex items-center gap-1 text-[12px] text-[var(--muted)]">
      <Icon size={12} strokeWidth={SW} />{CHANNEL_LABEL[channel]}
    </span>
  );
}

function Badge({ tone, children }: { tone: "ok" | "warn" | "bad" | "info" | "neutral"; children: React.ReactNode }) {
  const map = {
    ok: "bg-[var(--ok-bg)] text-[var(--ok)]", warn: "bg-[var(--warn-bg)] text-[var(--warn)]", bad: "bg-[var(--bad-bg)] text-[var(--bad)]",
    info: "bg-[var(--info-bg)] text-[var(--info)]", neutral: "bg-[var(--raised)] text-[var(--muted)]",
  };
  return <span className={cn("inline-flex h-5 items-center rounded-md px-1.5 text-[11.5px] font-medium", map[tone])}>{children}</span>;
}

function Button({ children, variant = "secondary", className, onClick }: { children: React.ReactNode; variant?: "primary" | "secondary" | "ghost"; className?: string; onClick?: () => void }) {
  const v = {
    primary: "bg-[var(--accent)] text-[var(--on-accent)] hover:bg-[var(--accent-hover)]",
    secondary: "border border-[var(--line)] bg-[var(--surface)] text-[var(--ink)] hover:bg-[var(--raised)]",
    ghost: "text-[var(--muted)] hover:bg-[var(--raised)] hover:text-[var(--ink)]",
  };
  return <button type="button" onClick={onClick} className={cn("press inline-flex h-9 items-center justify-center gap-1.5 rounded-md px-3 text-[13px] font-medium max-sm:h-11", v[variant], className)}>{children}</button>;
}

function Avatar({ initials, size = 28 }: { initials: string; size?: number }) {
  return <span style={{ width: size, height: size }} className="inline-flex shrink-0 items-center justify-center rounded-full bg-[var(--raised)] text-[11px] font-semibold text-[var(--ink)]">{initials}</span>;
}

// ── shell ─────────────────────────────────────────────────────────────────────

function Shell({ screen, go, children, actions }: ScreenProps & { children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="lab-root lab-calm flex">
      <aside className="sticky top-0 hidden h-dvh w-[60px] shrink-0 flex-col border-r border-[var(--line)] bg-[var(--chrome)] md:flex lg:w-[232px]">
        <div className="flex h-14 items-center gap-2 px-3 lg:px-4">
          <span className="flex size-7 items-center justify-center rounded-md bg-[var(--accent)] text-[13px] font-bold text-[var(--on-accent)]">R</span>
          <span className="hidden text-[14px] font-semibold lg:block">Ratha</span>
        </div>
        <div className="px-2 pb-2 lg:px-3">
          <button type="button" className="press flex h-9 w-full items-center justify-center gap-2 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2 text-[13px] text-[var(--muted)] hover:border-[var(--field)] lg:justify-start">
            <Search size={15} strokeWidth={SW} /><span className="hidden flex-1 text-left lg:block">Search</span>
            <kbd className="hidden items-center gap-0.5 rounded border border-[var(--line)] px-1 font-[family-name:var(--font-mono)] text-[10.5px] lg:inline-flex"><Command size={10} />K</kbd>
          </button>
        </div>
        <nav aria-label="Main" className="scroll flex-1 space-y-0.5 overflow-y-auto px-2 lg:px-3">
          {NAV.map(item => {
            const active = item.id === screen;
            const isScreen = item.id === "home" || item.id === "inbox" || item.id === "leads" || item.id === "calendar";
            return (
              <button key={item.id} type="button" title={item.label} onClick={() => isScreen && go(item.id as Screen)}
                aria-current={active ? "page" : undefined}
                className={cn("press flex h-9 w-full items-center justify-center gap-2.5 rounded-md px-2 text-[13.5px] lg:justify-start",
                  active ? "bg-[var(--chrome-active)] font-medium text-[var(--ink)] shadow-[0_1px_2px_rgba(0,0,0,0.06)]" : "text-[var(--muted)] hover:bg-[var(--raised)] hover:text-[var(--ink)]")}>
                <item.icon size={17} strokeWidth={SW} />
                <span className="hidden flex-1 text-left lg:block">{item.label}</span>
                {item.count != null && <span className="num hidden text-[12px] text-[var(--muted)] lg:block">{item.count}</span>}
              </button>
            );
          })}
        </nav>
        <div className="flex items-center gap-2 border-t border-[var(--line)] p-3">
          <Avatar initials="SD" />
          <div className="hidden min-w-0 lg:block"><p className="truncate text-[13px] font-medium">Sharath D</p><p className="text-[11.5px] text-[var(--muted)]">Owner</p></div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-12 items-center gap-2 border-b border-[var(--line)] bg-[var(--bg)]/90 px-4 backdrop-blur-sm md:h-14 md:px-6">
          <h1 className="text-[15px] font-semibold md:text-[17px]">{TITLES[screen]}</h1>
          <span className="hidden text-[13px] text-[var(--muted)] sm:inline">· {PERIOD_LABEL}</span>
          <div className="ml-auto flex items-center gap-2">{actions}</div>
        </header>
        <main className="min-w-0 flex-1 pb-20 md:pb-8">{children}</main>
      </div>

      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 flex h-[60px] border-t border-[var(--line)] bg-[var(--surface)] pb-[env(safe-area-inset-bottom)] md:hidden">
        {NAV.slice(0, 4).concat([{ id: "settings", label: "More", icon: MoreHorizontal }]).map(item => {
          const active = item.id === screen;
          return (
            <button key={item.label} type="button" onClick={() => (item.id === "home" || item.id === "inbox" || item.id === "leads" || item.id === "calendar") && go(item.id)}
              className={cn("relative flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px]", active ? "font-semibold text-[var(--accent)]" : "text-[var(--muted)]")}>
              <item.icon size={20} strokeWidth={SW} />
              {item.label}
              {item.count ? <span className="num absolute right-[calc(50%-18px)] top-1.5 rounded-full bg-[var(--accent)] px-1 text-[10px] font-semibold leading-4 text-[var(--on-accent)]">{item.count}</span> : null}
            </button>
          );
        })}
      </nav>
    </div>
  );
}

// ── home ──────────────────────────────────────────────────────────────────────

function Kpi({ label, value, change, note }: { label: string; value: string; change: number; note: string }) {
  const up = change >= 0;
  return (
    <div className="bg-[var(--surface)] px-4 py-3.5">
      <p className="text-[12.5px] text-[var(--muted)]">{label}</p>
      <p className="num mt-1 font-[family-name:var(--font-mono)] text-[22px] font-medium tracking-tight">{value}</p>
      <p className="mt-0.5 flex items-center gap-1.5 text-[12px] text-[var(--muted)]">
        <span className={cn("inline-flex items-center", up ? "text-[var(--ok)]" : "text-[var(--bad)]")}>{up ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}{Math.abs(change)}%</span>
        {note}
      </p>
    </div>
  );
}

function Home(props: ScreenProps) {
  const t = trendPath(640, 140, 6);
  const max = Math.max(...SOURCES.map(s => s.value));
  return (
    <Shell {...props} actions={<><div className="hidden rounded-md border border-[var(--line)] bg-[var(--surface)] p-0.5 sm:flex">{["Today", "7 days", "Month"].map((p, i) => <button key={p} type="button" className={cn("h-8 rounded px-2.5 text-[12.5px]", i === 1 ? "bg-[var(--raised)] font-medium" : "text-[var(--muted)]")}>{p}</button>)}</div><Button variant="secondary"><SlidersHorizontal size={14} />Filters</Button></>}>
      <div className="mx-auto max-w-[1180px] space-y-6 px-4 py-5 md:px-6">
        <section aria-labelledby="calm-queue">
          <div className="mb-2 flex items-baseline justify-between"><h2 id="calm-queue" className="text-[14px] font-semibold">Needs you now</h2><span className="text-[12.5px] text-[var(--muted)]">14 people · 8 past target</span></div>
          <ul className="divide-y divide-[var(--line)] overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--surface)]">
            {QUEUE.map(q => (
              <li key={q.kind} className="flex items-center gap-3 px-4 py-3">
                <span className={cn("num w-7 font-[family-name:var(--font-mono)] text-[17px] font-medium", q.urgency === "now" ? "text-[var(--bad)]" : "text-[var(--ink)]")}>{q.count}</span>
                <div className="min-w-0 flex-1"><p className="truncate text-[13.5px] font-medium">{q.label}</p><p className="text-[12px] text-[var(--muted)]">oldest {q.oldest}</p></div>
                {q.urgency === "now" && <Badge tone="bad">Past target</Badge>}
                <Button variant="ghost" className="hidden sm:inline-flex">Open</Button>
              </li>
            ))}
          </ul>
        </section>

        <section aria-label="Key numbers" className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--line)] lg:grid-cols-3">
          <Kpi label={KPIS.newLeads.label} value={String(KPIS.newLeads.value)} change={KPIS.newLeads.change} note="vs prior 7d" />
          <Kpi label={KPIS.bookings.label} value={String(KPIS.bookings.value)} change={KPIS.bookings.change} note={KPIS.bookings.note} />
          <Kpi label={KPIS.bookedValue.label} value={inr(KPIS.bookedValue.value)} change={KPIS.bookedValue.change} note={KPIS.bookedValue.note} />
          <Kpi label={KPIS.cash.label} value={inr(KPIS.cash.value)} change={KPIS.cash.change} note="after refunds" />
          <Kpi label={KPIS.occupancy.label} value={`${KPIS.occupancy.value}%`} change={KPIS.occupancy.change} note="2 caravans" />
          <Kpi label={KPIS.response.label} value={`${KPIS.response.value}m`} change={KPIS.response.change} note="median" />
        </section>

        <div className="grid gap-6 lg:grid-cols-3">
          <section className="rounded-lg border border-[var(--line)] bg-[var(--surface)] p-4 lg:col-span-2" aria-labelledby="calm-trend">
            <div className="flex items-baseline justify-between"><h2 id="calm-trend" className="text-[14px] font-semibold">Booked value per day</h2><span className="text-[12px] text-[var(--muted)]">14 days, by booking date</span></div>
            <svg viewBox="0 0 640 140" className="mt-3 h-[140px] w-full" role="img" aria-label="Booked value per day, last 14 days">
              {[35, 70, 105].map(y => <line key={y} x1="0" x2="640" y1={y} y2={y} stroke="var(--line)" strokeDasharray="3 4" />)}
              <path d={t.area} fill="var(--accent)" opacity="0.08" />
              <path d={t.line} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" />
              <circle cx={t.points[t.points.length - 1][0]} cy={t.points[t.points.length - 1][1]} r="4" fill="var(--accent)" />
            </svg>
            <div className="mt-1 flex justify-between font-[family-name:var(--font-mono)] text-[10.5px] text-[var(--muted)]">{TREND_DAYS.filter((_, i) => i % 3 === 0).map(d => <span key={d}>{d} Oct</span>)}</div>
            <p className="mt-2 text-[12.5px] text-[var(--muted)]">Today: <span className="num font-medium text-[var(--ink)]">{inr(TREND[TREND.length - 1])}</span></p>
          </section>
          <section className="rounded-lg border border-[var(--line)] bg-[var(--surface)] p-4" aria-labelledby="calm-src">
            <h2 id="calm-src" className="text-[14px] font-semibold">Where leads came from</h2>
            <ul className="mt-3 space-y-3">
              {SOURCES.map(s => (
                <li key={s.label}>
                  <div className="flex justify-between text-[13px]"><ChannelTag channel={s.channel} /><span className="num font-medium">{s.value}</span></div>
                  <div className="mt-1 h-1.5 rounded-full bg-[var(--raised)]"><div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${(s.value / max) * 100}%` }} /></div>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <section aria-labelledby="calm-alerts">
          <h2 id="calm-alerts" className="mb-2 text-[14px] font-semibold">Worth a look</h2>
          <ul className="divide-y divide-[var(--line)] rounded-lg border border-[var(--line)] bg-[var(--surface)]">
            {ALERTS.map(a => (
              <li key={a.text} className="flex items-center gap-3 px-4 py-3 text-[13.5px]">
                <span className={cn("size-1.5 shrink-0 rounded-full", a.tone === "danger" ? "bg-[var(--bad)]" : a.tone === "warning" ? "bg-[var(--warn)]" : "bg-[var(--info)]")} aria-hidden />
                <span className="min-w-0 flex-1">{a.text}</span>
                <Button variant="secondary" className="shrink-0">{a.action}</Button>
              </li>
            ))}
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
    <Shell {...props} actions={<Button variant="primary"><Plus size={15} /><span className="hidden sm:inline">New message</span></Button>}>
      <div className="grid grid-cols-1 h-[calc(100dvh-48px-60px)] md:h-[calc(100dvh-56px)] md:grid-cols-[320px_1fr] xl:grid-cols-[320px_1fr_300px]">
        <section aria-label="Conversations" className={cn("flex min-h-0 min-w-0 flex-col border-r border-[var(--line)] bg-[var(--surface)]", ib.open && "max-md:hidden")}>
          <div className="space-y-2 border-b border-[var(--line)] p-3">
            <label className="flex h-9 items-center gap-2 rounded-md border border-[var(--field)] bg-[var(--surface)] px-2.5 max-sm:h-11"><Search size={15} className="text-[var(--muted)]" /><input placeholder="Search guests and messages" className="w-full bg-transparent text-[16px] outline-none sm:text-[13px]" /></label>
            <div className="flex gap-1">{(["all", "waiting", "mine"] as const).map(f => <button key={f} type="button" onClick={() => ib.setFilter(f)} className={cn("h-8 rounded-md px-2.5 text-[12.5px] capitalize", ib.filter === f ? "bg-[var(--raised)] font-medium" : "text-[var(--muted)] hover:bg-[var(--raised)]")}>{f === "waiting" ? "Needs reply" : f}</button>)}</div>
          </div>
          <ul className="scroll min-h-0 flex-1 overflow-y-auto">
            {ib.list.map(conv => (
              <li key={conv.id}>
                <button type="button" onClick={() => ib.pick(conv.id)} aria-current={conv.id === ib.selected ? "true" : undefined}
                  className={cn("flex w-full gap-3 border-b border-[var(--line)] px-3 py-3 text-left", conv.id === ib.selected ? "bg-[var(--raised)]" : "hover:bg-[var(--bg)]")}>
                  <Avatar initials={conv.initials} size={34} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2"><span className={cn("truncate text-[13.5px]", conv.unread ? "font-semibold" : "font-medium")}>{conv.name}</span><span className="ml-auto shrink-0 text-[11.5px] text-[var(--muted)]">{conv.time}</span></span>
                    <span className="mt-0.5 block truncate text-[12.5px] text-[var(--muted)]">{conv.preview}</span>
                    <span className="mt-1.5 flex items-center gap-2"><ChannelTag channel={conv.channel} />{conv.waiting && <Badge tone={conv.hot ? "bad" : "warn"}>Waiting {conv.waiting}</Badge>}{conv.unread > 0 && <span className="num ml-auto rounded-full bg-[var(--accent)] px-1.5 text-[10.5px] font-semibold leading-[18px] text-[var(--on-accent)]">{conv.unread}</span>}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section aria-label="Conversation" className={cn("flex min-h-0 min-w-0 flex-col bg-[var(--bg)]", !ib.open && "max-md:hidden")}>
          <div className="flex h-14 items-center gap-3 border-b border-[var(--line)] bg-[var(--surface)] px-3 md:px-4">
            <button type="button" onClick={ib.back} aria-label="Back to conversations" className="flex size-10 items-center justify-center rounded-md hover:bg-[var(--raised)] md:hidden"><ArrowLeft size={18} /></button>
            <Avatar initials={c.initials} size={32} />
            <div className="min-w-0 flex-1"><p className="truncate text-[14px] font-semibold">{c.name}</p><p className="text-[12px] text-[var(--muted)]"><ChannelTag channel={c.channel} /> · {c.agent ?? "Unassigned"}</p></div>
            <Button variant="secondary" className="hidden sm:inline-flex"><Phone size={14} />Call</Button>
            <select aria-label="Assign to" data-assign className="h-9 rounded-md border border-[var(--field)] bg-[var(--surface)] px-2 text-[13px] max-lg:hidden" defaultValue={c.agent ?? ""}><option value="">Unassigned</option>{AGENTS.map(a => <option key={a.id}>{a.name}</option>)}</select>
          </div>
          <div className="scroll min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-4 md:px-6">
            {THREAD.map(m => m.from === "note" ? (
              <div key={m.id} className="mx-auto flex max-w-[560px] gap-2 rounded-md border border-dashed border-[var(--line-strong)] bg-[var(--warn-bg)] px-3 py-2 text-[12.5px]"><StickyNote size={14} className="mt-0.5 shrink-0 text-[var(--warn)]" /><span><span className="font-medium">{m.author}: </span>{m.text}</span></div>
            ) : (
              <div key={m.id} className={cn("flex", m.from === "guest" ? "justify-start" : "justify-end")}>
                <div className={cn("max-w-[78%] rounded-lg px-3 py-2 text-[13.5px] leading-relaxed", m.from === "guest" ? "border border-[var(--line)] bg-[var(--surface)]" : "bg-[var(--accent)] text-[var(--on-accent)]")}>
                  <p>{m.text}</p><p className={cn("mt-1 text-[11px]", m.from === "guest" ? "text-[var(--muted)]" : "opacity-80")}>{m.time}{m.author ? ` · ${m.author}` : ""}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="border-t border-[var(--line)] bg-[var(--surface)] p-3">
            {ib.draft !== "sent" && (
              <div className="mb-2 rounded-md border border-[var(--line)] bg-[var(--bg)] p-2.5">
                <p className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--accent)]"><Sparkles size={13} />Suggested reply · grounded in availability</p>
                <p className="mt-1 text-[13px] leading-relaxed">{AI_DRAFT}</p>
                <div className="mt-2 flex gap-2"><Button variant="primary" onClick={() => ib.setDraft("sent")}>Send</Button><Button variant="secondary" onClick={() => ib.setDraft("edited")}>Edit</Button></div>
              </div>
            )}
            <div className="flex items-end gap-2">
              <button type="button" aria-label="Attach" className="flex size-10 items-center justify-center rounded-md text-[var(--muted)] hover:bg-[var(--raised)]"><Paperclip size={17} /></button>
              <textarea rows={1} placeholder={ib.draft === "sent" ? "Reply sent. Type a follow-up…" : "Write a reply…"} className="min-h-10 flex-1 resize-none rounded-md border border-[var(--field)] bg-[var(--surface)] px-3 py-2 text-[16px] outline-none sm:text-[13.5px]" />
              <Button variant="primary" className="h-10"><Send size={15} /></Button>
            </div>
          </div>
        </section>

        <aside aria-label="Guest" className="scroll hidden min-h-0 overflow-y-auto border-l border-[var(--line)] bg-[var(--surface)] p-4 xl:block">
          <div className="flex items-center gap-3"><Avatar initials="PN" size={40} /><div><p className="text-[14px] font-semibold">{GUEST.name}</p><p className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--muted)]">{GUEST.phone}</p></div></div>
          <dl className="mt-4 divide-y divide-[var(--line)] text-[13px]">
            {[["Stage", GUEST.stage], ["Owner", GUEST.owner], ["Dates", GUEST.trip.dates], ["Party", GUEST.trip.party], ["Route", GUEST.trip.route], ["Estimate", GUEST.value], ["First touch", GUEST.firstTouch]].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 py-2"><dt className="text-[var(--muted)]">{k}</dt><dd className="text-right font-medium">{v}</dd></div>
            ))}
          </dl>
          <h3 className="mt-5 text-[12.5px] font-semibold text-[var(--muted)]">Timeline</h3>
          <ol className="mt-2 space-y-2.5">{GUEST.journey.map(j => <li key={j.label} className="flex gap-2.5 text-[13px]"><span className={cn("mt-1.5 size-2 shrink-0 rounded-full", j.done ? "bg-[var(--accent)]" : "border border-[var(--field)]")} /><span><span className={j.done ? "" : "text-[var(--muted)]"}>{j.label}</span>{j.when && <span className="block text-[11.5px] text-[var(--muted)]">{j.when}</span>}</span></li>)}</ol>
        </aside>
      </div>
    </Shell>
  );
}

// ── leads ─────────────────────────────────────────────────────────────────────

const PRIORITY_TONE = { hot: "bad", warm: "warn", cold: "neutral" } as const;

function LeadRow({ l }: { l: Lead }) {
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface)] p-3 hover:border-[var(--line-strong)]">
      <div className="flex items-center gap-2"><span className="truncate text-[13.5px] font-medium">{l.name}</span><span className="ml-auto"><Badge tone={PRIORITY_TONE[l.priority]}>{l.priority === "hot" ? "Hot" : l.priority === "warm" ? "Warm" : "Cold"}</Badge></span></div>
      <p className="mt-1 text-[12.5px] text-[var(--muted)]">{[l.dates, l.party].filter(Boolean).join(" · ") || "No dates yet"}</p>
      <div className="mt-2 flex items-center gap-2 text-[12px]"><ChannelTag channel={l.channel} />{l.value ? <span className="num ml-auto font-[family-name:var(--font-mono)]">{inrShort(l.value)}</span> : null}</div>
      <div className="mt-2.5 flex items-center gap-2 border-t border-[var(--line)] pt-2.5 text-[12.5px]">
        <span className={cn("min-w-0 flex-1 truncate", l.due === "now" ? "font-medium text-[var(--bad)]" : "")}>{l.next}</span>
        <span className="text-[var(--muted)]">{l.owner ? l.owner.split(" ")[0] : "No owner"}</span>
      </div>
    </div>
  );
}

function LeadsScreen(props: ScreenProps) {
  const ld = useLeads();
  return (
    <Shell {...props} actions={<><div className="hidden rounded-md border border-[var(--line)] bg-[var(--surface)] p-0.5 md:flex"><button type="button" onClick={() => ld.setView("board")} className={cn("flex h-8 items-center gap-1 rounded px-2 text-[12.5px]", ld.view === "board" ? "bg-[var(--raised)] font-medium" : "text-[var(--muted)]")}><LayoutGrid size={14} />Board</button><button type="button" onClick={() => ld.setView("list")} className={cn("flex h-8 items-center gap-1 rounded px-2 text-[12.5px]", ld.view === "list" ? "bg-[var(--raised)] font-medium" : "text-[var(--muted)]")}><List size={14} />List</button></div><Button variant="primary"><Plus size={15} /><span className="hidden sm:inline">Add lead</span></Button></>}>
      <div className="px-4 py-4 md:px-6">
        <div className="scroll -mx-4 mb-4 flex gap-1.5 overflow-x-auto px-4 md:mx-0 md:px-0">
          <button type="button" onClick={() => ld.setStage("all")} className={cn("h-8 shrink-0 rounded-md border px-2.5 text-[12.5px]", ld.stage === "all" ? "border-[var(--ink)] bg-[var(--ink)] text-[var(--surface)]" : "border-[var(--line)] bg-[var(--surface)]")}>All 55</button>
          {STAGES.map(s => <button key={s.key} type="button" onClick={() => ld.setStage(s.key)} className={cn("h-8 shrink-0 rounded-md border px-2.5 text-[12.5px]", ld.stage === s.key ? "border-[var(--ink)] bg-[var(--ink)] text-[var(--surface)]" : "border-[var(--line)] bg-[var(--surface)]")}>{s.label} <span className="num opacity-70">{s.count}</span></button>)}
        </div>

        {ld.view === "board" ? (
          <>
            <div className="hidden gap-3 md:grid md:grid-cols-3 xl:grid-cols-5">
              {STAGES.map(s => (
                <section key={s.key} aria-label={s.label} className="min-w-0">
                  <div className="mb-2 flex items-baseline justify-between px-0.5"><h2 className="text-[13px] font-semibold">{s.label}</h2><span className="num text-[12px] text-[var(--muted)]">{s.count}{s.value && ` · ${s.value}`}</span></div>
                  <div className="space-y-2">{LEADS.filter(l => l.stage === s.key).map(l => <LeadRow key={l.id} l={l} />)}</div>
                </section>
              ))}
            </div>
            <div className="space-y-2 md:hidden">{ld.list.map(l => <LeadRow key={l.id} l={l} />)}</div>
          </>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-[var(--line)] bg-[var(--surface)]">
            <table className="w-full min-w-[720px] text-[13px]">
              <thead><tr className="border-b border-[var(--line)] text-left text-[12px] text-[var(--muted)]">{["Guest", "Stage", "Dates", "Value", "Owner", "Next step"].map(h => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-[var(--line)]">{ld.list.map(l => (
                <tr key={l.id} className="hover:bg-[var(--bg)]"><td className="px-4 py-2.5 font-medium">{l.name}</td><td className="px-4 py-2.5">{STAGES.find(s => s.key === l.stage)?.label}</td><td className="px-4 py-2.5 text-[var(--muted)]">{l.dates ?? "—"}</td><td className="num px-4 py-2.5 font-[family-name:var(--font-mono)]">{l.value ? inr(l.value) : "—"}</td><td className="px-4 py-2.5">{l.owner ?? <span className="text-[var(--warn)]">No owner</span>}</td><td className={cn("px-4 py-2.5", l.due === "now" && "font-medium text-[var(--bad)]")}>{l.next}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </Shell>
  );
}

// ── calendar ──────────────────────────────────────────────────────────────────

const KIND_STYLE: Record<ResKind, string> = {
  direct: "bg-[var(--accent)] text-[var(--on-accent)]",
  ota: "bg-[var(--info)] text-[var(--on-accent)]",
  hold: "border border-dashed border-[var(--accent)] bg-[var(--surface)] text-[var(--accent)]",
  blocked: "bg-[var(--raised)] text-[var(--muted)] border border-[var(--line-strong)]",
  maintenance: "bg-[var(--bad-bg)] text-[var(--bad)] border border-[var(--bad)]",
};
const KIND_LABEL: Record<ResKind, string> = { direct: "Direct", ota: "Airbnb", hold: "On hold", blocked: "Blocked", maintenance: "Maintenance" };

function CalendarScreen(props: ScreenProps) {
  const cal = useCalendar();
  const days = Array.from({ length: CAL_DAYS }, (_, i) => i);
  return (
    <Shell {...props} actions={<><Button variant="secondary" className="max-sm:px-2"><ChevronLeft size={15} /></Button><span className="text-[13px] font-medium">12 Oct – 1 Nov</span><Button variant="secondary" className="max-sm:px-2"><ChevronRight size={15} /></Button><Button variant="primary" className="hidden sm:inline-flex"><Plus size={15} />Booking</Button></>}>
      <div className="px-4 py-4 md:px-6">
        <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-[var(--muted)]">{(Object.keys(KIND_LABEL) as ResKind[]).map(k => <span key={k} className="inline-flex items-center gap-1.5"><span className={cn("h-2.5 w-4 rounded-sm", KIND_STYLE[k])} />{KIND_LABEL[k]}</span>)}</div>

        {/* Desktop/tablet: timeline, one row per caravan. */}
        <div className="hidden gap-4 md:flex">
          <div className="min-w-0 flex-1 overflow-x-auto rounded-lg border border-[var(--line)] bg-[var(--surface)]">
            <div className="min-w-[840px]">
              <div className="grid grid-cols-[120px_1fr] border-b border-[var(--line)]">
                <div />
                <div className="grid" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>
                  {days.map(i => { const d = dayLabel(i); return <div key={i} className={cn("border-l border-[var(--line)] py-1.5 text-center", i === CAL_TODAY_INDEX && "bg-[var(--accent)]/10")}><p className="text-[10.5px] text-[var(--muted)]">{d.dow}</p><p className={cn("num text-[12.5px] font-medium", i === CAL_TODAY_INDEX && "text-[var(--accent)]")}>{d.day}</p></div>; })}
                </div>
              </div>
              {PROPERTIES.map(p => (
                <div key={p.id} className="grid grid-cols-[120px_1fr] border-b border-[var(--line)] last:border-b-0">
                  <div className="px-3 py-3"><p className="text-[13px] font-semibold">{p.name}</p><p className="text-[11.5px] text-[var(--muted)]">{p.note}</p></div>
                  <div className="relative h-[64px]">
                    <div className="absolute inset-0 grid" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>{days.map(i => <div key={i} className={cn("border-l border-[var(--line)]", i === CAL_TODAY_INDEX && "bg-[var(--accent)]/5", (i % 7 === 5 || i % 7 === 6) && "bg-[var(--bg)]")} />)}</div>
                    {RESERVATIONS.filter(r => r.property === p.id).map(r => (
                      <button key={r.id} type="button" onClick={() => cal.setSelected(r.id)} style={barStyle(r)}
                        className={cn("press absolute top-3 flex h-10 items-center overflow-hidden rounded-md px-2 text-left text-[12px] font-medium", KIND_STYLE[r.kind], cal.selected === r.id && "ring-2 ring-[var(--ink)] ring-offset-1")}>
                        <span className="truncate">{r.guest}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
          {cal.res && (
            <aside aria-label="Reservation" className="w-[280px] shrink-0 rounded-lg border border-[var(--line)] bg-[var(--surface)] p-4 max-lg:hidden">
              <div className="flex items-center gap-2"><span className={cn("rounded px-1.5 py-0.5 text-[11px] font-medium", KIND_STYLE[cal.res.kind])}>{KIND_LABEL[cal.res.kind]}</span><span className="text-[12px] text-[var(--muted)]">{cal.res.status}</span></div>
              <p className="mt-2 text-[16px] font-semibold">{cal.res.guest}</p>
              <p className="text-[13px] text-[var(--muted)]">{PROPERTIES.find(p => p.id === cal.res!.property)?.name} · {dayLabel(cal.res.start).day} – {dayLabel(cal.res.end).day} {dayLabel(cal.res.end).month} · {cal.res.end - cal.res.start} nights</p>
              {cal.res.amount != null && (
                <dl className="mt-4 divide-y divide-[var(--line)] text-[13px]">
                  {[["Party", cal.res.party], ["Route", cal.res.route], ["Source", cal.res.source], ["Total", inr(cal.res.amount)], ["Paid", inr(cal.res.paid ?? 0)], ["Balance", inr(cal.res.amount - (cal.res.paid ?? 0))]].map(([k, v]) => <div key={k} className="flex justify-between py-2"><dt className="text-[var(--muted)]">{k}</dt><dd className="num font-medium">{v}</dd></div>)}
                </dl>
              )}
              <Button variant="primary" className="mt-4 w-full">Open booking</Button>
            </aside>
          )}
        </div>

        {/* Phone: three weeks as a grid, then the selected day's stays. */}
        <div className="md:hidden">
          <div className="grid grid-cols-7 gap-px overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--line)]">
            {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <div key={i} className="bg-[var(--surface)] py-1 text-center text-[11px] text-[var(--muted)]">{d}</div>)}
            {days.map(i => {
              const stays = cal.onDay(i);
              return (
                <button key={i} type="button" onClick={() => cal.setDay(i)} aria-pressed={cal.day === i}
                  className={cn("flex h-14 flex-col items-center gap-1 bg-[var(--surface)] pt-1.5", cal.day === i && "bg-[var(--raised)]")}>
                  <span className={cn("num flex size-6 items-center justify-center rounded-full text-[12.5px]", i === CAL_TODAY_INDEX && "bg-[var(--accent)] font-semibold text-[var(--on-accent)]")}>{dayLabel(i).day}</span>
                  <span className="flex gap-0.5">{stays.map(r => <span key={r.id} className={cn("h-1.5 w-1.5 rounded-full", r.kind === "maintenance" ? "bg-[var(--bad)]" : r.kind === "blocked" ? "bg-[var(--line-strong)]" : r.kind === "ota" ? "bg-[var(--info)]" : "bg-[var(--accent)]")} />)}</span>
                </button>
              );
            })}
          </div>
          <h2 className="mb-2 mt-4 text-[13.5px] font-semibold">{dayLabel(cal.day).dow} {dayLabel(cal.day).day} {dayLabel(cal.day).month}</h2>
          <ul className="space-y-2">
            {cal.onDay(cal.day).length === 0 && <li className="rounded-lg border border-dashed border-[var(--line-strong)] p-4 text-center text-[13px] text-[var(--muted)]">Both caravans are free.</li>}
            {cal.onDay(cal.day).map(r => (
              <li key={r.id} className="flex items-center gap-3 rounded-lg border border-[var(--line)] bg-[var(--surface)] p-3">
                <span className={cn("h-9 w-1.5 shrink-0 rounded-full", KIND_STYLE[r.kind])} />
                <div className="min-w-0 flex-1"><p className="truncate text-[13.5px] font-medium">{r.guest}</p><p className="text-[12px] text-[var(--muted)]">{PROPERTIES.find(p => p.id === r.property)?.name} · {dayLabel(r.start).day}–{dayLabel(r.end).day} {dayLabel(r.end).month} · {KIND_LABEL[r.kind]}</p></div>
                {r.amount != null && <span className="num font-[family-name:var(--font-mono)] text-[12.5px]">{inrShort(r.amount)}</span>}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Shell>
  );
}

export default function Calm(props: ScreenProps) {
  if (props.screen === "inbox") return <InboxScreen {...props} />;
  if (props.screen === "leads") return <LeadsScreen {...props} />;
  if (props.screen === "calendar") return <CalendarScreen {...props} />;
  return <Home {...props} />;
}
