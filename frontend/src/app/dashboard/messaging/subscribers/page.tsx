"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  UserCheck, UserX, Plus, Search, Download, Upload,
  CheckCircle2, XCircle, X, Loader2, AlertCircle,
  Tag, Phone, Clock, Filter,
} from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

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

function Toast({ msg, type, onClose }: { msg: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div className={cn("fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium max-w-sm",
      type === "success" ? "bg-green-50 text-green-800 border-green-200" : "bg-red-50 text-red-800 border-red-200")}>
      {type === "success" ? <CheckCircle2 size={15} className="text-green-600" /> : <AlertCircle size={15} className="text-red-600" />}
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
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-gray-900">Add subscriber</h2>
            <p className="text-xs text-gray-400 mt-0.5">Manually add an opted-in contact.</p>
          </div>
          <button onClick={onClose}><X size={18} className="text-gray-400 hover:text-gray-600" /></button>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">WhatsApp number <span className="text-red-500">*</span></label>
            <div className="relative">
              <Phone size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                placeholder="+91 98765 43210" className="w-full pl-9 pr-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
            </div>
            <p className="text-[10px] text-gray-400 mt-1">Include country code. E.g. +91 for India.</p>
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Name <span className="text-gray-400 font-normal">(optional)</span></label>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="Priya Sharma" className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Tags <span className="text-gray-400 font-normal">(optional)</span></label>
            <input value={form.tags} onChange={e => setForm(f => ({ ...f, tags: e.target.value }))}
              placeholder="vip, repeat-guest (comma-separated)" className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
          </div>
          <div className="bg-teal-50 border border-teal-200 rounded-xl p-3 text-[11px] text-teal-700">
            By adding this contact, you confirm they have explicitly opted in to receive WhatsApp messages from you, as required by Meta's policies.
          </div>
          {error && <div className="flex items-center gap-2 text-xs text-red-700 bg-red-50 rounded-xl px-3 py-2"><AlertCircle size={13} /> {error}</div>}
          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className="flex-1 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50 transition-colors">Cancel</button>
            <button type="submit" disabled={submitting}
              className="flex-1 py-2.5 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 disabled:opacity-50 transition-colors flex items-center justify-center gap-2">
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

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const { data: subscribers = [], isLoading, isError, refetch, isFetching } = useQuery<Subscriber[]>({
    queryKey: ["wa-subscribers", filter],
    queryFn: () => {
      const params: Record<string, string> = {};
      if (filter === "opted_in") params.opted_in = "true";
      if (filter === "opted_out") params.opted_in = "false";
      return api.get("/messaging/subscribers", { params }).then(r => r.data);
    },
    staleTime: 30_000,
  });

  const optOutMutation = useMutation({
    mutationFn: (id: string) => api.patch(`/messaging/subscribers/${id}/opt-out`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["wa-subscribers"] }); showToast("Subscriber opted out.", "success"); },
    onError: () => showToast("Failed to opt out.", "error"),
  });

  const optInMutation = useMutation({
    mutationFn: (id: string) => api.patch(`/messaging/subscribers/${id}/opt-in`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["wa-subscribers"] }); showToast("Subscriber opted back in.", "success"); },
    onError: () => showToast("Failed to opt in.", "error"),
  });

  const filtered = subscribers.filter(s =>
    !search.trim() ||
    s.phone.includes(search) ||
    (s.name?.toLowerCase().includes(search.toLowerCase())) ||
    s.tags.some(t => t.toLowerCase().includes(search.toLowerCase()))
  );

  const optedInCount = subscribers.filter(s => s.opted_in).length;
  const optedOutCount = subscribers.filter(s => !s.opted_in).length;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="haip-page-title">Subscribers</h1>
            <p className="text-sm text-gray-400 mt-0.5">Manage opt-in/opt-out status for your WhatsApp marketing list.</p>
          </div>
          <div className="flex items-center gap-2">
            <button className="flex items-center gap-1.5 text-xs border border-gray-200 text-gray-600 px-3 py-2 rounded-xl hover:bg-gray-50 transition-colors font-medium">
              <Download size={13} /> Export
            </button>
            <button onClick={() => setShowAdd(true)}
              className="flex items-center gap-2 bg-teal-500 text-white px-4 py-2.5 rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors shadow-sm shadow-teal-200">
              <Plus size={15} /> Add contact
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          {[
            { label: "Total contacts", value: subscribers.length, cls: "text-gray-900" },
            { label: "Opted in", value: optedInCount, cls: "text-teal-600" },
            { label: "Opted out", value: optedOutCount, cls: "text-red-500" },
          ].map(s => (
            <div key={s.label} className="bg-gray-50 rounded-xl p-3">
              <p className={cn("text-2xl font-bold", s.cls)}>{s.value.toLocaleString()}</p>
              <p className="text-[10px] text-gray-500 mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>

        {/* Search + filter */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by name, phone, or tag…"
              className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-teal-500/30 bg-white" />
          </div>
          <div className="flex gap-1">
            {(["all", "opted_in", "opted_out"] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={cn("px-3 py-2 rounded-xl text-xs font-medium transition-colors",
                  filter === f ? "bg-[#0F766E] text-white" : "border border-gray-200 text-gray-600 hover:bg-gray-50")}>
                {f === "all" ? "All" : f === "opted_in" ? "Opted in" : "Opted out"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {isError ? (
          <div className="py-20 text-center">
            <AlertCircle size={32} className="text-red-300 mx-auto mb-3" />
            <p className="text-sm text-gray-700 font-medium">Couldn't load subscribers</p>
            <p className="text-xs text-gray-400 mt-1">The server didn't respond — this isn't your saved subscriber list.</p>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="mt-4 text-xs font-semibold text-teal-600 border border-teal-200 bg-teal-50 hover:bg-teal-100 px-3 py-1.5 rounded-lg transition-colors"
            >
              {isFetching ? "Retrying…" : "Retry"}
            </button>
          </div>
        ) : isLoading ? (
          <div className="p-6 space-y-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-14 rounded-xl" />)}</div>
        ) : filtered.length === 0 ? (
          <div className="py-20 text-center">
            <UserCheck size={40} className="text-gray-200 mx-auto mb-3" />
            <p className="text-sm text-gray-500 font-medium">No subscribers found</p>
            <p className="text-xs text-gray-400 mt-1">Add contacts manually or import a CSV file.</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {filtered.map(sub => (
              <div key={sub.id} className="px-6 py-3.5 flex items-center gap-4 hover:bg-gray-50/60 transition-colors">
                {/* Status indicator */}
                <div className={cn("w-2.5 h-2.5 rounded-full flex-shrink-0", sub.opted_in ? "bg-teal-400" : "bg-red-400")} />

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm font-semibold text-gray-900 truncate">{sub.name || sub.phone}</span>
                    {sub.name && <span className="text-xs text-gray-400 font-mono truncate">{sub.phone}</span>}
                  </div>
                  <div className="flex items-center gap-3 flex-wrap">
                    {sub.tags.map(tag => (
                      <span key={tag} className="inline-flex items-center gap-1 text-[10px] bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded-full">
                        <Tag size={8} /> {tag}
                      </span>
                    ))}
                    {sub.source && <span className="text-[10px] text-gray-400">via {sub.source}</span>}
                  </div>
                </div>

                {/* Opt timing */}
                <div className="text-right flex-shrink-0">
                  <div className="flex items-center gap-1 text-[10px] text-gray-400 justify-end">
                    <Clock size={10} />
                    {sub.opted_in ? `Opt-in: ${timeAgo(sub.opt_in_at)}` : `Opt-out: ${timeAgo(sub.opt_out_at)}`}
                  </div>
                </div>

                {/* Status badge + action */}
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className={cn("inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border",
                    sub.opted_in ? "bg-green-50 text-green-700 border-green-200" : "bg-red-50 text-red-600 border-red-200")}>
                    {sub.opted_in ? <><CheckCircle2 size={9} /> Opted in</> : <><XCircle size={9} /> Opted out</>}
                  </span>
                  <button
                    onClick={() => sub.opted_in ? optOutMutation.mutate(sub.id) : optInMutation.mutate(sub.id)}
                    className={cn("text-xs px-2.5 py-1 rounded-lg font-medium transition-colors border",
                      sub.opted_in ? "text-red-500 border-red-200 hover:bg-red-50" : "text-teal-600 border-teal-200 hover:bg-teal-50"
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

      {showAdd && (
        <AddSubscriberModal
          onClose={() => setShowAdd(false)}
          onAdded={() => { queryClient.invalidateQueries({ queryKey: ["wa-subscribers"] }); showToast("Subscriber added!", "success"); }}
        />
      )}
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
}
