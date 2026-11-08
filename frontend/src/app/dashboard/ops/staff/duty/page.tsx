"use client";
// Ops › Staff › Who is on duty (owner pick "A", 8 Nov 2026): a week grid, one row per duty, one column per day; night (on
// call) shifts are dark pills; a day with nobody for a duty that works other days is a yellow gap (alerts for it skip to the
// next step of the chain). Phones get a day picker and that day's list. Reads GET /ops/staff, /ops/shifts,
// /ops/shift-overrides; writes POST/DELETE /ops/shifts and /ops/shift-overrides (ops.manage, audited on the server).
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { todayIST, useHydrated } from "@/lib/bookingAgenda";
import { canManageOps, DUTY_LABELS, type OpsStaff } from "@/lib/ops";
import {
  buildWeek, countGaps, dayRange, DUTY_ORDER, mondayOf, shiftWeek, weekDates, WEEKDAYS,
  type CellItem, type DutyRow, type ShiftOverride, type ShiftPattern,
} from "@/lib/opsRoster";
import { AlertTriangle, ChevronLeft, ChevronRight, Moon } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { BottomSheet, Card, EmptyState, Fab, PageHeader, SheetActions, sheetActionCls } from "@/components/ui/kit";
import { OpsNav } from "@/components/ops/OpsNav";
import { StaffTabs } from "@/components/ops/StaffTabs";
import { input, label, Shell } from "@/components/ops/TripSheets";

type Person = Exclude<CellItem, { kind: "gap" }>;
interface Picked { day: number; duty: string; item: Person }
interface AddForm { staffId: string; duty: string; days: number[]; start: string; end: string }

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Check your connection and try again.";
}
const dayNum = (iso: string) => Number(iso.slice(8, 10));
const weekLabel = (monday: string) => {
  const end = new Date(`${shiftWeek(monday, 1)}T00:00:00Z`);
  end.setUTCDate(end.getUTCDate() - 1);
  const f = (d: Date, o: Intl.DateTimeFormatOptions) => d.toLocaleDateString("en-IN", { ...o, timeZone: "UTC" });
  return `${dayNum(monday)}-${f(end, { day: "numeric", month: "short", year: "numeric" })}`;
};

