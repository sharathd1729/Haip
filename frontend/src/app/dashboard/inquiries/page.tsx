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
import { canTransition, type InquiryStage } from "@/lib/inquiry/transitions";

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
  assigned_to?: string;
  assignee_name?: string;
  current_stage_entered_at?: string;
  sla_state?: string;
  sla_elapsed_seconds?: number;
}

const STAGES = [
  { id: "new",        title: "New",        color: "border-l-4 border-l-blue-400" },
  { id: "responding", title: "Responding", color: "border-l-4 border-l-purple-400" },
  { id: "quoted",     title: "Quoted",     color: "border-l-4 border-l-amber-400" },
  { id: "site_visit", title: "Site Visit", color: "border-l-4 border-l-orange-400" },
  { id: "booked",     title: "Booked",     color: "border-l-4 border-l-teal-500" },
  { id: "lost",       title: "Lost",       color: "border-l-4 border-l-red-400" },
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

  // K1: track drag state for highlighting
  const [draggingFrom, setDraggingFrom] = useState<InquiryStage | null>(null);

  // Lost reason modal (K9: "Other" with required free-text)
  const [lostModal, setLostModal] = useState<{ cardId: string; fromStage: string } | null>(null);
  const [lostReason, setLostReason] = useState("");
  const [lostCustom, setLostCustom] = useState("");   // K9: free-text for "Other"

  // Backward transition modal (K1)
  const [backModal, setBackModal] = useState<{ cardId: string; to: string; from: string } | null>(null);
  const [backReason, setBackReason] = useState("");

  const { data: inquiries = [], isLoading } = useQuery<Inquiry[]>({
    queryKey: ["inquiries"],
    queryFn: () => api.get("/inquiries").then(r => r.data),
    staleTime: 30_000,
  });

  const stageMutation = useMutation({
    mutationFn: ({ id, stage, lost_reason, lost_note, reason }:
      { id: string; stage: string; lost_reason?: string; lost_note?: string; reason?: string }) =>
      api.patch(`/inquiries/${id}`, { stage, lost_reason, lost_note, reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inquiries"] });
      toast({ variant: "success", title: "Stage updated" });
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? "Update failed";
      toast({ variant: "error", title: msg });
    },
  });

  const handleDrop = (cardId: string, newStage: string) => {
    const inquiry = inquiries.find(i => i.id === cardId);
    if (!inquiry) return;
    const from = inquiry.stage as InquiryStage;
    const to   = newStage as InquiryStage;

    const result = canTransition(from, to);

    if (result.allowed === false) {
      toast({ variant: "error", title: `Cannot move from "${from}" to "${to}"` });
      return;
    }
    if (result.allowed === "backward") {
      setBackModal({ cardId, to: newStage, from: inquiry.stage });
      setBackReason("");
      return;
    }
    if (to === "lost") {
      setLostModal({ cardId, fromStage: from });
      setLostReason("");
      setLostCustom("");
      return;
    }
    stageMutation.mutate({ id: cardId, stage: newStage });
  };

  const confirmLost = () => {
    if (!lostModal) return;
    const isOther = lostReason === "Other";
    // K9: require free-text when "Other" is selected
    if (isOther && lostCustom.trim().length < 5) return;
    stageMutation.mutate({
      id: lostModal.cardId,
      stage: "lost",
      lost_reason: isOther ? "other" : lostReason.toLowerCase().replace(/ /g, "_"),
      lost_note: isOther ? lostCustom.trim() : undefined,
    });
    setLostModal(null);
    setLostReason("");
    setLostCustom("");
  };

  const confirmBackward = () => {
    if (!backModal || !backReason.trim()) return;
    stageMutation.mutate({ id: backModal.cardId, stage: backModal.to, reason: backReason.trim() });
    setBackModal(null);
    setBackReason("");
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
              : STAGES.map(stage => {
                  // K1: compute if this column is an allowed drop target during drag
                  const isAllowedDrop = draggingFrom
                    ? (() => { const r = canTransition(draggingFrom, stage.id as InquiryStage); return r.allowed !== false; })()
                    : true;

                  return (
                    <KanbanColumn
                      key={stage.id}
                      id={stage.id}
                      title={stage.title}
                      color={cn(stage.color, !isAllowedDrop && draggingFrom && "opacity-40")}
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
                        assigned_to: inq.assigned_to,
                        assignee_name: inq.assignee_name,
                        current_stage_entered_at: inq.current_stage_entered_at,
                        sla_state: inq.sla_state,
                        sla_elapsed_seconds: inq.sla_elapsed_seconds,
                      }))}
                      count={grouped[stage.id].length}
                      onCardClick={id => router.push(`/dashboard/guests?inquiry=${id}`)}
                      onDrop={handleDrop}
                      onDragStart={(cardId) => {
                        const inq = inquiries.find(i => i.id === cardId);
                        if (inq) setDraggingFrom(inq.stage as InquiryStage);
                      }}
                      onDragEnd={() => setDraggingFrom(null)}
                    />
                  );
                })
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
                        <Badge variant={inq.stage === "booked" ? "success" : inq.stage === "lost" ? "destructive" : inq.stage === "quoted" ? "info" : "secondary"} className="capitalize">{inq.stage}</Badge>
                      </td>
                      <td className="px-4 py-3 text-gray-600 capitalize">{inq.channel || "—"}</td>
                    </tr>
                  ))
              }
            </tbody>
          </table>
        </div>
      )}

      {/* Lost reason modal (K9) */}
      {lostModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-gray-900">Why was this inquiry lost?</h3>
              <button onClick={() => setLostModal(null)}><X size={16} className="text-gray-400" /></button>
            </div>
            <div className="space-y-2 mb-4">
              {LOST_REASONS.map(r => (
                <button key={r} onClick={() => { setLostReason(r); if (r !== "Other") setLostCustom(""); }}
                  className={cn("w-full text-left px-4 py-2.5 rounded-xl border text-sm transition-all",
                    lostReason === r ? "bg-red-50 border-red-200 text-red-700 font-medium" : "bg-gray-50 border-gray-100 text-gray-700 hover:bg-gray-100"
                  )}>{r}</button>
              ))}
            </div>
            {/* K9: "Other" free-text input */}
            {lostReason === "Other" && (
              <div className="mb-4">
                <textarea
                  value={lostCustom}
                  onChange={e => setLostCustom(e.target.value)}
                  placeholder="Please describe the reason (min 5 characters)…"
                  rows={3}
                  className="w-full text-sm border border-gray-200 rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-red-300 resize-none"
                />
                {lostCustom.trim().length > 0 && lostCustom.trim().length < 5 && (
                  <p className="text-xs text-red-500 mt-1">Please add at least 5 characters</p>
                )}
              </div>
            )}
            <div className="flex gap-2">
              <button onClick={() => setLostModal(null)} className="flex-1 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50 transition-colors">Cancel</button>
              <button
                onClick={confirmLost}
                disabled={!lostReason || (lostReason === "Other" && lostCustom.trim().length < 5)}
                className="flex-1 py-2.5 bg-red-500 hover:bg-red-600 disabled:opacity-40 text-white font-semibold rounded-xl text-sm transition-colors"
              >Mark as lost</button>
            </div>
          </div>
        </div>
      )}

      {/* K1: backward transition reason modal */}
      {backModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-bold text-gray-900">Why is this moving back?</h3>
              <button onClick={() => setBackModal(null)}><X size={16} className="text-gray-400" /></button>
            </div>
            <p className="text-xs text-gray-500 mb-4">
              Moving from <strong>{backModal.from}</strong> → <strong>{backModal.to}</strong> requires a reason.
              Owner/manager role required.
            </p>
            <textarea
              value={backReason}
              onChange={e => setBackReason(e.target.value)}
              placeholder="Reason for moving backward…"
              rows={3}
              className="w-full text-sm border border-gray-200 rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-amber-300 resize-none mb-4"
            />
            <div className="flex gap-2">
              <button onClick={() => setBackModal(null)} className="flex-1 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50 transition-colors">Cancel</button>
              <button
                onClick={confirmBackward}
                disabled={!backReason.trim()}
                className="flex-1 py-2.5 bg-amber-500 hover:bg-amber-600 disabled:opacity-40 text-white font-semibold rounded-xl text-sm transition-colors"
              >Move back</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
