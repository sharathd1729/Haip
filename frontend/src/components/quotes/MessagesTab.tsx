"use client";
// "WhatsApp messages" tab of /dashboard/quotes (owner/manager): the four templates HAIP sends around a quote and a booking,
// with their Meta status. Reuses the Phase 4 card from Settings > Invoice details; Create drafts never submits to Meta.
import Link from "next/link";
import { BookingTemplatesCard } from "@/components/settings/BookingTemplatesCard";
import type { Catalog } from "@/app/dashboard/quotes/types";
import { Callout } from "./ui";

export function MessagesTab({ catalog }: { catalog: Catalog }) {
  const quoteReady = catalog.send_setup.template_status === "approved";
  return (
    <div className="mx-auto w-full max-w-3xl space-y-3">
      <Callout tone={quoteReady ? "success" : "warning"}>
        {quoteReady
          ? "The quote template is approved: \"Send quote + payment link\" sends the quote PDF and the pay button on WhatsApp."
          : "Until Meta approves ratha_quote_payment_v1, sending a quote only creates the payment links for you to copy."}
        {!catalog.send_setup.razorpay_connected && (
          <> Razorpay is not connected yet: <Link href="/dashboard/settings/payments" className="font-semibold underline">connect it</Link>.</>
        )}
      </Callout>
      <BookingTemplatesCard canCreate={catalog.permissions.can_manage_templates} />
    </div>
  );
}
