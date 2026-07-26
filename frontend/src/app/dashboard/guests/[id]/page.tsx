"use client";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowLeft, Phone, MessageSquare, Home, Star, Shield, Trash2 } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { GuestJourney } from "@/components/guests/GuestJourney";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

interface GuestDetail {
  id: string;
  full_name?: string;
  phone: string;
  email?: string;
  tags?: string[];
  predicted_csat?: number;
  lifetime_value?: number;
  consent_recording?: boolean;
  created_at: string;
  timeline: Array<{
    type: "call" | "message" | "stay" | "inquiry";
    title: string;
    subtitle?: string;
    timestamp: string;
    score?: number;
  }>;
  inquiries: Array<{ id: string; stage: string; property_name?: string; check_in?: string; budget?: number }>;
  stays: Array<{ id: string; property_name?: string; check_in?: string; check_out?: string; status?: string }>;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export default function GuestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { toast } = useToast();

  const { data: guest, isLoading } = useQuery<GuestDetail>({
    queryKey: ["guest", id],
    queryFn: () => api.get(`/guests/${id}`).then(r => r.data),
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
    <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">
      {/* Back */}
      <Link href="/dashboard/guests" className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-700 transition-colors w-fit">
        <ArrowLeft size={16} /> Back to guests
      </Link>

      <div className="grid grid-cols-12 gap-6">
        {/* Left: profile card + stats */}
        <div className="col-span-12 lg:col-span-4 space-y-5">
          {/* Profile */}
          <div className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm">
            <div className="flex items-start gap-4 mb-5">
              <GuestAvatar name={guest.full_name} phone={guest.phone} size="lg" />
              <div className="flex-1 min-w-0">
                <h1 className="text-lg font-bold text-gray-900 truncate">{guest.full_name || guest.phone}</h1>
                <div className="flex items-center gap-1.5 mt-1">
                  <Phone size={12} className="text-gray-400" />
                  <span className="text-sm text-gray-500">{guest.phone}</span>
                </div>
                {guest.email && (
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <MessageSquare size={12} className="text-gray-400" />
                    <span className="text-sm text-gray-500 truncate">{guest.email}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Tags */}
            {guest.tags && guest.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-4">
                {guest.tags.map(tag => (
                  <Badge key={tag} variant="ghost" className="text-xs">{tag}</Badge>
                ))}
              </div>
            )}

            {/* Stats */}
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

            <p className="text-xs text-gray-400 mt-3 text-center">
              Guest since {formatDate(guest.created_at)}
            </p>
          </div>

          {/* Inquiries */}
          <div className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <Star size={14} className="text-amber-400" /> Inquiries
            </h3>
            {guest.inquiries.length === 0 ? (
              <p className="text-xs text-gray-400">No inquiries yet</p>
            ) : (
              <div className="space-y-2">
                {guest.inquiries.map(inq => (
                  <div key={inq.id} className="flex items-center justify-between p-2.5 bg-gray-50 rounded-xl">
                    <div>
                      <p className="text-xs font-medium text-gray-800">{inq.property_name || "Property"}</p>
                      {inq.check_in && <p className="text-[11px] text-gray-400">{formatDate(inq.check_in)}</p>}
                    </div>
                    <Badge variant={
                      inq.stage === "booked" ? "success" : inq.stage === "lost" ? "destructive" : "secondary"
                    } className="capitalize text-[10px]">{inq.stage}</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Stays */}
          <div className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <Home size={14} className="text-purple-400" /> Stays
            </h3>
            {guest.stays.length === 0 ? (
              <p className="text-xs text-gray-400">No stays yet</p>
            ) : (
              <div className="space-y-2">
                {guest.stays.map(stay => (
                  <div key={stay.id} className="flex items-center justify-between p-2.5 bg-gray-50 rounded-xl">
                    <div>
                      <p className="text-xs font-medium text-gray-800">{stay.property_name || "Property"}</p>
                      {stay.check_in && (
                        <p className="text-[11px] text-gray-400">
                          {formatDate(stay.check_in)}{stay.check_out && ` – ${formatDate(stay.check_out)}`}
                        </p>
                      )}
                    </div>
                    {stay.status && (
                      <Badge variant="ghost" className="capitalize text-[10px]">{stay.status}</Badge>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

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

        {/* Right: journey — the single timeline. Ledger-backed, spans every
            module and every inquiry (messages, calls, inquiry stage moves,
            automations). Stays don't emit ledger events yet, so they stay
            visible via the "Stays" list card on the left instead of here. */}
        <div className="col-span-12 lg:col-span-8 space-y-5">
          <div className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-900 mb-5">Guest journey</h2>
            <GuestJourney guestId={id} />
          </div>
        </div>
      </div>
    </div>
  );
}

function GuestDetailSkeleton() {
  return (
    <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">
      <Skeleton className="h-4 w-24" />
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-4 space-y-5">
          <Skeleton className="h-48 rounded-2xl" />
          <Skeleton className="h-36 rounded-2xl" />
        </div>
        <div className="col-span-8">
          <Skeleton className="h-96 rounded-2xl" />
        </div>
      </div>
    </div>
  );
}
