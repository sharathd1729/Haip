"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, Download, Loader2, AlertCircle, Search, CheckCircle2, Eye, Send } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface Recipient {
  id: string; phone: string; name: string | null; status: "queued" | "sent" | "delivered" | "read" | "failed";
  error_code: string | null; error_reason: string | null;
  sent_at: string | null; delivered_at: string | null; read_at: string | null; failed_at: string | null;
}
interface Failure { code: string | null; reason: string; group: string; group_label: string; hint: string | null; count: number }
interface Report {
  campaign: { id: string; name: string; status: string; template_name: string | null; scheduled_at: string | null };
  summary: { total: number; sent: number; delivered: number; read: number; failed: number; queued: number;
             delivery_rate: number | null; read_rate: number | null; failure_rate: number | null };
  failures: Failure[];
  recipients: Recipient[];
  total_matching: number;
  limit: number;
  offset: number;
}

const PAGE = 50;
const FILTERS = [
  { value: "", label: "Everyone" }, { value: "delivered", label: "Delivered" },
  { value: "read", label: "Read" }, { value: "failed", label: "Failed" },
] as const;

const STATUS_STYLE: Record<Recipient["status"], { label: string; cls: string }> = {
  queued:    { label: "Waiting",   cls: "bg-gray-50 text-gray-600 border-gray-200" },
  sent:      { label: "Sent",      cls: "bg-blue-50 text-blue-700 border-blue-200" },
  delivered: { label: "Delivered", cls: "bg-teal-50 text-teal-700 border-teal-200" },
  read:      { label: "Read",      cls: "bg-green-50 text-green-700 border-green-200" },
  failed:    { label: "Failed",    cls: "bg-red-50 text-red-600 border-red-200" },
};

const pct = (v: number | null) => (v === null ? "—" : `${v}%`);
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");

function Tile({ label, value, sub, icon, tone }: { label: string; value: number; sub?: string; icon: React.ReactNode; tone: string }) {
  return (
    <div className="rounded-xl bg-gray-50 p-3">
      <div className={cn("flex items-center gap-1.5 text-[11px] font-medium", tone)}>{icon}{label}</div>
      <p className="text-2xl font-bold text-gray-900 mt-1 tabular-nums">{value.toLocaleString()}</p>
      {sub && <p className="text-[10px] text-gray-400">{sub}</p>}
    </div>
  );
}

