"use client";
// Yaad calendar, layout A (owner pick 15 Nov): month grid + the open event's panel (desktop), an agenda list + the panel as
// a sheet (phones). Plans said on calls arrive as suggestions (dashed) to Add or Dismiss. Every event has notes / remarks and
// people (stakeholders). "Also in Google Calendar" is the person's choice per event; the push to Google is a later step.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { SourceChip } from "./Cite";
import { ChevronLeft, ChevronRight, Plus, X } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Drawer } from "@/components/ui/kit";
import { dayLabel, monthGrid, shiftMonth, type CalEvent } from "@/lib/personal";
import { openOAuth } from "@/components/marketing/studio/types";
import { useCalendar, useDeleteEvent, useDisconnectGoogle, useGoogleCalendar, useSaveEvent } from "./hooks";

const field = "min-h-11 w-full rounded-xl border border-[var(--y-line-strong)] bg-[var(--y-card)] px-3 text-[16px] text-[var(--y-ink)] focus:border-[var(--y-ink)] focus:outline-none";
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
type Draft = Partial<CalEvent> & { title: string; day: string };

function pill(e: CalEvent) {
  return cn("block w-full truncate rounded-md px-1.5 py-0.5 text-left text-[11.5px] font-semibold",
    e.status === "suggested" ? "border border-dashed border-[var(--y-line-strong)] bg-[var(--y-card)] text-[var(--y-ink-2)]"
      : e.google ? "bg-[var(--y-folder-sky)]/15 text-[var(--y-ink)]" : "bg-[var(--y-soft)] text-[var(--y-soft-ink)]");
}

