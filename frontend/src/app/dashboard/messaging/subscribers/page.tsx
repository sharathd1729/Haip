"use client";
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { UserX, Plus, Search, Download, Upload, CheckCircle2, XCircle, X, Loader2, AlertCircle, Tag, Phone, Clock, Filter } from "@/lib/icons";
import { UserCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { ImportSubscribersDialog } from "@/components/messaging/ImportSubscribersDialog";
import { ContactGrowthChart } from "@/components/messaging/contacts/ContactGrowthChart";
import { ContactListsBar, type ContactList } from "@/components/messaging/contacts/ContactListsBar";
import { BulkActionBar } from "@/components/messaging/contacts/BulkActionBar";
import type { ContactFilter } from "@/components/messaging/contacts/contactsHelpers";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface Subscriber {
  id: string;
  phone: string;
  name: string | null;
  opted_in: boolean;
  opt_in_at: string | null;
  opt_out_at: string | null;
  source: string | null;
  tags: string[];
  list_ids?: string[] | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const d = Math.floor(diff / 86400000);
  if (d < 1) return "today";
  if (d === 1) return "yesterday";
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

function downloadCsv(filename: string, rows: string[][]) {
  const csv = rows.map(r => r.map(c => `"${(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function Toast({ msg, type, onClose }: { msg: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div className={cn("fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium max-w-sm",
      type === "success" ? "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)] border-[var(--haip-status-success-border)]" : "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)] border-[var(--haip-status-danger-border)]")}>
      {type === "success" ? <CheckCircle2 size={15} className="text-[var(--haip-status-success-fg)]" /> : <AlertCircle size={15} className="text-[var(--haip-status-danger-fg)]" />}
      <span className="flex-1">{msg}</span>
      <button onClick={onClose}><X size={13} className="opacity-60" /></button>
    </div>
  );
}

// ─── Add Subscriber Modal ─────────────────────────────────────────────────────

function AddSubscriberModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [form, setForm] = useState({ phone: "", name: "", tags: "" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.phone.trim()) { setError("Phone number is required."); return; }
    setError("");
    setSubmitting(true);
    try {
      await api.post("/messaging/subscribers", {
        phone: form.phone.trim(),
        name: form.name.trim() || null,
        opted_in: true,
        source: "manual",
        tags: form.tags ? form.tags.split(",").map(t => t.trim()).filter(Boolean) : [],
      });
      onAdded();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to add subscriber.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-[var(--haip-border)] flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-[var(--haip-fg)]">Add subscriber</h2>
            <p className="text-xs text-[var(--haip-fg-subtle)] mt-0.5">Manually add an opted-in contact.</p>
          </div>
          <button onClick={onClose}><X size={18} className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)]" /></button>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          <div>
            <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">WhatsApp number <span className="text-[var(--haip-status-danger-fg)]">*</span></label>
            <div className="relative">
              <Phone size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
              <input value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                placeholder="+91 98765 43210" className="w-full pl-9 pr-4 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
            </div>
            <p className="text-[11.5px] text-[var(--haip-fg-subtle)] mt-1">Include country code. E.g. +91 for India.</p>
          </div>
          <div>
            <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Name <span className="text-[var(--haip-fg-subtle)] font-normal">(optional)</span></label>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="Priya Sharma" className="w-full px-3 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
          </div>
          <div>
            <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Tags <span className="text-[var(--haip-fg-subtle)] font-normal">(optional)</span></label>
            <input value={form.tags} onChange={e => setForm(f => ({ ...f, tags: e.target.value }))}
              placeholder="vip, repeat-guest (comma-separated)" className="w-full px-3 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
          </div>
          <div className="bg-[var(--haip-primary-tint)] border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] rounded-xl p-3 text-[11px] text-primary">
            By adding this contact, you confirm they have explicitly opted in to receive WhatsApp messages from you, as required by Meta's policies.
          </div>
          {error && <div className="flex items-center gap-2 text-xs text-[var(--haip-status-danger-fg)] bg-[var(--haip-status-danger-bg)] rounded-xl px-3 py-2"><AlertCircle size={13} /> {error}</div>}
          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className="flex-1 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)] transition-colors">Cancel</button>
            <button type="submit" disabled={submitting}
              className="flex-1 py-2.5 bg-primary text-white rounded-xl text-sm font-semibold hover:bg-primary disabled:opacity-50 transition-colors flex items-center justify-center gap-2">
              {submitting ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
              Add subscriber
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function SubscribersPage() {
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "opted_in" | "opted_out">("all");
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [listId, setListId] = useState<string | null>(null);
  const [tag, setTag] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [allMatching, setAllMatching] = useState(false);
  // Names and numbers are searched on the server so a search reaches everyone,
  // not just the newest rows that happen to be loaded.
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 5000);
  };
  const onToast = (msg: string, ok = true) => showToast(msg, ok ? "success" : "error");

  // One filter drives the list, its count and "pick all matching", so a bulk action reaches exactly who is shown.
  const contactFilter: ContactFilter = {
    ...(filter !== "all" && { opted_in: filter === "opted_in" }),
    ...(debouncedSearch && { search: debouncedSearch }),
    ...(listId && { list_id: listId }),
    ...(tag && { tag }),
  };
  const filterKey = JSON.stringify(contactFilter);
  useEffect(() => { setPicked(new Set()); setAllMatching(false); }, [filterKey]);

  const { data: subscribers = [], isLoading, isError, refetch, isFetching } = useQuery<Subscriber[]>({
    queryKey: ["wa-subscribers", filterKey],
    queryFn: () => api.get("/messaging/subscribers", { params: { limit: 500, ...contactFilter } }).then(r => r.data),
    staleTime: 30_000,
  });

  const { data: lists = [], isLoading: listsLoading } = useQuery<ContactList[]>({
    queryKey: ["wa-contact-lists"],
    queryFn: () => api.get("/messaging/contact-lists").then(r => r.data),
    staleTime: 30_000,
  });

  const { data: matching } = useQuery<{ count: number }>({
    queryKey: ["wa-subscriber-count", filterKey],
    queryFn: () => api.get("/messaging/subscribers/count", { params: contactFilter }).then(r => r.data),
    enabled: picked.size > 0,
    staleTime: 30_000,
  });

  // The list is paged; the totals must not be "how many rows happen to be loaded".
  const { data: stats } = useQuery<{ total: number; opted_in: number; opted_out: number }>({
    queryKey: ["wa-subscriber-stats"],
    queryFn: () => api.get("/messaging/subscribers/stats").then(r => r.data),
    staleTime: 30_000,
  });

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ["wa-subscribers"] });
    queryClient.invalidateQueries({ queryKey: ["wa-subscriber-stats"] });
    queryClient.invalidateQueries({ queryKey: ["wa-subscriber-count"] });
    queryClient.invalidateQueries({ queryKey: ["wa-subscriber-growth"] });
    queryClient.invalidateQueries({ queryKey: ["wa-contact-lists"] });
  };
  const togglePick = (id: string) => {
    setAllMatching(false);
    setPicked(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  };
  const allShownPicked = subscribers.length > 0 && subscribers.every(s => picked.has(s.id));
  const togglePickShown = () => {
    setAllMatching(false);
    setPicked(allShownPicked ? new Set() : new Set(subscribers.map(s => s.id)));
  };

  const optOutMutation = useMutation({
    mutationFn: (id: string) => api.patch(`/messaging/subscribers/${id}/opt-out`),
    onSuccess: () => { refreshAll(); showToast("Subscriber opted out.", "success"); },
    onError: () => showToast("Failed to opt out.", "error"),
  });

  const optInMutation = useMutation({
    mutationFn: (id: string) => api.patch(`/messaging/subscribers/${id}/opt-in`),
    onSuccess: () => { refreshAll(); showToast("Subscriber opted back in.", "success"); },
    onError: () => showToast("Failed to opt in.", "error"),
  });

  const handleExport = () => {
    if (subscribers.length === 0) { showToast("No subscribers to export.", "error"); return; }
    downloadCsv("wa-subscribers.csv", [
      ["phone", "name", "opted_in", "source", "tags"],
      ...subscribers.map(s => [s.phone, s.name ?? "", String(s.opted_in), s.source ?? "", s.tags.join("|")]),
    ]);
  };

  const filtered = subscribers;
  const listName = (id: string) => lists.find(l => l.id === id)?.name;

  const totalCount = stats?.total ?? subscribers.length;
  const optedInCount = stats?.opted_in ?? subscribers.filter(s => s.opted_in).length;
  const optedOutCount = stats?.opted_out ?? subscribers.filter(s => !s.opted_in).length;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-4 sm:px-6 py-5 bg-white border-b border-[var(--haip-border)] flex-shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <h1 className="haip-page-title">WhatsApp contacts</h1>
            <p className="text-sm text-[var(--haip-fg-subtle)] mt-0.5">Everyone you can send WhatsApp campaigns to. Tick contacts to tag them, put them on a list or start a drip.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setShowImport(true)}
              className="flex items-center gap-1.5 text-xs border border-[var(--haip-border)] text-[var(--haip-fg-muted)] px-3 py-2 rounded-xl hover:bg-[var(--haip-surface)] transition-colors font-medium"
            >
              <Upload size={13} /> Import CSV
            </button>
            <button onClick={handleExport} className="flex items-center gap-1.5 text-xs border border-[var(--haip-border)] text-[var(--haip-fg-muted)] px-3 py-2 rounded-xl hover:bg-[var(--haip-surface)] transition-colors font-medium">
              <Download size={13} /> Export
            </button>
            <button onClick={() => setShowAdd(true)}
              className="flex items-center gap-2 bg-primary text-white px-4 py-2.5 rounded-xl text-sm font-semibold hover:bg-primary transition-colors shadow-sm shadow-[color-mix(in_srgb,var(--primary)_18%,transparent)]">
              <Plus size={15} /> Add contact
            </button>
          </div>
        </div>

        <div className="mb-4"><ContactGrowthChart /></div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          {[
            { label: "Total contacts", value: totalCount, cls: "text-[var(--haip-fg)]" },
            { label: "Opted in", value: optedInCount, cls: "text-primary" },
            { label: "Opted out", value: optedOutCount, cls: "text-[var(--haip-status-danger-fg)]" },
          ].map(s => (
            <div key={s.label} className="bg-[var(--haip-surface)] rounded-xl p-3">
              <p className={cn("text-2xl font-bold", s.cls)}>{s.value.toLocaleString()}</p>
              <p className="text-[11.5px] text-[var(--haip-fg-subtle)] mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>

        <ContactListsBar lists={lists} loading={listsLoading} active={listId} onPick={setListId} onToast={onToast} />

        {!debouncedSearch && filter === "all" && !listId && !tag && totalCount > subscribers.length && (
          <p className="text-[11px] text-[var(--haip-fg-subtle)] mb-3">
            Showing the newest {subscribers.length.toLocaleString()} of {totalCount.toLocaleString()} contacts. Search by name or number to find anyone else.
          </p>
        )}

        {/* Search + filter */}
        <div className="flex flex-wrap gap-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by name or phone"
              className="w-full pl-9 pr-4 py-2 text-base sm:text-sm border border-[var(--haip-border)] rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/30 bg-white" />
          </div>
          <div className="flex gap-1">
            {(["all", "opted_in", "opted_out"] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={cn("px-3 py-2 rounded-xl text-xs font-medium transition-colors",
                  filter === f ? "bg-[var(--haip-tab-active-bg)] text-[var(--haip-tab-active-fg)]" : "border border-[var(--haip-border)] text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]")}>
                {f === "all" ? "All" : f === "opted_in" ? "Opted in" : "Opted out"}
              </button>
            ))}
          </div>
        </div>
        {tag && (
          <button type="button" onClick={() => setTag(null)} className="mt-2 inline-flex items-center gap-1 text-[11.5px] bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)] px-2.5 py-1 rounded-full min-h-[32px]">
            <Tag size={10} /> Tag: {tag} <X size={11} aria-label="Clear tag filter" />
          </button>
        )}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {picked.size > 0 && (
          <BulkActionBar
            selected={[...picked]} allMatching={allMatching} matchingCount={matching?.count} filter={contactFilter} lists={lists}
            onSelectAll={() => setAllMatching(true)} onClear={() => { setPicked(new Set()); setAllMatching(false); }}
            onDone={() => { setPicked(new Set()); setAllMatching(false); refreshAll(); }} onToast={onToast}
          />
        )}
        {isError ? (
          <div className="py-20 text-center">
            <AlertCircle size={32} className="text-[var(--haip-status-danger-fg)] mx-auto mb-3" />
            <p className="text-sm text-[var(--haip-fg-2)] font-medium">Couldn't load subscribers</p>
            <p className="text-xs text-[var(--haip-fg-subtle)] mt-1">The server didn't respond — this isn't your saved subscriber list.</p>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="mt-4 text-xs font-semibold text-primary border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] bg-[var(--haip-primary-tint)] hover:bg-[var(--haip-primary-tint)] px-3 py-1.5 rounded-lg transition-colors"
            >
              {isFetching ? "Retrying…" : "Retry"}
            </button>
          </div>
        ) : isLoading ? (
          <div className="p-6 space-y-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-14 rounded-xl" />)}</div>
        ) : filtered.length === 0 ? (
          <div className="py-20 text-center">
            <UserCheck size={40} className="text-[var(--haip-fg-subtle)]/70 mx-auto mb-3" />
            <p className="text-sm text-[var(--haip-fg-subtle)] font-medium">{listId || tag || debouncedSearch || filter !== "all" ? "No contacts match" : "No contacts yet"}</p>
            <p className="text-xs text-[var(--haip-fg-subtle)] mt-1">{listId ? "Tick contacts under Everyone and choose Add to list." : "Add a contact or import a spreadsheet (CSV)."}</p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--haip-border)]">
            <label className="px-4 sm:px-6 py-2 flex items-center gap-3 text-[11.5px] text-[var(--haip-fg-subtle)] cursor-pointer min-h-[44px]">
              <input type="checkbox" checked={allShownPicked} onChange={togglePickShown} className="h-4 w-4 accent-[var(--primary)]" />
              Pick all {filtered.length.toLocaleString("en-IN")} shown
            </label>
            {filtered.map(sub => (
              <div key={sub.id} className={cn("px-4 sm:px-6 py-3.5 flex items-center gap-3 sm:gap-4 hover:bg-[var(--haip-surface)]/60 transition-colors", (allMatching || picked.has(sub.id)) && "bg-[var(--haip-primary-tint)]")}>
                <label className="-m-3 p-3 flex-shrink-0 cursor-pointer">
                  <input type="checkbox" checked={allMatching || picked.has(sub.id)} onChange={() => togglePick(sub.id)}
                    aria-label={`Pick ${sub.name || sub.phone}`} className="h-4 w-4 accent-[var(--primary)]" />
                </label>
                {/* Status indicator */}
                <div className={cn("w-2.5 h-2.5 rounded-full flex-shrink-0", sub.opted_in ? "bg-primary" : "bg-[var(--haip-status-danger-fg)]")} />

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm font-semibold text-[var(--haip-fg)] truncate">{sub.name || sub.phone}</span>
                    {sub.name && <span className="text-xs text-[var(--haip-fg-subtle)] font-mono truncate">{sub.phone}</span>}
                  </div>
                  <div className="flex items-center gap-3 flex-wrap">
                    {sub.tags.map(t => (
                      <button type="button" key={t} onClick={() => setTag(t)} title={`Show everyone tagged ${t}`}
                        className="inline-flex items-center gap-1 text-[11.5px] bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)] px-1.5 py-0.5 rounded-full">
                        <Tag size={8} /> {t}
                      </button>
                    ))}
                    {(sub.list_ids ?? []).map(id => listName(id) && (
                      <span key={id} className="inline-flex items-center text-[11.5px] border border-[var(--haip-border)] text-[var(--haip-fg-muted)] px-1.5 py-0.5 rounded-full">{listName(id)}</span>
                    ))}
                    {sub.source && <span className="text-[11.5px] text-[var(--haip-fg-subtle)]">via {sub.source}</span>}
                  </div>
                </div>

                {/* Opt timing */}
                <div className="hidden md:block text-right flex-shrink-0">
                  <div className="flex items-center gap-1 text-[11.5px] text-[var(--haip-fg-subtle)] justify-end">
                    <Clock size={10} />
                    {sub.opted_in ? `Opt-in: ${timeAgo(sub.opt_in_at)}` : `Opt-out: ${timeAgo(sub.opt_out_at)}`}
                  </div>
                </div>

                {/* Status badge + action */}
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className={cn("hidden sm:inline-flex items-center gap-1 text-[11.5px] font-semibold px-2 py-0.5 rounded-full border",
                    sub.opted_in ? "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)] border-[var(--haip-status-success-border)]" : "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)] border-[var(--haip-status-danger-border)]")}>
                    {sub.opted_in ? <><CheckCircle2 size={9} /> Opted in</> : <><XCircle size={9} /> Opted out</>}
                  </span>
                  <button
                    onClick={() => sub.opted_in ? optOutMutation.mutate(sub.id) : optInMutation.mutate(sub.id)}
                    className={cn("text-xs px-2.5 py-1 rounded-lg font-medium transition-colors border",
                      sub.opted_in ? "text-[var(--haip-status-danger-fg)] border-[var(--haip-status-danger-border)] hover:bg-[var(--haip-status-danger-bg)]" : "text-primary border-[color-mix(in_srgb,var(--primary)_25%,transparent)] hover:bg-[var(--haip-primary-tint)]"
                    )}
                  >
                    {sub.opted_in ? "Opt out" : "Opt in"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showImport && (
        <ImportSubscribersDialog
          onClose={() => setShowImport(false)}
          onImported={() => { refreshAll(); queryClient.invalidateQueries({ queryKey: ["wa-audience-count"] }); }}
        />
      )}
      {showAdd && (
        <AddSubscriberModal
          onClose={() => setShowAdd(false)}
          onAdded={() => { refreshAll(); showToast("Subscriber added!", "success"); }}
        />
      )}
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
}
