"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Calendar, Plus, RefreshCw, Trash2, Copy, X, CheckCircle2, AlertCircle } from "@/lib/icons";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/ui/page";
import { CalendarActivity } from "@/components/settings/CalendarActivity";

interface Feed {
  id: string;
  property_id: string;
  property_name: string | null;
  name: string;
  has_import: boolean;
  import_hint: string | null;
  export_url: string;
  is_active: boolean;
  last_synced_at: string | null;
  last_status: "ok" | "error" | null;
  last_error: string | null;
  last_event_count: number | null;
  last_conflicts: number;
  vehicles: { property_id: string; property_name: string | null; keywords: string[] }[];
  needs_vehicle: number;
  bookings: number;
}

interface Property { id: string; name: string }

// keywords: property id -> comma-separated words that mean "this event is for that vehicle"
interface FormState { property_id: string; name: string; import_url: string; feedId?: string; keywords: Record<string, string> }

function vehiclesPayload(keywords: Record<string, string>): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [pid, raw] of Object.entries(keywords)) {
    const words = raw.split(",").map(w => w.trim()).filter(Boolean);
    if (words.length) out[pid] = words;
  }
  return out;
}

const PRESETS = ["Airbnb", "Booking.com", "Google Calendar", "MakeMyTrip", "Agoda", "Other"];

function ago(iso: string | null): string {
  if (!iso) return "never";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
}

function errText(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
}

