"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { LayoutGrid, List, Plus, X } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { KanbanColumn } from "@/components/crm/KanbanColumn";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

interface Inquiry {
  id: string;
  stage: string;
  guest_name?: string;
  guest_phone: string;
  property_name?: string;
  check_in?: string;
  check_out?: string;
  budget?: number;
  channel?: string;
  tags?: string[];
  last_activity?: string;
  created_at: string;
}

const STAGES = [
  { id: "new",       title: "New",       color: "border-l-4 border-l-blue-400" },
  { id: "qualified", title: "Qualified", color: "border-l-4 border-l-purple-400" },
  { id: "proposal",  title: "Proposal",  color: "border-l-4 border-l-amber-400" },
  { id: "booked",    title: "Booked",    color: "border-l-4 border-l-teal-500" },
  { id: "lost",      title: "Lost",      color: "border-l-4 border-l-red-400" },
];

const LOST_REASONS = [
  "Price too high", "Went with competitor", "Dates unavailable",
  "No response", "Changed plans", "Other",
];

export default function InquiriesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [view, setView] = useState<"kanban" | "table">("kanban");
  const [lostModal, setLostModal] = useState<{ cardId: string } | null>(null);
  const [lostReason, setLostReason] = useState("");

  const { data: inquiries = [], isLoading } = useQuery<Inquiry[]>({
    queryKey: ["inquiries"],
    queryFn: () => api.get("/inquiries").then(r => r.data),
    staleTime: 30_000,
  });

  const stageMutation = useMutation({
    mutationFn: ({ id, stage, lost_reason }: { id: string; stage: string; lost_reason?: string }) =>
      api.patch(`/inquiries/${id}`, { stage, lost_reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inquiries"] });
      toast({ variant: "success", title: "Stage updated" });
    },
    onError: () => toast({ variant: "error", title: "Update failed" }),
  });

  const handleDrop = (cardId: string, newStage: string) => {
    if (newStage === "lost") { setLostModal({ cardId }); return; }
    stageMutation.mutate({ id: cardId, stage: newStage });
  };

  const confirmLost = () => {
    if (!lostModal) return;
    stageMutation.mutate({ id: lostModal.cardId, stage: "lost", lost_reason: lostReason || "Other" });
    setLostModal(null);
    setLostReason("");
  };

  const grouped: Record<string, Inquiry[]> = {};
  for (const s of STAGES) grouped[s.id] = [];
  for (const inq of inquiries) (grouped[inq.stage ?? "new"] ??= []).push(inq);

  return (
    <div className="h-full flex flex-col bg-white overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Inquiries</h1>
          <p className="text-xs text-gray-400 mt-0.5">{inquiries.length} total · drag cards to update stage</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
            <button onClick={() => setView("kanban")} className={cn("p-1.5 rounded-md transition-colors", view === "kanban" ? "bg-white shadow-sm text-gray-800" : "text-gray-400")}>
              <LayoutGrid size={15} />
            </button>
            <button onClick={() => setView("table")} className={cn("p-1.5 rounded-md transition-colors", view === "table" ? "bg-white shadow-sm text-gray-800" : "text-gray-400")}>
              <List size={15} />
            </button>
          </div>
          <button className="flex items-center gap-1.5 text-xs bg-teal-500 text-white px-3 py-1.5 rounded-lg font-medium hover:bg-teal-600 transition-colors">
            <Plus size={13} /> New inquiry
          </button>
        </div>
      </div>

      {view === "kanban" && (
        <div className="flex-1 overflow-x-auto overflow-y-hidden">
          <div className="flex gap-4 p-5 h-full min-w-max">
            {isLoading
              ? Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="w-[272px] flex-shrink-0 space-y-3">
                    <Skeleton className="h-10 w-full rounded-t-2xl" />
                    {Array.from({ length: 3 }).map((_, j) => <Skeleton key={j} className="h-24 w-full rounded-xl" />)}
                  </div>
                ))
              : STAGES.map(stage => (
                  <KanbanColumn
                    key={stage.id}
                    id={stage.id}
                    title={stage.title}
                    color={stage.color}
                    cards={grouped[stage.id].map(inq => ({
                      id: inq.id,
                      guest_name: inq.guest_name,
                      guest_phone: inq.guest_phone,
                      property_name: inq.property_name,
                      check_in: inq.check_in,
                      check_out: inq.check_out,
                      budget: inq.budget,
                      channel: inq.channel,
                      tags: inq.tags,
                    }))}
                    count={grouped[stage.id].length}
                    onCardClick={id => router.push(`/dashboard/guests?inquiry=${id}`)}
                    onDrop={handleDrop}
                  />
                ))
            }
          </div>
        </div>
      )}

      {view === "table" && (
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white border-b border-gray-100">
              <tr>
                {["Guest", "Property", "Check-in", "Budget", "Stage", "Channel"].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {isLoading
                ? Array.from({ length: 6 }).map((_, i) => (
                    <tr key={i}>{Array.from({ length: 6 }).map((_, j) => <td key={j} className="px-4 py-3"><Skeleton className="h-4 w-full" /></td>)}</tr>
                  ))
                : inquiries.length === 0
                ? <tr><td colSpan={6} className="text-center py-16 text-sm text-gray-400">No inquiries yet</td></tr>
                : inquiries.map(inq => (
                    <tr key={inq.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => router.push(`/dashboard/guests?inquiry=${inq.id}`)}>
                      <td className="px-4 py-3 font-medium text-gray-900">{inq.guest_name || inq.guest_phone}</td>
                      <td className="px-4 py-3 text-gray-600">{inq.property_name || "—"}</td>
                      <td className="px-4 py-3 text-gray-600">{inq.check_in ? new Date(inq.check_in).toLocaleDateString("en-IN") : "—"}</td>
                      <td className="px-4 py-3 font-semibold text-gray-800">{inq.budget ? `₹${inq.budget.toLocaleString("en-IN")}` : "—"}</td>
                      <td className="px-4 py-3">
                        <Badge variant={inq.stage === "booked" ? "success" : inq.stage === "lost" ? "destructive" : inq.stage === "qualified" ? "info" : "secondary"} className="capitalize">{inq.stage}</Badge>
                      </td>
                      <td className="px-4 py-3 text-gray-600 capitalize">{inq.channel || "—"}</td>
                    </tr>
                  ))
              }
            </tbody>
          </table>
        </div>
      )}

      {lostModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-gray-900">Why was this inquiry lost?</h3>
              <button onClick={() => setLostModal(null)}><X size={16} className="text-gray-400" /></button>
            </div>
            <div className="space-y-2 mb-5">
              {LOST_REASONS.map(r => (
                <button key={r} onClick={() => setLostReason(r)}
                  className={cn("w-full text-left px-4 py-2.5 rounded-xl border text-sm transition-all",
                    lostReason === r ? "bg-red-50 border-red-200 text-red-700 font-medium" : "bg-gray-50 border-gray-100 text-gray-700 hover:bg-gray-100"
                  )}>{r}</button>
              ))}
            </div>
            <div className="flex gap-2">
              <button onClick={() => setLostModal(null)} className="flex-1 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50 transition-colors">Cancel</button>
              <button onClick={confirmLost} className="flex-1 py-2.5 bg-red-500 hover:bg-red-600 text-white font-semibold rounded-xl text-sm transition-colors">Mark as lost</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
