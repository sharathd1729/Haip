"use client";
// F · Hospitality Hybrid: built around today's guests. Stone-white surfaces, jamun plum for brand and actions, marigold for
// highlights, friendly radii and colour-coded guest avatars. Top bar with a property switcher on desktop; on phones a bottom
// bar with a raised "Now" button that holds the queue. Signatures: the Today strip, stay cards, an Airbnb-grade calendar.
import {
  ArrowLeft, ArrowUpRight, Bell, CalendarDays, Camera, ChevronDown, ChevronLeft, ChevronRight, Globe, House, Inbox,
  MessageCircle, Paperclip, Phone, Plus, Search, Send, Sparkles, SquareKanban, Zap,
} from "lucide-react";
import { useState, type ComponentType } from "react";
import { cn } from "@/lib/utils";
import {
  AGENTS, AI_DRAFT, CAL_DAYS, CAL_TODAY_INDEX, CHANNEL_LABEL, GUEST, KPIS, LEADS, PROPERTIES, RESERVATIONS,
  SOURCES, STAGES, THREAD, TREND, TREND_DAYS, dayLabel, inr, inrShort, type Channel, type Lead, type ResKind,
} from "../data";
import { barStyle, useCalendar, useInbox, useLeads, type ScreenProps } from "../hooks";
import type { Screen } from "../concepts";

type Icon = ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
const SW = 2;
const DISPLAY = "font-[family-name:var(--font-display)]";
const NAV: { id: Screen; label: string; icon: Icon; count?: number }[] = [
  { id: "home", label: "Today", icon: House },
  { id: "inbox", label: "Inbox", icon: Inbox, count: 4 },
  { id: "calendar", label: "Calendar", icon: CalendarDays },
  { id: "leads", label: "Leads", icon: SquareKanban, count: 5 },
];
const TITLES: Record<Screen, string> = { home: "Today", inbox: "Inbox", leads: "Leads", calendar: "Calendar" };

// Warm, distinct avatar tints (each passes AA for its initials).
const TINTS = [["#F1E8F4", "#5A2D6B"], ["#FCEFD2", "#7A4E05"], ["#E5F0E8", "#24613E"], ["#E8EEF8", "#2F4F8F"], ["#F8E6E2", "#8E3227"]];
function tint(name: string) { let h = 0; for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return TINTS[h % TINTS.length]; }
function Avatar({ name, initials, size = 36, channel }: { name: string; initials: string; size?: number; channel?: Channel }) {
  const [bg, fg] = tint(name);
  return (
    <span className="relative inline-flex shrink-0">
      <span style={{ width: size, height: size, background: bg, color: fg, fontSize: size * 0.36 }} className="inline-flex items-center justify-center rounded-full font-semibold">{initials}</span>
      {channel && <span className="absolute -bottom-0.5 -right-0.5 flex size-[17px] items-center justify-center rounded-full border-2 border-[var(--surface)] bg-[var(--surface)]"><ChIcon channel={channel} size={11} /></span>}
    </span>
  );
}
const CH_ICON: Record<Channel, Icon> = { whatsapp: MessageCircle, instagram: Camera, call: Phone, website: Globe };
const CH_COLOR: Record<Channel, string> = { whatsapp: "text-[var(--ok)]", instagram: "text-[var(--accent)]", call: "text-[var(--info)]", website: "text-[var(--muted)]" };
function ChIcon({ channel, size = 13 }: { channel: Channel; size?: number }) { const I = CH_ICON[channel]; return <I size={size} strokeWidth={SW} className={CH_COLOR[channel]} />; }
function Ch({ channel }: { channel: Channel }) { return <span className="inline-flex items-center gap-1 text-[12.5px] text-[var(--muted)]"><ChIcon channel={channel} />{CHANNEL_LABEL[channel]}</span>; }

function Btn({ children, kind = "soft", className, onClick }: { children: React.ReactNode; kind?: "plum" | "soft" | "marigold"; className?: string; onClick?: () => void }) {
  const k = {
    plum: "bg-[var(--accent)] text-[var(--on-accent)] hover:bg-[var(--accent-hover)] shadow-[0_2px_6px_-2px_rgba(90,45,107,0.5)]",
    soft: "bg-[var(--raised)] text-[var(--ink)] hover:bg-[var(--line)]",
    marigold: "bg-[var(--marigold)] text-[var(--ink)] hover:brightness-95",
  };
  return <button type="button" onClick={onClick} className={cn("press inline-flex h-10 items-center justify-center gap-1.5 rounded-xl px-3.5 text-[13.5px] font-semibold max-sm:h-11", k[kind], className)}>{children}</button>;
}
function Chip({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("inline-flex h-6 items-center gap-1 rounded-full bg-[var(--raised)] px-2.5 text-[12px] font-medium", className)}>{children}</span>;
}
function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("rounded-2xl bg-[var(--surface)] shadow-[0_1px_2px_rgba(28,25,23,0.05),0_4px_16px_-8px_rgba(28,25,23,0.10)]", className)}>{children}</div>;
}

