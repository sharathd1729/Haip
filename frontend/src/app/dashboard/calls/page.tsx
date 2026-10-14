"use client";
// Calls (redesign). Summary tiles for the selected range, a "Call back" tab
// for missed calls nobody has returned, one row per call, inline Call back /
// play, and a single detail panel (desktop: right column; phone: full
// screen). Row + tiles live in components/calls/CallListParts.tsx.
import { useMemo, useState, useEffect } from "react";
import dynamic from "next/dynamic";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Phone, Upload, X, Search, Loader2, PhoneMissed, Delete, PhoneCall, AlertCircle, CheckCircle2 } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useCallsStore } from "@/store/calls";
import { CallDetailPanel, OUTCOMES } from "@/components/calls/CallDetailPanel";
import {
  CallRow, SummaryTiles, RANGES, dayLabel,
  type CallItem, type CallsSummary, type Tab,
} from "@/components/calls/CallListParts";

// B5: only needed once the user opens the upload dialog.
const UploadModal = dynamic(
  () => import("@/components/calls/UploadModal").then(m => m.UploadModal),
  { ssr: false }
);

// ─── Dialer modal ───────────────────────────────────────────────────────────

const DIAL_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

// Dial pad only collects digits/*/# -- normalize to E.164 before sending so
// a bare "918179631737" or "8179631737" doesn't reach the backend as
// something Vobiz's Call API silently rejects. Mirrors the same "+91"
// convention used throughout the backend's own phone normalization.
function toE164In(raw: string): string {
  const trimmed = raw.trim();
  if (trimmed.startsWith("+")) return trimmed;
  const digits = trimmed.replace(/^0+/, "");
  if (digits.startsWith("91") && digits.length === 12) return `+${digits}`;
  return `+91${digits}`;
}