export function CampaignReport({ campaignId, campaignName, onClose }: { campaignId: string; campaignName: string; onClose: () => void }) {
  const [status, setStatus] = useState<string>("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");

  const { data, isLoading, isError, refetch } = useQuery<Report>({
    queryKey: ["wa-campaign-report", campaignId, status, search, page],
    queryFn: () => api.get(`/messaging/campaigns/${campaignId}/report`, {
      params: { status: status || undefined, search: search.trim() || undefined, limit: PAGE, offset: page * PAGE },
    }).then(r => r.data),
    // Delivered/read arrive minutes after sending: keep the numbers moving
    // while the campaign is still going out.
    refetchInterval: (q) => (q.state.data?.campaign.status === "running" ? 8000 : false),
    placeholderData: (prev) => prev,
  });

  const exportCsv = async () => {
    setExporting(true);
    setExportError("");
    try {
      const res = await api.get(`/messaging/campaigns/${campaignId}/recipients.csv`, {
        params: { status: status || undefined }, responseType: "blob",
      });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${campaignName.replace(/[^a-z0-9]+/gi, "-").slice(0, 40) || "campaign"}-recipients.csv`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      setExportError("Couldn't export. Try again.");
    } finally {
      setExporting(false);
    }
  };

  const s = data?.summary;
  const pages = data ? Math.max(1, Math.ceil(data.total_matching / PAGE)) : 1;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-3 sm:p-6" role="dialog" aria-modal="true" aria-label="Campaign report">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[94vh] flex flex-col overflow-hidden" style={{ maxHeight: "calc(100dvh - 3rem)" }}>
        <div className="px-6 pt-5 pb-4 border-b border-gray-100 flex items-start justify-between gap-4 flex-shrink-0">
          <div className="min-w-0">
            <h2 className="text-base font-bold text-gray-900 truncate">{campaignName}</h2>
            <p className="text-xs text-gray-400 mt-0.5">
              {data?.campaign.template_name ? <>Template <span className="font-mono">{data.campaign.template_name}</span> · </> : null}
              <span className="capitalize">{data?.campaign.status ?? "…"}</span>
              {data?.campaign.status === "running" && " · updating live"}
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button onClick={exportCsv} disabled={exporting || !s || s.total === 0}
              className="flex items-center gap-1.5 text-xs border border-gray-200 text-gray-600 px-3 py-2 rounded-xl hover:bg-gray-50 font-medium disabled:opacity-50">
              {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />} Export CSV
            </button>
            <button onClick={onClose} aria-label="Close"><X size={18} className="text-gray-400 hover:text-gray-600" /></button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {isError && (
            <div className="py-10 text-center">
              <AlertCircle size={28} className="text-red-300 mx-auto mb-2" />
              <p className="text-sm text-gray-700 font-medium">Couldn't load the report</p>
              <button onClick={() => refetch()} className="mt-3 text-xs font-semibold text-teal-600 border border-teal-200 bg-teal-50 px-3 py-1.5 rounded-lg">Retry</button>
            </div>
          )}
          {isLoading && !data && <div className="py-16 flex justify-center"><Loader2 className="animate-spin text-gray-300" /></div>}

          {s && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Tile label="Sent" value={s.sent} sub={s.total ? `of ${s.total.toLocaleString()} guests` : undefined} icon={<Send size={12} />} tone="text-blue-600" />
                <Tile label="Delivered" value={s.delivered} sub={`${pct(s.delivery_rate)} of sent`} icon={<CheckCircle2 size={12} />} tone="text-teal-600" />
                <Tile label="Read" value={s.read} sub={`${pct(s.read_rate)} of delivered`} icon={<Eye size={12} />} tone="text-green-600" />
                <Tile label="Failed" value={s.failed} sub={s.failed ? `${pct(s.failure_rate)} of attempts` : undefined} icon={<AlertCircle size={12} />} tone="text-red-500" />
              </div>

              {s.total === 0 && (
                <p className="text-sm text-gray-500 text-center py-6">Nothing has been sent yet. Once the campaign runs, each guest appears here.</p>
              )}

              {data!.failures.length > 0 && (
                <section>
                  <h3 className="text-xs font-semibold text-gray-700 mb-2">Why messages failed</h3>
                  <ul className="space-y-2">
                    {data!.failures.map((f, i) => (
                      <li key={`${f.code}-${i}`} className="flex items-start gap-3 rounded-xl border border-red-100 bg-red-50/40 p-3">
                        <span className="text-sm font-bold text-red-600 tabular-nums w-10 text-right flex-shrink-0">{f.count}</span>
                        <div className="min-w-0">
                          <p className="text-xs font-semibold text-gray-800">{f.group_label}</p>
                          <p className="text-xs text-gray-600">{f.reason}</p>
                          {f.hint && <p className="text-[11px] text-gray-500 mt-0.5">→ {f.hint}</p>}
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section>
                <div className="flex flex-wrap items-center gap-2 mb-3">
                  <div className="inline-flex rounded-xl bg-gray-100 p-0.5">
                    {FILTERS.map(f => (
                      <button key={f.value} onClick={() => { setStatus(f.value); setPage(0); }}
                        className={cn("px-3 py-1.5 rounded-[10px] text-xs font-medium transition-colors",
                          status === f.value ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700")}>
                        {f.label}
                      </button>
                    ))}
                  </div>
                  <div className="relative flex-1 min-w-[160px] max-w-xs">
                    <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                    <input value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} placeholder="Search name or number"
                      className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
                  </div>
                  {exportError && <span className="text-[11px] text-red-600">{exportError}</span>}
                </div>

                <div className="border border-gray-100 rounded-xl overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-gray-50 text-gray-500">
                      <tr>
                        <th className="text-left font-medium px-3 py-2">Guest</th>
                        <th className="text-left font-medium px-3 py-2">Status</th>
                        <th className="text-left font-medium px-3 py-2 hidden sm:table-cell">Sent</th>
                        <th className="text-left font-medium px-3 py-2">Details</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {data!.recipients.length === 0 ? (
                        <tr><td colSpan={4} className="px-3 py-8 text-center text-gray-400">No guests match.</td></tr>
                      ) : data!.recipients.map(r => {
                        const st = STATUS_STYLE[r.status];
                        return (
                          <tr key={r.id}>
                            <td className="px-3 py-2">
                              <p className="font-medium text-gray-800">{r.name || "—"}</p>
                              <p className="text-[10px] text-gray-400 font-mono">{r.phone}</p>
                            </td>
                            <td className="px-3 py-2"><span className={cn("inline-block text-[10px] font-semibold px-2 py-0.5 rounded-full border", st.cls)}>{st.label}</span></td>
                            <td className="px-3 py-2 text-gray-500 hidden sm:table-cell whitespace-nowrap">{when(r.sent_at)}</td>
                            <td className="px-3 py-2 text-gray-600">
                              {r.status === "failed" ? <span className="text-red-600">{r.error_reason ?? "Failed"}</span>
                                : r.status === "read" ? `Read ${when(r.read_at)}`
                                : r.status === "delivered" ? `Delivered ${when(r.delivered_at)}` : ""}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {data!.total_matching > PAGE && (
                  <div className="flex items-center justify-between mt-3 text-xs text-gray-500">
                    <span>{data!.offset + 1}–{Math.min(data!.offset + PAGE, data!.total_matching)} of {data!.total_matching.toLocaleString()}</span>
                    <div className="flex gap-2">
                      <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
                        className="px-3 py-1.5 border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50">Previous</button>
                      <button onClick={() => setPage(p => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1}
                        className="px-3 py-1.5 border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50">Next</button>
                    </div>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