// ── shell ─────────────────────────────────────────────────────────────────────

function Shell({ screen, go, children, actions, title }: ScreenProps & { children: React.ReactNode; actions?: React.ReactNode; title?: React.ReactNode }) {
  return (
    <div className="lab-root lab-hybrid">
      <header className="sticky top-0 z-30 border-b border-[var(--line)] bg-[var(--chrome)]">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-3 px-4 md:h-16 md:px-6">
          <span className={cn(DISPLAY, "flex size-9 items-center justify-center rounded-xl bg-[var(--accent)] text-[17px] font-bold text-[var(--on-accent)]")}>r</span>
          <button type="button" className="hidden h-10 items-center gap-1.5 rounded-xl px-2.5 text-[14px] font-semibold hover:bg-[var(--raised)] sm:flex">All caravans<ChevronDown size={15} strokeWidth={SW} /></button>
          <nav aria-label="Main" className="ml-2 hidden items-center gap-1 md:flex">
            {NAV.map(item => (
              <button key={item.id} type="button" aria-current={item.id === screen ? "page" : undefined} onClick={() => go(item.id)}
                className={cn("press flex h-10 items-center gap-2 rounded-xl px-3.5 text-[14px] font-semibold", item.id === screen ? "bg-[var(--chrome-active)] text-[var(--accent)]" : "text-[var(--muted)] hover:bg-[var(--raised)] hover:text-[var(--ink)]")}>
                {item.label}{item.count ? <span className="num rounded-full bg-[var(--accent)] px-1.5 text-[11px] leading-[18px] text-[var(--on-accent)]">{item.count}</span> : null}
              </button>
            ))}
            <button type="button" className="flex h-10 items-center gap-1 rounded-xl px-3 text-[14px] font-semibold text-[var(--muted)] hover:bg-[var(--raised)]">More<ChevronDown size={15} /></button>
          </nav>
          <div className="ml-auto flex items-center gap-1.5">
            <button type="button" aria-label="Search" className="flex size-10 items-center justify-center rounded-xl hover:bg-[var(--raised)]"><Search size={19} strokeWidth={SW} /></button>
            <button type="button" aria-label="Notifications" className="relative flex size-10 items-center justify-center rounded-xl hover:bg-[var(--raised)]"><Bell size={19} strokeWidth={SW} /><span className="absolute right-2.5 top-2.5 size-2 rounded-full bg-[var(--marigold)] ring-2 ring-[var(--surface)]" /></button>
            <Avatar name="Sharath D" initials="SD" size={34} />
          </div>
        </div>
      </header>
      <div className="mx-auto max-w-[1400px] px-4 pb-28 pt-5 md:px-6 md:pb-10 md:pt-7">
        <div className="mb-5 flex flex-wrap items-end gap-3">
          <div className="min-w-0">{title ?? <h1 className={cn(DISPLAY, "text-[26px] font-semibold leading-none tracking-[-0.02em] md:text-[34px]")}>{TITLES[screen]}</h1>}</div>
          <div className="ml-auto flex items-center gap-2">{actions}</div>
        </div>
        <main>{children}</main>
      </div>
      {/* Phone: four destinations and a raised "Now" button for the queue in the middle. */}
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 grid h-[68px] grid-cols-5 border-t border-[var(--line)] bg-[var(--surface)] pb-[env(safe-area-inset-bottom)] md:hidden">
        {[NAV[0], NAV[1], null, NAV[2], NAV[3]].map((item, i) => item ? (
          <button key={item.id} type="button" onClick={() => go(item.id)} className={cn("relative flex flex-col items-center justify-center gap-1 text-[11.5px] font-semibold", item.id === screen ? "text-[var(--accent)]" : "text-[var(--muted)]")}>
            <item.icon size={21} strokeWidth={SW} />{item.label}
            {item.count ? <span className="num absolute right-[calc(50%-21px)] top-2 rounded-full bg-[var(--accent)] px-1 text-[10px] leading-4 text-[var(--on-accent)]">{item.count}</span> : null}
          </button>
        ) : (
          <button key={`now-${i}`} type="button" onClick={() => go("home")} aria-label="Now: 14 people waiting" className="relative flex flex-col items-center">
            <span className="press -mt-5 flex size-14 flex-col items-center justify-center rounded-2xl bg-[var(--accent)] text-[var(--on-accent)] shadow-[0_8px_20px_-6px_rgba(90,45,107,0.6)] ring-4 ring-[var(--bg)]"><Zap size={20} strokeWidth={SW} /><span className="num text-[11px] font-bold leading-none">14</span></span>
            <span className="mt-0.5 text-[11.5px] font-semibold text-[var(--accent)]">Now</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

// ── home ──────────────────────────────────────────────────────────────────────

const WAITING = [
  { name: "Kabir Shah", initials: "KS", channel: "call" as Channel, why: "Missed call", wait: "2h 10m", act: "Call back", urgent: true },
  { name: "Priya Nair", initials: "PN", channel: "whatsapp" as Channel, why: "Asked for the total, twice", wait: "22m", act: "Reply", urgent: true },
  { name: "Rahul Sharma", initials: "RS", channel: "instagram" as Channel, why: "New lead, no number yet", wait: "18m", act: "Reply", urgent: false },
  { name: "Isha Gupta", initials: "IG", channel: "website" as Channel, why: "No owner yet", wait: "1d", act: "Take it", urgent: false },
];

function Home(props: ScreenProps) {
  const max = Math.max(...TREND);
  return (
    <Shell {...props} title={<><p className="text-[13.5px] font-medium text-[var(--muted)]">Saturday, 17 October</p><h1 className={cn(DISPLAY, "text-[26px] font-semibold leading-tight tracking-[-0.02em] md:text-[34px]")}>Good evening, Sharath</h1></>}
      actions={<><select aria-label="Period" className="h-10 rounded-xl border border-[var(--field)] bg-[var(--surface)] px-3 text-[14px] font-medium max-sm:hidden"><option>Last 7 days</option><option>This month</option></select><Btn kind="plum"><Plus size={17} strokeWidth={SW} /><span className="max-sm:hidden">New booking</span></Btn></>}>
      {/* Signature: the Today strip. Who arrives, who leaves, what each caravan is doing. */}
      <section aria-label="Today at the caravans" className="scroll -mx-4 flex gap-3 overflow-x-auto px-4 pb-1 md:mx-0 md:grid md:grid-cols-3 md:overflow-visible md:px-0">
        <Card className="w-[260px] shrink-0 p-4 md:w-auto">
          <p className="text-[13px] font-semibold text-[var(--muted)]">Next arrivals</p>
          <ul className="mt-2.5 space-y-2.5">{[["Vikram Pillai", "VP", "Ratha 1 · Tue 20 Oct"], ["Meera Reddy", "MR", "Ratha 2 · Tue 20 Oct"]].map(([n, i, d]) => <li key={n} className="flex items-center gap-2.5"><Avatar name={n} initials={i} size={34} /><span className="min-w-0"><span className="block truncate text-[14px] font-semibold">{n}</span><span className="text-[12.5px] text-[var(--muted)]">{d}</span></span></li>)}</ul>
        </Card>
        <Card className="w-[260px] shrink-0 p-4 md:w-auto">
          <p className="text-[13px] font-semibold text-[var(--muted)]">Caravans today</p>
          <ul className="mt-2.5 space-y-2.5">
            <li className="flex items-center justify-between"><span className="text-[14px] font-semibold">Ratha 1</span><Chip className="bg-[var(--ok-bg)] text-[var(--ok)]">Ready</Chip></li>
            <li className="flex items-center justify-between"><span className="text-[14px] font-semibold">Ratha 2</span><Chip className="bg-[var(--warn-bg)] text-[var(--warn)]">Service ends today</Chip></li>
          </ul>
        </Card>
        <Card className="w-[260px] shrink-0 bg-[var(--accent)] p-4 text-[var(--on-accent)] md:w-auto">
          <p className="text-[13px] font-semibold opacity-85">Waiting for your team</p>
          <p className={cn(DISPLAY, "num mt-1 text-[40px] font-semibold leading-none")}>14</p>
          <p className="mt-1 text-[13px] opacity-90">people · 8 past their reply time</p>
        </Card>
      </section>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <section aria-labelledby="hy-wait" className="min-w-0">
          <div className="mb-3 flex items-baseline justify-between"><h2 id="hy-wait" className={cn(DISPLAY, "text-[19px] font-semibold")}>Waiting for you</h2><button type="button" className="min-h-11 text-[13.5px] font-semibold text-[var(--accent)] sm:min-h-0">See all 14</button></div>
          <ul className="space-y-2.5">
            {WAITING.map(w => (
              <li key={w.name}><Card className="flex items-center gap-3 p-3">
                <Avatar name={w.name} initials={w.initials} size={42} channel={w.channel} />
                <div className="min-w-0 flex-1"><p className="truncate text-[14.5px] font-semibold">{w.name}</p><p className="truncate text-[13px] text-[var(--muted)]">{w.why}</p></div>
                <span className={cn("num shrink-0 text-[13px] font-semibold", w.urgent ? "text-[var(--bad)]" : "text-[var(--muted)]")}>{w.wait}</span>
                <Btn kind={w.urgent ? "plum" : "soft"} className="h-10 shrink-0 max-sm:px-3">{w.act}</Btn>
              </Card></li>
            ))}
          </ul>
        </section>
        <div className="space-y-6">
          <section aria-labelledby="hy-week">
            <h2 id="hy-week" className={cn(DISPLAY, "mb-3 text-[19px] font-semibold")}>This week</h2>
            <Card className="grid grid-cols-2 gap-x-4 gap-y-4 p-4 sm:grid-cols-3">
              {[[KPIS.newLeads.label, String(KPIS.newLeads.value), KPIS.newLeads.change], [KPIS.bookings.label, String(KPIS.bookings.value), KPIS.bookings.change], [KPIS.bookedValue.label, inrShort(KPIS.bookedValue.value), KPIS.bookedValue.change], [KPIS.cash.label, inrShort(KPIS.cash.value), KPIS.cash.change], [KPIS.occupancy.label, `${KPIS.occupancy.value}%`, KPIS.occupancy.change], [KPIS.response.label, `${KPIS.response.value} min`, KPIS.response.change]].map(([k, v, d]) => (
                <div key={String(k)}><p className="text-[12.5px] font-medium text-[var(--muted)]">{k}</p><p className={cn(DISPLAY, "num text-[24px] font-semibold leading-tight")}>{v}</p><p className={cn("text-[12px] font-semibold", Number(d) >= 0 ? "text-[var(--ok)]" : "text-[var(--bad)]")}>{Number(d) >= 0 ? "+" : ""}{d}%</p></div>
              ))}
            </Card>
          </section>
          <section aria-labelledby="hy-trend">
            <Card className="p-4">
              <div className="flex items-baseline justify-between"><h2 id="hy-trend" className="text-[14px] font-semibold">Booked value per day</h2><span className="text-[12.5px] text-[var(--muted)]">14 days</span></div>
              <div className="mt-3 flex h-[110px] items-end gap-1.5" role="img" aria-label="Booked value per day, last 14 days">{TREND.map((v, i) => <span key={i} className={cn("flex-1 rounded-md", i === TREND.length - 1 ? "bg-[var(--marigold)]" : i >= 7 ? "bg-[var(--accent)]" : "bg-[var(--plum-bg)]")} style={{ height: `${Math.max(4, (v / max) * 100)}%` }} />)}</div>
              <div className="mt-1.5 flex gap-1.5">{TREND_DAYS.map(d => <span key={d} className="num flex-1 text-center text-[10.5px] text-[var(--muted)]">{d}</span>)}</div>
            </Card>
          </section>
          <section aria-labelledby="hy-src"><Card className="p-4"><h2 id="hy-src" className="text-[14px] font-semibold">Where leads came from</h2><ul className="mt-3 flex flex-wrap gap-2">{SOURCES.map(s => <li key={s.label}><Chip className="h-8 gap-1.5 px-3 text-[13px]"><ChIcon channel={s.channel} />{s.label}<span className="num font-bold">{s.value}</span></Chip></li>)}</ul></Card></section>
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
    <Shell {...props} actions={<div className="flex rounded-xl bg-[var(--raised)] p-1">{(["all", "waiting", "mine"] as const).map(f => <button key={f} type="button" onClick={() => ib.setFilter(f)} className={cn("h-8 rounded-lg px-3 text-[13px] font-semibold max-sm:h-9", ib.filter === f ? "bg-[var(--surface)] text-[var(--ink)] shadow-[0_1px_2px_rgba(0,0,0,0.08)]" : "text-[var(--muted)]")}>{f === "waiting" ? "Waiting" : f === "mine" ? "Mine" : "All"}</button>)}</div>}>
      <div className="grid grid-cols-1 gap-4 md:h-[calc(100dvh-64px-130px)] md:grid-cols-[330px_1fr] xl:grid-cols-[330px_1fr_300px]">
        <Card className={cn("scroll min-h-0 overflow-y-auto p-1.5", ib.open && "max-md:hidden")}>
          <ul>
            {ib.list.map(conv => (
              <li key={conv.id}>
                <button type="button" onClick={() => ib.pick(conv.id)} className={cn("flex w-full items-center gap-3 rounded-xl p-2.5 text-left", conv.id === ib.selected ? "bg-[var(--plum-bg)]" : "hover:bg-[var(--raised)]")}>
                  <Avatar name={conv.name} initials={conv.initials} size={44} channel={conv.channel} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2"><span className={cn("truncate text-[14.5px]", conv.unread ? "font-bold" : "font-semibold")}>{conv.name}</span><span className="ml-auto shrink-0 text-[12px] text-[var(--muted)]">{conv.time}</span></span>
                    <span className="mt-0.5 flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-[13px] text-[var(--muted)]">{conv.preview}</span>{conv.unread > 0 && <span className="num flex size-5 shrink-0 items-center justify-center rounded-full bg-[var(--accent)] text-[11px] font-bold text-[var(--on-accent)]">{conv.unread}</span>}</span>
                    {conv.waiting && <span className={cn("mt-1 inline-block text-[12px] font-semibold", conv.hot ? "text-[var(--bad)]" : "text-[var(--marigold-ink)]")}>Waiting {conv.waiting}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <Card className={cn("flex min-h-[70dvh] flex-col overflow-hidden md:min-h-0", !ib.open && "max-md:hidden")}>
          <div className="flex items-center gap-3 border-b border-[var(--line)] p-3">
            <button type="button" onClick={ib.back} aria-label="Back to conversations" className="flex size-10 items-center justify-center rounded-xl hover:bg-[var(--raised)] md:hidden"><ArrowLeft size={19} /></button>
            <Avatar name={c.name} initials={c.initials} size={40} channel={c.channel} />
            <div className="min-w-0 flex-1"><p className="truncate text-[15px] font-bold">{c.name}</p><p className="text-[12.5px] text-[var(--muted)]">{CHANNEL_LABEL[c.channel]} · {c.agent ?? "Unassigned"}</p></div>
            <Btn kind="soft" className="max-sm:hidden"><Phone size={15} strokeWidth={SW} />Call</Btn>
            <select aria-label="Assign to" data-assign defaultValue={c.agent ?? ""} className="h-10 rounded-xl border border-[var(--field)] bg-[var(--surface)] px-2.5 text-[13.5px] max-lg:hidden"><option value="">Unassigned</option>{AGENTS.map(a => <option key={a.id}>{a.name}</option>)}</select>
          </div>
          <div className="scroll min-h-0 flex-1 space-y-3 overflow-y-auto bg-[var(--bg)] px-3 py-4 md:px-6">
            {THREAD.map(m => m.from === "note" ? (
              <p key={m.id} className="mx-auto max-w-[520px] rounded-xl bg-[var(--marigold-bg)] px-3 py-2 text-[13px]"><span className="font-semibold">{m.author}:</span> {m.text}</p>
            ) : (
              <div key={m.id} className={cn("flex", m.from === "guest" ? "justify-start" : "justify-end")}>
                <div className={cn("max-w-[80%] rounded-2xl px-3.5 py-2.5 text-[14px] leading-relaxed", m.from === "guest" ? "rounded-bl-md bg-[var(--surface)] shadow-[0_1px_2px_rgba(0,0,0,0.05)]" : "rounded-br-md bg-[var(--accent)] text-[var(--on-accent)]")}>
                  {m.text}<span className={cn("mt-1 block text-[11.5px]", m.from === "guest" ? "text-[var(--muted)]" : "opacity-80")}>{m.time}{m.author ? ` · ${m.author}` : ""}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="border-t border-[var(--line)] p-3">
            <div className="scroll mb-2 flex gap-2 overflow-x-auto">{["Share the Coorg itinerary", "Ask for travel dates", "Send payment link"].map(q => <button key={q} type="button" className="h-9 shrink-0 rounded-full border border-[var(--line-strong)] px-3 text-[13px] font-medium hover:border-[var(--accent)] hover:text-[var(--accent)]">{q}</button>)}</div>
            {ib.draft !== "sent" && (
              <div className="mb-2 rounded-2xl bg-[var(--plum-bg)] p-3">
                <p className="flex items-center gap-1.5 text-[12.5px] font-bold text-[var(--accent)]"><Sparkles size={14} />Suggested reply</p>
                <p className="mt-1 text-[14px] leading-relaxed">{AI_DRAFT}</p>
                <div className="mt-2 flex gap-2"><Btn kind="plum" onClick={() => ib.setDraft("sent")}>Send</Btn><Btn kind="soft" className="bg-[var(--surface)]" onClick={() => ib.setDraft("edited")}>Edit</Btn></div>
              </div>
            )}
            <div className="flex items-end gap-2 rounded-2xl bg-[var(--raised)] p-1.5">
              <button type="button" aria-label="Attach" className="flex size-10 items-center justify-center rounded-xl text-[var(--muted)]"><Paperclip size={18} /></button>
              <textarea rows={1} placeholder="Message Priya" className="min-h-10 flex-1 resize-none bg-transparent py-2 text-[16px] outline-none sm:text-[14px]" />
              <Btn kind="plum" className="h-10 w-10 px-0"><Send size={16} /></Btn>
            </div>
          </div>
        </Card>

        <div className="scroll hidden min-h-0 space-y-4 overflow-y-auto xl:block">
          {/* Signature: the stay card. The guest shown as a trip, ready to become a booking. */}
          <Card className="overflow-hidden">
            <div className="bg-[var(--accent)] p-4 text-[var(--on-accent)]">
              <p className="text-[12.5px] font-semibold opacity-85">Planned stay</p>
              <p className={cn(DISPLAY, "text-[22px] font-semibold leading-tight")}>{GUEST.trip.route} · {GUEST.trip.dates}</p>
              <p className="mt-0.5 text-[13px] opacity-90">Ratha 1 · 2 nights · {GUEST.trip.party}</p>
            </div>
            <div className="space-y-3 p-4">
              <div className="flex flex-wrap gap-1.5"><Chip>{GUEST.trip.occasion}</Chip><Chip>Kids 6 and 9</Chip><Chip className="bg-[var(--marigold-bg)] text-[var(--marigold-ink)]">Asked for price</Chip></div>
              <div className="flex items-baseline justify-between"><span className="text-[13px] text-[var(--muted)]">Estimate</span><span className={cn(DISPLAY, "num text-[22px] font-semibold")}>₹45,500</span></div>
              <Btn kind="plum" className="w-full">Create booking</Btn>
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-3"><Avatar name={GUEST.name} initials="PN" size={40} /><div><p className="text-[14.5px] font-bold">{GUEST.name}</p><p className="num text-[12.5px] text-[var(--muted)]">{GUEST.phone}</p></div></div>
            <ol className="mt-4 space-y-2.5">{GUEST.journey.map(j => <li key={j.label} className="flex items-start gap-2.5 text-[13px]"><span className={cn("mt-1 size-2.5 shrink-0 rounded-full", j.done ? "bg-[var(--accent)]" : "border-2 border-[var(--marigold)]")} /><span className={j.done ? "" : "text-[var(--muted)]"}>{j.label}{j.when && <span className="block text-[12px] text-[var(--muted)]">{j.when}</span>}</span></li>)}</ol>
          </Card>
        </div>
      </div>
    </Shell>
  );
}

// ── leads ─────────────────────────────────────────────────────────────────────

function LeadCard({ l }: { l: Lead }) {
  return (
    <Card className="p-3.5">
      <div className="flex items-center gap-2.5"><Avatar name={l.name} initials={l.initials} size={38} channel={l.channel} /><div className="min-w-0 flex-1"><p className="truncate text-[14.5px] font-bold">{l.name}</p><p className="text-[12.5px] text-[var(--muted)]">{l.owner ?? "No owner yet"}</p></div>{l.value ? <span className={cn(DISPLAY, "num text-[17px] font-semibold")}>{inrShort(l.value)}</span> : null}</div>
      {(l.dates || l.party) && <div className="mt-2.5 flex flex-wrap gap-1.5">{l.dates && <Chip><CalendarDays size={12} />{l.dates}</Chip>}{l.party && <Chip>{l.party}</Chip>}</div>}
      <div className={cn("mt-2.5 flex items-center gap-2 rounded-xl px-2.5 py-2 text-[13px] font-semibold", l.due === "now" ? "bg-[var(--bad-bg)] text-[var(--bad)]" : "bg-[var(--raised)]")}><ArrowUpRight size={14} className="shrink-0" /><span className="min-w-0 flex-1 truncate">{l.next}</span><span className="shrink-0 text-[12px] font-medium opacity-80">{l.due ?? ""}</span></div>
    </Card>
  );
}

function LeadsScreen(props: ScreenProps) {
  const ld = useLeads();
  const groups = [
    { title: "Act now", items: ld.list.filter(l => l.due === "now") },
    { title: "Today", items: ld.list.filter(l => l.due === "today") },
    { title: "Later", items: ld.list.filter(l => l.due !== "now" && l.due !== "today") },
  ];
  return (
    <Shell {...props} actions={<Btn kind="plum"><Plus size={17} /><span className="max-sm:hidden">Add lead</span></Btn>}>
      <div className="scroll -mx-4 mb-5 flex gap-2 overflow-x-auto px-4 md:mx-0 md:px-0">
        {[{ key: "all", label: "All", count: 55 }, ...STAGES].map(s => <button key={s.key} type="button" onClick={() => ld.setStage(s.key)} className={cn("press h-10 shrink-0 rounded-full px-4 text-[13.5px] font-semibold", ld.stage === s.key ? "bg-[var(--ink)] text-[var(--surface)]" : "bg-[var(--surface)] text-[var(--muted)] shadow-[inset_0_0_0_1px_var(--line)]")}>{s.label} <span className="num opacity-70">{s.count}</span></button>)}
      </div>
      <div className="hidden gap-4 md:grid md:grid-cols-3 xl:grid-cols-5">
        {STAGES.map(s => (
          <section key={s.key} aria-label={s.label} className="min-w-0 rounded-2xl bg-[var(--raised)] p-2.5">
            <div className="mb-2.5 flex items-baseline justify-between px-1"><h2 className={cn(DISPLAY, "text-[16px] font-semibold")}>{s.label}</h2><span className="num text-[12.5px] font-semibold text-[var(--muted)]">{s.count}</span></div>
            {s.value && <p className="num -mt-1.5 mb-2 px-1 text-[12.5px] text-[var(--muted)]">{s.value}</p>}
            <div className="space-y-2.5">{LEADS.filter(l => l.stage === s.key).map(l => <LeadCard key={l.id} l={l} />)}</div>
          </section>
        ))}
      </div>
      {/* Phone: grouped by when to act, not by pipeline stage. */}
      <div className="space-y-5 md:hidden">
        {groups.filter(g => g.items.length).map(g => (
          <section key={g.title} aria-label={g.title}>
            <h2 className={cn(DISPLAY, "mb-2 text-[17px] font-semibold", g.title === "Act now" && "text-[var(--bad)]")}>{g.title} <span className="num text-[13px] font-medium text-[var(--muted)]">{g.items.length}</span></h2>
            <div className="space-y-2.5">{g.items.map(l => <LeadCard key={l.id} l={l} />)}</div>
          </section>
        ))}
      </div>
    </Shell>
  );
}

// ── calendar ──────────────────────────────────────────────────────────────────

const STAY: Record<ResKind, string> = {
  direct: "bg-[var(--accent)] text-[var(--on-accent)]",
  ota: "bg-[var(--info)] text-[var(--on-accent)]",
  hold: "bg-[var(--marigold-bg)] text-[var(--marigold-ink)] shadow-[inset_0_0_0_1.5px_var(--marigold)]",
  blocked: "bg-[repeating-linear-gradient(135deg,var(--raised)_0_6px,var(--line)_6px_12px)] text-[var(--muted)]",
  maintenance: "bg-[var(--bad-bg)] text-[var(--bad)] shadow-[inset_0_0_0_1.5px_var(--bad)]",
};
const STAY_LABEL: Record<ResKind, string> = { direct: "Direct", ota: "Airbnb", hold: "On hold", blocked: "Blocked", maintenance: "Maintenance" };
function initialsOf(n: string) { return n.split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase(); }

function CalendarScreen(props: ScreenProps) {
  const cal = useCalendar();
  const [prop, setProp] = useState<"r1" | "r2">("r1");
  const days = Array.from({ length: CAL_DAYS }, (_, i) => i);
  const weeks = [0, 1, 2];
  return (
    <Shell {...props} actions={<><Btn kind="soft" className="w-10 px-0"><ChevronLeft size={18} /></Btn><span className="text-[14.5px] font-semibold max-sm:hidden">October 2026</span><Btn kind="soft" className="w-10 px-0"><ChevronRight size={18} /></Btn><Btn kind="plum" className="max-sm:hidden"><Plus size={17} />Booking</Btn></>}>
      <ul className="mb-4 flex flex-wrap gap-2">{(Object.keys(STAY) as ResKind[]).map(k => <li key={k}><Chip className="h-7 gap-1.5 bg-[var(--surface)] shadow-[inset_0_0_0_1px_var(--line)]"><span className={cn("size-3 rounded-[4px]", STAY[k])} />{STAY_LABEL[k]}</Chip></li>)}</ul>

      <div className="hidden gap-5 md:flex">
        <Card className="min-w-0 flex-1 overflow-x-auto p-2">
          <div className="min-w-[880px]">
            <div className="grid grid-cols-[130px_1fr]">
              <div />
              <div className="grid" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>{days.map(i => { const d = dayLabel(i); return <div key={i} className="py-2 text-center"><p className="text-[11px] font-semibold text-[var(--muted)]">{d.dow.slice(0, 2)}</p><p className={cn("num mx-auto flex size-7 items-center justify-center rounded-full text-[13.5px] font-semibold", i === CAL_TODAY_INDEX && "bg-[var(--ink)] text-[var(--surface)]")}>{d.day}</p></div>; })}</div>
            </div>
            {PROPERTIES.map(p => (
              <div key={p.id} className="grid grid-cols-[130px_1fr] border-t border-[var(--line)]">
                <div className="flex items-center gap-2.5 px-2 py-4"><span className={cn(DISPLAY, "flex size-9 items-center justify-center rounded-xl bg-[var(--plum-bg)] text-[14px] font-bold text-[var(--accent)]")}>{p.name.slice(-1)}</span><span><span className="block text-[14px] font-bold">{p.name}</span><span className="text-[12px] text-[var(--muted)]">{p.note}</span></span></div>
                <div className="relative h-[72px]">
                  <div className="absolute inset-0 grid" style={{ gridTemplateColumns: `repeat(${CAL_DAYS}, minmax(0,1fr))` }}>{days.map(i => <div key={i} className={cn(i % 7 >= 5 && "bg-[var(--bg)]", i === CAL_TODAY_INDEX && "bg-[var(--plum-bg)]/60")} />)}</div>
                  {RESERVATIONS.filter(r => r.property === p.id).map(r => (
                    <button key={r.id} type="button" onClick={() => cal.setSelected(r.id)} style={barStyle(r)} className={cn("press absolute top-3.5 flex h-11 items-center gap-2 overflow-hidden rounded-full pl-1.5 pr-3 text-left text-[12.5px] font-semibold", STAY[r.kind], cal.selected === r.id && "ring-[3px] ring-[var(--marigold)]")}>
                      {r.kind !== "blocked" && r.kind !== "maintenance" && <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-[var(--surface)] text-[11px] font-bold text-[var(--accent)]">{initialsOf(r.guest)}</span>}
                      <span className="truncate">{r.guest}</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
        {cal.res && (
          <Card className="w-[290px] shrink-0 overflow-hidden max-lg:hidden">
            <div className={cn("p-4", cal.res.kind === "direct" ? "bg-[var(--accent)] text-[var(--on-accent)]" : "bg-[var(--raised)]")}>
              <p className="text-[12.5px] font-semibold opacity-85">{STAY_LABEL[cal.res.kind]} · {cal.res.status}</p>
              <p className={cn(DISPLAY, "text-[22px] font-semibold leading-tight")}>{cal.res.guest}</p>
              <p className="mt-0.5 text-[13px] opacity-90">{PROPERTIES.find(p => p.id === cal.res!.property)?.name} · {dayLabel(cal.res.start).day}–{dayLabel(cal.res.end).day} {dayLabel(cal.res.end).month} · {cal.res.end - cal.res.start} nights</p>
            </div>
            {cal.res.amount != null && (
              <div className="space-y-3 p-4">
                <div className="flex flex-wrap gap-1.5">{cal.res.party && <Chip>{cal.res.party}</Chip>}{cal.res.route && <Chip>{cal.res.route}</Chip>}<Chip>{cal.res.source}</Chip></div>
                <div><div className="flex justify-between text-[13px]"><span className="text-[var(--muted)]">Paid {inr(cal.res.paid ?? 0)}</span><span className="num font-semibold">{inr(cal.res.amount)}</span></div><div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[var(--raised)]"><div className="h-full rounded-full bg-[var(--ok)]" style={{ width: `${((cal.res.paid ?? 0) / cal.res.amount) * 100}%` }} /></div><p className="mt-1 text-[12.5px] font-semibold text-[var(--warn)]">{inr(cal.res.amount - (cal.res.paid ?? 0))} still to collect</p></div>
                <Btn kind="plum" className="w-full">Open booking</Btn>
              </div>
            )}
          </Card>
        )}
      </div>

      {/* Phone: one caravan at a time, stays drawn as bars across the days they cover. */}
      <div className="md:hidden">
        <div className="mb-3 grid grid-cols-2 rounded-xl bg-[var(--raised)] p-1">{PROPERTIES.map(p => <button key={p.id} type="button" onClick={() => setProp(p.id as "r1" | "r2")} className={cn("h-10 rounded-lg text-[14px] font-semibold", prop === p.id ? "bg-[var(--surface)] shadow-[0_1px_2px_rgba(0,0,0,0.08)]" : "text-[var(--muted)]")}>{p.name}</button>)}</div>
        <Card className="p-2">
          <div className="grid grid-cols-7">{["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <div key={i} className="py-1 text-center text-[11.5px] font-semibold text-[var(--muted)]">{d}</div>)}</div>
          {weeks.map(w => (
            <div key={w} className="relative">
              <div className="grid grid-cols-7">{days.slice(w * 7, w * 7 + 7).map(i => (
                <button key={i} type="button" onClick={() => cal.setDay(i)} aria-pressed={cal.day === i} className={cn("flex h-[68px] flex-col items-center rounded-xl pt-1.5", cal.day === i && "bg-[var(--plum-bg)]")}>
                  <span className={cn("num flex size-7 items-center justify-center rounded-full text-[13.5px] font-semibold", i === CAL_TODAY_INDEX && "bg-[var(--ink)] text-[var(--surface)]")}>{dayLabel(i).day}</span>
                </button>
              ))}</div>
              {RESERVATIONS.filter(r => r.property === prop && r.start < w * 7 + 7 && r.end > w * 7).map(r => {
                const s = Math.max(r.start, w * 7) - w * 7, e = Math.min(r.end, w * 7 + 7) - w * 7;
                const left = ((s + (r.start >= w * 7 ? 0.5 : 0)) / 7) * 100, right = ((e + (r.end <= w * 7 + 7 ? 0.5 : 0)) / 7) * 100;
                return <span key={r.id} className={cn("pointer-events-none absolute bottom-2 flex h-6 items-center overflow-hidden px-1.5 text-[10.5px] font-bold", STAY[r.kind], r.start >= w * 7 ? "rounded-l-full" : "", r.end <= w * 7 + 7 ? "rounded-r-full" : "")} style={{ left: `${left}%`, width: `${right - left}%` }}><span className="truncate">{r.guest.split(" ")[0]}</span></span>;
              })}
            </div>
          ))}
        </Card>
        <h2 className={cn(DISPLAY, "mb-2 mt-5 text-[18px] font-semibold")}>{dayLabel(cal.day).dow} {dayLabel(cal.day).day} {dayLabel(cal.day).month}</h2>
        <div className="space-y-2.5">
          {cal.onDay(cal.day).length === 0 && <Card className="p-4 text-center text-[14px] font-semibold text-[var(--ok)]">Both caravans are free</Card>}
          {cal.onDay(cal.day).map(r => <Card key={r.id} className="flex items-center gap-3 p-3"><span className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl text-[12px] font-bold", STAY[r.kind])}>{r.kind === "blocked" || r.kind === "maintenance" ? "—" : initialsOf(r.guest)}</span><div className="min-w-0 flex-1"><p className="truncate text-[14.5px] font-bold">{r.guest}</p><p className="text-[12.5px] text-[var(--muted)]">{PROPERTIES.find(p => p.id === r.property)?.name} · {dayLabel(r.start).day}–{dayLabel(r.end).day} {dayLabel(r.end).month} · {STAY_LABEL[r.kind]}</p></div>{r.amount != null && <span className={cn(DISPLAY, "num text-[16px] font-semibold")}>{inrShort(r.amount)}</span>}</Card>)}
        </div>
      </div>
    </Shell>
  );
}

export default function Hybrid(props: ScreenProps) {
  if (props.screen === "inbox") return <InboxScreen {...props} />;
  if (props.screen === "leads") return <LeadsScreen {...props} />;
  if (props.screen === "calendar") return <CalendarScreen {...props} />;
  return <Home {...props} />;
}

