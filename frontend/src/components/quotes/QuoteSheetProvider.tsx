"use client";
// The "Send quote" sheet: the rate calculator on top of whatever the agent is doing (Inbox, a call, My day, Home, Leads), prefilled,
// so nobody copies a number to the Quotes page and back. Mounted once in dashboard/layout.tsx; any page opens it with
// useQuoteSheet().open({ inquiryId | guestId | conversationId | callId | phone, from }).
// Desktop: the kit's right-hand Drawer, wide (1100px). Phones (<640px): full screen. Close by button, Esc or the scrim; the
// sheet (Radix dialog) locks body scroll and traps focus.
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { Drawer } from "@/components/ui/kit";
import { QuoteCalculator } from "./calc/QuoteCalculator";
import type { QuoteOpenArgs } from "./calc/types";

interface QuoteSheet { open: (args: QuoteOpenArgs) => void; close: () => void }

const Ctx = createContext<QuoteSheet | null>(null);

/** Outside the provider (a test, a page rendered on its own) the opener falls back to the Quotes page with the same prefill. */
function fallbackOpen(args: QuoteOpenArgs) {
  const q = new URLSearchParams();
  if (args.inquiryId) q.set("inquiry", args.inquiryId);
  if (args.guestId) q.set("guest", args.guestId);
  if (args.conversationId) q.set("conversation", args.conversationId);
  if (args.callId) q.set("call", args.callId);
  if (args.phone) q.set("phone", args.phone);
  if (args.from) q.set("from", args.from);
  window.location.assign(`/dashboard/quotes${q.toString() ? `?${q}` : ""}`);
}

export function useQuoteSheet(): QuoteSheet {
  return useContext(Ctx) ?? { open: fallbackOpen, close: () => undefined };
}

export function QuoteSheetProvider({ children }: { children: ReactNode }) {
  const [args, setArgs] = useState<QuoteOpenArgs | null>(null);
  const [opened, setOpened] = useState(0);
  const [header, setHeader] = useState<{ title: string; from: string }>({ title: "New quote", from: "" });
  const open = useCallback((a: QuoteOpenArgs) => {
    setHeader({ title: a.name ? `Quote for ${a.name}` : "New quote", from: "" });
    setArgs(a);
    setOpened(n => n + 1);
  }, []);
  const close = useCallback(() => setArgs(null), []);
  const value = useMemo(() => ({ open, close }), [open, close]);
  const onHeader = useCallback((h: { title: string; from: string }) => setHeader(h), []);

  return (
    <Ctx.Provider value={value}>
      {children}
      <Drawer open={!!args} onOpenChange={o => { if (!o) close(); }} title={header.title}
        description={header.from || "Price a trip, then copy the quote or send it to the guest on WhatsApp."}
        className="sm:max-w-[1100px]">
        {args && <QuoteCalculator key={opened} args={args} onHeader={onHeader} />}
      </Drawer>
    </Ctx.Provider>
  );
}