/** lg and up: the event sits in the side panel; below it, in a sheet (the sheet portals out, so it must not render on lg). */
function useWide(): boolean {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const on = () => setWide(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return wide;
}

export function CalendarView({ initialMonth }: { initialMonth: string }) {
  const [month, setMonth] = useState(initialMonth);
  const wide = useWide();
  const { toast } = useToast();
  useEffect(() => { // back from Google's sign-in: say how it went once, then clean the address
    const q = new URLSearchParams(window.location.search);
    const g = q.get("google");
    if (!g) return;
    if (g === "connected") toast({ variant: "success", title: "Google Calendar connected", description: "Events you switch on go there now." });
    else toast({ variant: "error", title: "Couldn't connect Google Calendar", description: q.get("reason") ?? "Try again." });
    window.history.replaceState(null, "", window.location.pathname);
  }, [toast]);
  const [open, setOpen] = useState<Draft | null>(null);
  const q = useCalendar(month);
  const events = q.data?.events ?? [];
  const today = q.data?.today ?? "";
  const byDay = useMemo(() => {
    const m = new Map<string, CalEvent[]>();
    for (const e of events) m.set(e.day, [...(m.get(e.day) ?? []), e]);
    return m;
  }, [events]);
  const title = new Date(`${month}-01T00:00:00Z`).toLocaleDateString("en-IN", { month: "long", year: "numeric", timeZone: "UTC" });
  const suggestions = events.filter(e => e.status === "suggested");
  const newEvent = (day?: string) => setOpen({ title: "", day: day ?? today ?? `${month}-01`, start_time: null, place: "", notes: "", people: [], google: false });

  const header = (
    <div className="flex flex-wrap items-center gap-2">
      <h1 className="text-[24px] font-semibold tracking-[-0.02em] max-md:sr-only sm:text-[28px]">{title}</h1>
      <span className="text-[16px] font-semibold md:hidden">{title}</span>
      <button type="button" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}
        className="y-press flex size-10 items-center justify-center rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)]"><ChevronLeft size={16} aria-hidden /></button>
      <button type="button" aria-label="Next month" onClick={() => setMonth(shiftMonth(month, 1))}
        className="y-press flex size-10 items-center justify-center rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)]"><ChevronRight size={16} aria-hidden /></button>
      <span className="ml-auto hidden gap-3 text-[12.5px] text-[var(--y-ink-2)] lg:flex">
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-5 rounded bg-[var(--y-soft)]" aria-hidden /> In Yaad</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-5 rounded bg-[var(--y-folder-sky)]/15" aria-hidden /> Also in Google</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-5 rounded border border-dashed border-[var(--y-line-strong)]" aria-hidden /> Suggested from a call</span>
      </span>
      <GoogleButton />
      <button type="button" onClick={() => newEvent()} className="y-press ml-auto inline-flex min-h-10 items-center gap-1.5 rounded-full bg-[var(--y-brand)] px-4 text-[14px] font-semibold text-[var(--y-on-brand)] lg:ml-0">
        <Plus size={15} aria-hidden /> Event
      </button>
    </div>
  );

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-start lg:gap-6">
      <div className="grid min-w-0 gap-4">
        {header}
        {q.isPending ? (
          <div className="h-[520px] animate-pulse rounded-[20px] bg-[var(--y-line)]" aria-busy="true" aria-label="Loading calendar" />
        ) : q.isError ? (
          <div className="rounded-[20px] border border-[var(--y-line)] bg-[var(--y-card)] p-6 text-center">
            <p className="font-semibold">Couldn't load your calendar</p>
            <button type="button" onClick={() => q.refetch()} className="y-press mt-3 min-h-11 rounded-full bg-[var(--y-brand)] px-5 text-[15px] font-semibold text-[var(--y-on-brand)]">Try again</button>
          </div>
        ) : (
          <>
            {suggestions.length > 0 && (
              <p className="rounded-[14px] bg-[var(--y-soft)] px-4 py-2.5 text-[14px] text-[var(--y-soft-ink)]">
                {suggestions.length} plan{suggestions.length === 1 ? "" : "s"} from your calls to add. Open one to Add or Dismiss it.
              </p>
            )}
            <div className="hidden overflow-hidden rounded-[20px] border border-[var(--y-line)] bg-[var(--y-card)] md:block">
              <div className="grid grid-cols-7 border-b border-[var(--y-line)] text-[12.5px] font-semibold text-[var(--y-ink-2)]">
                {WEEKDAYS.map(d => <div key={d} className="px-2 py-2">{d}</div>)}
              </div>
              <div className="grid grid-cols-7">
                {monthGrid(month).map(day => {
                  const inMonth = day.startsWith(month);
                  return (
                    <div key={day} className={cn("flex min-h-[96px] flex-col gap-1 border-b border-r border-[var(--y-line)] p-1.5", !inMonth && "bg-[var(--y-canvas)]/60")}>
                      <button type="button" onClick={() => newEvent(day)} aria-label={`New event on ${dayLabel(day)}`}
                        className={cn("self-start rounded-full px-1.5 text-[12.5px]", day === today ? "bg-[var(--y-brand)] font-bold text-[var(--y-on-brand)]" : inMonth ? "text-[var(--y-ink)]" : "text-[var(--y-ink-3)]")}>
                        {Number(day.slice(8))}
                      </button>
                      {(byDay.get(day) ?? []).slice(0, 3).map(e => (
                        <button key={e.id} type="button" onClick={() => setOpen(e)} className={cn(pill(e), open?.id === e.id && "ring-2 ring-[var(--y-ink)]")}>
                          {e.start_time && <span className="font-normal">{e.start_time} </span>}{e.title}
                        </button>
                      ))}
                      {(byDay.get(day)?.length ?? 0) > 3 && <span className="px-1.5 text-[11px] text-[var(--y-ink-3)]">+{byDay.get(day)!.length - 3} more</span>}
                    </div>
                  );
                })}
              </div>
            </div>
            <Agenda events={events.filter(e => e.day.startsWith(month))} onOpen={setOpen} />
          </>
        )}
      </div>
      <aside className="sticky top-0 hidden rounded-[24px] border border-[var(--y-line)] bg-[var(--y-card)] p-5 shadow-[var(--y-shadow)] lg:block" aria-label="Event">
        {open ? <EventForm key={open.id ?? "new"} draft={open} onDone={() => setOpen(null)} />
          : <p className="py-10 text-center text-[14.5px] text-[var(--y-ink-2)]">Pick an event, or a day to add one.</p>}
      </aside>
      {!wide && (
        <Drawer open={!!open} onOpenChange={o => !o && setOpen(null)} title={open?.id ? "Event" : "New event"} className="yaad">
          {open && <EventForm key={open.id ?? "new"} draft={open} onDone={() => setOpen(null)} />}
        </Drawer>
      )}
    </div>
  );
}