function DialerModal({ onClose }: { onClose: () => void }) {
  const { toast } = useToast();
  const [number, setNumber] = useState("");

  const call = useMutation({
  mutationFn: (guest_number: string) => api.post("/calls/click-to-call", { guest_number }),
  onSuccess: () => {
  toast({ variant: "success", title: "Calling…", description: "Your phone will ring shortly." });
  onClose();
  },
  onError: (err: any) => {
  // FastAPI validation errors (422) return `detail` as an array of
  // objects, not a string -- rendering that directly produced the
  // unhelpful generic fallback instead of the real reason.
  const raw = err?.response?.data?.detail;
  const msg = typeof raw === "string"
  ? raw
  : Array.isArray(raw)
  ? raw.map((e: any) => e?.msg ?? JSON.stringify(e)).join("; ")
  : err?.message || "Could not start call — check the network tab for details";
  toast({ variant: "error", title: "Call failed", description: msg });
  },
  });

  const press = (k: string) => setNumber(n => n + k);
  const backspace = () => setNumber(n => n.slice(0, -1));

  return (
  <>
  <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
  <div
  className="clx-dialer-modal fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[300px] overflow-hidden"
  style={{ background: "var(--haip-card, #fff)", boxShadow: "0 20px 40px rgba(0,0,0,0.2)" }}
  >
  <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: "1px solid var(--haip-border)" }}>
  <p className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>New call</p>
  <button onClick={onClose} className="w-6 h-6 flex items-center justify-center rounded-lg hover:bg-muted" style={{ color: "var(--haip-fg-subtle)" }}>
  <X size={14} />
  </button>
  </div>

  <div className="p-5 flex flex-col items-center gap-4">
  <div className="w-full flex items-center justify-center gap-2">
  <input
  value={number}
  onChange={e => setNumber(e.target.value.replace(/[^\d+*#]/g, ""))}
  placeholder="+91 98765 43210"
  autoFocus
  className="flex-1 text-center text-lg font-semibold tabular-nums px-2 py-2 rounded-xl outline-none"
  style={{ color: "var(--haip-fg)", background: "var(--muted)" }}
  />
  {number && (
  <button onClick={backspace} className="w-9 h-9 flex items-center justify-center rounded-xl hover:bg-muted flex-shrink-0" style={{ color: "var(--haip-fg-muted)" }}>
  <Delete size={16} />
  </button>
  )}
  </div>

  <div className="grid grid-cols-3 gap-3">
  {DIAL_KEYS.map(k => (
  <button
  key={k}
  onClick={() => press(k)}
  className="clx-dial-key w-14 h-14 text-lg font-semibold transition-colors duration-150"
  style={{ background: "var(--muted)", color: "var(--haip-fg)" }}
  >
  {k}
  </button>
  ))}
  </div>

  <button
  onClick={() => number.trim() && call.mutate(toE164In(number))}
  disabled={call.isPending || !number.trim()}
  className="clx-dial-call-btn w-14 h-14 flex items-center justify-center text-white disabled:opacity-50 mt-1"
  >
  {call.isPending ? <Loader2 size={20} className="animate-spin" /> : <PhoneCall size={20} />}
  </button>
  </div>
  </div>
  </>
  );
}


// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CallsPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { wrapUpQueue, dismissWrapUp } = useCallsStore();
  const [tab, setTab] = useState<Tab>("callback");
  // Until someone picks a tab themselves, an empty call-back list falls back to the full call
  // log, so the page opens on calls instead of an empty "all returned" card.
  const [tabPicked, setTabPicked] = useState(false);
  const pickTab = (t: Tab) => { setTabPicked(true); setTab(t); };
  const [range, setRange] = useState("last_7d");
  const [agentId, setAgentId] = useState("");
  const [outcome, setOutcome] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [activeCallId, setActiveCallId] = useState<string | null>(null);
  const [autoPlay, setAutoPlay] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [showDialer, setShowDialer] = useState(false);
  const pageSize = 25;
  const rangeLabel = RANGES.find(r => r.value === range)?.label ?? "Today";

  const { data: summary } = useQuery<CallsSummary>({
  queryKey: ["calls", "summary", range],
  queryFn: () => api.get("/calls/summary", { params: { date_preset: range } }).then(r => r.data),
  staleTime: 30_000,
  refetchInterval: 60_000,
  });

  const { data: team = [] } = useQuery<{ id: string; name: string }[]>({
  queryKey: ["users-lite"],
  queryFn: () => api.get("/users/lite").then(r => r.data),
  staleTime: 300_000,
  });

  const { data, isLoading, isError, error } = useQuery<{ items: CallItem[]; total: number }>({
  queryKey: ["calls", tab, range, agentId, outcome, page],
  queryFn: () => {
  const params: Record<string, string | number | boolean> = { page, limit: pageSize, date_preset: range };
  if (tab === "callback") params.view = "needs_callback";
  if (tab === "incoming") { params.direction = "inbound"; params.missed = false; }
  if (tab === "outgoing") params.direction = "outbound";
  if (agentId) params.agent_id = agentId;
  if (outcome) params.disposition = outcome;
  return api.get("/calls", { params }).then(r => ({ items: r.data?.items ?? [], total: r.data?.total ?? 0 }));
  },
  staleTime: 30_000,
  });
  useEffect(() => { setPage(1); }, [tab, range, agentId, outcome]);
  useEffect(() => {
  if (tab === "callback" && !tabPicked && !isLoading && !isError && data && data.total === 0) setTab("all");
  }, [tab, tabPicked, isLoading, isError, data]);

  const calls = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const q = search.trim().toLowerCase();
  const shown = q
  ? calls.filter(c => (c.guest_name ?? "").toLowerCase().includes(q) || (c.guest_phone ?? "").includes(q) || (c.agent_name ?? "").toLowerCase().includes(q))
  : calls;

  // Group by day for the "TODAY / YESTERDAY" headers.
  const groups = useMemo(() => {
  const out: { label: string; items: CallItem[] }[] = [];
  for (const c of shown) {
  const label = dayLabel(c.created_at || c.started_at || new Date().toISOString());
  const last = out[out.length - 1];
  if (last && last.label === label) last.items.push(c); else out.push({ label, items: [c] });
  }
  return out;
  }, [shown]);

  const callBack = useMutation({
  mutationFn: (guest_number: string) => api.post("/calls/click-to-call", { guest_number }),
  onSuccess: () => toast({ variant: "success", title: "Calling…", description: "Your phone will ring shortly." }),
  onError: (err: any) => toast({ variant: "error", title: "Call failed", description: err?.response?.data?.detail ?? "Could not start call" }),
  });

  const active = calls.find(c => c.id === activeCallId);
  const open = (id: string, play = false) => { setActiveCallId(id); setAutoPlay(play); };

  const selectCls = "text-xs font-semibold rounded-lg px-2.5 py-1.5 border outline-none";
  const selectStyle = { background: "var(--haip-card)", borderColor: "var(--haip-border)", color: "var(--haip-fg)" };

  return (
  <div className="haip-calls-v2 h-full flex overflow-hidden bg-background">
  <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
  {/* Header */}
  <div className="px-3 sm:px-5 pt-2 sm:pt-4 pb-2 sm:pb-3 space-y-2 sm:space-y-3 flex-shrink-0">
  <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between">
  <h1 className="haip-page-title hidden sm:block">Calls</h1>
  <div className="flex items-center gap-2">
  <div className="relative flex-1 sm:w-64 sm:flex-none">
  <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "var(--haip-fg-subtle)" }} />
  <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search guest, phone or agent"
  aria-label="Search calls"
  className="w-full pl-8 pr-3 py-2 text-sm rounded-lg outline-none border focus-visible:ring-2 focus-visible:ring-primary"
  style={{ background: "var(--haip-card)", borderColor: "var(--haip-border)", color: "var(--haip-fg)" }} />
  </div>
  <button onClick={() => setShowDialer(true)} className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90">
  <PhoneCall size={13} /> Dial
  </button>
  <button onClick={() => setShowUpload(true)} className="hidden sm:inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border"
  style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg)" }}>
  <Upload size={13} /> Upload
  </button>
  </div>
  </div>

  <SummaryTiles s={summary} rangeLabel={rangeLabel} onPick={pickTab} />

  <div className="flex flex-wrap items-center gap-2">
  <div role="tablist" aria-label="Call type" className="flex gap-1.5 overflow-x-auto scrollbar-hide">
  {([["callback", "Call back"], ["all", "All"], ["incoming", "Incoming"], ["outgoing", "Outgoing"]] as const).map(([key, label]) => {
  const on = tab === key;
  const n = key === "callback" ? summary?.missed_not_called_back : undefined;
  return (
  <button key={key} role="tab" aria-selected={on} onClick={() => pickTab(key)}
  className={cn("flex-shrink-0 inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full border",
 "border-[color:var(--haip-border)]")}
  style={on ? { background: "color-mix(in srgb, var(--primary) 12%, var(--haip-card))", color: "var(--primary)", borderColor: "color-mix(in srgb, var(--primary) 50%, transparent)" } : { color: "var(--haip-fg-2, var(--haip-fg))", background: "var(--haip-card)" }}>
  {label}
  {n != null && n > 0 && <span className="text-[var(--haip-status-danger-fg)] tabular-nums">{n}</span>}
  </button>
  );
  })}
  </div>
  <div className="flex gap-2 sm:ml-auto overflow-x-auto scrollbar-hide">
  <select value={range} onChange={e => setRange(e.target.value)} aria-label="Date range" className={selectCls} style={selectStyle}>
  {RANGES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
  </select>
  <select value={agentId} onChange={e => setAgentId(e.target.value)} aria-label="Agent" className={selectCls} style={selectStyle}>
  <option value="">All agents</option>
  {team.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
  </select>
  <select value={outcome} onChange={e => setOutcome(e.target.value)} aria-label="Outcome" className={selectCls} style={selectStyle}>
  <option value="">Any outcome</option>
  {OUTCOMES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
  </select>
  </div>
  </div>

  {wrapUpQueue.length > 0 && (
  <div className="flex flex-wrap gap-1.5">
  {wrapUpQueue.map(callId => (
  <span key={callId} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-semibold bg-primary/10 text-primary">
  Wrap-up ready
  <button onClick={() => { open(callId); dismissWrapUp(callId); }} className="underline">View</button>
  <button onClick={() => dismissWrapUp(callId)} aria-label="Dismiss"><X size={10} /></button>
  </span>
  ))}
  </div>
  )}
  </div>

  {/* List */}
  <div className="flex-1 overflow-y-auto haip-scrollbar px-4 sm:px-5 pb-4">
  <div className="haip-card overflow-hidden p-0">
  {isLoading ? (
  [...Array(6)].map((_, i) => (
  <div key={i} className="px-4 py-3 flex items-center gap-3"><Skeleton className="w-10 h-10 rounded-full" /><div className="flex-1 space-y-1.5"><Skeleton className="h-3.5 w-40" /><Skeleton className="h-3 w-24" /></div></div>
  ))
  ) : isError ? (
  <div className="flex flex-col items-center justify-center py-20 text-center gap-2">
  <AlertCircle size={26} className="text-rose-500" />
  <p className="font-semibold" style={{ color: "var(--haip-fg)" }}>Couldn&apos;t load calls</p>
  <p className="text-xs max-w-sm" style={{ color: "var(--haip-fg-subtle)" }}>
  {(error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Try refreshing the page."}
  </p>
  </div>
  ) : shown.length === 0 ? (
  tab === "callback" && !q ? (
  <div className="flex flex-col items-center justify-center py-20 text-center gap-1.5">
  <CheckCircle2 size={26} className="text-[var(--haip-status-success-fg)]" />
  <p className="font-semibold" style={{ color: "var(--haip-fg)" }}>Every missed call has been returned</p>
  <button onClick={() => pickTab("all")} className="text-xs font-semibold text-primary">See all calls</button>
  </div>
  ) : tab !== "all" || q || agentId || outcome ? (
  <div className="flex flex-col items-center justify-center py-20 text-center gap-1.5">
  <PhoneMissed size={24} style={{ color: "var(--haip-fg-subtle)" }} />
  <p className="font-semibold" style={{ color: "var(--haip-fg)" }}>No calls match</p>
  <button onClick={() => { pickTab("all"); setSearch(""); setAgentId(""); setOutcome(""); }} className="text-xs font-semibold text-primary">Clear filters</button>
  </div>
  ) : (
  // Nothing in this range -- say so, instead of the "connect
  // your IVR" onboarding card, which only fits a new account.
  <div className="flex flex-col items-center justify-center py-20 text-center gap-1.5">
  <Phone size={24} style={{ color: "var(--haip-fg-subtle)" }} />
  <p className="font-semibold" style={{ color: "var(--haip-fg)" }}>No calls {rangeLabel.toLowerCase()}</p>
  {range !== "this_month" && (
  <button onClick={() => setRange("this_month")} className="text-xs font-semibold text-primary">Show this month</button>
  )}
  </div>
  )
  ) : (
  groups.map(g => (
  <div key={g.label}>
  <p className="px-4 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--haip-fg-subtle)" }}>{g.label}</p>
  {g.items.map(c => (
  <CallRow key={c.id} call={c} selected={c.id === activeCallId}
  onSelect={() => open(c.id)} onPlay={() => open(c.id, true)}
  onCallBack={() => callBack.mutate(c.guest_phone)}
  calling={callBack.isPending && callBack.variables === c.guest_phone} />
  ))}
  </div>
  ))
  )}
  </div>

  {!isLoading && !isError && totalPages > 1 && (
  <div className="flex items-center justify-between pt-3">
  <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>Page {page} of {totalPages} · {total} calls</p>
  <div className="flex gap-2">
  <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1} className="text-xs px-3 py-1.5 rounded-lg border font-medium disabled:opacity-40" style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-muted)" }}>Previous</button>
  <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="text-xs px-3 py-1.5 rounded-lg border font-medium disabled:opacity-40" style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-muted)" }}>Next</button>
  </div>
  </div>
  )}
  </div>
  </div>

  {/* Detail: right column on desktop, full screen on phones */}
  {activeCallId && (
  <>
  <div className="hidden lg:flex w-[440px] flex-shrink-0" style={{ borderLeft: "1px solid var(--haip-border)" }}>
  <CallDetailPanel key={activeCallId} callId={activeCallId} channels={active?.guest_channels} autoPlay={autoPlay}
  onClose={() => setActiveCallId(null)} className="w-full" />
  </div>
  <div className="lg:hidden fixed inset-0 z-50 flex">
  <CallDetailPanel key={`m-${activeCallId}`} callId={activeCallId} channels={active?.guest_channels} autoPlay={autoPlay}
  onClose={() => setActiveCallId(null)} className="w-full" />
  </div>
  </>
  )}

  {showUpload && (
  <UploadModal onClose={() => setShowUpload(false)}
  onSuccess={() => { queryClient.invalidateQueries({ queryKey: ["calls"] }); setShowUpload(false); }} />
  )}
  {showDialer && <DialerModal onClose={() => setShowDialer(false)} />}
  </div>
  );
}
