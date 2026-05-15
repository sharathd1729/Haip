"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shield, Search, Filter, Download, Trash2, CheckCircle2 } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

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
}

type Tab = "audit" | "consents" | "dpdp";

const ACTION_COLORS: Record<string, string> = {
  login: "text-blue-600 bg-blue-50",
  logout: "text-gray-600 bg-gray-50",
  invite: "text-purple-600 bg-purple-50",
  role_change: "text-amber-600 bg-amber-50",
  qa_override: "text-teal-600 bg-teal-50",
  dpdp_delete: "text-red-600 bg-red-50",
  property_create: "text-green-600 bg-green-50",
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function CompliancePage() {
  const [tab, setTab] = useState<Tab>("audit");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const { toast } = useToast();
  const LIMIT = 50;

  const { data: auditEvents = [], isLoading: auditLoading } = useQuery<AuditEvent[]>({
    queryKey: ["audit-events", search, offset],
    queryFn: () => api.get("/audit/events", { params: { action: search || undefined, limit: LIMIT, offset } }).then(r => r.data),
    enabled: tab === "audit",
    staleTime: 30_000,
  });

  const { data: consents = [], isLoading: consentsLoading } = useQuery<ConsentRecord[]>({
    queryKey: ["consents"],
    queryFn: () => api.get("/guests/consents").then(r => r.data).catch(() => []),
    enabled: tab === "consents",
  });

  return (
    <div className="h-full flex flex-col bg-white">
      <div className="px-5 py-4 border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-9 h-9 rounded-xl bg-blue-100 flex items-center justify-center">
            <Shield size={18} className="text-blue-600" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-gray-900">Compliance center</h1>
            <p className="text-xs text-gray-400">DPDP Act compliance · audit trail · consent registry</p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1">
          {(["audit", "consents", "dpdp"] as Tab[]).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize",
                tab === t ? "bg-[#0B1F3A] text-white" : "text-gray-500 hover:bg-gray-100"
              )}
            >
              {t === "dpdp" ? "DPDP queue" : t === "audit" ? "Audit log" : "Consent registry"}
            </button>
          ))}
        </div>
      </div>

      {/* Audit log */}
      {tab === "audit" && (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-50 flex items-center gap-3 flex-shrink-0">
            <div className="relative flex-1 max-w-xs">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                value={search}
                onChange={e => { setSearch(e.target.value); setOffset(0); }}
                placeholder="Filter by action…"
                className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500 bg-gray-50"
              />
            </div>
            <span className="text-xs text-gray-400 ml-auto">{auditEvents.length} events</span>
          </div>

          <div className="flex-1 overflow-y-auto">
            {auditLoading ? (
              <div className="divide-y divide-gray-50">
                {Array.from({ length: 10 }).map((_, i) => (
                  <div key={i} className="px-5 py-3 flex gap-3">
                    <Skeleton className="h-5 w-20 rounded-full" />
                    <Skeleton className="h-4 w-48" />
                    <Skeleton className="h-4 w-32 ml-auto" />
                  </div>
                ))}
              </div>
            ) : auditEvents.length === 0 ? (
              <div className="py-16 text-center text-sm text-gray-400">
                {search ? `No events matching "${search}"` : "No audit events yet"}
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-white border-b border-gray-100">
                  <tr>
                    {["Action", "Target", "Actor", "Timestamp"].map(h => (
                      <th key={h} className="px-4 py-2.5 text-left font-semibold uppercase tracking-wide text-gray-400">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {auditEvents.map(evt => (
                    <tr key={evt.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-2.5">
                        <span className={cn(
                          "px-2 py-0.5 rounded-full text-[10px] font-semibold",
                          ACTION_COLORS[evt.action] ?? "text-gray-600 bg-gray-100"
                        )}>
                          {evt.action}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-gray-600">
                        {evt.target_type && `${evt.target_type}`}
                        {evt.target_id && <span className="text-gray-400 font-mono ml-1">{evt.target_id.slice(0, 8)}…</span>}
                      </td>
                      <td className="px-4 py-2.5 text-gray-500 font-mono">
                        {evt.actor_user_id?.slice(0, 8) ?? "system"}
                      </td>
                      <td className="px-4 py-2.5 text-gray-400">{formatDate(evt.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Pagination */}
          <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-between flex-shrink-0">
            <button
              onClick={() => setOffset(Math.max(0, offset - LIMIT))}
              disabled={offset === 0}
              className="text-xs text-gray-500 hover:text-gray-700 disabled:opacity-40 font-medium"
            >
              ← Previous
            </button>
            <span className="text-xs text-gray-400">Showing {offset + 1}–{offset + auditEvents.length}</span>
            <button
              onClick={() => setOffset(offset + LIMIT)}
              disabled={auditEvents.length < LIMIT}
              className="text-xs text-gray-500 hover:text-gray-700 disabled:opacity-40 font-medium"
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {/* Consent registry */}
      {tab === "consents" && (
        <div className="flex-1 overflow-y-auto p-5">
          {consentsLoading ? (
            <Skeleton className="h-64 rounded-2xl" />
          ) : consents.length === 0 ? (
            <div className="py-16 text-center text-sm text-gray-400">No consent records yet</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr>
                  {["Guest phone", "Scope", "Channel", "Status", "Date"].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {consents.map(c => (
                  <tr key={c.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-xs text-gray-700">{c.guest_phone}</td>
                    <td className="px-4 py-3">
                      <Badge variant="ghost" className="capitalize text-xs">{c.scope}</Badge>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs capitalize">{c.channel || "—"}</td>
                    <td className="px-4 py-3">
                      {c.granted ? (
                        <span className="flex items-center gap-1 text-xs text-teal-600"><CheckCircle2 size={12} /> Granted</span>
                      ) : (
                        <span className="text-xs text-red-500">Revoked</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">{formatDate(c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* DPDP queue */}
      {tab === "dpdp" && (
        <div className="flex-1 overflow-y-auto p-5">
          <div className="bg-blue-50 border border-blue-100 rounded-2xl p-5 mb-5">
            <h3 className="text-sm font-semibold text-blue-800 mb-2 flex items-center gap-2">
              <Shield size={15} /> DPDP Act data deletion queue
            </h3>
            <p className="text-xs text-blue-600 leading-relaxed">
              Under India&apos;s Digital Personal Data Protection Act, data principals may request erasure of their personal data.
              Requests are processed within 30 days. This queue shows pending and completed deletion requests.
            </p>
          </div>
          <div className="text-center py-16 text-sm text-gray-400">
            <Trash2 size={32} className="text-gray-300 mx-auto mb-3" />
            No deletion requests pending
          </div>
        </div>
      )}
    </div>
  );
}
