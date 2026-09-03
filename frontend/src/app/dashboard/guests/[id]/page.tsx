"use client";
import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import Link from "next/link";
import {
  ArrowLeft, Phone, Mail, Home, Star, Shield, Trash2, FileText,
  PlayCircle, Sparkles, Loader2, Send,
} from "@/lib/icons";
import { UserCheck, Bed } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { GuestJourney } from "@/components/guests/GuestJourney";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

interface GuestDetail {
  id: string;
  name?: string;
  phone: string;
  email?: string;
  tags?: string[];
  consent_status?: string;
  predicted_csat?: number;
  lifetime_value?: number;
  created_at?: string;
}

interface GuestInquiry {
  id: string;
  stage: string;
  created_at?: string | null;
}

interface LeadOwnerStage {
  inquiry_id: string;
  assigned_agent_name?: string | null;
  assigned_agent_id?: string | null;
  stage_key?: string | null;
}

interface PipelineStage {
  id: string;
  key: string;
  label: string;
}

interface TeamMember {
  id: string;
  name: string;
}

interface GuestStay {
  id: string;
  checkin?: string | null;
  checkout?: string | null;
  status?: string;
  property?: { id: string; name: string } | null;
}

interface CallListItem {
  id: string;
  direction: string;
  duration_seconds: number;
  is_missed: boolean;
  started_at?: string | null;
  disposition: string;
  qa_score?: number | null;
  ai_summary?: string | null;
  has_transcript: boolean;
  created_at?: string | null;
}

