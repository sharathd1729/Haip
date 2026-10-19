"use client";
// "Waiting for you" (Hospitality Hybrid Home): the first few PEOPLE from the shared work queue, as faces rather than counts,
// worst first. Same query key as My day and the nav badge, so all three agree. Each card opens the person's record; calling
// and replying happen on My day / the inbox, never from here.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { canSeeNav } from "@/lib/permissions";
import { ArrowRight, CheckCircle2 } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { AvatarChannelBadges, toGuestChannel } from "@/components/inbox/ChannelBadges";
import { SendQuoteButton } from "@/components/quotes/SendQuoteButton";

type Kind = "callback" | "new_lead" | "reply" | "no_reply" | "followup" | "clash";
type Severity = "fresh" | "late" | "urgent" | "critical" | "stale";
interface Item {
  kind: Kind; title: string; detail: string; action: string; href: string; guest_id: string | null;
  inquiry_id?: string | null; guest_phone?: string | null;
  channels: string[]; since: string | null; severity: Severity; has_draft: boolean;
}
interface Queue { total: number; severity: Record<Severity, number>; items: Item[] }

const KIND: Record<Kind, string> = { new_lead: "New lead", callback: "Missed call", reply: "Waiting for a reply", no_reply: "Not replying to us", followup: "Follow-up due", clash: "Calendar clash" };
const LATE = new Set<Severity>(["late", "urgent", "critical"]);

function wait(iso: string | null): string {
  if (!iso) return "";
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (m < 1) return "just now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

export function WaitingForYou({ role, limit = 4 }: { role: string; limit?: number }) {
  const allowed = canSeeNav(role, "inbox");
  const { data, isLoading, isError } = useQuery<Queue>({
    queryKey: ["work-queue", ""],
    queryFn: () => api.get("/work-queue").then(r => r.data),
    enabled: allowed,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  if (!allowed) return null;
  // People only: calendar clashes are listed on My day, not as faces here.
  const items = (data?.items ?? []).filter(i => i.severity !== "stale" && i.kind !== "clash");
  const shown = items.slice(0, limit);

  return (
    <section aria-labelledby="waiting-title">
      <div className="mb-2.5 flex items-baseline justify-between gap-3 px-0.5">
        <h2 id="waiting-title" className="font-[family-name:var(--font-display)] text-[17px] font-semibold tracking-[-0.01em] text-[var(--haip-fg)]">Waiting for you</h2>
        {items.length > 0 && (
          <Link href="/dashboard/my-day" className="inline-flex min-h-11 items-center gap-1 text-[13.5px] font-semibold text-primary hover:underline sm:min-h-0">
            {items.length > limit ? `All ${items.length} in My day` : "Open My day"}<ArrowRight size={14} />
          </Link>
        )}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: limit }, (_, i) => <Skeleton key={i} className="h-[132px] rounded-2xl" />)}</div>
      ) : isError ? (
        <p className="haip-card px-4 py-4 text-[13.5px] text-[var(--haip-status-danger-fg)]" role="alert">Couldn’t load who is waiting. <Link href="/dashboard/my-day" className="font-semibold underline">Open My day</Link></p>
      ) : shown.length === 0 ? (
        <p className="haip-card flex items-center gap-2.5 px-4 py-4 text-[14px] text-[var(--haip-fg-2)]">
          <CheckCircle2 size={18} className="shrink-0 text-[var(--haip-status-success-fg)]" aria-hidden />
          Nobody is waiting on the team right now.
        </p>
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {shown.map(item => {
            const late = LATE.has(item.severity);
            const channels = item.channels.map(toGuestChannel).filter(Boolean) as NonNullable<ReturnType<typeof toGuestChannel>>[];
            return (
              <li key={`${item.kind}:${item.guest_id ?? item.href}`} className="flex flex-col gap-1">
                <Link href={item.href}
                  className={cn("haip-card group flex h-full min-h-[132px] flex-col gap-2.5 px-4 py-3.5 transition-shadow hover:shadow-[var(--haip-shadow-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                    late && "shadow-[inset_3px_0_0_var(--haip-status-danger-fg)]")}>
                  <span className="flex items-center gap-3">
                    <span className="relative shrink-0"><GuestAvatar name={item.title} size="md" className="size-11 text-[14px]" /><AvatarChannelBadges channels={channels} size={15} /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[15px] font-semibold text-[var(--haip-fg)]">{item.title}</span>
                      <span className="block truncate text-[12.5px] text-[var(--haip-fg-subtle)]">{KIND[item.kind]}</span>
                    </span>
                    <span className={cn("num shrink-0 rounded-full px-2 py-0.5 text-[12px] font-bold",
                      late ? "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]" : "bg-[var(--haip-accent-light)] text-[var(--haip-accent-ink)]")}>
                      {wait(item.since)}
                    </span>
                  </span>
                  <span className="line-clamp-2 text-[13px] leading-snug text-[var(--haip-fg-2)]">{item.detail}</span>
                  <span className="mt-auto flex items-center justify-between gap-2 text-[13px] font-semibold text-primary">
                    {item.has_draft ? "AI reply ready to review" : item.action}
                    <ArrowRight size={14} className="transition-transform group-hover:translate-x-0.5" aria-hidden />
                  </span>
                </Link>
                <SendQuoteButton variant="link" className="self-start"
                  args={{ inquiryId: item.inquiry_id ?? null, guestId: item.guest_id, phone: item.inquiry_id || item.guest_id ? null : item.guest_phone ?? null,
                    from: "home", name: item.title }} />
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
