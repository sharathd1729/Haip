"use client";
import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { LayoutGrid, List, Plus, X, StickyNote, Send } from "@/lib/icons";
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

// ─── M3: Kanban scroll-snap container with indicator dots ─────────────────────

function KanbanScrollContainer({ children, stageCount }: { children: React.ReactNode; stageCount: number }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    function onScroll() {
      if (!el) return;
      // Each column is ~276px (272 + 4px gap)
      const colWidth = 276;
      setActiveIdx(Math.round(el.scrollLeft / colWidth));
    }
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  function scrollTo(idx: number) {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ left: idx * 276, behavior: "smooth" });
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Scroll area with snap on mobile */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-x-auto overflow-y-hidden"
        style={{
          scrollSnapType: "x mandatory",
          WebkitOverflowScrolling: "touch",
        }}
      >
        <div
          className="flex gap-4 p-5 h-full"
          style={{ minWidth: "max-content" }}
        >
          {children}
        </div>
      </div>

      {/* M3: indicator dots — visible on mobile only */}
      <div className="md:hidden flex items-center justify-center gap-1.5 py-2 flex-shrink-0">
        {Array.from({ length: stageCount }).map((_, i) => (
          <button
            key={i}
            onClick={() => scrollTo(i)}
            aria-label={`Go to column ${i + 1}`}
            className={cn(
              "rounded-full transition-all duration-200",
              i === activeIdx
                ? "w-4 h-1.5 bg-teal-500"
                : "w-1.5 h-1.5 bg-gray-300"
            )}
          />
        ))}
      </div>
    </div>
  );
}

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

  // K13: aging widget stats
  const now = Date.now();
  const activeInqs = inquiries.filter(i => !["booked","lost","ghosted"].includes(i.stage));
  const staleCount  = activeInqs.filter(i => {
    const ref = i.current_stage_entered_at ?? i.created_at;
    return ref && (now - new Date(ref).getTime()) > 3 * 86_400_000;
  }).length;
  const breachCount = activeInqs.filter(i => i.sla_state === "breach").length;
  const newCount    = grouped["new"]?.length ?? 0;

  const [agingFilter, setAgingFilter] = useState<"stale" | "breach" | null>(null);

  // K11: saved views for inquiries
  const { data: inquirySavedViews = [] } = useQuery({
    queryKey: ["saved-views", "inquiries"],
    queryFn: () => api.get("/saved-views?scope=inquiries").then(r => r.data),
  } as any);
  const [activeViewId, setActiveViewId] = useState<string | null>(null);

  // K15: internal notes per inquiry
  const [notesPanel, setNotesPanel] = useState<{ inquiryId: string; guestName: string } | null>(null);
  const [noteText, setNoteText] = useState("");

  const { data: inquiryNotes = [], refetch: refetchNotes } = useQuery({
    queryKey: ["inquiry-notes", notesPanel?.inquiryId],
    queryFn: () => api.get(`/inquiries/${notesPanel!.inquiryId}/notes`).then(r => r.data),
    enabled: !!notesPanel,
  } as any);

  const addNoteMutation = useMutation({
    mutationFn: (text: string) => api.post(`/inquiries/${notesPanel!.inquiryId}/notes`, { body: text }),
    onSuccess: () => {
      setNoteText("");
      refetchNotes();
      toast({ variant: "success", title: "Note added" });
    },
    onError: () => toast({ variant: "error", title: "Failed to add note" }),
  });

  return (
    <div className="h-full flex flex-col bg-background overflow-hidden">
      <div className="px-5 py-4 border-b border-border flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-lg font-bold text-foreground">Inquiries</h1>
          <p className="text-xs text-muted-foreground mt-0.5">{inquiries.length} total · drag cards to update stage</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-white/[0.06] rounded-lg p-0.5">
            <button onClick={() => setView("kanban")} className={cn("p-1.5 rounded-md transition-colors", view === "kanban" ? "bg-white/10 text-foreground" : "text-muted-foreground")}>
              <LayoutGrid size={15} />
            </button>
            <button onClick={() => setView("table")} className={cn("p-1.5 rounded-md transition-colors", view === "table" ? "bg-white/10 text-foreground" : "text-muted-foreground")}>
              <List size={15} />
            </button>
          </div>
          <button className="flex items-center gap-1.5 text-xs bg-teal-500 text-white px-3 py-1.5 rounded-lg font-medium hover:bg-teal-600 transition-colors">
            <Plus size={13} /> New inquiry
          </button>
        </div>
      </div>

      {/* K11: saved views chips */}
      {(inquirySavedViews as any[]).length > 0 && (
        <div className="px-5 py-2 border-b border-gray-50 flex items-center gap-2 flex-shrink-0 overflow-x-auto">
          <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400 flex-shrink-0">Views:</span>
          <button
            onClick={() => setActiveViewId(null)}
            className={cn(
              "text-[11px] font-medium px-2.5 py-1 rounded-lg flex-shrink-0 transition-colors",
              activeViewId === null ? "bg-teal-100 text-teal-700" : "text-gray-500 hover:bg-gray-100"
            )}
          >
            All
          </button>
          {(inquirySavedViews as any[]).map((view: any) => (
            <button
              key={view.id}
              onClick={() => setActiveViewId(activeViewId === view.id ? null : view.id)}
              className={cn(
                "text-[11px] font-medium px-2.5 py-1 rounded-lg flex-shrink-0 transition-colors",
                activeViewId === view.id ? "bg-teal-100 text-teal-700" : "text-gray-500 hover:bg-gray-100"
              )}
            >
              {view.name}
              {view.is_shared && <span className="ml-1 text-gray-400">·shared</span>}
            </button>
          ))}
        </div>
      )}

      {/* K13: Inquiry-aging chip strip */}
      {!isLoading && (
        <div className="px-5 py-2 border-b border-border flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => setAgingFilter(null)}
            className={cn("text-[11px] font-medium px-2.5 py-1 rounded-lg transition-colors",
              agingFilter === null ? "bg-teal-500/20 text-teal-400" : "text-muted-foreground hover:bg-white/[0.06]"
            )}
          >
            All active: {activeInqs.length}
          </button>
          <button
            onClick={() => setAgingFilter(f => f === "breach" ? null : "breach")}
            className={cn("text-[11px] font-medium px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1",
              agingFilter === "breach"
                ? "bg-red-500/20 text-red-400"
                : breachCount > 0 ? "text-red-400 hover:bg-red-500/10" : "text-muted-foreground/50 cursor-default"
            )}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-current" />
            {breachCount} SLA breach
          </button>
          <button
            onClick={() => setAgingFilter(f => f === "stale" ? null : "stale")}
            className={cn("text-[11px] font-medium px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1",
              agingFilter === "stale"
                ? "bg-amber-500/20 text-amber-400"
                : staleCount > 0 ? "text-amber-400 hover:bg-amber-500/10" : "text-muted-foreground/50 cursor-default"
            )}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-current" />
            {staleCount} stale &gt;3d
          </button>
          <span className="text-[11px] text-muted-foreground ml-auto">
            {newCount} in New
          </span>
        </div>
      )}

      {view === "kanban" && (
        <KanbanScrollContainer stageCount={STAGES.length}>
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

                  // K13: filter cards by aging chip selection
                  const visibleCards = (grouped[stage.id] ?? []).filter(inq => {
                    if (!agingFilter) return true;
                    if (agingFilter === "breach") return inq.sla_state === "breach";
                    if (agingFilter === "stale") {
                      const ref = inq.current_stage_entered_at ?? inq.created_at;
                      return ref && (now - new Date(ref).getTime()) > 3 * 86_400_000;
                    }
                    return true;
                  });

                  return (
                    <KanbanColumn
                      key={stage.id}
                      id={stage.id}
                      title={stage.title}
                      color={cn(stage.color, !isAllowedDrop && draggingFrom && "opacity-40")}
                      cards={visibleCards.map(inq => ({
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
                      count={visibleCards.length}
                      onCardClick={id => router.push(`/dashboard/guests?inquiry=${id}`)}
                      onNoteClick={(id, guestName) => {
                        setNotesPanel({ inquiryId: id, guestName });
                        setNoteText("");
                      }}
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
        </KanbanScrollContainer>
      )}

      {view === "table" && (
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-background border-b border-border">
              <tr>
                {["Guest", "Property", "Check-in", "Budget", "Stage", "Channel"].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {isLoading
                ? Array.from({ length: 6 }).map((_, i) => (
                    <tr key={i}>{Array.from({ length: 6 }).map((_, j) => <td key={j} className="px-4 py-3"><Skeleton className="h-4 w-full" /></td>)}</tr>
                  ))
                : inquiries.length === 0
                ? <tr><td colSpan={6} className="text-center py-16 text-sm text-muted-foreground">No inquiries yet</td></tr>
                : inquiries.map(inq => (
                    <tr key={inq.id} className="hover:bg-white/[0.04] cursor-pointer transition-colors" onClick={() => router.push(`/dashboard/guests?inquiry=${inq.id}`)}>
                      <td className="px-4 py-3 font-medium text-foreground">{inq.guest_name || inq.guest_phone}</td>
                      <td className="px-4 py-3 text-muted-foreground">{inq.property_name || "—"}</td>
                      <td className="px-4 py-3 text-muted-foreground">{inq.check_in ? new Date(inq.check_in).toLocaleDateString("en-IN") : "—"}</td>
                      <td className="px-4 py-3 font-semibold text-foreground">{inq.budget ? `₹${inq.budget.toLocaleString("en-IN")}` : "—"}</td>
                      <td className="px-4 py-3">
                        <Badge variant={inq.stage === "booked" ? "success" : inq.stage === "lost" ? "destructive" : inq.stage === "quoted" ? "info" : "secondary"} className="capitalize">{inq.stage}</Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground capitalize">{inq.channel || "—"}</td>
                    </tr>
                  ))
              }
            </tbody>
          </table>
        </div>
      )}

      {/* Lost reason modal (K9) */}
      {lostModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-card border border-border rounded-2xl shadow-2xl w-full max-w-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-foreground">Why was this inquiry lost?</h3>
              <button onClick={() => setLostModal(null)}><X size={16} className="text-muted-foreground" /></button>
            </div>
            <div className="space-y-2 mb-4">
              {LOST_REASONS.map(r => (
                <button key={r} onClick={() => { setLostReason(r); if (r !== "Other") setLostCustom(""); }}
                  className={cn("w-full text-left px-4 py-2.5 rounded-xl border text-sm transition-all",
                    lostReason === r ? "bg-red-500/20 border-red-500/40 text-red-400 font-medium" : "bg-white/[0.04] border-border text-foreground hover:bg-white/[0.08]"
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
                  className="w-full text-sm bg-white/[0.05] border border-border rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-red-400/40 resize-none"
                />
                {lostCustom.trim().length > 0 && lostCustom.trim().length < 5 && (
                  <p className="text-xs text-red-400 mt-1">Please add at least 5 characters</p>
                )}
              </div>
            )}
            <div className="flex gap-2">
              <button onClick={() => setLostModal(null)} className="flex-1 py-2.5 border border-border rounded-xl text-sm text-muted-foreground hover:bg-white/[0.05] transition-colors">Cancel</button>
              <button
                onClick={confirmLost}
                disabled={!lostReason || (lostReason === "Other" && lostCustom.trim().length < 5)}
                className="flex-1 py-2.5 bg-red-500 hover:bg-red-600 disabled:opacity-40 text-white font-semibold rounded-xl text-sm transition-colors"
              >Mark as lost</button>
            </div>
          </div>
        </div>
      )}

      {/* K15: Internal notes slide-over panel */}
      {notesPanel && (
        <div className="fixed inset-0 z-40 flex justify-end">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/20" onClick={() => setNotesPanel(null)} />
          <div className="relative w-80 bg-card border-l border-border shadow-2xl flex flex-col h-full">
            {/* Header */}
            <div className="flex items-center gap-3 px-4 py-4 border-b border-border">
              <StickyNote size={16} className="text-amber-400" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-bold text-foreground">Internal Notes</p>
                <p className="text-xs text-muted-foreground truncate">{notesPanel.guestName}</p>
              </div>
              <button onClick={() => setNotesPanel(null)} className="text-muted-foreground hover:text-foreground transition-colors">
                <X size={16} />
              </button>
            </div>

            {/* Notes list */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {(inquiryNotes as any[]).length === 0 ? (
                <div className="text-center py-12">
                  <StickyNote size={24} className="text-white/10 mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">No notes yet</p>
                  <p className="text-xs text-muted-foreground/60 mt-1">Notes are only visible to your team</p>
                </div>
              ) : (
                (inquiryNotes as any[]).map((note: any) => (
                  <div key={note.id} className="bg-amber-50 border border-amber-100 rounded-xl px-3 py-2.5">
                    <p className="text-sm text-amber-900 whitespace-pre-wrap">{note.body}</p>
                    <div className="flex items-center gap-2 mt-1.5">
                      <span className="text-[10px] text-amber-400">
                        {note.sender_name || "Team"}
                      </span>
                      <span className="text-[10px] text-amber-300">·</span>
                      <span className="text-[10px] text-amber-400">
                        {new Date(note.created_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Composer */}
            <div className="p-3 border-t border-border bg-background/50">
              <textarea
                value={noteText}
                onChange={e => setNoteText(e.target.value)}
                placeholder="Add a note… (only visible to team)"
                rows={3}
                className="w-full text-sm border border-amber-500/30 rounded-xl px-3 py-2.5 bg-amber-500/[0.08] text-foreground placeholder:text-amber-400/40 focus:outline-none focus:ring-2 focus:ring-amber-400/30 resize-none mb-2"
                onKeyDown={e => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && noteText.trim()) {
                    addNoteMutation.mutate(noteText.trim());
                  }
                }}
              />
              <button
                onClick={() => noteText.trim() && addNoteMutation.mutate(noteText.trim())}
                disabled={!noteText.trim() || addNoteMutation.isPending}
                className="w-full py-2 bg-amber-500 hover:bg-amber-600 disabled:opacity-40 text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2"
              >
                {addNoteMutation.isPending ? <span className="animate-spin">⏳</span> : <Send size={13} />}
                Add note
              </button>
              <p className="text-[10px] text-gray-400 text-center mt-1">Ctrl+Enter to submit</p>
            </div>
          </div>
        </div>
      )}

      {/* K1: backward transition reason modal */}
      {backModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-card border border-border rounded-2xl shadow-2xl w-full max-w-sm p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-bold text-foreground">Why is this moving back?</h3>
              <button onClick={() => setBackModal(null)}><X size={16} className="text-muted-foreground" /></button>
            </div>
            <p className="text-xs text-muted-foreground mb-4">
              Moving from <strong className="text-foreground">{backModal.from}</strong> → <strong className="text-foreground">{backModal.to}</strong> requires a reason.
              Owner/manager role required.
            </p>
            <textarea
              value={backReason}
              onChange={e => setBackReason(e.target.value)}
              placeholder="Reason for moving backward…"
              rows={3}
              className="w-full text-sm bg-white/[0.05] border border-border rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-amber-400/40 resize-none mb-4"
            />
            <div className="flex gap-2">
              <button onClick={() => setBackModal(null)} className="flex-1 py-2.5 border border-border rounded-xl text-sm text-muted-foreground hover:bg-white/[0.05] transition-colors">Cancel</button>
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