interface InquiryNote {
  id: string;
  body: string;
  sender_name?: string | null;
  created_at?: string | null;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function formatDuration(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function GuestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { toast } = useToast();
  const qc = useQueryClient();
  const { data: session } = useSession();
  const currentUserId = session?.user?.id;
  const canAssignAnyone = session?.user?.role === "owner" || session?.user?.role === "manager";

  const [noteDraft, setNoteDraft] = useState("");

  const { data: guest, isLoading } = useQuery<GuestDetail>({
    queryKey: ["guest", id],
    queryFn: () => api.get(`/guests/${id}`).then(r => r.data),
  });

  // Most recent inquiry drives the Assign Owner / Lead Stage / Agent Remarks
  // widgets below -- a guest with multiple inquiries gets those scoped to
  // whichever is newest (list is already created_at desc server-side).
  const { data: inquiries = [] } = useQuery<GuestInquiry[]>({
    queryKey: ["guest-inquiries", id],
    queryFn: () => api.get(`/inquiries?guest_id=${id}`).then(r => r.data),
    enabled: !!id,
  });
  const currentInquiryId = inquiries[0]?.id ?? null;

  const { data: leadOwnerStage } = useQuery<LeadOwnerStage>({
    queryKey: ["lead-detail", currentInquiryId],
    queryFn: () => api.get(`/leads/${currentInquiryId}`).then(r => r.data),
    enabled: !!currentInquiryId,
  });

  const { data: stages } = useQuery<PipelineStage[]>({
    queryKey: ["pipeline-stages"],
    queryFn: () => api.get("/pipeline-stages").then(r => r.data),
    staleTime: 60_000,
  });

  const { data: teamMembers } = useQuery<TeamMember[]>({
    queryKey: ["team-members"],
    queryFn: () => api.get("/users").then(r => r.data),
    enabled: canAssignAnyone,
    staleTime: 60_000,
  });

  const { data: stays = [] } = useQuery<GuestStay[]>({
    queryKey: ["guest-stays", id],
    queryFn: () => api.get(`/bookings?guest_id=${id}&per_page=100`).then(r => r.data.data),
    enabled: !!id,
  });

  const { data: calls } = useQuery<{ items: CallListItem[] }>({
    queryKey: ["guest-calls", id],
    queryFn: () => api.get(`/calls?guest_id=${id}&limit=10`).then(r => r.data),
    enabled: !!id,
  });

  const { data: notes = [] } = useQuery<InquiryNote[]>({
    queryKey: ["inquiry-notes", currentInquiryId],
    queryFn: () => api.get(`/inquiries/${currentInquiryId}/notes`).then(r => r.data),
    enabled: !!currentInquiryId,
  });

  const assignLead = useMutation({
    mutationFn: (userId: string) =>
      api.post("/automations/actions/execute", {
        action_type: "assign_to",
        entity_refs: { inquiry_id: currentInquiryId },
        action_config: { user_id: userId },
        source: "profile_360",
      }),
    onSuccess: () => {
      toast({ title: "Lead assigned" });
      qc.invalidateQueries({ queryKey: ["lead-detail", currentInquiryId] });
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Could not assign lead", description: typeof msg === "string" ? msg : "Please try again." });
    },
  });

  const moveStage = useMutation({
    mutationFn: (newStageId: string) =>
      api.post("/automations/actions/execute", {
        action_type: "move_stage",
        entity_refs: { inquiry_id: currentInquiryId },
        action_config: { new_stage_id: newStageId },
        source: "profile_360",
      }),
    onSuccess: () => {
      toast({ title: "Lead stage updated" });
      qc.invalidateQueries({ queryKey: ["lead-detail", currentInquiryId] });
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Could not update stage", description: typeof msg === "string" ? msg : "Please try again." });
    },
  });

  const addNote = useMutation({
    mutationFn: (body: string) => api.post(`/inquiries/${currentInquiryId}/notes`, { body }),
    onSuccess: () => {
      setNoteDraft("");
      qc.invalidateQueries({ queryKey: ["inquiry-notes", currentInquiryId] });
    },
    onError: () => toast({ variant: "error", title: "Could not save remark", description: "Please try again." }),
  });

  const handleDpdpDelete = async () => {
    if (!confirm("This will permanently delete all personal data for this guest. This action cannot be undone.")) return;
    try {
      await api.post(`/guests/${id}/dpdp/delete`, {});
      toast({ variant: "success", title: "Deletion request queued", description: "Data will be purged within 30 days." });
      router.push("/dashboard/guests");
    } catch {
      toast({ variant: "error", title: "Failed", description: "Could not queue deletion request." });
    }
  };

  if (isLoading) return <GuestDetailSkeleton />;
  if (!guest) return (
    <div className="p-8 text-center">
      <p className="text-gray-500 text-sm">Guest not found.</p>
      <button onClick={() => router.back()} className="mt-3 text-teal-600 text-sm font-medium">← Back</button>
    </div>
  );

  return (
    <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
      <Link href="/dashboard/guests" className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-700 transition-colors w-fit">
        <ArrowLeft size={16} /> Back to guests
      </Link>

      {/* Hero identity band */}
      <div className="haip-card p-5 shadow-sm flex items-center gap-4">
        <GuestAvatar name={guest.name} phone={guest.phone} size="lg" />
        <div className="flex-1 min-w-0">
          <h1 className="haip-page-title truncate">{guest.name || guest.phone}</h1>
          <div className="flex items-center gap-4 mt-1 flex-wrap">
            <span className="flex items-center gap-1.5 text-sm text-gray-500">
              <Phone size={12} className="text-gray-400" /> {guest.phone}
            </span>
            {guest.email && (
              <span className="flex items-center gap-1.5 text-sm text-gray-500">
                <Mail size={12} className="text-gray-400" /> {guest.email}
              </span>
            )}
            {guest.created_at && (
              <span className="text-xs text-gray-400">Guest since {formatDate(guest.created_at)}</span>
            )}
          </div>
          {(guest.tags ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {guest.tags!.map(tag => (
                <Badge key={tag} variant="ghost" className="text-xs">{tag}</Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Left rail */}
        <div className="col-span-12 lg:col-span-4 space-y-5">
          {/* Lifetime stats */}
          <div className="haip-card p-5 shadow-sm">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-gray-50 rounded-xl p-3 text-center">
                <p className="text-xs text-gray-400 mb-0.5">Predicted CSAT</p>
                <p className={cn(
                  "text-lg font-black",
                  (guest.predicted_csat ?? 0) >= 4 ? "text-teal-600" : "text-amber-600"
                )}>
                  {guest.predicted_csat?.toFixed(1) ?? "—"}
                  <span className="text-xs font-normal text-gray-400">/5</span>
                </p>
              </div>
              <div className="bg-gray-50 rounded-xl p-3 text-center">
                <p className="text-xs text-gray-400 mb-0.5">Lifetime value</p>
                <p className="text-lg font-black text-gray-800">
                  {guest.lifetime_value ? `₹${(guest.lifetime_value / 1000).toFixed(0)}k` : "—"}
                </p>
              </div>
            </div>
            {guest.consent_status && (
              <div className="flex items-center gap-1.5 mt-3 justify-center">
                <div
                  className={cn("w-1.5 h-1.5 rounded-full", guest.consent_status === "granted" ? "bg-emerald-500" : "bg-amber-500")}
                />
                <span className="text-[11px] text-gray-400 capitalize">Consent {guest.consent_status}</span>
              </div>
            )}
          </div>

          {/* Assign Owner + Lead Stage */}
          {currentInquiryId && (
            <div className="haip-card p-4 space-y-3 text-[13px]">
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Current Lead</p>
              <div className="flex items-center justify-between gap-2">
                <span className="text-gray-400">Assigned owner</span>
                {canAssignAnyone ? (
                  <select
                    value={leadOwnerStage?.assigned_agent_id ?? ""}
                    onChange={e => e.target.value && assignLead.mutate(e.target.value)}
                    disabled={assignLead.isPending}
                    className="font-semibold text-[12px] rounded-md px-1.5 py-0.5 border border-gray-200 outline-none disabled:opacity-60 text-teal-600"
                  >
                    <option value="" disabled>Unassigned</option>
                    {(teamMembers ?? []).map(m => (
                      <option key={m.id} value={m.id}>{m.id === currentUserId ? `${m.name} (you)` : m.name}</option>
                    ))}
                  </select>
                ) : (
                  <span className="font-semibold flex items-center gap-1.5 text-gray-800">
                    <UserCheck size={12} className="text-teal-600" />
                    {leadOwnerStage?.assigned_agent_id === currentUserId ? "You" : leadOwnerStage?.assigned_agent_name || "Unassigned"}
                    {leadOwnerStage?.assigned_agent_id !== currentUserId && currentUserId && (
                      <button
                        onClick={() => assignLead.mutate(currentUserId)}
                        disabled={assignLead.isPending}
                        className="text-[10px] font-medium rounded-md px-1.5 py-0.5 border border-gray-200 text-teal-600 disabled:opacity-60"
                      >
                        Assign to me
                      </button>
                    )}
                  </span>
                )}
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-gray-400">Lead stage</span>
                <select
                  value={stages?.find(s => s.key === leadOwnerStage?.stage_key)?.id ?? ""}
                  onChange={e => e.target.value && moveStage.mutate(e.target.value)}
                  disabled={moveStage.isPending || !stages?.length}
                  className="font-semibold text-[12px] rounded-md px-1.5 py-0.5 border border-gray-200 outline-none disabled:opacity-60 text-teal-600"
                >
                  {!stages?.some(s => s.key === leadOwnerStage?.stage_key) && (
                    <option value="" disabled>{leadOwnerStage?.stage_key ?? "Not set"}</option>
                  )}
                  {(stages ?? []).map(s => (
                    <option key={s.id} value={s.id}>{s.label}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {/* Agent Remarks */}
          {currentInquiryId && (
            <div className="haip-card p-4 space-y-3">
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Agent Remarks</p>
              <div className="space-y-2 max-h-56 overflow-y-auto haip-scrollbar">
                {notes.length === 0 ? (
                  <p className="text-xs text-gray-400">No remarks yet</p>
                ) : (
                  notes.map(n => (
                    <div key={n.id} className="bg-gray-50 rounded-xl p-2.5">
                      <p className="text-xs text-gray-700 leading-relaxed">{n.body}</p>
                      <p className="text-[10px] text-gray-400 mt-1">
                        {n.sender_name || "Agent"}{n.created_at ? ` · ${formatDate(n.created_at)}` : ""}
                      </p>
                    </div>
                  ))
                )}
              </div>
              <div className="flex items-center gap-2">
                <input
                  value={noteDraft}
                  onChange={e => setNoteDraft(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === "Enter" && noteDraft.trim()) addNote.mutate(noteDraft.trim());
                  }}
                  placeholder="Add a remark…"
                  className="flex-1 text-xs rounded-lg border border-gray-200 px-2.5 py-1.5 outline-none focus:border-teal-400"
                />
                <button
                  onClick={() => noteDraft.trim() && addNote.mutate(noteDraft.trim())}
                  disabled={addNote.isPending || !noteDraft.trim()}
                  className="w-7 h-7 flex items-center justify-center rounded-lg bg-teal-600 text-white disabled:opacity-40 flex-shrink-0"
                >
                  {addNote.isPending ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                </button>
              </div>
            </div>
          )}

          {/* DPDP deletion */}
          <div className="bg-red-50 border border-red-100 rounded-2xl p-4">
            <div className="flex items-start gap-2 mb-3">
              <Shield size={14} className="text-red-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-semibold text-red-700">DPDP data rights</p>
                <p className="text-[11px] text-red-500 mt-0.5">Guest has the right to request data deletion.</p>
              </div>
            </div>
            <button
              onClick={handleDpdpDelete}
              className="w-full py-2 border border-red-200 rounded-xl text-xs font-semibold text-red-600 hover:bg-red-100 transition-colors flex items-center justify-center gap-1.5"
            >
              <Trash2 size={12} /> Process deletion request
            </button>
          </div>
        </div>

        {/* Right column */}
        <div className="col-span-12 lg:col-span-8 space-y-5">
          <div className="haip-card p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-900 mb-5">Guest journey</h2>
            <GuestJourney guestId={id} />
          </div>

          {/* Calls & Recordings */}
          <div className="haip-card p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <PlayCircle size={14} className="text-teal-500" /> Calls &amp; Recordings
            </h2>
            {!calls || calls.items.length === 0 ? (
              <p className="text-xs text-gray-400">No calls yet</p>
            ) : (
              <div className="space-y-2">
                {calls.items.map(call => (
                  <Link
                    key={call.id}
                    href={`/dashboard/calls/${call.id}`}
                    className="flex items-center justify-between p-3 bg-gray-50 rounded-xl hover:bg-gray-100 transition-colors"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-gray-800 capitalize">{call.direction}</span>
                        {call.is_missed && <Badge variant="destructive" className="text-[10px]">Missed</Badge>}
                        <Badge variant="secondary" className="text-[10px] capitalize">{call.disposition}</Badge>
                      </div>
                      {call.ai_summary && (
                        <p className="text-[11px] text-gray-500 truncate mt-1 max-w-md">{call.ai_summary}</p>
                      )}
                    </div>
                    <div className="text-right flex-shrink-0 ml-3">
                      <p className="text-xs font-semibold text-gray-700 tabular-nums">{formatDuration(call.duration_seconds)}</p>
                      {call.started_at && (
                        <p className="text-[10px] text-gray-400">{formatDate(call.started_at)}</p>
                      )}
                      {call.qa_score != null && (
                        <p className="text-[10px] text-teal-600 font-semibold flex items-center gap-0.5 justify-end mt-0.5">
                          <Sparkles size={9} /> {call.qa_score.toFixed(0)}
                        </p>
                      )}
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* Bookings */}
          <div className="haip-card p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Home size={14} className="text-purple-400" /> Bookings
            </h2>
            {stays.length === 0 ? (
              <p className="text-xs text-gray-400">No bookings yet</p>
            ) : (
              <div className="space-y-2">
                {stays.map(stay => (
                  <div key={stay.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-xl">
                    <div className="flex items-center gap-2">
                      <Bed size={12} className="text-purple-400 flex-shrink-0" />
                      <div>
                        <p className="text-xs font-medium text-gray-800">{stay.property?.name || "Property"}</p>
                        {stay.checkin && (
                          <p className="text-[11px] text-gray-400">
                            {formatDate(stay.checkin)}{stay.checkout && ` – ${formatDate(stay.checkout)}`}
                          </p>
                        )}
                      </div>
                    </div>
                    {stay.status && (
                      <Badge variant="ghost" className="capitalize text-[10px]">{stay.status}</Badge>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Inquiries */}
          <div className="haip-card p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <FileText size={14} className="text-amber-400" /> Inquiries
            </h2>
            {inquiries.length === 0 ? (
              <p className="text-xs text-gray-400">No inquiries yet</p>
            ) : (
              <div className="space-y-2">
                {inquiries.map(inq => (
                  <div key={inq.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-xl">
                    <div className="flex items-center gap-2">
                      <Star size={12} className="text-amber-400 flex-shrink-0" />
                      <div>
                        <p className="text-xs font-medium text-gray-800">
                          {inq.created_at ? formatDate(inq.created_at) : "Inquiry"}
                        </p>
                      </div>
                    </div>
                    <Badge variant={
                      inq.stage === "booked" ? "success" : inq.stage === "lost" ? "destructive" : "secondary"
                    } className="capitalize text-[10px]">{inq.stage}</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function GuestDetailSkeleton() {
  return (
    <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-24 rounded-2xl" />
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-4 space-y-5">
          <Skeleton className="h-32 rounded-2xl" />
          <Skeleton className="h-40 rounded-2xl" />
        </div>
        <div className="col-span-8 space-y-5">
          <Skeleton className="h-64 rounded-2xl" />
          <Skeleton className="h-40 rounded-2xl" />
        </div>
      </div>
    </div>
  );
}