export default function CalendarSyncPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [form, setForm] = useState<FormState | null>(null);

  const { data: feeds = [], isLoading } = useQuery<Feed[]>({
    queryKey: ["ical-feeds"],
    queryFn: () => api.get("/ical-feeds").then(r => r.data),
  });
  const { data: properties = [] } = useQuery<Property[]>({
    queryKey: ["properties"],
    queryFn: () => api.get("/properties").then(r => r.data),
    staleTime: 60_000,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["ical-feeds"] });

  const saveMutation = useMutation({
    mutationFn: (f: FormState) =>
      f.feedId
        ? api.patch(`/ical-feeds/${f.feedId}`, { name: f.name, import_url: f.import_url, vehicles: vehiclesPayload(f.keywords) })
        : api.post("/ical-feeds", { property_id: f.property_id, name: f.name, import_url: f.import_url || null, vehicles: vehiclesPayload(f.keywords) }),
    onSuccess: res => {
      refresh();
      setForm(null);
      const sync = res.data?.sync;
      if (sync?.status === "error") toast({ variant: "error", title: "Saved, but the link could not be read", description: sync.error });
      else toast({ variant: "success", title: "Calendar link saved" });
    },
    onError: e => toast({ variant: "error", title: errText(e, "Could not save") }),
  });

  const syncMutation = useMutation({
    mutationFn: (id: string) => api.post(`/ical-feeds/${id}/sync`),
    onSuccess: res => {
      refresh();
      const s = res.data?.sync;
      if (s?.status === "error") toast({ variant: "error", title: "Could not read the calendar", description: s.error });
      else toast({ variant: "success", title: "Calendar read", description: `${s?.events ?? 0} reservations found` });
    },
    onError: e => toast({ variant: "error", title: errText(e, "Sync failed") }),
  });

  const toggleMutation = useMutation({
    mutationFn: (f: Feed) => api.patch(`/ical-feeds/${f.id}`, { is_active: !f.is_active }),
    onSuccess: refresh,
  });

  const regenMutation = useMutation({
    mutationFn: (id: string) => api.post(`/ical-feeds/${id}/regenerate`),
    onSuccess: () => { refresh(); toast({ variant: "success", title: "New export link created", description: "Paste it into the other calendar. The old one has stopped working." }); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/ical-feeds/${id}`),
    onSuccess: () => { refresh(); toast({ variant: "success", title: "Link removed" }); },
  });

  function copy(text: string) {
    navigator.clipboard?.writeText(text).then(
      () => toast({ variant: "success", title: "Link copied" }),
      () => toast({ variant: "error", title: "Could not copy. Select the link and copy it by hand." }),
    );
  }

  const byProperty = properties
    .map(p => ({ p, items: feeds.filter(f => f.property_id === p.id) }))
    .filter(g => g.items.length > 0);

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <PageHeader
        title="Calendar sync"
        subtitle="Keep Airbnb, Booking.com and Google Calendar in step with your bookings"
        actions={
        <button
          onClick={() => setForm({ property_id: properties[0]?.id ?? "", name: "Airbnb", import_url: "", keywords: {} })}
          disabled={properties.length === 0}
          className="flex items-center gap-1.5 text-xs bg-primary text-white px-3 py-1.5 rounded-lg font-medium hover:bg-primary disabled:opacity-40 transition-colors"
        >
          <Plus size={13} /> Add calendar link
        </button>
        }
      />

      <div className="bg-[var(--haip-primary-tint)] border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] rounded-xl p-4 text-xs text-[var(--accent-foreground)] space-y-1.5">
        <p className="font-semibold">How it works</p>
        <p><b>Their calendar into HAIP:</b> paste the calendar (iCal) link from Airbnb or Booking.com. Their reservations block those dates here, so nobody books them twice.</p>
        <p><b>HAIP into their calendar:</b> copy the HAIP link below and add it in Airbnb, Booking.com or Google Calendar (&ldquo;import calendar&rdquo; or &ldquo;from URL&rdquo;). Your bookings then block those dates there.</p>
        <p className="text-primary">Calendar links share dates only, never guest names or prices. Each side refreshes on its own schedule, usually every few hours, so a new booking can take a while to appear. For Google, use the calendar&apos;s &ldquo;secret address in iCal format&rdquo;.</p>
      </div>

      {isLoading ? (
        <div className="space-y-3">{Array.from({ length: 2 }).map((_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)}</div>
      ) : feeds.length === 0 ? (
        <div className="text-center py-14 text-[var(--haip-fg-subtle)] text-sm">
          No calendar links yet. Click &ldquo;Add calendar link&rdquo; to connect your first one.
        </div>
      ) : (
        byProperty.map(({ p, items }) => (
          <section key={p.id} className="space-y-2">
            <h2 className="text-xs font-semibold text-[var(--haip-fg-subtle)] uppercase tracking-wide">{p.name}</h2>
            {items.map(f => (
              <div key={f.id} className="bg-white border border-[var(--haip-border)] rounded-xl p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-semibold text-[var(--haip-fg)]">{f.name}</p>
                  {!f.is_active && <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-subtle)]">Paused</span>}
                  <div className="ml-auto flex items-center gap-1">
                    {f.has_import && (
                      <button
                        onClick={() => syncMutation.mutate(f.id)}
                        disabled={syncMutation.isPending}
                        className="flex items-center gap-1 text-[11px] text-[var(--haip-fg-muted)] border border-[var(--haip-border)] hover:bg-[var(--haip-surface)] px-2 py-1 rounded-lg"
                      >
                        <RefreshCw size={11} /> Sync now
                      </button>
                    )}
                    <button
                      onClick={() => setForm({
                        property_id: f.property_id, name: f.name, import_url: "", feedId: f.id,
                        keywords: Object.fromEntries(f.vehicles.map(v => [v.property_id, v.keywords.join(", ")])),
                      })}
                      className="text-[11px] text-[var(--haip-fg-muted)] border border-[var(--haip-border)] hover:bg-[var(--haip-surface)] px-2 py-1 rounded-lg"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => toggleMutation.mutate(f)}
                      className="text-[11px] text-[var(--haip-fg-muted)] border border-[var(--haip-border)] hover:bg-[var(--haip-surface)] px-2 py-1 rounded-lg"
                    >
                      {f.is_active ? "Pause" : "Resume"}
                    </button>
                    <button
                      onClick={() => { if (confirm(`Remove ${f.name}? Dates it blocked in HAIP will be freed.`)) deleteMutation.mutate(f.id); }}
                      aria-label={`Remove ${f.name}`}
                      className="w-7 h-7 rounded-lg flex items-center justify-center text-[var(--haip-fg-subtle)] hover:text-red-500 hover:bg-red-50"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>

                <div className="text-xs">
                  <p className="text-[var(--haip-fg-subtle)] font-medium mb-1">Their calendar into HAIP</p>
                  {f.has_import ? (
                    <div className="flex items-center gap-2 flex-wrap">
                      {f.last_status === "ok" && <CheckCircle2 size={13} className="text-green-600" />}
                      {f.last_status === "error" && <AlertCircle size={13} className="text-red-500" />}
                      <span className="text-[var(--haip-fg-muted)]">Reading {f.import_hint}</span>
                      <span className="text-[var(--haip-fg-subtle)]">· last read {ago(f.last_synced_at)}</span>
                      {f.last_status === "ok" && <span className="text-[var(--haip-fg-subtle)]">· {f.last_event_count ?? 0} reservations</span>}
                    </div>
                  ) : (
                    <p className="text-[var(--haip-fg-subtle)]">No link added. Edit this entry to paste the calendar link from {f.name}.</p>
                  )}
                  {f.last_status === "error" && f.last_error && <p className="text-red-600 mt-1">{f.last_error}</p>}
                  {f.vehicles.length > 0 && (
                    <p className="text-[var(--haip-fg-subtle)] mt-1">
                      Shared calendar: {f.vehicles.map(v => `${v.property_name ?? "Vehicle"} (${v.keywords.join(", ")})`).join(" · ")}
                    </p>
                  )}
                  {f.vehicles.length > 0 && (
                    <p className="text-[var(--haip-fg-subtle)] mt-1">
                      {f.bookings} booking{f.bookings === 1 ? "" : "s"} made from this calendar. An event with a guest name, phone, total and dates becomes a booking;
                      if it names no vehicle it waits on the &ldquo;Unassigned&rdquo; vehicle until you pick one at check-in.
                    </p>
                  )}
                  {f.vehicles.length > 0 && <div className="mt-1.5"><CalendarActivity feedId={f.id} /></div>}
                  {f.needs_vehicle > 0 && (
                    <p className="text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-2 py-1 mt-1.5">
                      {f.needs_vehicle} event{f.needs_vehicle > 1 ? "s are" : " is"} missing details for a booking (name, phone or total) and name no vehicle. Every vehicle is held until you complete {f.needs_vehicle > 1 ? "them" : "it"} in Google Calendar.
                    </p>
                  )}
                  {f.last_conflicts > 0 && (
                    <p className="text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-2 py-1 mt-1.5">
                      {f.last_conflicts} reservation{f.last_conflicts > 1 ? "s" : ""} here overlap{f.last_conflicts > 1 ? "" : "s"} a HAIP booking. A task was added to My Day.
                    </p>
                  )}
                </div>

                <div className="text-xs">
                  <p className="text-[var(--haip-fg-subtle)] font-medium mb-1">HAIP calendar for {f.name} to read</p>
                  <div className="flex items-center gap-2">
                    <input
                      readOnly
                      value={f.export_url}
                      onFocus={e => e.currentTarget.select()}
                      className="flex-1 min-w-0 text-[11px] font-mono bg-[var(--haip-surface)] border border-[var(--haip-border)] rounded-lg px-2 py-1.5 text-[var(--haip-fg-muted)]"
                    />
                    <button onClick={() => copy(f.export_url)} className="flex items-center gap-1 text-[11px] text-[var(--haip-fg-muted)] border border-[var(--haip-border)] hover:bg-[var(--haip-surface)] px-2 py-1.5 rounded-lg">
                      <Copy size={11} /> Copy
                    </button>
                    <button
                      onClick={() => { if (confirm("Create a new link? The current one stops working, so you must paste the new one into the other calendar.")) regenMutation.mutate(f.id); }}
                      className="text-[11px] text-[var(--haip-fg-muted)] border border-[var(--haip-border)] hover:bg-[var(--haip-surface)] px-2 py-1.5 rounded-lg"
                    >
                      New link
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </section>
        ))
      )}

      {form && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md max-h-[calc(100dvh-2rem)] overflow-y-auto p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[var(--haip-fg)]">{form.feedId ? "Edit calendar link" : "Add calendar link"}</h3>
              <button onClick={() => setForm(null)} aria-label="Close"><X size={16} className="text-[var(--haip-fg-subtle)]" /></button>
            </div>
            <div className="space-y-3 mb-5">
              {!form.feedId && (
                <div>
                  <label className="block text-xs font-semibold text-[var(--haip-fg-subtle)] mb-1">Property</label>
                  <select
                    value={form.property_id}
                    onChange={e => setForm(f => f ? { ...f, property_id: e.target.value } : f)}
                    className="w-full text-sm border border-[var(--haip-border)] rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                </div>
              )}
              <div>
                <label className="block text-xs font-semibold text-[var(--haip-fg-subtle)] mb-1">Which calendar is this?</label>
                <input
                  list="ical-presets"
                  value={form.name}
                  onChange={e => setForm(f => f ? { ...f, name: e.target.value } : f)}
                  maxLength={80}
                  className="w-full text-sm border border-[var(--haip-border)] rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
                />
                <datalist id="ical-presets">{PRESETS.map(p => <option key={p} value={p} />)}</datalist>
              </div>
              <div>
                <label className="block text-xs font-semibold text-[var(--haip-fg-subtle)] mb-1">
                  Their calendar link (iCal / .ics){form.feedId ? " - leave blank to keep the saved one" : ""}
                </label>
                <input
                  value={form.import_url}
                  onChange={e => setForm(f => f ? { ...f, import_url: e.target.value } : f)}
                  placeholder="https://www.airbnb.com/calendar/ical/....ics"
                  className="w-full text-sm border border-[var(--haip-border)] rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
                />
                <p className="text-[11px] text-[var(--haip-fg-subtle)] mt-1">
                  Optional. Leave empty if you only want to send HAIP bookings to this calendar. Treat the link like a password.
                </p>
              </div>
              {properties.length > 1 && (
                <div>
                  <label className="block text-xs font-semibold text-[var(--haip-fg-subtle)] mb-1">One calendar for several vehicles? (optional)</label>
                  <p className="text-[11px] text-[var(--haip-fg-subtle)] mb-2">
                    Type the words that appear in an event for each vehicle, separated by commas, e.g. &ldquo;white, white ratha&rdquo;. Leave a vehicle blank if it is not in this calendar.
                    An event that names no vehicle holds all of them and adds a task.
                  </p>
                  <div className="space-y-2">
                    {properties.map(p => (
                      <div key={p.id} className="flex items-center gap-2">
                        <span className="w-28 shrink-0 text-xs text-[var(--haip-fg-muted)] truncate" title={p.name}>{p.name}</span>
                        <input
                          value={form.keywords[p.id] ?? ""}
                          onChange={e => setForm(f => f ? { ...f, keywords: { ...f.keywords, [p.id]: e.target.value } } : f)}
                          aria-label={`Words for ${p.name}`}
                          placeholder="white, white ratha"
                          className="flex-1 min-w-0 text-base sm:text-sm border border-[var(--haip-border)] rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="flex gap-2">
              <button onClick={() => setForm(null)} className="flex-1 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]">Cancel</button>
              <button
                onClick={() => saveMutation.mutate(
                  form.feedId && !form.import_url.trim() ? { ...form, import_url: undefined as unknown as string } : form,
                )}
                disabled={!form.name.trim() || !form.property_id || saveMutation.isPending}
                className="flex-1 py-2.5 bg-primary hover:bg-primary disabled:opacity-40 text-white font-semibold rounded-xl text-sm"
              >
                {saveMutation.isPending ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
