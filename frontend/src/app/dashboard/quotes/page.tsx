"use client";
// Rate calculator (owner feedback: "one page, price appears instantly, then Copy or Send"). The same calculator opens as a
// sheet from the Inbox, calls, My day, Home and Leads ("Send quote", QuoteSheetProvider); this page is the "New quote" for
// anything else. ?inquiry= / ?guest= / ?conversation= / ?call= / ?phone= prefill it; ?quote=<id> opens a saved quote (the
// owner's approval link). Packages, routes and the WhatsApp templates live in Settings > Quotes.
import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { PageHeader } from "@/components/ui/kit";
import { QuoteCalculator } from "@/components/quotes/calc/QuoteCalculator";
import { SavedQuote } from "@/components/quotes/calc/SavedQuote";
import type { QuoteFrom, QuoteOpenArgs } from "@/components/quotes/calc/types";
import { BTN, BTN_GHOST } from "@/components/quotes/ui";

export default function QuotesPage() {
  const params = useSearchParams();
  const { data: session } = useSession();
  const role = (session?.user as { role?: string } | undefined)?.role;
  const [fresh, setFresh] = useState(0);
  const quoteId = params.get("quote");
  const args: QuoteOpenArgs | undefined = fresh === 0 && (params.get("inquiry") || params.get("guest") || params.get("conversation") || params.get("call") || params.get("phone"))
    ? { inquiryId: params.get("inquiry"), guestId: params.get("guest"), conversationId: params.get("conversation"), callId: params.get("call"),
        phone: params.get("phone"), from: (params.get("from") as QuoteFrom | null) ?? "lead" }
    : undefined;

  return (
    <div className="mx-auto w-full max-w-[1180px] space-y-4 px-4 py-4 sm:px-6 sm:py-6">
      <PageHeader title="Rate calculator" subtitle="Price a trip, then copy the quote or send it to the guest on WhatsApp."
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            {(role === "owner" || role === "manager") && <Link href="/dashboard/settings/quotes" className={BTN_GHOST}>Edit packages and routes</Link>}
            {(quoteId || args || fresh > 0) && (
              <Link href="/dashboard/quotes" className={BTN} onClick={() => setFresh(n => n + 1)}>New quote</Link>
            )}
          </div>
        )} />
      {quoteId ? <SavedQuote quoteId={quoteId} /> : <QuoteCalculator key={`${fresh}-${params.toString()}`} args={args} />}
    </div>
  );
}