export default function WhoIsOnDutyPage() {
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const { toast } = useToast();
  const session = useSession();
  const manage = canManageOps(session.data?.user?.role);
  const [today, setToday] = useState("");
  const [monday, setMonday] = useState("");
  const [day, setDay] = useState(0);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [add, setAdd] = useState<AddForm | null>(null);

  // Today is read after hydration only: the first client render must match the server's.
  useEffect(() => {
    const t = todayIST();
    setToday(t);
    setMonday(mondayOf(t));
    setDay((new Date(`${t}T00:00:00Z`).getUTCDay() + 6) % 7);
  }, []);

  const staffQ = useQuery<OpsStaff[]>({ queryKey: ["ops-staff", "all"], queryFn: () => api.get("/ops/staff?include_inactive=true").then(r => r.data), staleTime: 30_000, enabled: manage });
  const shiftsQ = useQuery<ShiftPattern[]>({ queryKey: ["ops-shifts"], queryFn: () => api.get("/ops/shifts").then(r => r.data), enabled: manage });
  const overQ = useQuery<ShiftOverride[]>({
    queryKey: ["ops-overrides", monday],
    queryFn: () => api.get("/ops/shift-overrides", { params: { since: dayRange(monday)[0] } }).then(r => r.data),
    enabled: manage && !!monday,
  });
  const rows = useMemo<DutyRow[]>(
    () => (monday && staffQ.data && shiftsQ.data && overQ.data ? buildWeek(monday, shiftsQ.data, overQ.data, staffQ.data) : []),
    [monday, staffQ.data, shiftsQ.data, overQ.data],
  );
  const dates = monday ? weekDates(monday) : [];
  const todayIdx = dates.indexOf(today);
  const activeStaff = (staffQ.data ?? []).filter(s => s.active);

  const done = (title: string) => () => {
    qc.invalidateQueries({ queryKey: ["ops-shifts"] });
    qc.invalidateQueries({ queryKey: ["ops-overrides"] });
    toast({ title, variant: "success" });
    setPicked(null);
    setAdd(null);
  };
  const fail = (e: unknown) => toast({ title: "Not saved", description: errorText(e), variant: "error" });
  const addShift = useMutation({
    mutationFn: (f: AddForm) => api.post("/ops/shifts", { staff_id: f.staffId, duty: f.duty, weekdays: f.days, start: f.start, end: f.end === "00:00" ? "24:00" : f.end }),
    onSuccess: done("Shift added"), onError: fail,
  });
  const removeShift = useMutation({ mutationFn: (id: string) => api.delete(`/ops/shifts/${id}`), onSuccess: done("Shift removed"), onError: fail });
  const addLeave = useMutation({
    mutationFn: ({ staffId, iso }: { staffId: string; iso: string }) => {
      const [starts_at, ends_at] = dayRange(iso);
      return api.post("/ops/shift-overrides", { staff_id: staffId, kind: "leave", starts_at, ends_at });
    },
    onSuccess: done("Marked on leave"), onError: fail,
  });
  const removeLeave = useMutation({ mutationFn: (id: string) => api.delete(`/ops/shift-overrides/${id}`), onSuccess: done("Leave cancelled"), onError: fail });
  const busy = addShift.isPending || removeShift.isPending || addLeave.isPending || removeLeave.isPending;

  const openAdd = (d = day) => {
    const first = activeStaff[0];
    setAdd({ staffId: first?.id ?? "", duty: first?.duties[0]?.duty ?? "caretaker", days: [d], start: "09:00", end: "17:00" });
  };
  const loading = !hydrated || session.status === "loading" || (manage && (staffQ.isPending || shiftsQ.isPending || !monday || overQ.isPending));
  const failed = staffQ.isError || shiftsQ.isError || overQ.isError;
  const gaps = countGaps(rows);

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 p-4 pb-24 sm:p-6">
      <PageHeader title="Who is on duty" subtitle="Weekly shifts. Alerts go first to whoever is on shift." />
      <OpsNav />
      <StaffTabs />
      {loading ? (
        <div className="flex flex-col gap-2" aria-busy="true"><Skeleton className="h-12" /><Skeleton className="h-40" /><Skeleton className="h-40" /></div>
      ) : !manage ? (
        <Card><EmptyState title="Only an owner or manager can set shifts" hint="Ask them to add you to the roster." /></Card>
      ) : failed ? (
        <Card><EmptyState title="Couldn't load the roster" hint="Check your connection, then try again."
          action={<button type="button" className="haip-btn-primary min-h-12" onClick={() => { staffQ.refetch(); shiftsQ.refetch(); overQ.refetch(); }}>Try again</button>} /></Card>
      ) : activeStaff.length === 0 ? (
        <Card><EmptyState title="Add your people first" hint="Shifts are for people on the People tab."
          action={<Link className="haip-btn-primary inline-flex min-h-12 items-center" href="/dashboard/ops/staff">Go to People</Link>} /></Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex h-11 items-center rounded-xl border border-[var(--haip-btn-secondary-border)] bg-[var(--haip-card)]">
              <button type="button" aria-label="Previous week" className="grid size-11 place-items-center text-primary" onClick={() => setMonday(m => shiftWeek(m, -1))}><ChevronLeft size={18} /></button>
              <span className="num px-1 text-[14px] font-semibold">{weekLabel(monday)}</span>
              <button type="button" aria-label="Next week" className="grid size-11 place-items-center text-primary" onClick={() => setMonday(m => shiftWeek(m, 1))}><ChevronRight size={18} /></button>
            </div>
            {monday !== mondayOf(today) && <button type="button" className="haip-btn-secondary min-h-11 px-4 text-[14px]" onClick={() => setMonday(mondayOf(today))}>This week</button>}
            {gaps > 0 && (
              <span className="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 text-[13px] font-semibold text-[var(--haip-status-warning-fg)]">
                <AlertTriangle size={14} />{gaps} {gaps === 1 ? "gap" : "gaps"} this week
              </span>
            )}
            <div className="ml-auto max-lg:hidden"><button type="button" className="haip-btn-primary min-h-11" onClick={() => openAdd()}>Add a shift</button></div>
          </div>
          {!shiftsQ.data?.length && (
            <Card className="p-4 text-[14px] text-[var(--haip-fg-subtle)]">No shifts yet. Add the first one: until then every alert goes to managers, then you.</Card>
          )}

          {/* Desktop: the week grid */}
          <Card className="overflow-hidden p-0 max-lg:hidden">
            <div className="grid grid-cols-[168px_repeat(7,minmax(0,1fr))]">
              <div className="border-b border-[var(--haip-band-border)] bg-[var(--haip-band-bg)] p-2.5 text-[13px] font-semibold text-[var(--haip-fg-subtle)]">Duty</div>
              {dates.map((iso, i) => (
                <div key={iso} className={cn("border-b border-[var(--haip-band-border)] p-2.5 text-[13px] font-semibold",
                  i === todayIdx ? "bg-[var(--haip-accent-light)] text-[var(--haip-accent-ink)]" : "bg-[var(--haip-band-bg)] text-[var(--haip-fg-subtle)]")}>
                  {i === todayIdx ? "Today, " : ""}{WEEKDAYS[i]} {dayNum(iso)}
                </div>
              ))}
              {rows.map(r => (
                <Row key={r.duty} row={r} todayIdx={todayIdx} onPick={(d, item) => setPicked({ day: d, duty: r.duty, item })} onAdd={d => openAdd(d)} />
              ))}
            </div>
          </Card>
          <Legend />

          {/* Phone and tablet: a day picker and that day's list */}
          <div className="flex flex-col gap-3 lg:hidden">
            <div className="grid grid-cols-7 gap-1">
              {dates.map((iso, i) => {
                const gap = countGaps(rows, i) > 0;
                return (
                  <button key={iso} type="button" aria-pressed={i === day} onClick={() => setDay(i)}
                    aria-label={`${WEEKDAYS[i]} ${dayNum(iso)}${i === todayIdx ? ", today" : ""}${gap ? ", has a gap" : ""}`}
                    className={cn("relative flex min-h-14 flex-col items-center justify-center rounded-xl border transition-transform active:scale-[0.96]",
                      i === day ? "border-primary bg-primary text-primary-foreground" : "border-[var(--haip-border)] bg-[var(--haip-card)]")}>
                    <span className="text-[11px] font-semibold opacity-80">{WEEKDAYS[i]}</span>
                    <span className={cn("num text-[17px] font-bold", i === todayIdx && i !== day && "text-[var(--haip-accent)]")}>{dayNum(iso)}</span>
                    {gap && <span aria-hidden className="absolute bottom-1 left-1/2 size-1.5 -translate-x-1/2 rounded-full bg-[var(--haip-status-warning-fg)]" />}
                  </button>
                );
              })}
            </div>
            <Card className="p-0">
              {rows.map(r => (
                <div key={r.duty} className="border-t border-[var(--haip-border)] first:border-t-0">
                  <div className="px-4 pb-0.5 pt-3 text-[13px] font-semibold text-[var(--haip-fg-subtle)]">{r.label}</div>
                  {r.cells[day].length === 0 && <div className="px-4 pb-3 text-[14px] text-[var(--haip-fg-subtle)]">No shift</div>}
                  {r.cells[day].map(item => item.kind === "gap" ? (
                    <div key={item.key} className="mx-3 mb-3 mt-1 flex gap-2 rounded-xl border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] p-3 text-[14px] text-[var(--haip-status-warning-fg)]">
                      <AlertTriangle size={16} className="mt-0.5 shrink-0" /><span><b>Nobody on.</b> Alerts skip to the next person in line.</span>
                    </div>
                  ) : (
                    <button key={item.key} type="button" onClick={() => setPicked({ day, duty: r.duty, item })}
                      className="flex min-h-14 w-full items-center gap-3 px-4 py-2 text-left">
                      <span className="min-w-0 flex-1">
                        <span className={cn("block truncate text-[15px] font-semibold", item.kind === "leave" && "text-[var(--haip-fg-subtle)]")}>{item.name}</span>
                        <span className="flex items-center gap-1.5 text-[13px] text-[var(--haip-fg-subtle)]">
                          {item.kind === "leave" ? "On leave" : item.time}{"note" in item && item.note ? ` · ${item.note}` : ""}
                          {item.kind === "night" && <span className="inline-flex items-center gap-1 rounded-full bg-[var(--haip-nav-field)] px-2 py-px text-[11.5px] font-semibold text-[var(--haip-nav-fg)]"><Moon size={11} className="text-[var(--haip-tile-fg)]" />On call</span>}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              ))}
            </Card>
            <Fab label="Add a shift" onClick={() => openAdd()} />
          </div>
        </>
      )}

      <BottomSheet open={!!picked} onOpenChange={o => !o && setPicked(null)} title={picked?.item.name ?? ""}
        description={picked ? `${DUTY_LABELS[picked.duty] ?? picked.duty} · ${WEEKDAYS[picked.day]} ${dates[picked.day] ? dayNum(dates[picked.day]) : ""}` : undefined}>
        {picked && (
          <div className="flex flex-col gap-3 pb-2">
            <p className="text-[15px]">
              {picked.item.kind === "leave" ? "On leave this day." : `${picked.item.time}${picked.item.kind === "night" ? ", on call overnight" : ""}${picked.item.note ? ` (${picked.item.note})` : ""}.`}
            </p>
            <SheetActions>
              {picked.item.kind === "leave" ? (
                <button type="button" disabled={busy} className={sheetActionCls(true)} onClick={() => picked.item.kind === "leave" && removeLeave.mutate(picked.item.overrideId)}>Cancel the leave</button>
              ) : (
                <>
                  <button type="button" disabled={busy} className={sheetActionCls(false)}
                    onClick={() => addLeave.mutate({ staffId: picked.item.staffId, iso: dates[picked.day] })}>On leave this day</button>
                  {picked.item.shiftId && (
                    <button type="button" disabled={busy} className={sheetActionCls(true)} onClick={() => picked.item.kind !== "leave" && picked.item.shiftId && removeShift.mutate(picked.item.shiftId)}>
                      Remove every {WEEKDAYS[picked.day]}
                    </button>
                  )}
                </>
              )}
            </SheetActions>
          </div>
        )}
      </BottomSheet>

      <Shell open={!!add} onClose={() => setAdd(null)} busy={addShift.isPending} title="Add a shift" submitLabel="Add shift"
        description="Repeats every week on the days you pick. An end before the start runs overnight (on call)."
        onSubmit={() => add && (add.days.length ? addShift.mutate(add) : toast({ title: "Pick at least one day", variant: "error" }))}>
        {add && (
          <>
            <label className={label}>Person
              <select className={input} required value={add.staffId} onChange={e => {
                const s = activeStaff.find(x => x.id === e.target.value);
                setAdd({ ...add, staffId: e.target.value, duty: s?.duties[0]?.duty ?? add.duty });
              }}>
                {activeStaff.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
            <label className={label}>Duty
              <select className={input} value={add.duty} onChange={e => setAdd({ ...add, duty: e.target.value })}>
                {DUTY_ORDER.map(d => <option key={d} value={d}>{DUTY_LABELS[d] ?? d}</option>)}
              </select>
            </label>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-[14px] font-semibold">Days</legend>
              <div className="grid grid-cols-7 gap-1">
                {WEEKDAYS.map((w, i) => {
                  const on = add.days.includes(i);
                  return (
                    <button key={w} type="button" aria-pressed={on} onClick={() => setAdd({ ...add, days: on ? add.days.filter(x => x !== i) : [...add.days, i].sort() })}
                      className={cn("min-h-11 rounded-xl border text-[13px] font-semibold", on ? "border-primary bg-primary text-primary-foreground" : "border-[var(--haip-border)] bg-[var(--haip-card)]")}>
                      {w}
                    </button>
                  );
                })}
              </div>
            </fieldset>
            <div className="grid grid-cols-2 gap-3">
              <label className={label}>Starts<input className={input} type="time" required value={add.start} onChange={e => setAdd({ ...add, start: e.target.value })} /></label>
              <label className={label}>Ends<input className={input} type="time" required value={add.end} onChange={e => setAdd({ ...add, end: e.target.value })} /></label>
            </div>
          </>
        )}
      </Shell>
    </div>
  );
}

function Row({ row, todayIdx, onPick, onAdd }: { row: DutyRow; todayIdx: number; onPick: (day: number, item: Person) => void; onAdd: (day: number) => void }) {
  return (
    <>
      <div className="flex flex-col justify-center gap-0.5 border-t border-[var(--haip-border)] px-3 py-2.5">
        <b className="text-[14px]">{row.label}</b>
        <span className="truncate text-[12px] text-[var(--haip-fg-subtle)]">{row.people.join(", ") || "No shifts yet"}</span>
      </div>
      {row.cells.map((cell, d) => (
        <div key={d} className={cn("group flex min-h-[72px] flex-col gap-1 border-l border-t border-[var(--haip-border)] p-1.5", d === todayIdx && "bg-[var(--haip-primary-tint)]")}>
          {cell.map(item => <Pill key={item.key} item={item} onClick={item.kind === "gap" ? () => onAdd(d) : () => onPick(d, item)} />)}
          {cell.length === 0 && (
            <button type="button" aria-label={`Add a ${row.label} shift on ${WEEKDAYS[d]}`} onClick={() => onAdd(d)}
              className="min-h-11 flex-1 rounded-lg text-[13px] font-semibold text-primary opacity-0 transition-opacity focus:opacity-100 group-hover:opacity-100">+ Add</button>
          )}
        </div>
      ))}
    </>
  );
}

function Pill({ item, onClick }: { item: CellItem; onClick: () => void }) {
  const base = "flex min-h-7 w-full items-center gap-1.5 rounded-full px-2 text-left text-[12px] font-semibold whitespace-nowrap overflow-hidden";
  if (item.kind === "gap") {
    return <button type="button" onClick={onClick} title="Nobody on. Tap to add a shift."
      className={cn(base, "border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]")}>Nobody on</button>;
  }
  const first = item.name.split(" ")[0];
  if (item.kind === "leave") {
    return <button type="button" onClick={onClick} className={cn(base, "border border-dashed border-[var(--haip-border)] font-medium text-[var(--haip-fg-subtle)]")}>{first} · leave</button>;
  }
  const label = `${item.name}, ${item.time}${item.kind === "night" ? ", on call" : ""}${item.note ? `, ${item.note}` : ""}`;
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
      className={cn(base, item.kind === "night" ? "bg-[var(--haip-nav-field)] text-[var(--haip-nav-fg)]" : "bg-[var(--haip-band-bg)] text-[var(--haip-band-fg)]")}>
      {item.kind === "night" && <Moon size={11} className="shrink-0 text-[var(--haip-tile-fg)]" />}
      <span className="truncate">{first} <span className="num font-medium opacity-80">{item.time}</span></span>
    </button>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-4 text-[12.5px] text-[var(--haip-fg-subtle)] max-lg:hidden">
      <span className="rounded-full bg-[var(--haip-band-bg)] px-2 py-0.5 font-semibold text-[var(--haip-band-fg)]">Shift</span>
      <span className="inline-flex items-center gap-1 rounded-full bg-[var(--haip-nav-field)] px-2 py-0.5 font-semibold text-[var(--haip-nav-fg)]"><Moon size={11} className="text-[var(--haip-tile-fg)]" />On call at night</span>
      <span className="rounded-full border border-dashed border-[var(--haip-border)] px-2 py-0.5">On leave</span>
      <span className="rounded-full border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-2 py-0.5 font-semibold text-[var(--haip-status-warning-fg)]">Nobody on: alerts skip to the next person</span>
      <span className="ml-auto">Times in IST</span>
    </div>
  );
}
