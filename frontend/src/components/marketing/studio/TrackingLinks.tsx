"use client";
// A post's tracking code and links (GET /marketing/studio/content/{id}/tracking): put the Instagram DM or WhatsApp link
// in the caption, story or bio, and a chat that starts from it is credited to this post in the Insights report.
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { STUDIO, btn } from "./types";

interface Tracking { code: string; instagram_dm: string | null; whatsapp: string | null }

export function TrackingLinks({ itemId }: { itemId: string }) {
  const { toast } = useToast();
  const q = useQuery<Tracking>({ queryKey: ["studio-tracking", itemId], queryFn: () => api.get(`${STUDIO}/content/${itemId}/tracking`).then(r => r.data) });
  if (!q.data) return null;
  const copy = (text: string) => navigator.clipboard?.writeText(text).then(() => toast({ variant: "success", title: "Copied" }));
  const rows = [["Instagram DM link", q.data.instagram_dm], ["WhatsApp link", q.data.whatsapp]] as const;
  return (
    <div className="space-y-2 rounded-xl border border-[var(--haip-border)] p-3">
      <p className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Tracking for this post: <span className="font-mono">{q.data.code}</span></p>
      <p className="text-xs text-[var(--haip-fg-subtle)]">A chat that starts from these links is credited to this post.</p>
      {rows.map(([label, url]) => (
        <div key={label} className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>{label}</span>
          {url ? <button type="button" className={btn} onClick={() => copy(url)}>Copy</button>
            : <span className="text-xs text-[var(--haip-fg-subtle)]">{label.startsWith("Instagram") ? "Connect Instagram first" : "Add a WhatsApp number to the brand profile"}</span>}
        </div>
      ))}
    </div>
  );
}
