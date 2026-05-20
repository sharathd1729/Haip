"use client";

/**
 * A4 — Lost-reason theme drill-down modal.
 *
 * Click a pie slice / theme card → modal lists all inquiries in that theme,
 * paginated, with links to inquiry detail and a bulk-action bar.
 */

import { useState } from "react";
import { X, ExternalLink, Download, Tag, Send, Flag } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

interface LostInquiry {
  id: string;
  guest_name?: string;
  guest_phone: string;
  property_name?: string;
  check_in?: string;
  check_out?: string;
  lost_reason?: string;
  last_contact?: string;
  created_at: string;
}

interface LostInquiryPage {
  theme: string;
  total: int;
  page: int;
  per_page: int;
  items: LostInquiry[];
}

// Patch: TypeScript doesn't know about `int` alias — use number
type PageData = {
  theme: string;
  total: number;
  page: number;
  per_page: number;
  items: LostInquiry[];
};

interface LostReasonModalProps {
  theme: string;
  themeLabel: string;
  count: number;
  onClose: () => void;
}

export function LostReasonModal({ theme, themeLabel, count, onClose }: LostReasonModalProps) {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data, isLoading } = useQuery<PageData>({
    queryKey: ["lost-reason-inquiries", theme, page],
    queryFn: () =>
      api.get(`/analytics/lost-reasons/${encodeURIComponent(theme)}/inquiries?page=${page}&per_page=20`).then(r => r.data),
    staleTime: 120_000,
  });

  const totalPages = data ? Math.ceil(data.total / data.per_page) : 1;

  function toggleSelect(id: string) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAll() {
    if (!data) return;
    const allIds = new Set(data.items.map(i => i.id));
    setSelected(prev => prev.size === allIds.size ? new Set() : allIds);
  }

  function exportCSV() {
    if (!data) return;
    const header = `# Lost reason theme: ${themeLabel}\n# Total: ${data.total}\n# Generated: ${new Date().toISOString()}\n`;
    const cols = "ID,Guest,Phone,Property,Check-in,Check-out,Lost reason,Last contact,Created\n";
    const body = data.items.map(i =>
      `"${i.id}","${i.guest_name ?? ""}","${i.guest_phone}","${i.property_name ?? ""}","${i.check_in ?? ""}","${i.check_out ?? ""}","${i.lost_reason ?? ""}","${i.last_contact ?? ""}","${i.created_at}"`
    ).join("\n");
    const blob = new Blob([header + cols + body], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `haip_lost_${theme}_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
        onClick={onClose}
      >
        {/* Modal */}
        <div
          className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-start justify-between px-5 py-4 border-b border-gray-100 flex-shrink-0">
            <div>
              <h2 className="text-base font-bold text-gray-900 capitalize">{themeLabel}</h2>
              <p className="text-xs text-gray-400 mt-0.5">{count} lost inquiries in this theme</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={exportCSV}
                className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800 bg-gray-100 hover:bg-gray-200 px-3 py-1.5 rounded-lg transition-colors font-medium"
              >
                <Download size={12} /> Export CSV
              </button>
              <button
                onClick={onClose}
                className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
              >
                <X size={16} />
              </button>
            </div>
          </div>

          {/* Bulk action bar */}
          {selected.size > 0 && (
            <div className="flex items-center gap-3 px-5 py-2.5 bg-teal-50 border-b border-teal-100 flex-shrink-0">
              <span className="text-xs font-semibold text-teal-700">{selected.size} selected</span>
              <button className="flex items-center gap-1 text-xs text-teal-700 hover:text-teal-900 bg-white px-2.5 py-1 rounded-lg border border-teal-200 transition-colors font-medium">
                <Tag size={11} /> Tag
              </button>
              <button className="flex items-center gap-1 text-xs text-teal-700 hover:text-teal-900 bg-white px-2.5 py-1 rounded-lg border border-teal-200 transition-colors font-medium">
                <Send size={11} /> Re-engage
              </button>
              <button className="flex items-center gap-1 text-xs text-teal-700 hover:text-teal-900 bg-white px-2.5 py-1 rounded-lg border border-teal-200 transition-colors font-medium">
                <Flag size={11} /> Flag for review
              </button>
              <button
                onClick={() => setSelected(new Set())}
                className="ml-auto text-xs text-gray-400 hover:text-gray-600 transition-colors"
              >
                Clear
              </button>
            </div>
          )}

          {/* Table header */}
          <div className="flex items-center gap-3 px-5 py-2 bg-gray-50 border-b border-gray-100 flex-shrink-0 text-[11px] font-bold text-gray-400 uppercase tracking-wider">
            <input
              type="checkbox"
              className="w-3.5 h-3.5 accent-teal-500 flex-shrink-0 cursor-pointer"
              checked={!!data && selected.size === data.items.length && data.items.length > 0}
              onChange={selectAll}
            />
            <span className="flex-1">Guest</span>
            <span className="w-28">Property</span>
            <span className="w-24">Dates</span>
            <span className="w-24">Lost reason</span>
            <span className="w-8" />
          </div>

          {/* Rows */}
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <div className="p-5 space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="h-12 bg-gray-50 rounded-xl animate-pulse" />
                ))}
              </div>
            ) : !data?.items.length ? (
              <p className="text-sm text-gray-400 py-8 text-center">No inquiries found for this theme</p>
            ) : (
              data.items.map(inq => (
                <div
                  key={inq.id}
                  className={cn(
                    "flex items-center gap-3 px-5 py-3 border-b border-gray-50 hover:bg-gray-50/80 transition-colors group",
                    selected.has(inq.id) && "bg-teal-50/40"
                  )}
                >
                  <input
                    type="checkbox"
                    className="w-3.5 h-3.5 accent-teal-500 flex-shrink-0 cursor-pointer"
                    checked={selected.has(inq.id)}
                    onChange={() => toggleSelect(inq.id)}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">
                      {inq.guest_name ?? inq.guest_phone}
                    </p>
                    <p className="text-[11px] text-gray-400 truncate">{inq.guest_phone}</p>
                  </div>
                  <span className="w-28 text-xs text-gray-500 truncate">{inq.property_name ?? "—"}</span>
                  <span className="w-24 text-xs text-gray-400">
                    {inq.check_in ? new Date(inq.check_in).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "—"}
                  </span>
                  <span className="w-24 text-xs text-gray-500 truncate capitalize">
                    {inq.lost_reason?.replace(/_/g, " ") ?? "—"}
                  </span>
                  <button
                    onClick={() => { onClose(); router.push(`/dashboard/inquiries/${inq.id}`); }}
                    className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-300 hover:text-teal-600 hover:bg-teal-50 transition-colors opacity-0 group-hover:opacity-100"
                    title="Open inquiry"
                  >
                    <ExternalLink size={13} />
                  </button>
                </div>
              ))
            )}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-5 py-3 border-t border-gray-100 flex-shrink-0">
              <span className="text-xs text-gray-400">
                Page {page} of {totalPages} · {data?.total ?? 0} total
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-3 py-1.5 text-xs font-medium text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  Previous
                </button>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="px-3 py-1.5 text-xs font-medium text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
