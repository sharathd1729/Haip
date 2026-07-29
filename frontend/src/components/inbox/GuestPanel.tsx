"use client";
import { useQuery } from "@tanstack/react-query";
import { Bed, ExternalLink, Star } from "lucide-react";
import { ChannelIcon } from "./ChannelIcon";
import { Skeleton } from "@/components/ui/skeleton";
import api from "@/lib/api";

interface ConversationDetail {
  id: string;
  guest_name?: string;
  guest_phone: string;
  channel: string;
  status: "open" | "resolved" | "snoozed";
}

interface GuestSummary {
  id?: string;
  name?: string;
  phone: string;
  tags?: string[];
  consent_status?: string;
  is_vip?: boolean;
  lifetime_value?: number;
  total_stays?: number;
  total_inquiries?: number;
  recent_stays?: { property_name?: string; check_in?: string; check_out?: string }[];
}

export function GuestPanel({ detail }: { detail: ConversationDetail }) {
  const { data: guest, isLoading } = useQuery<GuestSummary>({
    queryKey: ["guest-by-phone", detail.guest_phone],
    queryFn: () =>
      api.get(`/guests?phone=${encodeURIComponent(detail.guest_phone)}&limit=1`)
         .then(r => Array.isArray(r.data) ? r.data[0] : r.data),
    enabled: !!detail.guest_phone,
    staleTime: 60_000,
  });

  const initial = (detail.guest_name ?? detail.guest_phone)?.[0]?.toUpperCase() ?? "?";
  const isVip = guest?.is_vip;

  return (
    <div
      className="hidden md:flex md:flex-col w-[300px] flex-shrink-0 overflow-y-auto haip-scrollbar bg-card"
      style={{ borderLeft: "1px solid var(--haip-border)" }}
    >
      {/* Header */}
      <div className="px-4 py-4 flex-shrink-0" style={{ borderBottom: "1px solid var(--haip-border)" }}>
        <p className="text-[10px] font-medium uppercase tracking-widest mb-3" style={{ color: "var(--haip-fg-subtle)" }}>
          Guest 360
        </p>
        <div className="flex items-center gap-3">
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0"
            style={{
              background: isVip
                ? "linear-gradient(135deg, #F59E0B, #D97706)"
                : "var(--primary)",
              color: "var(--primary-foreground)",
            }}
          >
            {initial}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <p className="text-[13px] font-semibold truncate" style={{ color: "var(--haip-fg)" }}>
                {detail.guest_name || "Unknown"}
              </p>
              {isVip && <Star size={10} className="flex-shrink-0" style={{ color: "#F59E0B" }} fill="#F59E0B" />}
            </div>
            <p className="text-[10px] truncate" style={{ color: "var(--haip-fg-subtle)" }}>
              ···{detail.guest_phone.slice(-4)}
            </p>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 px-4 py-4 space-y-4">
        {isLoading ? (
          <div className="space-y-2.5">
            <Skeleton className="h-3 w-3/4 rounded" />
            <Skeleton className="h-3 w-1/2 rounded" />
            <Skeleton className="h-3 w-2/3 rounded" />
          </div>
        ) : (
          <>
            {/* LTV stats */}
            {(guest?.lifetime_value != null || guest?.total_stays != null || guest?.total_inquiries != null) && (
              <div className="grid grid-cols-3 gap-2">
                {[
                  { val: guest?.total_stays, label: "Stays" },
                  { val: guest?.total_inquiries, label: "Inquiries" },
                  { val: guest?.lifetime_value != null
                      ? `₹${guest.lifetime_value >= 1000 ? `${(guest.lifetime_value / 1000).toFixed(0)}k` : guest.lifetime_value}`
                      : null,
                    label: "LTV" },
                ].filter(s => s.val != null).map(s => (
                  <div
                    key={s.label}
                    className="text-center p-2 rounded-lg"
                    style={{ background: "color-mix(in srgb, var(--primary) 7%, transparent)" }}
                  >
                    <p className="text-sm font-bold leading-none tabular-nums" style={{ color: "var(--primary)" }}>
                      {s.val}
                    </p>
                    <p className="text-[9px] mt-1" style={{ color: "var(--haip-fg-subtle)" }}>{s.label}</p>
                  </div>
                ))}
              </div>
            )}

            {/* Tags */}
            {(guest?.tags ?? []).length > 0 && (
              <div className="flex flex-wrap gap-1">
                {guest!.tags!.slice(0, 4).map(tag => (
                  <span
                    key={tag}
                    className="px-2 py-0.5 rounded-full text-[10px] font-medium capitalize"
                    style={{
                      background: "color-mix(in srgb, var(--primary) 10%, transparent)",
                      color: "var(--primary)",
                    }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}

            {/* Channel + status */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <ChannelIcon channel={detail.channel} />
                <span className="text-[11px] capitalize" style={{ color: "var(--haip-fg-muted)" }}>
                  {detail.channel}
                </span>
              </div>
              <span
                className="px-2 py-0.5 rounded-full text-[10px] font-medium capitalize"
                style={{
                  background: detail.status === "open"
                    ? "color-mix(in srgb, var(--primary) 10%, transparent)"
                    : "var(--muted)",
                  color: detail.status === "open" ? "var(--primary)" : "var(--haip-fg-subtle)",
                }}
              >
                {detail.status}
              </span>
            </div>

            {/* Recent stays */}
            {(guest?.recent_stays ?? []).length > 0 && (
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wider mb-2" style={{ color: "var(--haip-fg-subtle)" }}>
                  Recent stays
                </p>
                <div className="space-y-2">
                  {guest!.recent_stays!.slice(0, 3).map((s, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <Bed size={10} className="mt-0.5 flex-shrink-0" style={{ color: "var(--primary)" }} />
                      <div className="min-w-0">
                        <p className="text-xs font-medium truncate" style={{ color: "var(--haip-fg)" }}>
                          {s.property_name || "Property"}
                        </p>
                        {s.check_in && (
                          <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>
                            {new Date(s.check_in).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                            {s.check_out && ` → ${new Date(s.check_out).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Consent */}
            {guest?.consent_status && (
              <div className="flex items-center gap-1.5">
                <div
                  className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  style={{ background: guest.consent_status === "granted" ? "var(--haip-green)" : "var(--haip-amber)" }}
                />
                <span className="text-[10px] capitalize" style={{ color: "var(--haip-fg-subtle)" }}>
                  Consent {guest.consent_status}
                </span>
              </div>
            )}
          </>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 flex-shrink-0" style={{ borderTop: "1px solid var(--haip-border)" }}>
        <a
          href={`/dashboard/guests?phone=${encodeURIComponent(detail.guest_phone)}`}
          className="flex items-center gap-1.5 text-xs font-medium transition-colors duration-150"
          style={{ color: "var(--primary)" }}
        >
          <ExternalLink size={11} />
          View full Guest 360
        </a>
      </div>
    </div>
  );
}