/** Connect / disconnect Google Calendar. Only events switched on go there. */
function GoogleButton() {
  const g = useGoogleCalendar();
  const off = useDisconnectGoogle();
  const { toast } = useToast();
  if (!g.data?.available) return null;
  if (g.data.connected) {
    return (
      <button type="button" disabled={off.isPending}
        onClick={() => { if (window.confirm("Stop sending events to Google Calendar? Copies already there stay.")) off.mutate(undefined, { onSuccess: () => toast({ variant: "success", title: "Google Calendar disconnected" }) }); }}
        className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-3.5 text-[13.5px] font-medium">
        <span aria-hidden className="size-2 rounded-full bg-[var(--y-folder-leaf)]" /> Google Calendar connected
      </button>
    );
  }
  return (
    <button type="button" onClick={() => openOAuth("/me/calendar/google/oauth-start")}
      className="y-press inline-flex min-h-10 items-center rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-3.5 text-[13.5px] font-medium">
      Connect Google Calendar
    </button>
  );
}

/** Phones: the month as a list of days (the grid is too small to read at 375px). */
function Agenda({ events, onOpen }: { events: CalEvent[]; onOpen: (e: CalEvent) => void }) {
  if (!events.length) {
    return <p className="rounded-[20px] border border-dashed border-[var(--y-line-strong)] bg-[var(--y-card)] px-6 py-10 text-center text-[14.5px] text-[var(--y-ink-2)] md:hidden">Nothing this month. Plans said on your calls show up here to add.</p>;
  }
  const days = Array.from(new Set(events.map(e => e.day)));
  return (
    <div className="grid gap-4 md:hidden">
      {days.map(d => (
        <section key={d} aria-label={dayLabel(d)}>
          <h2 className="mb-1.5 text-[13px] font-semibold text-[var(--y-ink-2)]">{dayLabel(d)}</h2>
          <ul className="grid gap-1.5">
            {events.filter(e => e.day === d).map(e => (
              <li key={e.id}>
                <button type="button" onClick={() => onOpen(e)} className={cn(pill(e), "min-h-12 px-3 py-2 text-[14.5px]")}>
                  {e.start_time && <span className="font-normal">{e.start_time} · </span>}{e.title}
                  {e.status === "suggested" && <span className="ml-1 font-normal">(suggested)</span>}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function EventForm({ draft, onDone }: { draft: Draft; onDone: () => void }) {
  const { toast } = useToast();
  const save = useSaveEvent();
  const del = useDeleteEvent();
  const [d, setD] = useState<Draft>(draft);
  const [person, setPerson] = useState("");
  const suggested = d.status === "suggested";
  const run = (patch: Partial<CalEvent>, msg: string) =>
    save.mutate({ id: d.id, ...patch }, {
      onSuccess: () => { toast({ variant: "success", title: msg }); onDone(); },
      onError: e => toast({ variant: "error", title: "Couldn't save", description: (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Try again." }),
    });
  const body = { title: d.title.trim(), day: d.day, start_time: d.start_time || "", place: d.place ?? "", notes: d.notes ?? "", people: d.people ?? [], google: !!d.google };
  const addPerson = () => { const n = person.trim(); if (n) setD({ ...d, people: [...(d.people ?? []), { name: n, role: "" }] }); setPerson(""); };

  return (
    <form className="grid gap-3.5" onSubmit={e => { e.preventDefault(); if (d.title.trim()) run(body, suggested ? "Added to your calendar" : "Saved"); }}>
      {suggested && <p className="rounded-xl bg-[var(--y-soft)] px-3 py-2 text-[13px] text-[var(--y-soft-ink)]">Suggested from a call. Change anything, then Add.</p>}
      <label className="grid gap-1 text-[12.5px] font-semibold text-[var(--y-ink-2)]">Event
        <input value={d.title} maxLength={160} onChange={e => setD({ ...d, title: e.target.value })} className={cn(field, "font-semibold")} />
      </label>
      <div className="grid grid-cols-2 gap-2.5">
        <label className="grid gap-1 text-[12.5px] font-semibold text-[var(--y-ink-2)]">Date
          <input type="date" value={d.day} onChange={e => setD({ ...d, day: e.target.value })} className={field} />
        </label>
        <label className="grid gap-1 text-[12.5px] font-semibold text-[var(--y-ink-2)]">Time
          <input type="time" value={d.start_time ?? ""} onChange={e => setD({ ...d, start_time: e.target.value || null })} className={field} />
        </label>
      </div>
      <label className="grid gap-1 text-[12.5px] font-semibold text-[var(--y-ink-2)]">Place
        <input value={d.place ?? ""} maxLength={160} onChange={e => setD({ ...d, place: e.target.value })} className={field} />
      </label>
      <div className="grid gap-1.5">
        <span className="text-[12.5px] font-semibold text-[var(--y-ink-2)]">People / stakeholders</span>
        <div className="flex flex-wrap gap-1.5">
          {(d.people ?? []).map((p, i) => (
            <span key={`${p.name}-${i}`} className="inline-flex min-h-8 items-center gap-1 rounded-full border border-[var(--y-line-strong)] pl-3 pr-1 text-[13px]">
              {p.name}{p.role && <span className="text-[var(--y-ink-3)]">· {p.role}</span>}
              <button type="button" aria-label={`Remove ${p.name}`} onClick={() => setD({ ...d, people: (d.people ?? []).filter((_, j) => j !== i) })}
                className="flex size-7 items-center justify-center rounded-full text-[var(--y-ink-3)]"><X size={12} aria-hidden /></button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <label className="sr-only" htmlFor="event-person">Add a person</label>
          <input id="event-person" value={person} maxLength={80} onChange={e => setPerson(e.target.value)} placeholder="Add a person"
            onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addPerson(); } }} className={field} />
          <button type="button" onClick={addPerson} className="y-press min-h-11 shrink-0 rounded-full border border-[var(--y-line-strong)] px-3.5 text-[14px] font-medium">Add</button>
        </div>
      </div>
      <label className="grid gap-1 text-[12.5px] font-semibold text-[var(--y-ink-2)]">Notes / remarks
        <textarea rows={5} value={d.notes ?? ""} maxLength={4000} onChange={e => setD({ ...d, notes: e.target.value })} className={cn(field, "py-2.5 leading-relaxed")} />
      </label>
      <label className="flex items-center justify-between gap-3 rounded-[14px] bg-[var(--y-canvas)] px-3.5 py-3 text-[14px] font-semibold">
        Also in Google Calendar
        <input type="checkbox" role="switch" checked={!!d.google} onChange={e => setD({ ...d, google: e.target.checked })} className="size-5 accent-[var(--y-brand)]" />
      </label>
      <GoogleNote d={d} />
      {d.call_id && (d.source ? (
        <p className="text-[13.5px] text-[var(--y-ink-2)]">Said on the call<SourceChip n={1} quote={d.source.quote} at={d.source.at} callId={d.call_id} /></p>
      ) : <Link href={`/dashboard/me/calls/${d.call_id}`} className="text-[13.5px] font-medium text-[var(--y-ink-2)] underline">From the call ↗</Link>)}
      <div className="mt-1 flex flex-wrap gap-2">
        {d.id && (
          <button type="button" disabled={del.isPending}
            onClick={() => { if (window.confirm(`Delete “${d.title}”?`)) del.mutate(d.id!, { onSuccess: () => { toast({ variant: "success", title: "Deleted" }); onDone(); } }); }}
            className="y-press min-h-11 rounded-full border border-[var(--y-late)] px-4 text-[14px] font-semibold text-[var(--y-late)]">Delete</button>
        )}
        {suggested && (
          <button type="button" onClick={() => run({ status: "dismissed" }, "Dismissed")} className="y-press min-h-11 rounded-full border border-[var(--y-line-strong)] px-4 text-[14px] font-medium">Dismiss</button>
        )}
        <button type="submit" disabled={!d.title.trim() || save.isPending}
          className="y-press min-h-11 flex-1 rounded-full bg-[var(--y-brand)] text-[15px] font-semibold text-[var(--y-on-brand)] disabled:opacity-50">
          {save.isPending ? "Saving…" : suggested ? "Add" : "Save"}
        </button>
      </div>
    </form>
  );
}

/** Where this event stands with Google: only shown once the person switched it on. */
function GoogleNote({ d }: { d: Draft }) {
  const g = useGoogleCalendar();
  if (!d.google) return null;
  const note = !g.data?.connected ? "Connect Google Calendar (top of the page) to send it."
    : d.google_error ? d.google_error
    : d.google_synced ? "In your Google Calendar. Changes here update it; deleting here removes it there."
    : "Goes to your Google Calendar when you save.";
  return <p className={cn("-mt-2 text-[12px]", d.google_error ? "text-[var(--y-late)]" : "text-[var(--y-ink-3)]")}>{note}</p>;
}
