"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Shield, Search, Filter, Download, Trash2, CheckCircle2, AlertTriangle, Clock, ExternalLink, RefreshCw, RotateCcw, Wifi, WifiOff, FileWarning, Users, Bot } from "@/lib/icons";
import Link from "next/link";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AuditEvent {
  id: string;
  action: string;
  actor_user_id?: string;
  target_type?: string;
  target_id?: string;
  payload?: Record<string, unknown>;
  created_at: string;
}

interface ConsentRecord {
  id: string;
  guest_phone: string;
  scope: string;
  granted: boolean;
  channel?: string;
  created_at: string;
  expires_at?: string;
  withdrawn_at?: string;
  withdrawal_reason?: string;
}

interface PendingDeletion {
  id: string;
  name?: string;
  phone?: string;
  deletion_requested_at: string;
  days_until_hard_delete?: number;
}

interface Incident {
  id: string;
  incident_type: string;
  severity: string;
  scope?: string;
  affected_count: number;
  narrative: string;
  started_at?: string;
  status: string;
  created_at: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

type Tab = "audit" | "consents" | "dpdp" | "incidents";

const ACTION_COLORS: Record<string, string> = {
  login:             "text-blue-600 bg-blue-50",
  logout:            "text-gray-600 bg-gray-50",
  invite:            "text-purple-600 bg-purple-50",
  role_change:       "text-amber-600 bg-amber-50",
  qa_override:       "text-teal-600 bg-teal-50",
  "dpdp.delete_requested":  "text-red-600 bg-red-50",
  "dpdp.delete_restored":   "text-green-600 bg-green-50",
  "retention.purge": "text-orange-600 bg-orange-50",
  "consent.opt_out": "text-pink-600 bg-pink-50",
  "consent.opt_in":  "text-green-600 bg-green-50",
  "incident.created":"text-red-700 bg-red-50",
  property_create:   "text-green-600 bg-green-50",
};

// D7: resource type → dashboard URL prefix
const RESOURCE_LINKS: Record<string, string> = {
  guest:    "/dashboard/guests/",
  call:     "/dashboard/calls/",
  inquiry:  "/dashboard/leads/",
  user:     "/dashboard/settings/team/",
};

function resourceLink(type?: string, id?: string): string | null {
  if (!type || !id) return null;
  const prefix = RESOURCE_LINKS[type];
  return prefix ? `${prefix}${id}` : null;
}

function shortId(id?: string) {
  return id ? id.slice(0, 8) + "…" : null;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

const SEVERITY_COLORS: Record<string, string> = {
  low:      "bg-gray-100 text-gray-600",
  medium:   "bg-amber-100 text-amber-700",
  high:     "bg-orange-100 text-orange-700",
  critical: "bg-red-100 text-red-700",
};

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CompliancePage() {
  const [tab, setTab] = useState<Tab>("audit");
  const [search, setSearch] = useState("");
  const [resourceFilter, setResourceFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [showIncidentForm, setShowIncidentForm] = useState(false);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const LIMIT = 50;

  // ── Audit log ───────────────────────────────────────────────────────────────
  const { data: auditEvents = [], isLoading: auditLoading } = useQuery<AuditEvent[]>({
    queryKey: ["audit-events", search, resourceFilter, offset],
    queryFn: () => api.get("/audit/events", {
      params: {
        action: search || undefined,
        target_type: resourceFilter || undefined,
        limit: LIMIT,
        offset,
      },
    }).then(r => r.data),
    enabled: tab === "audit",
    staleTime: 30_000,
  });

  // ── Consents ────────────────────────────────────────────────────────────────
  const { data: consents = [], isLoading: consentsLoading, isError: consentsError, refetch: refetchConsents } =
    useQuery<ConsentRecord[]>({
      queryKey: ["consents"],
      queryFn: () => api.get("/guests/consents").then(r => r.data),
      enabled: tab === "consents",
    });

  // ── DPDP deletion queue ─────────────────────────────────────────────────────
  const { data: pendingDeletions = [], isLoading: dpdpLoading } = useQuery<PendingDeletion[]>({
    queryKey: ["dpdp-pending"],
    queryFn: () => api.get("/guests/dpdp/pending-deletions").then(r => r.data),
    enabled: tab === "dpdp",
    staleTime: 60_000,
  });

  const restoreMutation = useMutation({
    mutationFn: (guestId: string) => api.post(`/guests/${guestId}/dpdp/restore`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dpdp-pending"] });
      toast({ variant: "success", title: "Guest restored" });
    },
    onError: () => toast({ variant: "error", title: "Restore failed" }),
  });

  // ── Incidents ────────────────────────────────────────────────────────────────
  const { data: incidents = [], isLoading: incidentsLoading } = useQuery<Incident[]>({
    queryKey: ["incidents"],
    queryFn: () => api.get("/incidents").then(r => r.data),
    enabled: tab === "incidents",
  });

  const createIncidentMutation = useMutation({
    mutationFn: (body: any) => api.post("/incidents", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      setShowIncidentForm(false);
      toast({ variant: "success", title: "Incident created" });
    },
    onError: () => toast({ variant: "error", title: "Failed to create incident" }),
  });

  const TABS: { id: Tab; label: string }[] = [
    { id: "audit",     label: "Audit log" },
    { id: "consents",  label: "Consent registry" },
    { id: "dpdp",      label: "DPDP queue" },
    { id: "incidents", label: "Incidents" },
  ];

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-9 h-9 rounded-xl bg-blue-100 flex items-center justify-center">
            <Shield size={18} className="text-blue-600" />
          </div>
          <div>
            <h1 className="haip-page-title">Compliance centre</h1>
            <p className="text-xs text-gray-400">DPDP Act compliance · audit trail · consent registry · incidents</p>
          </div>
        </div>
        <div className="flex gap-1">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                tab === t.id ? "bg-[#0F766E] text-white" : "text-gray-500 hover:bg-gray-100"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Audit log ── */}
      {tab === "audit" && (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-50 flex items-center gap-3 flex-shrink-0 flex-wrap">
            {/* D7: action filter */}
            <div className="relative">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                value={search}
                onChange={e => { setSearch(e.target.value); setOffset(0); }}
                placeholder="Filter by action…"
                className="pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500 bg-gray-50 w-44"
              />
            </div>
            {/* D7: resource type filter */}
            <select
              value={resourceFilter}
              onChange={e => { setResourceFilter(e.target.value); setOffset(0); }}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-teal-500"
            >
              <option value="">All resources</option>
              <option value="guest">Guest</option>
              <option value="call">Call</option>
              <option value="inquiry">Inquiry</option>
              <option value="user">User</option>
              <option value="incident">Incident</option>
            </select>
            {/* 4.4: "what the AI did, per user, per day" -- one click into
                the same action filter (already ilike-matched server-side)
                rather than requiring the owner to know to type "mcp." */}
            <button
              onClick={() => { setSearch(search === "mcp." ? "" : "mcp."); setOffset(0); }}
              className={cn(
                "flex items-center gap-1 text-xs font-medium px-2.5 py-1.5 rounded-lg border transition-colors",
                search === "mcp."
                  ? "bg-teal-50 border-teal-200 text-teal-700"
                  : "bg-gray-50 border-gray-200 text-gray-500 hover:bg-gray-100"
              )}
            >
              <Bot size={12} />
              MCP activity
            </button>
            <span className="text-xs text-gray-400 ml-auto">{auditEvents.length} events</span>
          </div>

          <div className="flex-1 overflow-y-auto">
            {auditLoading ? (
              <div className="divide-y divide-gray-50">
                {Array.from({ length: 10 }).map((_, i) => (
                  <div key={i} className="px-5 py-3 flex gap-3">
                    <Skeleton className="h-5 w-20 rounded-full" />
                    <Skeleton className="h-4 w-48" /><Skeleton className="h-4 w-32 ml-auto" />
                  </div>
                ))}
              </div>
            ) : auditEvents.length === 0 ? (
              <div className="py-16 text-center text-sm text-gray-400">
                {search || resourceFilter ? "No matching events" : "No audit events yet"}
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-white border-b border-gray-100">
                  <tr>
                    {["Action", "Resource", "Actor", "Timestamp"].map(h => (
                      <th key={h} className="px-4 py-2.5 text-left font-semibold uppercase tracking-wide text-gray-400">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {auditEvents.map(evt => {
                    const link = resourceLink(evt.target_type, evt.target_id);
                    return (
                      <tr key={evt.id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-4 py-2.5">
                          <span className={cn(
                            "px-2 py-0.5 rounded-full text-[10px] font-semibold",
                            ACTION_COLORS[evt.action] ?? "text-gray-600 bg-gray-100"
                          )}>
                            {evt.action}
                          </span>
                        </td>
                        {/* D7: clickable resource link */}
                        <td className="px-4 py-2.5">
                          {evt.target_type && (
                            <span className="text-gray-600 capitalize">{evt.target_type}</span>
                          )}
                          {evt.target_id && link ? (
                            <Link
                              href={link}
                              className="text-teal-600 hover:underline font-mono ml-1 flex items-center gap-0.5 inline-flex"
                            >
                              {shortId(evt.target_id)}
                              <ExternalLink size={9} />
                            </Link>
                          ) : evt.target_id ? (
                            <span className="text-gray-400 font-mono ml-1">{shortId(evt.target_id)}</span>
                          ) : null}
                        </td>
                        <td className="px-4 py-2.5 text-gray-500 font-mono">
                          {evt.actor_user_id?.slice(0, 8) ?? "system"}
                        </td>
                        <td className="px-4 py-2.5 text-gray-400">{formatDate(evt.created_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
          <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-between flex-shrink-0">
            <button onClick={() => setOffset(Math.max(0, offset - LIMIT))} disabled={offset === 0}
              className="text-xs text-gray-500 hover:text-gray-700 disabled:opacity-40 font-medium">← Previous</button>
            <span className="text-xs text-gray-400">Showing {offset + 1}–{offset + auditEvents.length}</span>
            <button onClick={() => setOffset(offset + LIMIT)} disabled={auditEvents.length < LIMIT}
              className="text-xs text-gray-500 hover:text-gray-700 disabled:opacity-40 font-medium">Next →</button>
          </div>
        </div>
      )}

      {/* ── Consent registry ── */}
      {tab === "consents" && (
        <div className="flex-1 overflow-y-auto p-5">
          {consentsError && (
            <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 flex items-start gap-3">
              <AlertTriangle size={16} className="text-red-500 mt-0.5 flex-shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-semibold text-red-700">Failed to load consent records</p>
              </div>
              <button onClick={() => refetchConsents()} className="text-xs text-red-600 hover:underline">Retry</button>
            </div>
          )}
          {consentsLoading ? <Skeleton className="h-64 rounded-2xl" />
          : !consentsError && consents.length === 0 ? (
            <div className="py-16 text-center text-sm text-gray-400">No consent records yet</div>
          ) : !consentsError && (
            <table className="w-full text-sm">
              <thead>
                <tr>
                  {["Guest phone", "Scope", "Channel", "Status", "Withdrawn", "Date"].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {consents.map(c => (
                  <tr key={c.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-xs text-gray-700">{c.guest_phone}</td>
                    <td className="px-4 py-3"><Badge variant="ghost" className="capitalize text-xs">{c.scope}</Badge></td>
                    <td className="px-4 py-3 text-gray-500 text-xs capitalize">{c.channel || "—"}</td>
                    <td className="px-4 py-3">
                      {c.granted
                        ? <span className="flex items-center gap-1 text-xs text-teal-600"><CheckCircle2 size={12} /> Granted</span>
                        : <span className="text-xs text-red-500">Revoked</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {c.withdrawn_at ? (
                        <span title={c.withdrawal_reason ?? ""}>{formatDate(c.withdrawn_at)}</span>
                      ) : "—"}
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">{formatDate(c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── DPDP deletion queue (D11) ── */}
      {tab === "dpdp" && (
        <div className="flex-1 overflow-y-auto p-5">
          <div className="bg-blue-50 border border-blue-100 rounded-2xl p-5 mb-5">
            <h3 className="text-sm font-semibold text-blue-800 mb-2 flex items-center gap-2">
              <Shield size={15} /> DPDP Act — Data deletion queue
            </h3>
            <p className="text-xs text-blue-600 leading-relaxed">
              Guests marked for deletion enter a 30-day grace period before hard-deletion.
              Restore within the window to cancel. After 30 days, all data is permanently removed.
            </p>
          </div>

          {dpdpLoading ? <Skeleton className="h-48 rounded-2xl" />
          : pendingDeletions.length === 0 ? (
            <div className="text-center py-16 text-sm text-gray-400">
              <Trash2 size={32} className="text-gray-300 mx-auto mb-3" />
              No deletion requests pending
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr>
                  {["Guest", "Requested at", "Days until hard-delete", "Actions"].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {pendingDeletions.map(g => (
                  <tr key={g.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <p className="text-sm font-medium text-gray-900">{g.name ?? "Unknown"}</p>
                      <p className="text-xs text-gray-400 font-mono">***{g.phone}</p>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">{formatDate(g.deletion_requested_at)}</td>
                    <td className="px-4 py-3">
                      <span className={cn(
                        "text-xs font-semibold px-2 py-0.5 rounded-full",
                        (g.days_until_hard_delete ?? 30) <= 3
                          ? "bg-red-100 text-red-700"
                          : (g.days_until_hard_delete ?? 30) <= 7
                          ? "bg-amber-100 text-amber-700"
                          : "bg-gray-100 text-gray-600"
                      )}>
                        {g.days_until_hard_delete ?? "?"} days
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => restoreMutation.mutate(g.id)}
                        disabled={restoreMutation.isPending}
                        className="flex items-center gap-1 text-xs text-teal-600 border border-teal-200 bg-teal-50 hover:bg-teal-100 px-2.5 py-1 rounded-lg transition-colors"
                      >
                        <RotateCcw size={11} /> Restore
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Incidents (D12) ── */}
      {tab === "incidents" && (
        <div className="flex-1 overflow-y-auto p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-3 flex items-start gap-3 flex-1 mr-4">
              <FileWarning size={16} className="text-red-500 mt-0.5 flex-shrink-0" />
              <p className="text-xs text-red-700">
                Under DPDP §8(6), personal data breaches must be notified to the Data Protection Board within <strong>72 hours</strong> of discovery.
                Use this form to document and track incidents.
              </p>
            </div>
            <button
              onClick={() => setShowIncidentForm(v => !v)}
              className="flex items-center gap-1.5 text-xs bg-red-600 text-white px-3 py-2 rounded-xl font-medium hover:bg-red-700 transition-colors flex-shrink-0"
            >
              <AlertTriangle size={12} /> Report incident
            </button>
          </div>

          {/* Incident creation form */}
          {showIncidentForm && (
            <IncidentForm
              onSubmit={(data) => createIncidentMutation.mutate(data)}
              onCancel={() => setShowIncidentForm(false)}
              isPending={createIncidentMutation.isPending}
            />
          )}

          {incidentsLoading ? <Skeleton className="h-64 rounded-2xl" />
          : incidents.length === 0 ? (
            <div className="text-center py-12 text-sm text-gray-400">
              <Shield size={28} className="text-gray-200 mx-auto mb-3" />
              No incidents recorded — keep it that way
            </div>
          ) : (
            <div className="space-y-3">
              {incidents.map(inc => (
                <div key={inc.id} className="haip-card p-4 shadow-sm">
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={cn(
                        "text-[10px] font-bold px-2 py-0.5 rounded-full uppercase",
                        SEVERITY_COLORS[inc.severity] ?? "bg-gray-100 text-gray-600"
                      )}>
                        {inc.severity}
                      </span>
                      <span className="text-sm font-semibold text-gray-900 capitalize">
                        {inc.incident_type.replace(/_/g, " ")}
                      </span>
                      {inc.affected_count > 0 && (
                        <span className="flex items-center gap-0.5 text-xs text-gray-500">
                          <Users size={11} /> {inc.affected_count} affected
                        </span>
                      )}
                    </div>
                    <span className={cn(
                      "text-[10px] font-medium px-2 py-0.5 rounded-full flex-shrink-0",
                      inc.status === "open" ? "bg-red-100 text-red-600"
                      : inc.status === "contained" ? "bg-amber-100 text-amber-600"
                      : "bg-gray-100 text-gray-500"
                    )}>
                      {inc.status}
                    </span>
                  </div>
                  <p className="text-xs text-gray-600 line-clamp-2">{inc.narrative}</p>
                  <div className="mt-2 flex items-center gap-3">
                    <span className="text-[10px] text-gray-400">{formatDate(inc.created_at)}</span>
                    {inc.scope && <span className="text-[10px] text-gray-400">Scope: {inc.scope}</span>}
                    <Link
                      href={`/dashboard/compliance/incidents/${inc.id}`}
                      className="ml-auto text-[10px] text-teal-600 hover:underline flex items-center gap-0.5"
                    >
                      View + generate notification <ExternalLink size={9} />
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Incident creation form ────────────────────────────────────────────────────

function IncidentForm({
  onSubmit, onCancel, isPending,
}: {
  onSubmit: (data: any) => void;
  onCancel: () => void;
  isPending: boolean;
}) {
  const [form, setForm] = useState({
    incident_type: "data_breach",
    severity: "medium",
    scope: "",
    affected_count: 0,
    narrative: "",
    started_at: "",
  });

  const set = (k: string, v: any) => setForm(prev => ({ ...prev, [k]: v }));

  return (
    <div className="bg-red-50 border border-red-200 rounded-2xl p-5 mb-5">
      <h3 className="text-sm font-bold text-red-900 mb-4 flex items-center gap-2">
        <AlertTriangle size={14} /> Report Security Incident
      </h3>
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="text-xs font-semibold text-red-800 mb-1 block">Type</label>
          <select
            value={form.incident_type}
            onChange={e => set("incident_type", e.target.value)}
            className="w-full text-sm border border-red-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-red-400"
          >
            {["data_breach", "unauthorised_access", "loss", "destruction", "alteration", "other"].map(t => (
              <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs font-semibold text-red-800 mb-1 block">Severity</label>
          <select
            value={form.severity}
            onChange={e => set("severity", e.target.value)}
            className="w-full text-sm border border-red-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-red-400"
          >
            {["low", "medium", "high", "critical"].map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs font-semibold text-red-800 mb-1 block">Affected records (approx.)</label>
          <input
            type="number"
            value={form.affected_count}
            onChange={e => set("affected_count", parseInt(e.target.value) || 0)}
            className="w-full text-sm border border-red-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-red-400"
          />
        </div>
        <div>
          <label className="text-xs font-semibold text-red-800 mb-1 block">Scope / Systems affected</label>
          <input
            value={form.scope}
            onChange={e => set("scope", e.target.value)}
            placeholder="e.g. WhatsApp message DB, S3 bucket"
            className="w-full text-sm border border-red-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-red-400"
          />
        </div>
      </div>
      <div className="mb-3">
        <label className="text-xs font-semibold text-red-800 mb-1 block">Incident narrative *</label>
        <textarea
          value={form.narrative}
          onChange={e => set("narrative", e.target.value)}
          rows={4}
          placeholder="Describe what happened, how it was discovered, and initial containment steps…"
          className="w-full text-sm border border-red-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-red-400 resize-none"
        />
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => onSubmit(form)}
          disabled={isPending || form.narrative.trim().length < 20}
          className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-40 text-white font-semibold text-sm rounded-xl transition-colors"
        >
          {isPending ? "Saving…" : "Create incident record"}
        </button>
        <button onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-xl">
          Cancel
        </button>
      </div>
    </div>
  );
}
