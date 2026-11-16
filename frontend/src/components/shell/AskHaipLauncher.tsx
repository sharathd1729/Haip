"use client";
// Ask HAIP on every page (workspace redesign Phase 3): a round button bottom-right (above the phone's bottom bar) opens the
// same chat as AI › HAIP Executive › Ask HAIP in a side panel, with suggested questions for the area you're in. Owners of a
// workspace whose plan includes Ask HAIP only, as Ask HAIP itself (the server refuses everyone else). Hidden on the Executive page, which has the full chat.
import { useState } from "react";
import { useSession } from "next-auth/react";
import { Sparkles } from "@/lib/icons";
import { Drawer } from "@/components/ui/kit";
import { AskHaip, ASK_PROMPTS } from "@/components/analyst/AskHaip";
import { useNav } from "@/components/layout/nav";
import { useModule } from "@/components/providers/WorkspaceProvider";

const BY_AREA: Record<string, string[]> = {
  home: ["How many new leads did we get this week?", "What was our revenue this month?", "How many calls were missed today?"],
  inbox: ["How many conversations came in today?", "How many calls were missed this week?", "Which channel brought the most chats this month?"],
  leads: ["How many new leads this month, by source?", "How many leads are in each stage?", "How many leads were lost last month?"],
  bookings: ["How many bookings check in this week?", "Which property has the most bookings this month?", "What was our revenue each month this year?"],
  ops: ["How many guests check in tomorrow?", "How many bookings check out this week?", "Which property is busiest this month?"],
  marketing: ["Which source brought the most bookings last month?", "How many leads came from Instagram this month?", "How many new leads did we get each week this month?"],
};

export function AskHaipLauncher({ user }: { user?: { role?: string } }) {
  const nav = useNav(user?.role ?? "");
  const role = (useSession().data?.user as { role?: string } | undefined)?.role ?? user?.role;
  const [open, setOpen] = useState(false);
  const included = useModule("ask_haip");      // the workspace's plan includes Ask HAIP
  if (role !== "owner" || !included || nav.personal || nav.pathname.startsWith("/dashboard/analyst")) return null;
  const area = nav.activeArea;
  // The inbox composer sits bottom-right: keep the button above it there.
  const lift = nav.pathname.startsWith("/dashboard/inbox") ? "bottom-[calc(9.5rem+env(safe-area-inset-bottom))] md:bottom-28" : "bottom-[calc(4.75rem+env(safe-area-inset-bottom))] md:bottom-6";
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} aria-label="Ask HAIP"
        className={`fixed right-4 z-40 flex h-14 items-center gap-2 rounded-full bg-primary pl-4 pr-5 text-[15px] font-semibold text-primary-foreground shadow-[0_8px_24px_color-mix(in_srgb,var(--primary)_35%,transparent)] transition-transform active:scale-[0.97] md:right-6 ${lift}`}>
        <Sparkles size={20} aria-hidden />
        <span className="hidden sm:inline">Ask HAIP</span>
      </button>
      <Drawer open={open} onOpenChange={setOpen} title="Ask HAIP" wide
        description={area ? `Answers from your live data. Suggestions for ${area.title}.` : "Answers from your live data."}>
        <AskHaip compact prompts={BY_AREA[area?.key ?? ""] ?? ASK_PROMPTS} />
      </Drawer>
    </>
  );
}
